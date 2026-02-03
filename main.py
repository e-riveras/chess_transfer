from __future__ import annotations
import chess
import chess.pgn
import chess.engine
import chess.svg
import os
import sys
import logging
import io
import urllib.parse
from typing import Optional, List, Dict, Union, Tuple
from dataclasses import dataclass
from abc import ABC, abstractmethod
from dotenv import load_dotenv
import requests

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
    eval_after: int
    pv_line: str
    game_result: str
    hero_color: bool # True=White, False=Black
    explanation: Optional[str] = None
    image_url: Optional[str] = None # Relative path to saved image
    svg_content: Optional[str] = None # Raw SVG content

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
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self.model_name = 'gemini-2.0-flash'

    def explain_mistake(self, moment: CrucialMoment) -> str:
        # Determine extra context
        context_note = ""
        
        # Check for "Winning but Lost Eval" (Practical Trap)
        # If user WON (1-0 and White OR 0-1 and Black) BUT eval is negative (< -100 cp)
        user_won = (moment.game_result == "1-0" and moment.hero_color == chess.WHITE) or \
                   (moment.game_result == "0-1" and moment.hero_color == chess.BLACK)
        
        if user_won and moment.eval_after < -100:
            context_note = "\n**Context:** The user ultimately WON this game, but this move put them in a losing position engine-wise. Frame the commentary as: 'You were objectively lost here, but this move might have set a practical trap or complications that your opponent failed to navigate.'"

        prompt = (
            f"You are a chess coach.\n"
            f"Position FEN: {moment.fen}\n"
            f"The player played: {moment.move_played_san}\n"
            f"Stockfish Evaluation change: {moment.eval_swing} centipawns (Negative means bad).\n"
            f"Current Evaluation: {moment.eval_after} centipawns.\n"
            f"Stockfish suggests the best move was: {moment.best_move_san}\n"
            f"The continuation following the best move is: {moment.pv_line}\n"
            f"Game Result: {moment.game_result}\n"
            f"{context_note}\n\n"
            f"Task: Explain briefly and conceptually why the player's move was a mistake and why the engine's recommendation is superior. "
            f"Focus on chess concepts (e.g., 'This hangs the knight,' 'weakens the king side,' 'allows a fork'). "
            f"Do NOT calculate variations yourself; trust the engine data provided."
        )
        try:
            response = self.client.models.generate_content(
                model=self.model_name, contents=prompt
            )
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

    def analyze_game(self, pgn_text: str, hero_username: str = None, threshold: int = 250) -> Tuple[List[CrucialMoment], Dict[str, str]]:
        """Iterates through the game and identifies crucial moments."""
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if not game:
            logger.error("Could not parse PGN.")
            return [], {}

        # Extract Metadata
        headers = game.headers
        metadata = {
            "White": headers.get("White", "Unknown"),
            "Black": headers.get("Black", "Unknown"),
            "Date": headers.get("Date", "Unknown"),
            "Event": headers.get("Event", "Unknown"),
            "Site": headers.get("Site", "Unknown"),
            "Result": headers.get("Result", "*")
        }

        # Determine Hero Color
        hero_color = None
        if hero_username:
            if metadata["White"].lower() == hero_username.lower():
                hero_color = chess.WHITE
            elif metadata["Black"].lower() == hero_username.lower():
                hero_color = chess.BLACK
            else:
                logger.warning(f"Hero {hero_username} not found in players: {metadata['White']} vs {metadata['Black']}")

        moments = []
        board = game.board()
        
        for node in game.mainline():
            if not self.engine:
                break

            # Check who made the move: The move in 'node' was made by the side to move in 'node.parent'
            mover_color = node.parent.board().turn
            
            # Filter: Only analyze moves made by the hero
            if hero_color is not None and mover_color != hero_color:
                # Still need to update board state for next iteration
                continue

            # 1. Analyze Position BEFORE the move (Best Play)
            board_before = node.parent.board()
            info_before = self.engine.analyse(board_before, chess.engine.Limit(time=self.time_limit))
            score_before = info_before["score"].pov(mover_color)
            cp_before = self._score_to_cp(score_before)
            
            engine_best_move = info_before.get("pv", [None])[0]
            engine_best_move_san = board_before.san(engine_best_move) if engine_best_move else "N/A"
            engine_best_move_uci = engine_best_move.uci() if engine_best_move else "N/A"
            
            # 2. Analyze Position AFTER the user's move
            board_after = node.board()
            info_after = self.engine.analyse(board_after, chess.engine.Limit(time=self.time_limit))
            
            # Score from mover's perspective
            score_after_opponent = info_after["score"].pov(board_after.turn)
            cp_after = -self._score_to_cp(score_after_opponent)

            # 3. Calculate Swing
            delta = cp_after - cp_before
            
            # 4. Smart Filter (Context-Aware Mercy Rule)
            is_decided_before = abs(cp_before) > 500
            is_decided_after = abs(cp_after) > 500
            same_result = (cp_before > 0 and cp_after > 0) or (cp_before < 0 and cp_after < 0)

            # Logic: Skip if game was decided and result didn't flip
            if is_decided_before and is_decided_after and same_result:
                # But KEEP if it crosses threshold?
                # Requirement: "SKIP the analysis ONLY IF: is_decided_before AND is_decided_after AND same_result"
                # Requirement: "KEEP the analysis IF: The evaluation crosses the threshold"
                # If delta < -threshold (e.g. -600), does it override the skip?
                # Example: +900 -> +600 (Delta -300).
                # Decided (T), Decided (T), Same (T). -> SKIP.
                # Example: +600 -> +100 (Delta -500).
                # Decided (T), Decided (F), Same (T). -> KEEP (condition fails).
                # Example: +200 -> -200 (Delta -400).
                # Decided (F), Decided (F), Same (F). -> KEEP.
                
                # So the simple Skip condition handles all cases correctly EXCEPT if user wants to see "blunders in garbage time".
                # The user explicitly said: "SKIP... if I was winning and stayed winning... skip it."
                continue

            if delta < -threshold:
                # PV Line
                pv_moves = info_before.get("pv", [])
                dummy_board = board_before.copy()
                pv_san_list = []
                for move in pv_moves[:4]:
                    pv_san_list.append(dummy_board.san(move))
                    dummy_board.push(move)
                pv_line = " ".join(pv_san_list)

                # --- Generate SVG with Arrows ---
                arrows = []
                
                # Arrow for the move played (Mistake) - Red
                # node.move is the move played
                arrows.append(chess.svg.Arrow(node.move.from_square, node.move.to_square, color="#d40000cc")) # Red with alpha
                
                # Arrow for the best move (Engine) - Green
                if engine_best_move:
                    arrows.append(chess.svg.Arrow(engine_best_move.from_square, engine_best_move.to_square, color="#008800cc")) # Green with alpha

                # Orientation: View from Hero's perspective (defaults to White if unknown)
                orientation = hero_color if hero_color is not None else chess.WHITE

                svg_data = chess.svg.board(
                    board=board_before, # Show position BEFORE the move
                    arrows=arrows,
                    orientation=orientation,
                    size=400,
                    coordinates=True
                )

                moment = CrucialMoment(
                    fen=board_before.fen(),
                    move_played_san=node.san(),
                    move_played_uci=node.move.uci(),
                    best_move_san=engine_best_move_san,
                    best_move_uci=engine_best_move_uci,
                    eval_swing=delta,
                    eval_after=cp_after,
                    pv_line=pv_line,
                    explanation=None,
                    svg_content=svg_data, # Store SVG content
                    game_result=metadata["Result"],
                    hero_color=hero_color
                )
                
                moments.append(moment)
                logger.info(f"Crucial moment found for {hero_username}: {moment.move_played_san} (Delta: {delta})")

        return moments, metadata

def generate_markdown_report(moments: List[CrucialMoment], metadata: Dict[str, str], output_dir: str = "analysis"):
    """Generates a Markdown report from the analyzed moments."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Create images subdirectory
    images_dir = os.path.join(output_dir, "images")
    if not os.path.exists(images_dir):
        os.makedirs(images_dir)

    # Create filename: Date_White_vs_Black.md
    safe_date = metadata['Date'].replace('.', '-')
    safe_white = "".join(c for c in metadata['White'] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
    safe_black = "".join(c for c in metadata['Black'] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
    filename = f"{safe_date}_{safe_white}_vs_{safe_black}.md"
    output_path = os.path.join(output_dir, filename)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Analysis: {metadata['White']} vs {metadata['Black']}\n\n")
        f.write(f"**Date:** {metadata['Date']} | **Event:** {metadata['Event']} | **Site:** {metadata['Site']}\n\n")
        
        if not moments:
            f.write("No crucial moments (blunders/missed wins) detected for the hero in this game.\n")
            logger.info(f"Report generated (empty): {output_path}")
            return

        f.write(f"Found **{len(moments)}** crucial moments where evaluation dropped significantly.\n\n")
        
        for i, moment in enumerate(moments, 1):
            # Save SVG to file
            image_filename = f"{filename.replace('.md', '')}_moment_{i}.svg"
            image_path = os.path.join(images_dir, image_filename)
            with open(image_path, "w") as img_file:
                if moment.svg_content:
                    img_file.write(moment.svg_content)
            
            # Relative path for Markdown
            relative_image_path = f"images/{image_filename}"

            f.write(f"## Moment {i}\n\n")
            f.write(f"![Position]({relative_image_path})\n\n")
            f.write(f"**FEN:** `{moment.fen}`\n\n")
            f.write(f"- **You Played:** **{moment.move_played_san}** <span style='color:red'>❌ (Red Arrow)</span>\n")
            f.write(f"- **Engine Best:** **{moment.best_move_san}** <span style='color:green'>✅ (Green Arrow)</span>\n")
            f.write(f"- **Eval Swing:** {moment.eval_swing} cp\n")
            f.write(f"- **Variation:** _{moment.pv_line}_\n\n")
            f.write(f"### Coach Explanation\n")
            f.write(f"{moment.explanation}\n\n")
            f.write("---\n")
            
    logger.info(f"Report generated: {output_path}")

def fetch_latest_game(username: str) -> Optional[str]:
    """Fetches the latest game PGN for a user from Lichess."""
    url = f"https://lichess.org/api/games/user/{username}"
    params = {'max': 1, 'pgnInJson': 'true', 'clocks': 'true'}
    try:
        logger.info(f"Fetching latest game for {username} from Lichess...")
        resp = requests.get(url, params=params)
        if resp.status_code == 200:
            return resp.text
        else:
            logger.error(f"Failed to fetch game: {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error fetching game: {e}")
        return None

def main():
    # Configuration
    stockfish_path = os.getenv("STOCKFISH_PATH")
    gemini_key = os.getenv("GEMINI_API_KEY")
    lichess_username = os.getenv("LICHESS_USERNAME", "erivera90")
    pgn_file_path = "game.pgn" 
    
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
    pgn_text = ""
    try:
        with open(pgn_file_path, "r") as f:
            pgn_text = f.read()
    except FileNotFoundError:
        logger.info(f"PGN file not found: {pgn_file_path}. Attempting to fetch latest game...")
        pgn_text = fetch_latest_game(lichess_username)
        
        if not pgn_text:
            logger.warning("Could not fetch game. Creating dummy 'game.pgn' for demonstration...")
            dummy_pgn = '[Event "Demo"]\n1. e4 e5 2. Nf3 d6 3. Bc4 Bg4 4. Nc3 h6 5. Nxe5 Bxd1 6. Bxf7+ Ke7 7. Nd5#'
            pgn_text = dummy_pgn
        
        # Save whatever we got (fetched or dummy)
        with open("game.pgn", "w") as f:
            f.write(pgn_text)

    # Run Analysis
    try:
        with ChessAnalyzer(stockfish_path) as analyzer:
            logger.info(f"Starting Engine Analysis for hero: {lichess_username}...")
            # Pass username to filter blunders
            moments, metadata = analyzer.analyze_game(pgn_text, hero_username=lichess_username)
            
            logger.info(f"Engine Analysis complete. Found {len(moments)} moments. Starting LLM narration...")
            
            for moment in moments:
                moment.explanation = narrator.explain_mistake(moment)
                
            generate_markdown_report(moments, metadata, output_dir="analysis")
            
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
