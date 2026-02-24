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

# Missed-chance thresholds
MISSED_CHANCE_CP = 150          # min cp lost to count as a missed chance
WINNING_THRESHOLD = 200         # position must be ≥ this to qualify
MISSED_MATE_MOVES = 5           # mate-in ≤ N that was missed

# Severity tiers (absolute eval swing magnitude)
SEVERITY_CRITICAL_CP = 500
SEVERITY_MAJOR_CP = 300

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}

TACTIC_LABELS = {
    "forced_mate": "Forced Mate",
    "back_rank_mate": "Back-Rank Mate",
    "skewer": "Skewer",
    "pin": "Pin",
    "discovered_attack": "Discovered Attack",
    "hanging_piece": "Hanging Piece",
    "hanging_pawn": "Hanging Pawn",
    "losing_exchange": "Losing Exchange",
    "fork": "Fork",
    "trapped_piece": "Trapped Piece",
    "positional": "Positional",
    "unknown": "Unknown",
}

TACTIC_COLORS = {
    "forced_mate": "#e74c3c",
    "back_rank_mate": "#e74c3c",
    "skewer": "#e67e22",
    "pin": "#e67e22",
    "discovered_attack": "#9b59b6",
    "hanging_piece": "#f39c12",
    "hanging_pawn": "#f1c40f",
    "losing_exchange": "#e67e22",
    "fork": "#3498db",
    "trapped_piece": "#1abc9c",
    "positional": "#95a5a6",
    "unknown": "#7f8c8d",
}

MOMENT_TYPE_LABELS = {
    "blunder": "Blunder",
    "missed_chance": "Missed Opportunity",
    "missed_mate": "Missed Mate",
}

SEVERITY_COLORS = {
    "critical": "#e74c3c",
    "major": "#e67e22",
    "minor": "#f1c40f",
}


def _compute_severity(eval_swing: int) -> str:
    """Determine severity tier from absolute eval swing magnitude."""
    magnitude = abs(eval_swing)
    if magnitude >= SEVERITY_CRITICAL_CP:
        return "critical"
    elif magnitude >= SEVERITY_MAJOR_CP:
        return "major"
    return "minor"


def classify_moment(
    cp_before: int,
    cp_after: int,
    best_mate_in: Optional[int],
    played_mate_in: Optional[int],
) -> str:
    """
    Determine whether a position is a blunder, missed_chance, or missed_mate.

    Args:
        cp_before: eval before move from mover's POV (engine best).
        cp_after: eval after move from mover's POV.
        best_mate_in: mate-in from engine's best line (before move), or None.
        played_mate_in: mate-in from position after move, or None (opponent's POV negated).

    Returns:
        "blunder", "missed_chance", or "missed_mate"
    """
    delta = cp_after - cp_before

    # Case 1: Had a forced mate but didn't play it
    if best_mate_in is not None and best_mate_in <= MISSED_MATE_MOVES and best_mate_in > 0:
        # Check that the mate was lost (played move doesn't also give mate)
        if played_mate_in is None or played_mate_in <= 0:
            return "missed_mate"

    # Case 2: Large negative delta = blunder
    if delta < -BLUNDER_THRESHOLD_CP:
        return "blunder"

    # Case 3: Had a winning position but played a neutral/suboptimal move
    if cp_before >= WINNING_THRESHOLD and delta < -MISSED_CHANCE_CP:
        return "missed_chance"

    # Case 4: Missed mate with larger depth
    if best_mate_in is not None and best_mate_in > 0:
        if played_mate_in is None or played_mate_in <= 0:
            return "missed_mate"

    return "blunder"


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


def _is_back_rank_mate(board: chess.Board, mate_pv: list, mover_color: chess.Color) -> bool:
    """Check if a forced mate line ends with the king trapped on the back rank."""
    sim = board.copy()
    for m in mate_pv:
        try:
            sim.push(m)
        except Exception:
            return False
    if not sim.is_checkmate():
        return False
    loser = mover_color  # the side being mated
    king_sq = sim.king(loser)
    if king_sq is None:
        return False
    rank = chess.square_rank(king_sq)
    back = 0 if loser == chess.WHITE else 7
    return rank == back


def _ray_between(sq1: int, sq2: int) -> Optional[List[int]]:
    """Return squares strictly between sq1 and sq2 if they are collinear, else None."""
    f1, r1 = chess.square_file(sq1), chess.square_rank(sq1)
    f2, r2 = chess.square_file(sq2), chess.square_rank(sq2)
    df, dr = f2 - f1, r2 - r1
    if df == 0 and dr == 0:
        return None
    # Must be on same rank, file, or diagonal
    if df != 0 and dr != 0 and abs(df) != abs(dr):
        return None
    step_f = (1 if df > 0 else -1) if df != 0 else 0
    step_r = (1 if dr > 0 else -1) if dr != 0 else 0
    squares = []
    f, r = f1 + step_f, r1 + step_r
    while (f, r) != (f2, r2):
        squares.append(chess.square(f, r))
        f += step_f
        r += step_r
    return squares


def classify_tactic(
    board_after: chess.Board,
    refutation_pv: list,
    mate_in,
    mover_color: chess.Color
) -> str:
    """
    Deterministically label the tactic type from the refutation line.

    Detection order (highest priority first):
    1. Forced mate (+ back-rank sub-classification)
    2. Skewer
    3. Pin (absolute + relative)
    4. Discovered attack
    5. Hanging piece/pawn (+ en passant)
    6. Losing exchange
    7. Fork (moved piece only)
    8. Trapped piece
    9. Positional (catch-all)
    """
    opp_color = not mover_color

    # 1. Forced mate
    if mate_in is not None and mate_in <= 9:
        if refutation_pv and _is_back_rank_mate(board_after, refutation_pv, mover_color):
            return "back_rank_mate"
        return "forced_mate"

    if not refutation_pv:
        return "unknown"

    first_move = refutation_pv[0]

    # Apply first refutation move to get resulting position
    board_copy = board_after.copy()
    board_copy.push(first_move)

    # 2. Skewer — after the refutation move, check if a sliding piece attacks through
    #    a higher-value piece to a lower-value piece along a ray
    moved_piece = board_after.piece_at(first_move.from_square)
    if moved_piece and moved_piece.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        to_sq = first_move.to_square
        # Look for alignment: attacker -> front piece (mover's) -> back piece (mover's)
        for pt in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
            for target_sq in board_copy.pieces(pt, mover_color):
                ray = _ray_between(to_sq, target_sq)
                if ray is None:
                    continue
                # Check nothing blocks the ray
                blocked = any(board_copy.piece_at(s) is not None for s in ray)
                if blocked:
                    continue
                # Check for a piece behind the target on the same ray
                f_to, r_to = chess.square_file(to_sq), chess.square_rank(to_sq)
                f_tgt, r_tgt = chess.square_file(target_sq), chess.square_rank(target_sq)
                df = f_tgt - f_to
                dr = r_tgt - r_to
                step_f = (1 if df > 0 else -1) if df != 0 else 0
                step_r = (1 if dr > 0 else -1) if dr != 0 else 0
                # Scan beyond the target
                f, r = f_tgt + step_f, r_tgt + step_r
                while 0 <= f <= 7 and 0 <= r <= 7:
                    behind_sq = chess.square(f, r)
                    behind_piece = board_copy.piece_at(behind_sq)
                    if behind_piece:
                        if behind_piece.color == mover_color:
                            front_val = PIECE_VALUES.get(pt, 0)
                            back_val = PIECE_VALUES.get(behind_piece.piece_type, 0)
                            # Skewer: front piece is higher or equal value, attacker is a rook+
                            if front_val >= back_val and PIECE_VALUES.get(moved_piece.piece_type, 0) >= 5:
                                return "skewer"
                        break
                    f += step_f
                    r += step_r

    # 3. Pin — absolute (to king) or relative (front < back value)
    # Check absolute pins in board_after (before refutation)
    for sq in board_after.pieces(chess.QUEEN, mover_color) | board_after.pieces(chess.ROOK, mover_color) | \
              board_after.pieces(chess.BISHOP, mover_color) | board_after.pieces(chess.KNIGHT, mover_color):
        if board_after.is_pinned(mover_color, sq):
            return "pin"

    # Relative pin: after refutation move, check if the moved piece creates a pin
    if moved_piece and moved_piece.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        to_sq = first_move.to_square
        for pt in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
            for front_sq in board_copy.pieces(pt, mover_color):
                ray = _ray_between(to_sq, front_sq)
                if ray is None:
                    continue
                blocked = any(board_copy.piece_at(s) is not None for s in ray)
                if blocked:
                    continue
                # Scan behind the front piece
                f_to, r_to = chess.square_file(to_sq), chess.square_rank(to_sq)
                f_fr, r_fr = chess.square_file(front_sq), chess.square_rank(front_sq)
                df = f_fr - f_to
                dr = r_fr - r_to
                step_f = (1 if df > 0 else -1) if df != 0 else 0
                step_r = (1 if dr > 0 else -1) if dr != 0 else 0
                f, r = f_fr + step_f, r_fr + step_r
                while 0 <= f <= 7 and 0 <= r <= 7:
                    behind_sq = chess.square(f, r)
                    behind_piece = board_copy.piece_at(behind_sq)
                    if behind_piece:
                        if behind_piece.color == mover_color:
                            front_val = PIECE_VALUES.get(pt, 0)
                            back_val = PIECE_VALUES.get(behind_piece.piece_type, 0)
                            if front_val < back_val:
                                return "pin"
                        break
                    f += step_f
                    r += step_r

    # 4. Discovered attack — check/attack comes from a piece OTHER than the one that moved
    if board_copy.is_check():
        # Find which piece gives check
        opp_king_sq = board_copy.king(mover_color)
        if opp_king_sq is not None:
            checkers = board_copy.attackers(opp_color, opp_king_sq)
            # If check comes from a different square than where the moved piece landed
            if first_move.to_square not in checkers and len(checkers) > 0:
                return "discovered_attack"

    # 5. Hanging piece/pawn
    if board_after.is_capture(first_move):
        captured = board_after.piece_at(first_move.to_square)
        # Handle en passant
        if captured is None and board_after.is_en_passant(first_move):
            return "hanging_pawn"
        if captured and captured.color == mover_color:
            if captured.piece_type == chess.PAWN:
                return "hanging_pawn"
            # 6. Losing exchange — capture of a defended piece
            if board_after.is_attacked_by(mover_color, first_move.to_square):
                attacker_piece = board_after.piece_at(first_move.from_square)
                if attacker_piece:
                    attacker_val = PIECE_VALUES.get(attacker_piece.piece_type, 0)
                    captured_val = PIECE_VALUES.get(captured.piece_type, 0)
                    if attacker_val > captured_val:
                        return "losing_exchange"
            return "hanging_piece"

    # 7. Fork — restricted to attacks by the moved piece only
    if moved_piece:
        attacked_valuable = 0
        for pt in [chess.QUEEN, chess.ROOK, chess.KNIGHT, chess.BISHOP, chess.KING]:
            for sq in board_copy.pieces(pt, mover_color):
                if board_copy.is_attacked_by(opp_color, sq):
                    # Check if the attack comes from the moved piece's destination
                    attackers = board_copy.attackers(opp_color, sq)
                    if first_move.to_square in attackers:
                        attacked_valuable += 1
        if attacked_valuable >= 2:
            return "fork"

    # 8. Trapped piece — attacked piece with no safe escape square
    for pt in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
        for sq in board_copy.pieces(pt, mover_color):
            if not board_copy.is_attacked_by(opp_color, sq):
                continue
            piece_val = PIECE_VALUES.get(pt, 0)
            # Check if the piece has any safe escape
            has_escape = False
            for legal in board_copy.legal_moves:
                if legal.from_square != sq:
                    continue
                # Would the destination be safe?
                sim = board_copy.copy()
                sim.push(legal)
                if not sim.is_attacked_by(opp_color, legal.to_square):
                    has_escape = True
                    break
                # Or a favorable trade
                defender_piece = board_copy.piece_at(legal.to_square)
                if defender_piece and PIECE_VALUES.get(defender_piece.piece_type, 0) >= piece_val:
                    has_escape = True
                    break
            if not has_escape:
                return "trapped_piece"

    # 9. Positional (catch-all)
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

            # --- Detect best mate-in from before-move analysis ---
            best_mate_in = None
            if score_before.is_mate() and score_before.mate() is not None and score_before.mate() > 0:
                best_mate_in = score_before.mate()

            # Played mate-in (from after-move, mover's POV)
            played_mate_in = None
            score_after_mover = info_after["score"].pov(mover_color)
            if score_after_mover.is_mate() and score_after_mover.mate() is not None and score_after_mover.mate() > 0:
                played_mate_in = score_after_mover.mate()

            # Determine moment type
            moment_type = classify_moment(cp_before, cp_after, best_mate_in, played_mate_in)

            is_blunder = delta < -threshold
            is_missed = moment_type in ("missed_chance", "missed_mate") and not is_blunder

            if not is_blunder and not is_missed:
                # Also check: missed chance even if delta isn't past blunder threshold
                if cp_before >= WINNING_THRESHOLD and delta < -MISSED_CHANCE_CP:
                    is_missed = True
                    moment_type = "missed_chance"
                elif best_mate_in is not None and best_mate_in > 0 and (played_mate_in is None or played_mate_in <= 0):
                    is_missed = True
                    moment_type = "missed_mate"

            if is_blunder or is_missed:
                # PV Line (engine's best continuation from before move)
                pv_moves = info_before.get("pv", [])
                dummy_board = board_before.copy()
                pv_san_list = []
                for move in pv_moves[:4]:
                    pv_san_list.append(dummy_board.san(move))
                    dummy_board.push(move)
                pv_line = " ".join(pv_san_list)

                # Best line SAN (for missed chances)
                best_line = pv_line  # same as pv_line

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

                # Tactic classification
                if is_blunder:
                    tactic_type = classify_tactic(board_after.copy(), refutation_pv, mate_in, mover_color)
                else:
                    # For missed chances, classify based on engine's best PV (what could have been played)
                    opp_color = not mover_color
                    best_pv = info_before.get("pv", [])
                    tactic_type = classify_tactic(board_before.copy(), best_pv, best_mate_in, opp_color)

                severity = _compute_severity(delta)
                board_description = describe_board(board_before, mover_color)

                # Check opponent's best response to the user's move (refutation) — only for blunders
                if is_blunder:
                    refutation_move = refutation_pv[0] if refutation_pv else None
                    if refutation_move:
                        if board_after.is_capture(refutation_move):
                            captured_piece = board_after.piece_at(refutation_move.to_square)
                            if captured_piece and captured_piece.color == mover_color:
                                piece_name = chess.piece_name(captured_piece.piece_type).title()
                                color_name = "White" if mover_color == chess.WHITE else "Black"
                                square_name = chess.square_name(refutation_move.to_square)
                                tactical_alert = f"CRITICAL: Your move allowed the opponent to immediately capture your {color_name} {piece_name} on {square_name}."

                # --- Generate SVG with Arrows ---
                arrows = []
                if is_blunder:
                    # Arrow for the move played (Mistake) - Red
                    arrows.append(chess.svg.Arrow(node.move.from_square, node.move.to_square, color="#d40000cc"))
                else:
                    # Arrow for the move played (Neutral) - Yellow
                    arrows.append(chess.svg.Arrow(node.move.from_square, node.move.to_square, color="#ccaa00cc"))

                # Arrow for the best move (Engine) - Green for blunders, Blue for missed chances
                if engine_best_move:
                    arrow_color = "#008800cc" if is_blunder else "#0066ddcc"
                    arrows.append(chess.svg.Arrow(engine_best_move.from_square, engine_best_move.to_square, color=arrow_color))

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
                    refutation_line=refutation_line if is_blunder else "",
                    mate_in=mate_in,
                    tactic_type=tactic_type,
                    board_description=board_description,
                    moment_type=moment_type,
                    severity=severity,
                    best_line=best_line if not is_blunder else "",
                )

                moments.append(moment)
                label = "Blunder" if is_blunder else "Missed chance"
                logger.info(f"{label} found for {hero_username}: {moment.move_played_san} (Delta: {delta}, {moment_type}/{severity})")

        return moments, metadata
