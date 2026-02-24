"""Unit tests for classify_tactic() and classify_moment() in engine.py."""
import pytest
import chess
from chess_tools.analysis.engine import (
    classify_tactic,
    classify_moment,
    _compute_severity,
    BLUNDER_THRESHOLD_CP,
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
        board = chess.Board("rnbqkbnr/ppp1pppp/3p4/4P3/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
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
        # White knight on a2 pinned to king on a1 by Black rook on a8.
        # Black to move. mover_color = WHITE.
        board = chess.Board("r3k3/8/8/8/8/8/N7/K7 b - - 0 1")
        pv = _make_pv(board, ["Ke7"])
        result = classify_tactic(board, pv, mate_in=None, mover_color=chess.WHITE)
        assert result == "pin"

    def test_losing_exchange(self):
        # White knight on e4 defended by White pawn on d3.
        # Black queen on h4 captures Qxe4. Queen(9) captures defended Knight(3).
        # attacker_val(9) > captured_val(3) => losing_exchange.
        board = chess.Board("4k3/8/8/8/4N2q/3P4/8/4K3 b - - 0 1")
        pv = _make_pv(board, ["Qxe4"])
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


# ---------------------------------------------------------------------------
# classify_moment tests
# ---------------------------------------------------------------------------

class TestClassifyMoment:
    def test_blunder_large_negative_delta(self):
        result = classify_moment(cp_before=0, cp_after=-300, best_mate_in=None, played_mate_in=None)
        assert result == "blunder"

    def test_missed_mate_short(self):
        # Had mate in 3 but didn't play it
        result = classify_moment(cp_before=10000, cp_after=200, best_mate_in=3, played_mate_in=None)
        assert result == "missed_mate"

    def test_missed_mate_still_mates(self):
        # Had mate in 3, played mate in 5 — still finding mate, so not missed
        result = classify_moment(cp_before=10000, cp_after=10000, best_mate_in=3, played_mate_in=5)
        assert result == "blunder"  # delta = 0, not < -threshold, falls through

    def test_missed_chance(self):
        # Winning position (+300), played neutral move losing 200cp
        result = classify_moment(cp_before=300, cp_after=100, best_mate_in=None, played_mate_in=None)
        assert result == "missed_chance"

    def test_small_delta_no_flag(self):
        # Small delta, not winning enough for missed_chance
        result = classify_moment(cp_before=100, cp_after=50, best_mate_in=None, played_mate_in=None)
        assert result == "blunder"  # falls through to default

    def test_missed_mate_longer(self):
        # Had mate in 8 (> MISSED_MATE_MOVES=5) but didn't play it
        result = classify_moment(cp_before=10000, cp_after=200, best_mate_in=8, played_mate_in=None)
        # best_mate_in=8 > 5, skips first case. delta = -9800 < -250, so blunder fires.
        assert result == "blunder"


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
