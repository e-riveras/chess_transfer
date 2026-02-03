import os
import logging
import requests
import berserk
import time
import re
import json
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

# Allow importing main.py from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import ChessAnalyzer, GoogleGeminiNarrator, MockNarrator, generate_markdown_report, CrucialMoment

# Configure logging
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

CHESSCOM_USERNAME = os.getenv('CHESSCOM_USERNAME', 'erivera90')
LICHESS_TOKEN = os.getenv('LICHESS_TOKEN')
HISTORY_FILE = os.path.join(os.path.dirname(__file__), '../data/history.json')
MAX_IMPORTS_PER_RUN = 100

class StudyManager:
    def __init__(self, token):
        self.token = token
        self.headers = {
            'Authorization': f'Bearer {token}'
        }
        self.base_url = "https://lichess.org/api"

    def find_study_by_name(self, username, study_name):
        """
        Fetches user's studies and returns the ID of the one matching study_name.
        Lichess API returns NDJSON (newline delimited JSON).
        """
        url = f"{self.base_url}/study/by/{username}"
        try:
            resp = requests.get(url, headers=self.headers)
            if resp.status_code == 200:
                # Parse NDJSON
                for line in resp.iter_lines():
                    if line:
                        try:
                            study = json.loads(line)
                            if study.get('name') == study_name:
                                return study['id']
                        except json.JSONDecodeError:
                            continue
            else:
                logger.error(f"Failed to list studies: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"Request error listing studies: {e}")
        return None

    def add_game_to_study(self, study_id, pgn, chapter_name):
        url = f"{self.base_url}/study/{study_id}/import-pgn"
        payload = {'pgn': pgn, 'name': chapter_name}
        try:
            resp = requests.post(url, headers=self.headers, data=payload)
            if resp.status_code == 200:
                logger.info(f"Added game to study {study_id}")
                return True
            else:
                logger.error(f"Failed to add to study {study_id}: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Request error adding to study: {e}")
            return False

def get_lichess_client():
    session = berserk.TokenSession(LICHESS_TOKEN)
    return berserk.Client(session=session)

def get_chesscom_archives(username):
    """Fetches the list of monthly archives for a Chess.com user."""
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    headers = {
        'User-Agent': 'ChessTransferBot/1.0 (erivera90)' 
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get('archives', [])
    except requests.RequestException as e:
        logger.error(f"Error fetching Chess.com archives: {e}")
        return []

def get_games_from_archive(archive_url):
    """Fetches games from a specific Chess.com archive URL."""
    headers = {
        'User-Agent': 'ChessTransferBot/1.0 (erivera90)'
    }
    try:
        response = requests.get(archive_url, headers=headers)
        response.raise_for_status()
        return response.json().get('games', [])
    except requests.RequestException as e:
        logger.error(f"Error fetching games from archive {archive_url}: {e}")
        return []

def import_game_to_lichess(client, pgn):
    """Imports a PGN to Lichess."""
    def attempt_import():
        try:
            result = client.games.import_game(pgn)
            logger.info(f"Successfully imported game: {result.get('url')}")
            return "IMPORTED"
        except berserk.exceptions.ResponseError as e:
            if "Game already imported" in str(e):
                 logger.info("Game already imported (API check), skipping.")
                 return "DUPLICATE"
            
            # Check for Rate Limit (429)
            if e.status_code == 429 or "Too Many Requests" in str(e):
                return "RATE_LIMIT"
            
            logger.error(f"Failed to import game: {e}")
            return "ERROR"
        except Exception as e:
            logger.error(f"An unexpected error occurred during import: {e}")
            return "ERROR"

    status = attempt_import()
    
    if status == "RATE_LIMIT":
        logger.warning("Rate limit reached (429). Sleeping for 60 seconds before retrying...")
        time.sleep(60)
        status = attempt_import()
        if status == "RATE_LIMIT":
            logger.error("Rate limit hit again after retry. Skipping this game.")
            return "ERROR"
            
    return status

def load_history():
    """Loads the history of imported games from a JSON file."""
    if not os.path.exists(HISTORY_FILE):
        return {"imported_ids": [], "studied_ids": [], "monthly_studies": {}, "last_analyzed_id": None}
    try:
        with open(HISTORY_FILE, 'r') as f:
            data = json.load(f)
            if "monthly_studies" not in data:
                data["monthly_studies"] = {}
            if "studied_ids" not in data:
                data["studied_ids"] = []
            if "last_analyzed_id" not in data:
                data["last_analyzed_id"] = None
            return data
    except json.JSONDecodeError:
        logger.error("Failed to decode history file. Starting with empty history.")
        return {"imported_ids": [], "studied_ids": [], "monthly_studies": {}, "last_analyzed_id": None}

def save_history(history):
    """Saves the history of imported games to a JSON file."""
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save history: {e}")

def main():
    if not LICHESS_TOKEN:
        logger.error("LICHESS_TOKEN environment variable is not set.")
        exit(1)

    logger.info("Starting Chess.com to Lichess sync...")
    try:
        logger.info(f"Berserk version: {berserk.__version__}")
    except:
        logger.info("Berserk version unknown.")
    
    client = get_lichess_client()
    study_manager = StudyManager(LICHESS_TOKEN)

    # 1. Load local history
    history = load_history()
    imported_ids = set(history.get("imported_ids", []))
    studied_ids = set(history.get("studied_ids", []))
    last_analyzed_id = history.get("last_analyzed_id")
    
    logger.info(f"Loaded {len(imported_ids)} imported games, {len(studied_ids)} studied games.")

    # 2. Get Chess.com archives
    archives = get_chesscom_archives(CHESSCOM_USERNAME)
    archives.sort(reverse=True) 
    
    actions_count = 0
    last_analyzable_pgn = None
    last_analyzable_id = None
    
    # Track the absolute latest game found in the archives
    latest_candidate_game = None

    for archive_url in archives:
        logger.info(f"Checking archive: {archive_url}")
        games = get_games_from_archive(archive_url)
        # Reverse games to process newest first within the month
        games.reverse()
        
        for game in games:
            url = game.get('url') 
            end_time = game.get('end_time')
            pgn = game.get('pgn')
            time_class = game.get('time_class')
            
            if not url or not pgn:
                continue
                
            game_id = url.split('/')[-1]
            
            # Capture the very first game we see (which is the newest)
            if latest_candidate_game is None:
                latest_candidate_game = {'id': game_id, 'pgn': pgn}
            
            # --- STEP 1: IMPORT ---
            if game_id not in imported_ids:
                logger.info(f"Found new game {game_id} ended at {datetime.fromtimestamp(end_time)}. Attempting import...")
                import_status = import_game_to_lichess(client, pgn)
                
                if import_status == "IMPORTED" or import_status == "DUPLICATE":
                    imported_ids.add(game_id)
                    actions_count += 1
                    if import_status == "IMPORTED":
                        time.sleep(6)
                    else:
                        time.sleep(1)
                else:
                    time.sleep(1)
                    continue # Import failed, skip study logic for now
            
            # --- STEP 2: STUDY ---
            # Check eligibility: Rapid and >20 moves
            is_rapid = (time_class == 'rapid')
            has_moves = ("20." in pgn)
            
            if is_rapid and has_moves:
                if game_id not in studied_ids:
                    logger.info(f"Game {game_id} qualifies for study. Adding...")
                    game_dt = datetime.fromtimestamp(end_time, tz=timezone.utc)
                    month_name = game_dt.strftime("%B %Y")
                    # Avoid using "Chess.com" in title in case of filters
                    study_name = f"Rapid Games - {month_name}"
                    
                    study_id = history["monthly_studies"].get(study_name)
                    if not study_id:
                        # Try to find existing study on Lichess
                        study_id = study_manager.find_study_by_name(CHESSCOM_USERNAME, study_name)
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
                            # This was just transferred, so it's the primary candidate for analysis
                            last_analyzable_pgn = pgn
                            last_analyzable_id = game_id
                            time.sleep(2) 
                else:
                    logger.debug(f"Game {game_id} already in studied_ids.")
            else:
                if is_rapid: # Rapid but < 20 moves
                    logger.debug(f"Game {game_id} skipped: too short ({len(pgn)} chars).")
            
            # Update history object in memory
            history["imported_ids"] = sorted(list(imported_ids))
            history["studied_ids"] = sorted(list(studied_ids))

            # Check limit
            if actions_count >= MAX_IMPORTS_PER_RUN:
                logger.info(f"Reached limit of {MAX_IMPORTS_PER_RUN} actions for this run. Saving and stopping.")
                save_history(history)
                # Break out of both loops
                break
        
        if actions_count >= MAX_IMPORTS_PER_RUN:
            break
        
    # Final save
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
        # No new game moved, check if the latest available game needs analysis
        if latest_candidate_game['id'] != last_analyzed_id:
            logger.info(f"No new transfer, but found recent game {latest_candidate_game['id']} not yet analyzed. analyzing...")
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
                # Initialize Narrator
                if gemini_key:
                    narrator = GoogleGeminiNarrator(gemini_key)
                else:
                    logger.warning("GEMINI_API_KEY not set. Using MockNarrator.")
                    narrator = MockNarrator()
                
                # Run Analysis
                with ChessAnalyzer(stockfish_path) as analyzer:
                    # Pass username to filter blunders
                    moments, metadata = analyzer.analyze_game(pgn_to_analyze, hero_username=CHESSCOM_USERNAME)
                    
                    explanations = []
                    for moment in moments:
                        explanation = narrator.explain_mistake(moment)
                        moment.explanation = explanation
                        explanations.append(explanation)
                    
                    # Generate Summary
                    summary = narrator.summarize_game(explanations)

                    # Ensure analysis directory exists
                    output_dir = os.path.join(os.path.dirname(__file__), '../analysis')
                    if not os.path.exists(output_dir):
                        os.makedirs(output_dir)

                    generate_markdown_report(moments, metadata, output_dir=output_dir, summary=summary)
                    logger.info("Analysis report generated in analysis/ folder.")
                    
                    # Update history with analyzed ID
                    history["last_analyzed_id"] = id_to_analyze
                    save_history(history)
                    
            except Exception as e:
                logger.error(f"Analysis failed: {e}")
    else:
        logger.info("No games to analyze.")

if __name__ == "__main__":
    main()
