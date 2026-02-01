import os
import logging
import requests
import berserk
import time
import re
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

def get_lichess_client():
    session = berserk.TokenSession(LICHESS_TOKEN)
    return berserk.Client(session=session)

def get_latest_lichess_game_date(client):
    """Fetches the date of the most recent game on Lichess."""
    try:
        # Fetch the authenticated user's profile to get their username
        account = client.account.get()
        username = account['username']
        
        # Get the latest game
        games = list(client.games.export_by_player(username, max=1, sort='dateDesc'))
        
        if games:
            latest_game = games[0]
            # Lichess returns createdAt in milliseconds
            created_at = latest_game['createdAt'] 
            # Convert to seconds for comparison with standard unix timestamps if needed, 
            # but usually datetime objects are best.
            # However, Chess.com archives might just give PGNs with Date/Time headers.
            # Let's keep it as a datetime object.
            return created_at
        return None
    except Exception as e:
        logger.error(f"Error fetching latest Lichess game: {e}")
        return None

def get_chesscom_archives(username):
    """Fetches the list of monthly archives for a Chess.com user."""
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    headers = {
        'User-Agent': 'ChessTransferBot/1.0 (erivera90)' # Polite to define User-Agent
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
                 logger.info("Game already imported, skipping.")
                 return "DUPLICATE"
            
            # Check for Rate Limit (429)
            # e.status_code might be available, or we check the message
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

def get_existing_lichess_games(client, limit=500):
    """
    Fetches recent games from Lichess and returns a set of signatures to identify duplicates.
    Signature: (white_username, black_username, moves_start) 
    """
    signatures = set()
    latest_date = None
    try:
        account = client.account.get()
        username = account['username']
        
        # Fetch games with opening info to get moves or sufficient detail
        logger.info(f"Requesting up to {limit} games from Lichess for user {username}...")
        games = client.games.export_by_player(username, max=limit, sort='dateDesc', opening=True, moves=True)
        
        count = 0
        for i, game in enumerate(games):
            count += 1
            # Capture latest date from the first game
            if i == 0:
                latest_date = game['createdAt']
                logger.debug(f"First Lichess game sample: {game}")

            # Lichess players dict extraction
            # Native games have ['user']['name']
            # Imported games might have just ['name'] if the player isn't on Lichess
            def get_player_name(player_dict):
                if 'user' in player_dict:
                    return player_dict['user']['name'].lower()
                elif 'name' in player_dict:
                    return player_dict['name'].lower()
                return 'ai'

            white = get_player_name(game['players']['white'])
            black = get_player_name(game['players']['black'])
            
            # Moves: string "e4 e5 ..."
            moves = game.get('moves', '')
            # Normalize moves: remove spaces
            moves_clean = moves.replace(' ', '')
            # use first 50 chars of moves as signature component
            moves_sig = moves_clean[:50]
            
            sig = (white, black, moves_sig)
            signatures.add(sig)
            logger.debug(f"Added Lichess Signature: {sig}")
            
        logger.info(f"Successfully processed {count} games from Lichess.")
            
    except Exception as e:
        logger.error(f"Error fetching existing Lichess games: {e}")
        
    return signatures, latest_date

def main():
    if not LICHESS_TOKEN:
        logger.error("LICHESS_TOKEN environment variable is not set.")
        exit(1)

    logger.info("Starting Chess.com to Lichess sync...")
    
    client = get_lichess_client()

    # 1. Fetch existing games signatures to prevent duplicates
    logger.info("Fetching recent Lichess games for duplicate checking...")
    existing_signatures, latest_lichess_date = get_existing_lichess_games(client, limit=500)
    logger.info(f"Loaded {len(existing_signatures)} recent games for duplicate checking.")

    if latest_lichess_date:
        logger.info(f"Latest Lichess game date: {latest_lichess_date}")

    # 2. Get Chess.com archives
    archives = get_chesscom_archives(CHESSCOM_USERNAME)
    archives.sort(reverse=True) 

    for archive_url in archives:
        logger.info(f"Checking archive: {archive_url}")
        
        try:
            parts = archive_url.split('/')
            year = int(parts[-2])
            month = int(parts[-1])
            archive_month_start = datetime(year, month, 1, tzinfo=timezone.utc)
            
            if latest_lichess_date:
                # Ensure latest_lichess_date is timezone aware
                if latest_lichess_date.tzinfo is None:
                    latest_lichess_date = latest_lichess_date.replace(tzinfo=timezone.utc)
                    
                latest_game_month_start = latest_lichess_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                if archive_month_start < latest_game_month_start:
                    logger.info("Reached archives older than latest Lichess game. Stopping.")
                    break
        except Exception as e:
            logger.warning(f"Could not parse archive date optimization: {e}")

        games = get_games_from_archive(archive_url)
        archive_has_new_games = False
        
        for game in games:
            end_time = game.get('end_time')
            pgn = game.get('pgn', '')
            
            # Construct signature for this candidate game
            c_white = game['white']['username'].lower()
            c_black = game['black']['username'].lower()
            
            # Extract moves from PGN
            move_start_index = pgn.find("1. ")
            if move_start_index != -1:
                # Extract moves part
                raw_moves = pgn[move_start_index:]
                
                # Robust cleanup:
                # 1. Remove comments { ... }
                # 2. Remove variations ( ... )
                # 3. Remove numeric annotation glyphs like $1, $2
                # 4. Remove move numbers 1. 1...
                # 5. Remove result 1-0, 0-1, 1/2-1/2
                
                raw_moves = re.sub(r'\{.*?\}', '', raw_moves)
                raw_moves = re.sub(r'\(.*?\)', '', raw_moves)
                raw_moves = re.sub(r'\$\d+', '', raw_moves)
                raw_moves = re.sub(r'\d+\.+', '', raw_moves)
                raw_moves = re.sub(r'(1-0|0-1|1/2-1/2)', '', raw_moves)

                # Finally, strip all whitespace
                moves_clean_pgn = raw_moves.replace(' ', '').replace('\n', '').replace('\r', '')
                
                # Use a longer signature (50 chars)
                candidate_sig = (c_white, c_black, moves_clean_pgn[:50])
                
                # DEBUG: Log signatures to diagnose mismatch
                # Only log for the first few checks to avoid spam, or if we are about to import
                # logger.info(f"Candidate Sig: {candidate_sig}")
                # if len(existing_signatures) > 0:
                #    first_sig = next(iter(existing_signatures))
                #    logger.info(f"Sample Existing Sig: {first_sig}")
                
                if candidate_sig in existing_signatures:
                    logger.info(f"Skipping game {datetime.fromtimestamp(end_time)} vs {c_black if c_white == CHESSCOM_USERNAME.lower() else c_white} (Local Duplicate)")
                    continue
                else:
                     # Log why we are importing (did not find in existing)
                     # Useful for debugging the mismatch
                     logger.debug(f"Signature NOT found: {candidate_sig}")


            if pgn:
                logger.info(f"Found game ended at {datetime.fromtimestamp(end_time)}. Attempting import...")
                import_status = import_game_to_lichess(client, pgn)
                if import_status == "IMPORTED":
                    time.sleep(6)
                    archive_has_new_games = True
                elif import_status == "DUPLICATE":
                    time.sleep(1)
                else:
                    time.sleep(1)
        
        if latest_lichess_date and not archive_has_new_games:
            pass

    logger.info("Sync complete.")

if __name__ == "__main__":
    main()
