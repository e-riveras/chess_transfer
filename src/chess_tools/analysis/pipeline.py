import os
import sys
import logging
from chess_tools.lib.utils import check_env_var, get_output_dir
from chess_tools.analysis.engine import ChessAnalyzer
from chess_tools.analysis.narrator import GoogleGeminiNarrator, MockNarrator
from chess_tools.analysis.report import generate_markdown_report
from chess_tools.lib.api.lichess import fetch_latest_game, get_lichess_client, get_lichess_username

logger = logging.getLogger("chess_transfer")

def run_analysis_pipeline(pgn_file_path: str = "game.pgn"):
    """
    Orchestrates the analysis of a single game.
    """
    # Configuration
    stockfish_path = check_env_var("STOCKFISH_PATH")
    gemini_key = os.getenv("GEMINI_API_KEY")
    lichess_token = os.getenv("LICHESS_TOKEN")

    # Get username from API token if available
    lichess_username = None
    if lichess_token:
        client = get_lichess_client(lichess_token)
        lichess_username = get_lichess_username(client)

    if not lichess_username:
        logger.warning("Could not determine Lichess username from token. Using fallback.")
        lichess_username = "unknown"
    
    if not os.path.exists(stockfish_path):
        logger.error(f"Stockfish path not found or invalid: {stockfish_path}")
        sys.exit(1)

    # Initialize Narrator
    if gemini_key:
        narrator = GoogleGeminiNarrator(gemini_key)
    else:
        logger.warning("GEMINI_API_KEY not set. Using MockNarrator.")
        narrator = MockNarrator()

    # Read PGN
    pgn_text = ""
    try:
        with open(pgn_file_path, "r") as f:
            pgn_text = f.read()
    except FileNotFoundError:
        logger.info(f"PGN file not found: {pgn_file_path}. Attempting to fetch latest game...")
        pgn_text = fetch_latest_game(lichess_username)
        
        if not pgn_text:
            logger.warning("Could not fetch game. Creating dummy 'game.pgn' for demonstration...")
            dummy_pgn = '[Event "Demo"]\n1. e4 e5 2. Nf3 d6 3. Bc4 Bg4 4. Nc3 h6 5. Nxe5 Bxd1 6. Bxf7+ Ke7 7. Nd5#'
            pgn_text = dummy_pgn
        
        # Save whatever we got (fetched or dummy)
        with open(pgn_file_path, "w") as f:
            f.write(pgn_text)

    # Run Analysis
    try:
        with ChessAnalyzer(stockfish_path) as analyzer:
            logger.info(f"Starting Engine Analysis for hero: {lichess_username}...")
            # Pass username to filter blunders
            moments, metadata = analyzer.analyze_game(pgn_text, hero_username=lichess_username)
            
            logger.info(f"Engine Analysis complete. Found {len(moments)} moments. Starting LLM narration...")
            
            explanations = []
            for moment in moments:
                explanation = narrator.explain_mistake(moment)
                moment.explanation = explanation
                explanations.append(explanation)
            
            summary = narrator.summarize_game(explanations)
            
            output_dir = get_output_dir("analysis")
            
            generate_markdown_report(moments, metadata, output_dir=output_dir, summary=summary)
            
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        sys.exit(1)
