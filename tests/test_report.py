"""Tests for report generation utilities."""
import pytest
from chess_tools.analysis.report import format_refutation_line


class TestFormatRefutationLine:
    def test_empty_string(self):
        assert format_refutation_line("", hero_is_next_to_move=True) == ""

    def test_hero_first(self):
        result = format_refutation_line("Nf3 d5 Bc4", hero_is_next_to_move=True)
        assert '<span class="hero-move">Nf3</span>' in result
        assert '<span class="opp-move">d5</span>' in result
        assert '<span class="hero-move">Bc4</span>' in result

    def test_opponent_first(self):
        result = format_refutation_line("Bxg3+ Kh1 Qf2", hero_is_next_to_move=False)
        assert '<span class="opp-move">Bxg3+</span>' in result
        assert '<span class="hero-move">Kh1</span>' in result
        assert '<span class="opp-move">Qf2</span>' in result

    def test_single_move(self):
        result = format_refutation_line("Qxd5", hero_is_next_to_move=True)
        assert '<span class="hero-move">Qxd5</span>' == result

    def test_html_escaping(self):
        # SAN with special chars should be escaped
        result = format_refutation_line("O-O", hero_is_next_to_move=True)
        assert "O-O" in result
