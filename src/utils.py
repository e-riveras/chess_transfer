import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

def get_project_root() -> Path:
    """Returns the project root directory (where run_sync.py lives)."""
    # Navigate up from src/utils.py to project root
    return Path(__file__).parent.parent

def get_output_dir(subdir: str = "analysis") -> str:
    """Returns the path to an output directory within the project root."""
    return str(get_project_root() / subdir)

def setup_logging():
    """Configures the logging format and level based on environment variables."""
    load_dotenv()
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger("chess_transfer")

def check_env_var(name: str):
    """
    Checks if an environment variable is set. Exits if missing.
    
    Args:
        name (str): The name of the environment variable.
        
    Returns:
        str: The value of the environment variable.
    """
    value = os.getenv(name)
    if not value:
        logging.getLogger("chess_transfer").error(f"Environment variable {name} is not set.")
        sys.exit(1)
    return value
