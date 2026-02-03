import chess
import chess.pgn
import chess.engine
import os
import sys
import logging
import io
from typing import Optional, List, Dict, Union, Tuple
from dataclasses import dataclass
from abc import ABC, abstractmethod
from dotenv import load_dotenv

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

@dataclass
class CrucialMoment:
    fen: str
    move_played_san: str
    move_played_uci: str
    best_move_san: str
    best_move_uci: str
    eval_swing: int
    pv_line: str
    explanation: Optional[str] = None

class AnalysisNarrator(ABC):
    """Abstract base class for LLM narrators."""
    @abstractmethod
    def explain_mistake(self, moment: CrucialMoment) -> str:
        pass

class GoogleGeminiNarrator(AnalysisNarrator):
    """Google Gemini implementation of the narrator."""
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Google Gemini API Key is missing.")
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')

    def explain_mistake(self, moment: CrucialMoment) -> str:
        prompt = (
            f"You are a chess coach.\n"
            f"Position FEN: {moment.fen}\n"
            f"The player played: {moment.move_played_san}\n"
            f"Stockfish Evaluation change: {moment.eval_swing} (Negative means bad).\n"
            f"Stockfish suggests the best move was: {moment.best_move_san}\n"
            f"The continuation following the best move is: {moment.pv_line}\n\n"
            f"Task: Explain briefly and conceptually why the player's move was a mistake and why the engine's recommendation is superior. "
            f"Focus on chess concepts (e.g., 'This hangs the knight,' 'weakens the king side,' 'allows a fork'). "
            f"Do NOT calculate variations yourself; trust the engine data provided."
        )
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error(f"LLM Generation failed: {e}")
            return "Analysis unavailable due to LLM error."

class MockNarrator(AnalysisNarrator):
    """Mock narrator for testing without API keys."""
    def explain_mistake(self, moment: CrucialMoment) -> str:
        return f"[Mock Analysis] The move {moment.move_played_san} drops evaluation by {moment.eval_swing}. {moment.best_move_san} was better."

class ChessAnalyzer:
    """Handles the Stockfish engine analysis."""
    def __init__(self, engine_path: str, time_limit: float = 0.1):
        self.engine_path = engine_path
        self.time_limit = time_limit
        self.engine: Optional[chess.engine.SimpleEngine] = None

    def __enter__(self):
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
            logger.info(f"Engine loaded: {self.engine_path}")
        except Exception as e:
            logger.critical(f"Failed to load Stockfish engine at {self.engine_path}: {e}")
            raise e
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.engine:
            self.engine.quit()

    def _score_to_cp(self, score: chess.engine.Score) -> int:
        """Converts a chess.engine.Score object to centipawns (clamped)."""
        if score.is_mate():
            # Treat mate as +/- 10000 cp depending on side
            return 10000 if score.mate() > 0 else -10000
        return score.score(mate_score=10000)

    def analyze_game(self, pgn_text: str, threshold: int = 150) -> List[CrucialMoment]:
        """Iterates through the game and identifies crucial moments."""
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if not game:
            logger.error("Could not parse PGN.")
            return []

        moments = []
        board = game.board()
        
        # Analyze the root position first
        # Ideally we iterate nodes. game.mainline() gives us nodes.
        # A node represents the state AFTER the move.
        # So node.parent is state BEFORE the move.
        
        for node in game.mainline():
            if not self.engine:
                break

            # 1. Analyze Position BEFORE the move (Best Play)
            board_before = node.parent.board()
            info_before = self.engine.analyse(board_before, chess.engine.Limit(time=self.time_limit))
            score_before = info_before["score"].pov(board_before.turn) # Score from mover's perspective
            cp_before = self._score_to_cp(score_before)
            
            # Capture engine's best move suggestion for the position BEFORE the user moved
            engine_best_move = info_before.get("pv", [None])[0]
            engine_best_move_san = board_before.san(engine_best_move) if engine_best_move else "N/A"
            engine_best_move_uci = engine_best_move.uci() if engine_best_move else "N/A"
            
            # 2. Analyze Position AFTER the user's move (to see how bad it was)
            # To measure the "quality" of the move played, we can just look at the 
            # score of the *resulting* position from the perspective of the player who just moved.
            board_after = node.board()
            
            # If the game is over (mate), handle specifically or just eval
            info_after = self.engine.analyse(board_after, chess.engine.Limit(time=self.time_limit))
            
            # info_after score is from the perspective of the side to move (the opponent).
            # We negate it to get the score for the player who just moved.
            score_after_opponent = info_after["score"].pov(board_after.turn)
            cp_after = -self._score_to_cp(score_after_opponent)

            # 3. Calculate Swing
            delta = cp_after - cp_before
            
            logger.debug(f"Move: {node.move.uci()} | Before: {cp_before} | After: {cp_after} | Delta: {delta}")

            if delta < -threshold:
                # Get PV line San
                pv_moves = info_before.get("pv", [])
                # We need to simulate the PV on a board to get SANs
                dummy_board = board_before.copy()
                pv_san_list = []
                for move in pv_moves[:4]: # Next 3-4 moves
                    pv_san_list.append(dummy_board.san(move))
                    dummy_board.push(move)
                pv_line = " ".join(pv_san_list)

                moment = CrucialMoment(
                    fen=board_before.fen(),
                    move_played_san=node.san(),
                    move_played_uci=node.move.uci(),
                    best_move_san=engine_best_move_san,
                    best_move_uci=engine_best_move_uci,
                    eval_swing=delta,
                    pv_line=pv_line
                )
                moments.append(moment)
                logger.info(f"Crucial moment found: {moment.move_played_san} (Delta: {delta})")

        return moments

def generate_markdown_report(moments: List[CrucialMoment], output_file: str = "analysis_report.md"):
    """Generates a Markdown report from the analyzed moments."""
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# Chess Analysis Report\n\n")
        if not moments:
            f.write("No crucial moments (blunders/missed wins) detected in this game.\n")
            return

        f.write(f"Found **{len(moments)}** crucial moments where the evaluation dropped significantly.\n\n")
        
        for i, moment in enumerate(moments, 1):
            f.write(f"## Moment {i}\n")
            f.write(f"**FEN:** `{moment.fen}`\n\n")
            f.write(f"- **You Played:** {moment.move_played_san}\n")
            f.write(f"- **Engine Suggests:** {moment.best_move_san}\n")
            f.write(f"- **Evaluation Swing:** {moment.eval_swing} centipawns\n")
            f.write(f"- **Engine PV:** _{moment.pv_line}_\n\n")
            f.write(f"### Coach Explanation\n")
            f.write(f"{moment.explanation}\n\n")
            f.write("---\n")
    logger.info(f"Report generated: {output_file}")

def main():
    # Configuration
    stockfish_path = os.getenv("STOCKFISH_PATH")
    gemini_key = os.getenv("GEMINI_API_KEY")
    pgn_file_path = "game.pgn" # Assuming input file name or passed via args
    
    if len(sys.argv) > 1:
        pgn_file_path = sys.argv[1]

    if not stockfish_path or not os.path.exists(stockfish_path):
        logger.error(f"Stockfish path not found or invalid: {stockfish_path}")
        logger.error("Please set STOCKFISH_PATH in .env")
        sys.exit(1)

    # Initialize Narrator
    if gemini_key:
        narrator = GoogleGeminiNarrator(gemini_key)
    else:
        logger.warning("GEMINI_API_KEY not set. Using MockNarrator.")
        narrator = MockNarrator()

    # Read PGN
    try:
        with open(pgn_file_path, "r") as f:
            pgn_text = f.read()
    except FileNotFoundError:
        logger.error(f"PGN file not found: {pgn_file_path}")
        # Create a dummy PGN for testing purposes if none exists
        logger.info("Creating dummy 'game.pgn' for demonstration...")
        dummy_pgn = '[Event "Demo"]\n1. e4 e5 2. Nf3 d6 3. Bc4 Bg4 4. Nc3 h6 5. Nxe5 Bxd1 6. Bxf7+ Ke7 7. Nd5#'
        with open("game.pgn", "w") as f:
            f.write(dummy_pgn)
        pgn_text = dummy_pgn
        pgn_file_path = "game.pgn"

    # Run Analysis
    try:
        with ChessAnalyzer(stockfish_path) as analyzer:
            logger.info("Starting Engine Analysis...")
            moments = analyzer.analyze_game(pgn_text)
            
            logger.info(f"Engine Analysis complete. Found {len(moments)} moments. Starting LLM narration...")
            
            for moment in moments:
                moment.explanation = narrator.explain_mistake(moment)
                
            generate_markdown_report(moments)
            
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
