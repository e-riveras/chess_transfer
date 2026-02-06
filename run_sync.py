from src.utils import setup_logging
from src.pipelines.sync import run_sync_pipeline

if __name__ == "__main__":
    setup_logging()
    run_sync_pipeline()
