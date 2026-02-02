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
MAX_IMPORTS_PER_RUN = 100

class StudyManager:
    def __init__(self, client):
        self.client = client
        self.studies_cache = {} # Map "Name" -> "ID"

    def get_or_create_study(self, study_name):
        # ... (cached logic) ...
        return None

    def create_study(self, name):
        try:
            # berserk 0.14+ supports studies
            # visibility: 'public', 'private', 'unlisted'
            study = self.client.studies.create(name=name, visibility='public')
            return study['id']
        except berserk.exceptions.ResponseError as e:
            logger.error(f"Failed to create study {name}: {e}")
            return None
        except AttributeError:
            logger.error("Berserk client does not support studies (update library?).")
            return None

    def add_game_to_study(self, study_id, pgn, chapter_name):
        try:
            # import_pgn(study_id, pgn, name=None)
            self.client.studies.import_pgn(study_id, pgn, name=chapter_name)
            logger.info(f"Added game to study {study_id}")
            return True
        except berserk.exceptions.ResponseError as e:
            if e.status_code == 429:
                logger.warning("Rate limit on study write.")
                time.sleep(60)
                return False
            logger.error(f"Failed to add to study: {e}")
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
        return {"imported_ids": [], "studied_ids": [], "monthly_studies": {}}
    try:
        with open(HISTORY_FILE, 'r') as f:
            data = json.load(f)
            if "monthly_studies" not in data:
                data["monthly_studies"] = {}
            if "studied_ids" not in data:
                data["studied_ids"] = []
            return data
    except json.JSONDecodeError:
        logger.error("Failed to decode history file. Starting with empty history.")
        return {"imported_ids": [], "studied_ids": [], "monthly_studies": {}}

def save_history(history):
    """Saves the history of imported games to a JSON file."""
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        # Convert set to list for JSON serialization if needed
        # But we maintain imported_ids as list in dict, cast to set in memory
        # We will handle the casting in main.
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
    study_manager = StudyManager(client)

    # 1. Load local history
    history = load_history()
    imported_ids = set(history.get("imported_ids", []))
    studied_ids = set(history.get("studied_ids", []))
    logger.info(f"Loaded {len(imported_ids)} imported games and {len(studied_ids)} studied games from local history.")

    # 2. Get Chess.com archives
    archives = get_chesscom_archives(CHESSCOM_USERNAME)
    archives.sort(reverse=True) 
    
    actions_count = 0

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
                    study_name = f"Chess.com Rapid - {month_name}"
                    
                    study_id = history["monthly_studies"].get(study_name)
                    if not study_id:
                        logger.info(f"Creating new study: {study_name}")
                        study_id = study_manager.create_study(study_name)
                        if study_id:
                            history["monthly_studies"][study_name] = study_id
                            # Save immediately when a new study ID is acquired
                            save_history(history)
                    
                    if study_id:
                        chapter_name = f"{game['white']['username']} vs {game['black']['username']}"
                        if study_manager.add_game_to_study(study_id, pgn, chapter_name):
                            studied_ids.add(game_id)
                            actions_count += 1
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
                return

            # Save periodically
            if actions_count % 5 == 0 and actions_count > 0:
                save_history(history)
        
    # Final save
    save_history(history)
    logger.info(f"Sync complete. {actions_count} actions performed.")

if __name__ == "__main__":
    main()
