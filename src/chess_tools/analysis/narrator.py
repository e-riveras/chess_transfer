from abc import ABC, abstractmethod
import logging
import chess
from chess_tools.lib.models import CrucialMoment
from typing import List

logger = logging.getLogger("chess_transfer")

class AnalysisNarrator(ABC):
    """Abstract base class for LLM narrators."""
    @abstractmethod
    def explain_mistake(self, moment: CrucialMoment) -> str:
        """Generates an explanation for a single mistake."""
        pass

    @abstractmethod
    def summarize_game(self, explanations: List[str]) -> str:
        """Generates a summary of the game based on explanations."""
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
        user_won = (moment.game_result == "1-0" and moment.hero_color == chess.WHITE) or \
                   (moment.game_result == "0-1" and moment.hero_color == chess.BLACK)
        
        if user_won and moment.eval_after < -100:
            context_note = "\n**Context:** The user ultimately WON this game, but this move put them in a losing position engine-wise. Frame the commentary as: 'You were objectively lost here, but this move might have set a practical trap.'"

        # Tactical Alert Logic for Prompt
        tactical_instruction = ""
        if moment.tactical_alert:
            tactical_instruction = (
                f"TACTICAL ALERT: {moment.tactical_alert}\n"
                f"CRITICAL INSTRUCTION: You MUST ignore generic positional advice. "
                f"Start your response with 'BLUNDER: You hung your [Piece Name]. The opponent can simply take it with [Move].' "
                f"Do not use soft language."
            )

        prompt = (
            f"You are a strict Chess Coach.\n\n"
            f"POSITION (before the mistake):\n"
            f"FEN: {moment.fen}\n"
            f"{moment.board_description}\n\n"
            f"WHAT HAPPENED:\n"
            f"- Player played: {moment.move_played_san}\n"
            f"- Eval swing: {moment.eval_swing} centipawns (negative = bad for player)\n"
            f"- Current eval: {moment.eval_after} centipawns\n"
            f"- Engine best move: {moment.best_move_san}\n"
            f"- Best line after {moment.best_move_san}: {moment.pv_line}\n"
            f"- Tactic type: {moment.tactic_type}\n"
            f"- Game result: {moment.game_result}\n"
            f"{context_note}\n"
            f"{tactical_instruction}\n\n"
            f"WHAT THE OPPONENT CAN FORCE AFTER {moment.move_played_san}:\n"
            f"{moment.refutation_line if moment.refutation_line else 'unclear'}\n"
            f"{f'This leads to forced mate in {moment.mate_in}.' if moment.mate_in else ''}\n\n"
            f"Task: Explain briefly why the player's move was a mistake and why "
            f"{moment.best_move_san} is superior.\n\n"
            f"Constraints:\n"
            f"1. Reference the refutation moves by name (e.g. 'after Bxg3+...'). "
            f"Do NOT invent moves beyond those listed in the refutation line above.\n"
            f"2. Do NOT use conversational filler ('Okay', 'Let's look at', 'In this position').\n"
            f"3. Start IMMEDIATELY with the chess concept or piece name.\n"
            f"4. Be direct. Example: 'Rc2 walks into Bxg3+, exploiting the exposed king on h2...'\n"
            f"5. Do NOT calculate variations yourself beyond what the engine data provides."
        )
        try:
            response = self.client.models.generate_content(
                model=self.model_name, contents=prompt
            )
            return response.text
        except Exception as e:
            logger.error(f"LLM Generation failed: {e}")
            return "Analysis unavailable due to LLM error."

    def summarize_game(self, explanations: List[str]) -> str:
        if not explanations:
            return "No mistakes analyzed, so no summary available."
            
        combined_text = "\n".join([f"- {exp}" for exp in explanations])
        
        prompt = (
            f"You are a Chess Coach. Here is the analysis of the user's mistakes in this game:\n"
            f"{combined_text}\n\n"
            f"Task: Summarize the user's performance into a section titled '## 3 Key Takeaways'.\n"
            f"1. Identify the recurring theme of their errors (e.g., 'Passive Piece Play', 'Weakening Pawn Moves').\n"
            f"2. Provide 3 bullet points of actionable advice for their next game.\n"
            f"3. Keep it concise and encouraging."
        )
        try:
            response = self.client.models.generate_content(
                model=self.model_name, contents=prompt
            )
            return response.text
        except Exception as e:
            logger.error(f"LLM Summary Generation failed: {e}")
            return "Summary unavailable due to LLM error."

class MockNarrator(AnalysisNarrator):
    """Mock narrator for testing without API keys."""
    def explain_mistake(self, moment: CrucialMoment) -> str:
        refutation = f" Opponent can play {moment.refutation_line}." if moment.refutation_line else ""
        return (
            f"[Mock] {moment.move_played_san} drops eval by {moment.eval_swing}cp "
            f"({moment.tactic_type}).{refutation} Best was {moment.best_move_san}."
        )

    def summarize_game(self, explanations: List[str]) -> str:
        return "## 3 Key Takeaways\n\n- Mock Summary Point 1\n- Mock Summary Point 2\n- Mock Summary Point 3"
