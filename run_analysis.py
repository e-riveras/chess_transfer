from src.utils import setup_logging
from src.pipelines.analysis import run_analysis_pipeline
import sys

if __name__ == "__main__":
    setup_logging()
    pgn_file = sys.argv[1] if len(sys.argv) > 1 else "game.pgn"
    run_analysis_pipeline(pgn_file)
