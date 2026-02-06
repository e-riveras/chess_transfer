import requests
import berserk
import logging
import json
import time
from typing import Optional

logger = logging.getLogger("chess_transfer")

class StudyManager:
    """Manages interactions with Lichess Studies."""
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            'Authorization': f'Bearer {token}'
        }
        self.base_url = "https://lichess.org/api"

    def find_study_by_name(self, username: str, study_name: str) -> Optional[str]:
        """
        Fetches user's studies and returns the ID of the one matching study_name.
        Lichess API returns NDJSON.
        """
        url = f"{self.base_url}/study/by/{username}"
        try:
            resp = requests.get(url, headers=self.headers)
            if resp.status_code == 200:
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

    def add_game_to_study(self, study_id: str, pgn: str, chapter_name: str) -> bool:
        """Adds a PGN as a chapter to an existing study."""
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

def get_lichess_client(token: str) -> berserk.Client:
    """Creates an authenticated berserk client."""
    session = berserk.TokenSession(token)
    return berserk.Client(session=session)

def import_game_to_lichess(client: berserk.Client, pgn: str) -> str:
    """
    Imports a PGN to Lichess.
    Handles rate limits by sleeping and retrying once.
    """
    def attempt_import():
        try:
            result = client.games.import_game(pgn)
            logger.info(f"Successfully imported game: {result.get('url')}")
            return "IMPORTED"
        except berserk.exceptions.ResponseError as e:
            if "Game already imported" in str(e):
                 logger.info("Game already imported (API check), skipping.")
                 return "DUPLICATE"
            
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