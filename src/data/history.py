import json
import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("chess_transfer")

def get_history_file_path() -> str:
    """Returns the absolute path to history.json."""
    # Assuming this runs from project root or src/data
    # Let's anchor it to project root based on file location
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_dir, 'data', 'history.json')

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
