import os
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from chess_tools.lib.utils import check_env_var, get_output_dir, get_repo_root
from chess_tools.lib.api.lichess import get_lichess_client, StudyManager, import_game_to_lichess
from chess_tools.lib.api.chesscom import get_chesscom_archives, get_games_from_archive
from chess_tools.lib.data.history import load_history, save_history
from chess_tools.analysis.engine import ChessAnalyzer
from chess_tools.analysis.narrator import GoogleGeminiNarrator, MockNarrator
from chess_tools.analysis.report import generate_markdown_report, generate_html_report, regenerate_index_page

logger = logging.getLogger("chess_transfer")

MAX_IMPORTS_PER_RUN = 100
IMPORT_DELAY_SECONDS = 6
DUPLICATE_DELAY_SECONDS = 1
STUDY_ADD_DELAY_SECONDS = 2


def run_sync_pipeline():
    """
    Orchestrates the synchronization of games from Chess.com to Lichess
    and triggers analysis for the latest game.
    """
    lichess_token = check_env_var("LICHESS_TOKEN")
    chesscom_username = os.getenv('CHESSCOM_USERNAME', 'erivera90')
    max_imports = MAX_IMPORTS_PER_RUN

    logger.info("Starting Chess.com to Lichess sync...")
    
    client = get_lichess_client(lichess_token)
    study_manager = StudyManager(lichess_token)

    # 1. Load local history
    history = load_history()
    imported_ids = set(history.get("imported_ids", []))
    studied_ids = set(history.get("studied_ids", []))
    last_analyzed_id = history.get("last_analyzed_id")
    
    logger.info(f"Loaded {len(imported_ids)} imported games, {len(studied_ids)} studied games.")

    # 2. Get Chess.com archives
    archives = get_chesscom_archives(chesscom_username)
    archives.sort(reverse=True) 
    
    actions_count = 0
    last_analyzable_pgn = None
    last_analyzable_id = None
    
    # Track the absolute latest game found in the archives
    latest_candidate_game = None

    for archive_url in archives:
        logger.info(f"Checking archive: {archive_url}")
        games = get_games_from_archive(archive_url, chesscom_username)

        # Chess.com API returns games newest-first. Capture the latest game
        # before reversing so the fallback analysis always targets the most
        # recent game, not the oldest one in the archive.
        if latest_candidate_game is None:
            for g in games:
                url_g = g.get('url', '')
                pgn_g = g.get('pgn', '')
                if url_g and pgn_g:
                    gid = urlparse(url_g).path.rstrip('/').split('/')[-1]
                    latest_candidate_game = {'id': gid, 'pgn': pgn_g}
                    break

        games.reverse()

        for game in games:
            url = game.get('url')
            end_time = game.get('end_time')
            pgn = game.get('pgn')
            time_class = game.get('time_class')

            if not url or not pgn:
                continue

            game_id = urlparse(url).path.rstrip('/').split('/')[-1]
            
            # --- STEP 1: IMPORT ---
            if game_id not in imported_ids:
                logger.info(f"Found new game {game_id} ended at {datetime.fromtimestamp(end_time)}. Attempting import...")
                import_status = import_game_to_lichess(client, pgn)
                
                if import_status == "IMPORTED" or import_status == "DUPLICATE":
                    imported_ids.add(game_id)
                    actions_count += 1
                    if import_status == "IMPORTED":
                        time.sleep(IMPORT_DELAY_SECONDS)
                    else:
                        time.sleep(DUPLICATE_DELAY_SECONDS)
                else:
                    time.sleep(DUPLICATE_DELAY_SECONDS)
                    continue 
            
            # --- STEP 2: STUDY ---
            is_rapid = (time_class == 'rapid')
            has_moves = bool(re.search(r'\b20\.', pgn))
            
            if is_rapid and has_moves:
                if game_id not in studied_ids:
                    logger.info(f"Game {game_id} qualifies for study. Adding...")
                    game_dt = datetime.fromtimestamp(end_time, tz=timezone.utc)
                    month_name = game_dt.strftime("%B %Y")
                    study_name = f"Rapid Games - {month_name}"
                    
                    study_id = history["monthly_studies"].get(study_name)
                    if not study_id:
                        study_id = study_manager.find_study_by_name(chesscom_username, study_name)
                        if study_id:
                            logger.info(f"Found existing study: {study_name} ({study_id})")
                            history["monthly_studies"][study_name] = study_id
                            save_history(history)
                        else:
                            logger.warning(f"Study '{study_name}' not found. Please create it manually on Lichess to enable auto-import.")
                    
                    if study_id:
                        chapter_name = f"{game['white']['username']} vs {game['black']['username']}"
                        if study_manager.add_game_to_study(study_id, pgn, chapter_name):
                            studied_ids.add(game_id)
                            actions_count += 1
                            last_analyzable_pgn = pgn
                            last_analyzable_id = game_id
                            time.sleep(STUDY_ADD_DELAY_SECONDS)
                else:
                    logger.debug(f"Game {game_id} already in studied_ids.")
            else:
                if is_rapid:
                    logger.debug(f"Game {game_id} skipped: too short ({len(pgn)} chars).")
            
            # Update history object in memory
            history["imported_ids"] = sorted(list(imported_ids))
            history["studied_ids"] = sorted(list(studied_ids))

            if actions_count >= max_imports:
                logger.info(f"Reached limit of {max_imports} actions for this run. Saving and stopping.")
                save_history(history)
                break
        
        if actions_count >= max_imports:
            break
        
    save_history(history)
    logger.info(f"Sync complete. {actions_count} actions performed.")

    # --- STEP 3: ANALYSIS LOGIC ---
    pgn_to_analyze = None
    id_to_analyze = None

    if last_analyzable_pgn:
        logger.info("Analyzing the game just transferred to study...")
        pgn_to_analyze = last_analyzable_pgn
        id_to_analyze = last_analyzable_id
    elif latest_candidate_game:
        if latest_candidate_game['id'] != last_analyzed_id:
            logger.info(f"No new transfer, but found recent game {latest_candidate_game['id']} not yet analyzed. Analyzing...")
            pgn_to_analyze = latest_candidate_game['pgn']
            id_to_analyze = latest_candidate_game['id']
        else:
            logger.info(f"Latest game {latest_candidate_game['id']} has already been analyzed.")

    if pgn_to_analyze:
        stockfish_path = os.getenv("STOCKFISH_PATH")
        gemini_key = os.getenv("GEMINI_API_KEY")
        
        if not stockfish_path:
            logger.error("Skipping analysis: STOCKFISH_PATH not set.")
        else:
            try:
                if gemini_key:
                    narrator = GoogleGeminiNarrator(gemini_key)
                else:
                    logger.warning("GEMINI_API_KEY not set. Using MockNarrator.")
                    narrator = MockNarrator()
                
                with ChessAnalyzer(stockfish_path) as analyzer:
                    logger.info(f"Starting analysis for {chesscom_username}")
                    moments, metadata = analyzer.analyze_game(pgn_to_analyze, hero_username=chesscom_username)
                    
                    explanations = []
                    for moment in moments:
                        explanation = narrator.explain_mistake(moment)
                        moment.explanation = explanation
                        explanations.append(explanation)
                    
                    summary = narrator.summarize_game(explanations)

                    output_dir = get_output_dir("analysis")

                    generate_markdown_report(moments, metadata, output_dir=output_dir, summary=summary)

                    html_dir = str(get_repo_root() / "docs" / "analysis")
                    generate_html_report(moments, metadata, output_dir=html_dir, summary=summary)
                    regenerate_index_page(html_dir)

                    logger.info("Analysis report generated.")
                    
                    history["last_analyzed_id"] = id_to_analyze
                    save_history(history)
                    
            except Exception as e:
                logger.error(f"Analysis failed: {e}")
    else:
        logger.info("No games to analyze.")
