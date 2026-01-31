import os
import logging
import requests
import berserk
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
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

def get_existing_lichess_games(client, limit=100):
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
        games = client.games.export_by_player(username, max=limit, sort='dateDesc', opening=True, moves=True)
        
        for i, game in enumerate(games):
            # Capture latest date from the first game
            if i == 0:
                latest_date = game['createdAt']

            # Lichess players dict
            white = game['players']['white']['user']['name'].lower() if 'user' in game['players']['white'] else 'ai'
            black = game['players']['black']['user']['name'].lower() if 'user' in game['players']['black'] else 'ai'
            
            # Moves: string "e4 e5 ..."
            moves = game.get('moves', '')
            # Normalize moves: remove spaces
            moves_clean = moves.replace(' ', '')
            # use first 20 chars of moves as signature component
            moves_sig = moves_clean[:20]
            
            signatures.add((white, black, moves_sig))
            
    except Exception as e:
        logger.error(f"Error fetching existing Lichess games: {e}")
        
    return signatures, latest_date

def main():
    if not LICHESS_TOKEN:
        logger.error("LICHESS_TOKEN environment variable is not set.")
        exit(1)

    logger.info("Starting Chess.com to Lichess sync...")
    
    client = get_lichess_client()
    
    import re
    
        # ... (inside main loop) ...
        
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
                    
                    # Construct signature for this candidate game
                    c_white = game['white']['username'].lower()
                    c_black = game['black']['username'].lower()
                    
                    pgn = game.get('pgn', '')
                    
                    # Extract moves from PGN
                    # PGN usually contains metadata in brackets [], then moves starting with 1.
                    # We want to ignore headers.
                    # Simple heuristic: find the first "1. "
                    move_start_index = pgn.find("1. ")
                    if move_start_index != -1:
                        # Extract moves part
                        raw_moves = pgn[move_start_index:]
                        
                        # Robust cleanup:
                        # 1. Remove comments { ... }
                        # 2. Remove variations ( ... ) - non-recursive
                        # 3. Remove move numbers 1. 1...
                        # 4. Remove numeric annotation glyphs like $1, $2
                        # 5. Remove result 1-0, 0-1, 1/2-1/2 (at the end usually)
                        
                        # Remove comments
                        raw_moves = re.sub(r'\{.*?\}', '', raw_moves)
                        # Remove variations
                        raw_moves = re.sub(r'\(.*?\)', '', raw_moves)
                        # Remove numeric annotation glyphs
                        raw_moves = re.sub(r'\$\d+', '', raw_moves)
                        
                        # Remove everything that is not a letter? 
                        # Moves like O-O-O contain dashes.
                        # Moves like R1a3 contain digits.
                        # Promotion: e8=Q
                        # Check: + #
                        
                        # Strategy: Remove move numbers "1.", "1..."
                        raw_moves = re.sub(r'\d+\.+', '', raw_moves)
                        
                        # Remove Result (1-0, 0-1, 1/2-1/2) often found at end
                        raw_moves = re.sub(r'(1-0|0-1|1/2-1/2)', '', raw_moves)
        
                        # Finally, strip all whitespace
                        moves_clean_pgn = raw_moves.replace(' ', '').replace('\n', '').replace('\r', '')
                        
                        candidate_sig = (c_white, c_black, moves_clean_pgn[:20])
                        
                        # Debug logging for first few games to verify signature match
                        # logger.debug(f"Signature for {game['url']}: {candidate_sig}")
                        
                        if candidate_sig in existing_signatures:
                            logger.info(f"Skipping game {datetime.fromtimestamp(end_time)} vs {c_black if c_white == CHESSCOM_USERNAME.lower() else c_white} (Local Duplicate)")
                            continue            if pgn:
                logger.info(f"Found game ended at {datetime.fromtimestamp(end_time)}. Attempting import...")
                import_status = import_game_to_lichess(client, pgn)
                if import_status == "IMPORTED":
                    # Respect rate limits - Lichess can be strict
                    # If we just imported, sleep significantly
                    time.sleep(6)
                    archive_has_new_games = True
                    
                    # Add to local signatures to prevent re-importing in same run if duplicate exists in archive?
                    # Unlikely for chess.com but good practice.
                    # But we don't have moves parsed easily here to add back to set.
                    
                elif import_status == "DUPLICATE":
                    # No need to sleep long for duplicates, but be polite to avoid 429 on check
                    time.sleep(1)
                else:
                    # Error occurred
                    time.sleep(1)

            
            # NEW STRATEGY IMPLEMENTED BELOW:
            # We will use (White, Black, Result) as a coarse filter.
            # If coarse filter matches, we inspect further or just skip to be safe?
            # No, skipping is dangerous.
            
            # Let's use (White, Black, Timestamp-Date).
            # Convert Chess.com end_time to Date (YYYY-MM-DD).
            # Check if Lichess has a game with same White, Black, and `createdAt` date?
            # NO, `createdAt` is import date.
            
            # Does Lichess have `originalDate`?
            # The `date` field in export might correspond to PGN Date.
            # Let's assume it does.
            
    # Redefine function to use Date if available


        
        # If we went through a whole archive and found NO new games (and we have a cutoff),
        # and since we are iterating archives backwards (newest months first),
        # logic dictates we *could* stop early if we assume strict ordering.
        # But monthly archives are coarse. 
        # Let's just process the last few months to be safe, or relies on the loop logic.
        # If we find a game older than cutoff, we skip.
        # If we process a whole month and all are older, we can probably stop fetching older months.
        
        if latest_lichess_date and not archive_has_new_games:
            # Check the last game of this archive. If it's older than cutoff, 
            # and we are iterating backwards in time (months), then all subsequent months are also older.
            # Archives list is sorted? Yes, usually chronologically by month string.
            # We sorted archives reverse=True.
            
            # To be robust, let's just break if the *latest* game in this archive is older than our cutoff.
            # But the loop above filtered game-by-game.
            pass

    logger.info("Sync complete.")

if __name__ == "__main__":
    main()
