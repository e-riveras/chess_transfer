from abc import ABC, abstractmethod
import logging
import chess
from src.models import CrucialMoment
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
            f"You are a strict Chess Coach.\n"
            f"Position FEN: {moment.fen}\n"
            f"The player played: {moment.move_played_san}\n"
            f"Stockfish Evaluation change: {moment.eval_swing} centipawns (Negative means bad).\n"
            f"Current Evaluation: {moment.eval_after} centipawns.\n"
            f"Stockfish suggests the best move was: {moment.best_move_san}\n"
            f"The continuation following the best move is: {moment.pv_line}\n"
            f"Game Result: {moment.game_result}\n"
            f"{context_note}\n"
            f"{tactical_instruction}\n\n"
            f"Task: Explain briefly and conceptually why the player's move was a mistake and why the engine's recommendation is superior.\n"
            f"Constraints:\n"
            f"1. Do NOT use conversational filler (e.g., 'Okay', 'Let's look at', 'In this position').\n"
            f"2. Start the response IMMEDIATELY with the chess concept or the piece name.\n"
            f"3. Be direct and ruthless. Example: 'f3 is a positional error that weakens the King...'.\n"
            f"4. Do NOT calculate variations yourself; trust the engine data provided."
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
        return f"[Mock Analysis] The move {moment.move_played_san} drops evaluation by {moment.eval_swing}. {moment.best_move_san} was better."

    def summarize_game(self, explanations: List[str]) -> str:
        return "## 3 Key Takeaways\n\n- Mock Summary Point 1\n- Mock Summary Point 2\n- Mock Summary Point 3"
