"""Unit tests for classify_tactic() and classify_moment() in engine.py."""
import pytest
import chess
from chess_tools.analysis.engine import (
    classify_tactic,
    classify_moment,
    _compute_severity,
    BLUNDER_CP,
    MISSED_CHANCE_CP,
    WINNING_THRESHOLD,
)


def _make_pv(board: chess.Board, san_moves: list[str]) -> list[chess.Move]:
    """Convert a list of SAN strings to Move objects on a copy of the board."""
    b = board.copy()
    moves = []
    for san in san_moves:
        m = b.parse_san(san)
        moves.append(m)
        b.push(m)
    return moves


# ---------------------------------------------------------------------------
# classify_tactic tests — one per tactic type
# ---------------------------------------------------------------------------

class TestClassifyTactic:
    def test_forced_mate(self):
        # Scholar's mate setup: after Black blunders with Na5, White plays Qxf7#
        # mate_in=1 and king is NOT on back rank (e8 rank 7 for Black is back rank, but
        # Qxf7# doesn't trap on back rank in the usual pattern).
        # Use a mid-board mate to ensure it's forced_mate, not back_rank_mate.
        # White queen mates on f7, Black king on e8 — king IS on back rank.
        # So let's just test with mate_in=5 and empty PV (no back-rank check possible).
        board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        result = classify_tactic(board, [], mate_in=5, mover_color=chess.WHITE)
        assert result == "forced_mate"

    def test_forced_mate_expanded_threshold(self):
        # Mate in 7 should still be forced_mate (threshold expanded to 9)
        board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        result = classify_tactic(board, [], mate_in=7, mover_color=chess.WHITE)
        assert result == "forced_mate"

    def test_back_rank_mate(self):
        # Classic back-rank: Black king on g8, pawns f7 g7 h7, White Rook on a1.
        # White to move, plays Ra8# — king trapped on back rank.
        # mover_color = BLACK (the one who blundered), it's White's turn to refute.
        board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R3K3 w - - 0 1")
        pv = _make_pv(board, ["Ra8"])
        result = classify_tactic(board, pv, mate_in=1, mover_color=chess.BLACK)
        assert result == "back_rank_mate"

    def test_hanging_piece(self):
        # White knight on d5 undefended. Black to move, captures Nxd5 (Black knight from f6).
        # mover_color = WHITE (who blundered), board_after has Black to move.
        board = chess.Board("r1bqkb1r/pppppppp/5n2/3N4/8/8/PPPPPPPP/R1BQKBNR b KQkq - 0 1")
        pv = _make_pv(board, ["Nxd5"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result == "hanging_piece"

    def test_hanging_pawn(self):
        # White pawn on e5 undefended. Black pawn on d6 can capture dxe5.
        # Minimal position to avoid pin detection side-effects.
        board = chess.Board("4k3/8/3p4/4P3/8/8/8/4K3 b - - 0 1")
        pv = _make_pv(board, ["dxe5"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result == "hanging_pawn"

    def test_fork(self):
        # White knight on d5, Black king on e8, Black rook on a8.
        # White plays Nc7+ forking king and rook. mover_color = BLACK.
        board = chess.Board("r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1")
        pv = _make_pv(board, ["Nc7"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.BLACK)
        assert result == "fork"

    def test_pin(self):
        # Black bishop on f8 moves to b4, NEWLY pinning White knight on c3 to king on e1.
        # Black to move. mover_color = WHITE.
        board = chess.Board("4kb2/8/8/8/8/2N5/8/4K3 b - - 0 1")
        pv = _make_pv(board, ["Bb4"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result == "pin"

    def test_losing_exchange(self):
        # White rook on e4 defended by White pawn on d3.
        # Black knight on f6 captures Nxe4. Knight(3) captures defended Rook(5).
        # attacker_val(3) < captured_val(5) => losing_exchange for White.
        board = chess.Board("4k3/8/5n2/8/4R3/3P4/8/4K3 b - - 0 1")
        pv = _make_pv(board, ["Nxe4"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result == "losing_exchange"

    def test_trapped_piece(self):
        # White knight on a1, White pawns on b3 and c2 block escape squares.
        # Black rook on a2 attacks the knight. After any Black move, knight is trapped.
        board = chess.Board("4k3/8/8/8/8/1P6/r1P5/N3K3 b - - 0 1")
        pv = _make_pv(board, ["Ke7"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result == "trapped_piece"

    def test_positional_fallback(self):
        # A quiet move that doesn't trigger any tactic pattern
        board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
        pv = _make_pv(board, ["d5"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result == "positional"

    def test_unknown_empty_pv(self):
        board = chess.Board()
        result = classify_tactic(board, [], mate_in=None, mover_color=chess.WHITE)
        assert result == "unknown"

    def test_discovered_attack(self):
        # White bishop on c1, White rook on d1, Black king on d8.
        # White plays Be3 — bishop leaves d-file, rook on d1 gives discovered check.
        board = chess.Board("3k4/8/8/8/8/8/8/2BRK3 w - - 0 1")
        pv = _make_pv(board, ["Be3"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.BLACK)
        assert result == "discovered_attack"

    def test_pin_must_be_new(self):
        # White knight on a2 already pinned to king on a1 by Black rook on a8.
        # Black plays Ke7 — the pin existed before, so it should NOT return "pin".
        board = chess.Board("r3k3/8/8/8/8/8/N7/K7 b - - 0 1")
        pv = _make_pv(board, ["Ke7"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result != "pin"

    def test_pin_with_different_board_state(self):
        # Pin is newly created by the refutation move. The baseline comparison
        # (board_after vs board_copy) correctly detects pins the refutation creates.
        board_after = chess.Board("4kb2/8/8/8/8/2N5/8/4K3 b - - 0 1")
        pv = _make_pv(board_after, ["Bb4"])
        result = classify_tactic(board_after, pv, mate_in=None, mover_color=chess.WHITE)
        assert result == "pin"

    def test_fork_must_have_new_targets(self):
        # Knight already attacks the king from d5. Moving Nc7 still attacks
        # king but ALSO attacks rook — at least one new target.
        board = chess.Board("r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1")
        pv = _make_pv(board, ["Nc7"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.BLACK)
        assert result == "fork"

    def test_discovered_attack_on_queen(self):
        # White rook on d1, White knight on d4 blocking. Black queen on d8.
        # After Ne6 (knight moves off d-file), rook on d1 attacks queen on d8.
        board = chess.Board("3q4/4k3/8/8/3N4/8/8/3RK3 w - - 0 1")
        pv = _make_pv(board, ["Ne6"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.BLACK)
        assert result == "discovered_attack"

    def test_skewer_through_king(self):
        # Classic file skewer: Black rook on a8 moves to a6, creating a skewer
        # through White king on a3 to White queen on a1.
        # mover_color = WHITE (the side being skewered).
        board = chess.Board("r3k3/8/8/8/8/K7/8/Q7 b - - 0 1")
        pv = _make_pv(board, ["Ra6"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result == "skewer"

    def test_skewer_bishop_not_on_rank(self):
        # Regression: bishop should NOT be detected as skewering along a file.
        # White bishop on a1 moves to b2. Black knight on b5 and Black rook on b8
        # are on the b-file — but a bishop can't attack along a file.
        board = chess.Board("1r6/8/8/1n6/8/8/8/B3K2k w - - 0 1")
        pv = _make_pv(board, ["Bb2"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.BLACK)
        assert result != "skewer"

    def test_defended_piece_not_hanging(self):
        # White rook on e4 defended by White rook on e1. Black queen captures Qxe4.
        # Queen(9) takes defended Rook(5). Attacker is MORE valuable than captured.
        # This should NOT be "hanging_piece" — should fall through to other checks.
        board = chess.Board("4k3/8/8/8/4R2q/8/8/4RK2 b - - 0 1")
        pv = _make_pv(board, ["Qxe4"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result != "hanging_piece"


# ---------------------------------------------------------------------------
# classify_moment tests
# ---------------------------------------------------------------------------

class TestClassifyMoment:
    def test_blunder_position_collapses(self):
        # Position goes from +50 to -300 (played_eval < -100, swing >= 200)
        result = classify_moment(best_eval=50, played_eval=-300, best_mate_in=None, played_mate_in=None)
        assert result is not None
        assert result[0] == "blunder"
        assert result[1] == "major"

    def test_missed_mate_short(self):
        # Had mate in 3 but didn't play it
        result = classify_moment(best_eval=10000, played_eval=200, best_mate_in=3, played_mate_in=None)
        assert result is not None
        assert result[0] == "missed_mate"
        assert result[1] == "critical"

    def test_missed_mate_still_mates(self):
        # Had mate in 3, played mate in 5 — still finding mate, so not missed
        result = classify_moment(best_eval=10000, played_eval=10000, best_mate_in=3, played_mate_in=5)
        # played_mate_in is not None, so missed_mate doesn't trigger; delta=0 so nothing triggers
        assert result is None

    def test_missed_chance(self):
        # Winning position (+500), played neutral move keeping +200 (swing=300, played_eval >= -100)
        result = classify_moment(best_eval=500, played_eval=200, best_mate_in=None, played_mate_in=None)
        assert result is not None
        assert result[0] == "missed_chance"
        assert result[1] == "major"

    def test_below_threshold_no_flag(self):
        # Small swing, position stays fine — not flagged
        result = classify_moment(best_eval=100, played_eval=50, best_mate_in=None, played_mate_in=None)
        assert result is None

    def test_missed_mate_beyond_threshold(self):
        # Had mate in 8 (> MISSED_MATE_MOVES=5) but didn't play it
        # Swing is huge but played_eval is +200 (not < -100), so blunder check fails.
        # best_eval >= WINNING_THRESHOLD and swing >= MISSED_CHANCE_CP, played_eval >= -100 => missed_chance
        result = classify_moment(best_eval=10000, played_eval=200, best_mate_in=8, played_mate_in=None)
        assert result is not None
        assert result[0] == "missed_chance"

    def test_large_swing_but_still_positive(self):
        # best=600, played=200, swing=400. played_eval >= -100, best_eval >= 200 => missed_chance
        result = classify_moment(best_eval=600, played_eval=200, best_mate_in=None, played_mate_in=None)
        assert result is not None
        assert result[0] == "missed_chance"
        assert result[1] == "major"


# ---------------------------------------------------------------------------
# _compute_severity tests
# ---------------------------------------------------------------------------

class TestComputeSeverity:
    def test_critical(self):
        assert _compute_severity(-600) == "critical"

    def test_major(self):
        assert _compute_severity(-350) == "major"

    def test_minor(self):
        assert _compute_severity(-200) == "minor"

    def test_positive_swing(self):
        assert _compute_severity(100) == "minor"
