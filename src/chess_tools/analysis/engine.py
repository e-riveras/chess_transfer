import chess
import chess.engine
import chess.svg
import logging
import urllib.parse
from typing import Optional, List, Dict, Tuple, Any
from chess_tools.lib.models import CrucialMoment

logger = logging.getLogger("chess_transfer")

class ChessAnalyzer:
    """
    Wraps the Stockfish chess engine to analyze games and identify mistakes.
    """
    def __init__(self, engine_path: str, time_limit: float = 0.1):
        """
        Args:
            engine_path (str): Path to the Stockfish binary.
            time_limit (float): Time in seconds to spend analyzing each move.
        """
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
        """
        Converts a chess.engine.Score object to centipawns (clamped).
        Handles mate scores by converting them to +/- 10000.
        """
        if score.is_mate():
            return 10000 if score.mate() > 0 else -10000
        return score.score(mate_score=10000)

    def analyze_game(self, pgn_text: str, hero_username: str = None, threshold: int = 250) -> Tuple[List[CrucialMoment], Dict[str, str]]:
        """
        Iterates through the game moves and identifies crucial moments.

        Args:
            pgn_text (str): The raw PGN text of the game.
            hero_username (str): The username of the player to analyze (skips opponent moves).
            threshold (int): Centipawn loss required to flag a move as a mistake.

        Returns:
            Tuple[List[CrucialMoment], Dict[str, str]]: A list of moments and the game metadata.
        """
        import io
        import chess.pgn
        
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

            # The move in 'node' was made by the side to move in 'node.parent'
            # node.parent.board().turn is the color of the player who made the move.
            mover_color = node.parent.board().turn
            
            # Filter: Only analyze moves made by the hero
            if hero_color is not None and mover_color != hero_color:
                # Still need to update board state implicitly by iterating
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
            
            # Score from mover's perspective (negate opponent's score)
            score_after_opponent = info_after["score"].pov(board_after.turn)
            cp_after = -self._score_to_cp(score_after_opponent)

            # 3. Calculate Swing
            delta = cp_after - cp_before
            
            # 4. Smart Filter (Context-Aware Mercy Rule)
            is_decided_before = abs(cp_before) > 500
            is_decided_after = abs(cp_after) > 500
            same_result = (cp_before > 0 and cp_after > 0) or (cp_before < 0 and cp_after < 0)

            if is_decided_before and is_decided_after and same_result:
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

                # --- Tactical Alert Logic ---
                tactical_alert = None
                
                # Check opponent's best response to the user's move (refutation)
                refutation_move = info_after.get("pv", [None])[0]
                if refutation_move:
                    if board_after.is_capture(refutation_move):
                        # What piece is being captured?
                        captured_piece = board_after.piece_at(refutation_move.to_square)
                        
                        if captured_piece and captured_piece.color == mover_color:
                            piece_name = chess.piece_name(captured_piece.piece_type).title()
                            color_name = "White" if mover_color == chess.WHITE else "Black"
                            square_name = chess.square_name(refutation_move.to_square)
                            tactical_alert = f"CRITICAL: Your move allowed the opponent to immediately capture your {color_name} {piece_name} on {square_name}."

                # --- Generate SVG with Arrows ---
                arrows = []
                # Arrow for the move played (Mistake) - Red
                arrows.append(chess.svg.Arrow(node.move.from_square, node.move.to_square, color="#d40000cc")) 
                
                # Arrow for the best move (Engine) - Green
                if engine_best_move:
                    arrows.append(chess.svg.Arrow(engine_best_move.from_square, engine_best_move.to_square, color="#008800cc"))

                # Orientation: View from Hero's perspective
                orientation = hero_color if hero_color is not None else chess.WHITE

                svg_data = chess.svg.board(
                    board=board_before, 
                    arrows=arrows,
                    orientation=orientation,
                    size=400,
                    coordinates=True
                )
                
                # Image URL (Legacy support / backup)
                fen_encoded = urllib.parse.quote(board_before.fen())
                color_str = "white" if orientation == chess.WHITE else "black"
                image_url = f"https://lichess.org/export/fen.gif?fen={fen_encoded}&color={color_str}"

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
                    svg_content=svg_data,
                    game_result=metadata["Result"],
                    hero_color=hero_color,
                    tactical_alert=tactical_alert,
                    image_url=image_url
                )
                
                moments.append(moment)
                logger.info(f"Crucial moment found for {hero_username}: {moment.move_played_san} (Delta: {delta})")

        return moments, metadata
