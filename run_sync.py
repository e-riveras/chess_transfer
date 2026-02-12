from chess_tools.lib.utils import setup_logging
from chess_tools.transfer.sync import run_sync_pipeline

if __name__ == "__main__":
    setup_logging()
    run_sync_pipeline()
