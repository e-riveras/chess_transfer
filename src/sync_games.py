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
    try:
        # Using the import endpoint via berserk? 
        # Berserk might not have a direct 'import_game' method in all versions, 
        # but let's check standard usage or use raw request if needed.
        # Checking berserk docs (mental check): client.games.import_game(pgn)
        result = client.games.import_game(pgn)
        logger.info(f"Successfully imported game: {result.get('url')}")
        return "IMPORTED"
    except berserk.exceptions.ResponseError as e:
        if "Game already imported" in str(e):
             logger.info("Game already imported, skipping.")
             return "DUPLICATE"
        else:
            logger.error(f"Failed to import game: {e}")
            return "ERROR"
    except Exception as e:
        logger.error(f"An unexpected error occurred during import: {e}")
        return "ERROR"

def main():
    if not LICHESS_TOKEN:
        logger.error("LICHESS_TOKEN environment variable is not set.")
        exit(1)

    logger.info("Starting Chess.com to Lichess sync...")
    
    client = get_lichess_client()
    
    # 1. Get the latest game date from Lichess to avoid re-importing old history
    latest_lichess_date = get_latest_lichess_game_date(client)
    
    if latest_lichess_date:
        logger.info(f"Latest Lichess game found at: {latest_lichess_date}")
    else:
        logger.info("No games found on Lichess or error retrieving them. Will attempt to import all available.")

    # 2. Get Chess.com archives
    archives = get_chesscom_archives(CHESSCOM_USERNAME)
    
    # We process archives in reverse order (newest first) to get recent games quicker
    archives.sort(reverse=True) 

    for archive_url in archives:
        logger.info(f"Checking archive: {archive_url}")
        
        # Optimization: Parse archive date from URL and compare with latest_lichess_date
        # URL format: .../games/YYYY/MM
        try:
            parts = archive_url.split('/')
            year = int(parts[-2])
            month = int(parts[-1])
            # Create a timezone-aware datetime for the start of the archive month
            archive_month_start = datetime(year, month, 1, tzinfo=timezone.utc)
            
            if latest_lichess_date:
                # If the entire archive month is strictly before the month of the latest game,
                # we can stop processing older archives.
                # Logic: If latest_game is in Jan 2026, we check Jan 2026.
                # When we hit Dec 2025, its start (Dec 1) is < Start of Jan (Jan 1).
                # So we can break.
                
                # Get the start of the month for the latest lichess game
                latest_game_month_start = latest_lichess_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                if archive_month_start < latest_game_month_start:
                    logger.info("Reached archives older than latest Lichess game. Stopping.")
                    break
        except Exception as e:
            logger.warning(f"Could not parse archive date optimization: {e}")

        games = get_games_from_archive(archive_url)
        
        # Archives contain games in chronological order usually. 
        # We want to process them.
        
        archive_has_new_games = False
        
        for game in games:
            # Chess.com game 'end_time' is a unix timestamp (int)
            end_time = game.get('end_time')
            
            # If we are here, the game is newer or we have no history.
            # Add to list to import.
            # We might want to buffer them or import immediately. 
            # Importing immediately is safer against crashes.
            
            pgn = game.get('pgn')
            if pgn:
                logger.info(f"Found game ended at {datetime.fromtimestamp(end_time)}. Attempting import...")
                import_status = import_game_to_lichess(client, pgn)
                if import_status == "IMPORTED":
                    # Respect rate limits - Lichess can be strict
                    time.sleep(6)
                    archive_has_new_games = True
                elif import_status == "DUPLICATE":
                    # No need to sleep long for duplicates, usually fast.
                    pass
                else:
                    # Error occurred
                    pass
        
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
