import os
import requests
import berserk
from dotenv import load_dotenv

load_dotenv()

LICHESS_TOKEN = os.getenv('LICHESS_TOKEN')
session = berserk.TokenSession(LICHESS_TOKEN)
client = berserk.Client(session=session)

# A known game PGN (shortened for test) or fetch one
# Let's fetch one from your archive first
username = "erivera90"
archive_url = "https://api.chess.com/pub/player/erivera90/games/2026/01"
resp = requests.get(archive_url, headers={'User-Agent': 'DebugBot/1.0'})
games = resp.json().get('games', [])

if not games:
    print("No games found to test.")
    exit()

# Pick the last game
game = games[-1]
pgn = game.get('pgn')
print(f"Testing import for game: {game.get('url')}")

try:
    result = client.games.import_game(pgn)
    print("Result:", result)
except berserk.exceptions.ResponseError as e:
    print("CAUGHT ERROR!")
    print(f"Status Code: {e.status_code if hasattr(e, 'status_code') else 'N/A'}")
    print(f"Args: {e.args}")
    print(f"String representation: {str(e)}")
except Exception as e:
    print(f"Unexpected error: {type(e)} {e}")
