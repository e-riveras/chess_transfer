import json
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("chess_transfer")

def _get_repo_root() -> Path:
    """Walks up from this file until the .git directory is found."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    return Path.cwd()

def get_history_file_path() -> str:
    """Returns the absolute path to history.json at the repo root."""
    return str(_get_repo_root() / 'data' / 'history.json')

def load_history() -> Dict:
    """Loads the history of imported games from a JSON file."""
    history_file = get_history_file_path()
    if not os.path.exists(history_file):
        return {"imported_ids": [], "studied_ids": [], "monthly_studies": {}, "last_analyzed_id": None}
    try:
        with open(history_file, 'r') as f:
            data = json.load(f)
            # Ensure schema validity
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

def save_history(history: Dict):
    """Saves the history of imported games to a JSON file."""
    history_file = get_history_file_path()
    try:
        os.makedirs(os.path.dirname(history_file), exist_ok=True)
        with open(history_file, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save history: {e}")
