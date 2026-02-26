from dataclasses import dataclass
from typing import Optional
import chess

@dataclass
class CrucialMoment:
    """
    Represents a significant moment in a chess game where the evaluation changed drastically.

    Attributes:
        fen: The FEN string of the position BEFORE the move.
        move_played_san: Standard Algebraic Notation of the move played (e.g., "Nf3").
        move_played_uci: Universal Chess Interface notation of the move (e.g., "g1f3").
        best_move_san: SAN of the engine's preferred move.
        best_move_uci: UCI of the engine's preferred move.
        eval_swing: The change in evaluation in centipawns (after - before). Negative means loss.
        eval_after: The evaluation of the position after the move (centipawns).
        pv_line: The Principal Variation (best continuation) according to the engine.
        game_result: The result of the game (e.g., "1-0", "0-1", "1/2-1/2").
        hero_color: The color played by the user (chess.WHITE, chess.BLACK, or None).
        explanation: Natural language explanation of the mistake (populated by LLM).
        image_url: URL to a static image of the position.
        svg_content: Raw SVG content with arrows highlighting the mistake and correction.
        tactical_alert: Warning message if the move allows an immediate capture.
    """
    fen: str
    move_played_san: str
    move_played_uci: str
    best_move_san: str
    best_move_uci: str
    eval_swing: int
    eval_after: int
    pv_line: str
    game_result: str
    hero_color: Optional[chess.Color]
    explanation: Optional[str] = None
    image_url: Optional[str] = None
    svg_content: Optional[str] = None
    tactical_alert: Optional[str] = None
    refutation_line: str = ""
    mate_in: Optional[int] = None
    tactic_type: str = "unknown"
    board_description: str = ""
    moment_type: str = "blunder"        # "blunder" | "missed_chance" | "missed_mate"
    severity: str = "minor"             # "critical" | "major" | "minor"
    best_line: str = ""                 # SAN moves of best PV (for missed chances)
    lichess_url: Optional[str] = None
    half_move_number: Optional[int] = None
