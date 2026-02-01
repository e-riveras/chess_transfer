import os
import logging
import requests
import berserk
import time
import re
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

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
        return {"imported_ids": []}
    try:
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error("Failed to decode history file. Starting with empty history.")
        return {"imported_ids": []}

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
    
    client = get_lichess_client()

    # 1. Load local history
    history = load_history()
    imported_ids = set(history.get("imported_ids", []))
    logger.info(f"Loaded {len(imported_ids)} imported games from local history.")

    # 2. Get Chess.com archives
    archives = get_chesscom_archives(CHESSCOM_USERNAME)
    archives.sort(reverse=True) 
    
    new_imports_count = 0

    for archive_url in archives:
        logger.info(f"Checking archive: {archive_url}")
        games = get_games_from_archive(archive_url)
        
        # Optimization: If all games in an archive are already imported, we can stop checking older archives?
        # Only if we assume chronological order and continuous history.
        # For now, let's process archives. We can break if we find a very old game that is already imported
        # AND we have a robust history. But be careful.
        
        for game in games:
            url = game.get('url') # e.g. https://www.chess.com/game/live/147465533948
            end_time = game.get('end_time')
            pgn = game.get('pgn')
            
            if not url or not pgn:
                continue
                
            # Extract Game ID
            game_id = url.split('/')[-1]
            
            if game_id in imported_ids:
                # logger.debug(f"Skipping game {game_id} (Local History)")
                continue

            logger.info(f"Found new game {game_id} ended at {datetime.fromtimestamp(end_time)}. Attempting import...")
            
            import_status = import_game_to_lichess(client, pgn)
            
            if import_status == "IMPORTED" or import_status == "DUPLICATE":
                # Mark as imported in our local history so we don't try again
                imported_ids.add(game_id)
                history["imported_ids"] = list(imported_ids)
                new_imports_count += 1
                
                # Save periodically or just keep in memory?
                # Safer to save periodically in case of crash, but strictly only need once at end.
                # Let's save every 5 imports to be safe.
                if new_imports_count % 5 == 0:
                    save_history(history)

                if import_status == "IMPORTED":
                    time.sleep(6) # Rate limit respect
                else:
                    time.sleep(1) # Polite check
            else:
                # Error (e.g. rate limit failed), do not add to history, try next time
                time.sleep(1)
        
    # Final save
    save_history(history)
    logger.info(f"Sync complete. {new_imports_count} new games processed.")

if __name__ == "__main__":
    main()
