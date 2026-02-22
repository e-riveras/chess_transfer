import chess
import chess.engine
import chess.svg
import logging
import urllib.parse
from typing import Optional, List, Dict, Tuple, Any
from chess_tools.lib.models import CrucialMoment

logger = logging.getLogger("chess_transfer")

MATE_SCORE_CP = 10000
BLUNDER_THRESHOLD_CP = 250
DECIDED_POSITION_CP = 500


def describe_board(board: chess.Board, hero_color: chess.Color) -> str:
    """Plain-English board summary to ground LLM context without FEN parsing."""
    lines = []

    piece_values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                    chess.ROOK: 5, chess.QUEEN: 9}
    hero_mat = sum(len(board.pieces(pt, hero_color)) * v for pt, v in piece_values.items())
    opp_mat  = sum(len(board.pieces(pt, not hero_color)) * v for pt, v in piece_values.items())
    diff = hero_mat - opp_mat
    if diff == 0:
        lines.append("Material: equal.")
    elif diff > 0:
        lines.append(f"Material: you are up {diff} point(s).")
    else:
        lines.append(f"Material: you are down {abs(diff)} point(s).")

    undefended = []
    for pt in [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
        for sq in board.pieces(pt, hero_color):
            if not board.is_attacked_by(hero_color, sq):
                undefended.append(f"{chess.piece_name(pt).title()} on {chess.square_name(sq)}")
    if undefended:
        lines.append(f"Your undefended pieces: {', '.join(undefended)}.")

    king_sq = board.king(hero_color)
    if king_sq is not None:
        f = chess.square_file(king_sq)
        r = chess.square_rank(king_sq)
        back_rank = 0 if hero_color == chess.WHITE else 7
        if f >= 6:
            lines.append("Your king is castled kingside.")
        elif f <= 2:
            lines.append("Your king is castled queenside.")
        elif r == back_rank:
            lines.append("Your king is in the center on the back rank.")
        else:
            lines.append("Your king is exposed / uncastled.")

    return " ".join(lines)


def classify_tactic(
    board_after: chess.Board,
    refutation_pv: list,
    mate_in,
    mover_color: chess.Color
) -> str:
    """Deterministically label the tactic type from the refutation line."""
    if mate_in is not None and mate_in <= 5:
        return "forced_mate"
    if not refutation_pv:
        return "unknown"

    first_move = refutation_pv[0]

    if board_after.is_capture(first_move):
        captured = board_after.piece_at(first_move.to_square)
        if captured and captured.color == mover_color:
            if captured.piece_type == chess.PAWN:
                return "hanging_pawn"
            return "hanging_piece"

    board_copy = board_after.copy()
    board_copy.push(first_move)
    attacked = sum(
        1 for pt in [chess.QUEEN, chess.ROOK, chess.KNIGHT, chess.BISHOP, chess.KING]
        for sq in board_copy.pieces(pt, mover_color)
        if board_copy.is_attacked_by(not mover_color, sq)
    )
    if attacked >= 2:
        return "fork"

    return "positional"


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
            return MATE_SCORE_CP if score.mate() > 0 else -MATE_SCORE_CP
        return score.score(mate_score=MATE_SCORE_CP)

    def analyze_game(self, pgn_text: str, hero_username: str = None, threshold: int = BLUNDER_THRESHOLD_CP) -> Tuple[List[CrucialMoment], Dict[str, str]]:
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

        for node in game.mainline():
            if not self.engine:
                break

            # board_before: the position the mover was facing (before their move).
            # node.parent.board() replays from root each call — always correct.
            board_before = node.parent.board()
            mover_color = board_before.turn

            # Filter: Only analyze moves made by the hero
            if hero_color is not None and mover_color != hero_color:
                continue

            # 1. Analyze Position BEFORE the move (Best Play)
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
            is_decided_before = abs(cp_before) > DECIDED_POSITION_CP
            is_decided_after = abs(cp_after) > DECIDED_POSITION_CP
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
                
                # Full refutation line: what the opponent can force after the blunder
                refutation_pv = info_after.get("pv", [])
                refutation_board = board_after.copy()
                refutation_san_list = []
                for move in refutation_pv[:4]:
                    try:
                        refutation_san_list.append(refutation_board.san(move))
                        refutation_board.push(move)
                    except Exception:
                        break
                refutation_line = " ".join(refutation_san_list)

                # Mate detection from info_after
                refutation_score = info_after["score"].pov(board_after.turn)
                mate_in = abs(refutation_score.mate()) if refutation_score.is_mate() else None

                tactic_type = classify_tactic(board_after.copy(), refutation_pv, mate_in, mover_color)
                board_description = describe_board(board_before, mover_color)

                # Check opponent's best response to the user's move (refutation)
                refutation_move = refutation_pv[0] if refutation_pv else None
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
                    image_url=image_url,
                    refutation_line=refutation_line,
                    mate_in=mate_in,
                    tactic_type=tactic_type,
                    board_description=board_description,
                )
                
                moments.append(moment)
                logger.info(f"Crucial moment found for {hero_username}: {moment.move_played_san} (Delta: {delta})")

        return moments, metadata
