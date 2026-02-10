#!/usr/bin/env python3
"""
chess_transfer/book_to_study.py

Convert chess books (PDF/EPUB) to Lichess study chapters.

Usage:
    python -m chess_transfer.book_to_study --pdf book.pdf --study-id xyz123
    python -m chess_transfer.book_to_study --epub book.epub --study-id xyz123
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import List, Dict, Optional

from dotenv import load_dotenv

try:
    import berserk
    import chess.pgn
    from PyPDF2 import PdfReader
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
    DEPS_AVAILABLE = True
except ImportError as e:
    DEPS_AVAILABLE = False
    MISSING_DEP = str(e)

# Load environment variables from .env file
load_dotenv()


class BookParser:
    """Parse chess books from various formats."""

    @staticmethod
    def parse_pdf(pdf_path: str) -> str:
        """
        Extract text from PDF file.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted text content
        """
        if not Path(pdf_path).exists():
            raise FileNotFoundError(f"File not found: {pdf_path}")

        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text

    @staticmethod
    def parse_epub(epub_path: str) -> str:
        """
        Extract text from EPUB file.

        Args:
            epub_path: Path to EPUB file

        Returns:
            Extracted text content
        """
        if not Path(epub_path).exists():
            raise FileNotFoundError(f"File not found: {epub_path}")

        book = epub.read_epub(epub_path)
        text = ""

        # Follow the spine to maintain correct reading order
        for item_id, linear in book.spine:
            item = book.get_item_with_id(item_id)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                # Add some spacing between documents
                text += soup.get_text() + "\n\n"

        # Fallback if spine is empty or didn't yield text
        if not text.strip():
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    text += soup.get_text() + "\n\n"

        return text

    @staticmethod
    def extract_chapters(text: str, min_content_length: int = 20) -> List[Dict]:
        """
        Split text into logical chapters.

        Detects various chapter header formats common in chess books.

        Args:
            text: Full book text
            min_content_length: Minimum chars for valid chapter content

        Returns:
            List of dicts with 'title' and 'content' keys
        """
        # Patterns for chapter headers
        patterns = [
            # "Chapter 1: Title" or "Chapter One"
            r'(?:^|\n)Chapter\s+(?:\d+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve|Thirteen|Fourteen|Fifteen)[^\n]*',
            # "CHAPTER 1: TITLE"
            r'(?:^|\n)CHAPTER\s+(?:\d+|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN)[^\n]*',
            # "Part I: Title"
            r'(?:^|\n)Part\s+(?:[IVX\d]+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)[^\n]*',
            # Numbered sections: "1. Title" at line start with minimum length
            r'(?:^|\n)\d+\.\s+[A-Z][^\n]{5,100}',
            # Markdown headers
            r'(?:^|\n)#{1,3}\s+[^\n]+',
        ]

        # Combine into one pattern
        combined_pattern = f"(?:{'|'.join(patterns)})"
        
        # Find all matches
        matches = list(re.finditer(combined_pattern, text, flags=re.MULTILINE))
        
        if not matches:
            return [{'title': 'Full Book', 'content': text}]

        chapters = []
        
        # Handle Introduction (text before first chapter)
        intro_text = text[:matches[0].start()].strip()
        if len(intro_text) > 100:
            chapters.append({
                'title': 'Introduction',
                'content': intro_text
            })

        # Extract chapters based on match positions
        for i in range(len(matches)):
            start_pos = matches[i].start()
            header_end = matches[i].end()
            end_pos = matches[i+1].start() if i + 1 < len(matches) else len(text)
            
            title = text[start_pos:header_end].strip()
            content = text[header_end:end_pos].strip()
            
            if len(content) >= min_content_length:
                chapters.append({
                    'title': title,
                    'content': content
                })
        
        # If we found very few chapters, maybe the pattern was too strict
        # (Already handled by returning intro + whatever we found)
        
        return chapters if chapters else [{'title': 'Full Book', 'content': text}]


class NotationParser:
    """Parse chess notation from text."""

    # Pattern for standard algebraic notation moves
    MOVE_PATTERN = r'(?:\d+\.+\s*)?(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O-O|O-O|0-0-0|0-0)'

    @staticmethod
    def extract_lines_from_chapter(text: str, chapter_title: str) -> List[Dict]:
        """
        Extract multiple lines/variations from a chapter.

        Returns list of dicts with 'title' and 'pgn' keys.
        Each major branch becomes its own entry.
        """
        import chess

        move_chars = r'[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O-O|O-O|0-0-0|0-0'
        seq_pattern = rf'(\d+)\.\s*({move_chars})([!?]*)\s+({move_chars})([!?]*)'
        white_pattern = rf'(\d+)\.\s*({move_chars})([!?]*)'
        black_pattern = rf'(\d+)\.{{2,3}}\s*({move_chars})([!?]*)'

        lines = []

        # First, extract the main line
        main_line_result = NotationParser._extract_main_line_with_positions(text)
        if main_line_result['moves']:
            main_pgn = NotationParser._build_pgn(
                chapter_title,
                main_line_result['moves'],
                main_line_result['comments']
            )
            lines.append({
                'title': chapter_title,
                'pgn': main_pgn
            })

            # Now find major branches
            branch_points = NotationParser._find_branch_points(
                text,
                main_line_result['last_position'],
                main_line_result['move_count'],
                main_line_result['moves'],
                main_line_result['comments']
            )

            for branch in branch_points:
                branch_pgn = NotationParser._build_pgn(
                    f"{chapter_title} - {branch['name']}",
                    branch['moves'],
                    branch['comments']
                )
                lines.append({
                    'title': f"{chapter_title} - {branch['name']}",
                    'pgn': branch_pgn
                })
        else:
            # Fallback: just use the whole text as one chapter
            lines.append({
                'title': chapter_title,
                'pgn': NotationParser.text_to_pgn(text, chapter_title)
            })

        return lines

    @staticmethod
    def _extract_main_line_with_positions(text: str) -> Dict:
        """Extract main line and track positions for branch detection."""
        import chess

        move_chars = r'[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O-O|O-O|0-0-0|0-0'
        seq_pattern = rf'(\d+)\.\s*({move_chars})([!?]*)\s+({move_chars})([!?]*)'
        white_pattern = rf'(\d+)\.\s*({move_chars})([!?]*)'
        black_pattern = rf'(\d+)\.{{2,3}}\s*({move_chars})([!?]*)'

        board = chess.Board()
        moves = []
        comments = {}
        last_end = 0
        expected_num = 1
        waiting_for_black = False

        pos = 0
        while pos < len(text):
            # If waiting for Black's move
            if waiting_for_black:
                match = re.match(black_pattern, text[pos:])
                if match:
                    num = int(match.group(1))
                    move_str = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    ann = match.group(3) or ''

                    if num == expected_num:
                        try:
                            move = board.parse_san(move_str)
                            between = text[last_end:pos].strip()
                            if between:
                                comments[len(moves)] = between

                            moves.append(f"{move_str}{ann}")
                            board.push(move)
                            expected_num += 1
                            waiting_for_black = False
                            last_end = pos + match.end()
                            pos = last_end
                            continue
                        except:
                            pass

            # Try White+Black sequence
            match = re.match(seq_pattern, text[pos:])
            if match:
                num = int(match.group(1))
                if num == expected_num:
                    white_move = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    white_ann = match.group(3) or ''
                    black_move = match.group(4).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    black_ann = match.group(5) or ''

                    between = text[last_end:pos].strip()
                    immediate = text[max(0, pos-80):pos].lower()
                    if 'instead' in immediate or ' or ' in immediate or 'after' in immediate:
                        pos += 1
                        continue

                    try:
                        w = board.parse_san(white_move)
                        board.push(w)
                        b = board.parse_san(black_move)
                        board.push(b)

                        if between:
                            comments[len(moves)] = between

                        moves.append(f"{num}. {white_move}{white_ann}")
                        moves.append(f"{black_move}{black_ann}")
                        expected_num += 1
                        waiting_for_black = False
                        last_end = pos + match.end()
                        pos = last_end
                        continue
                    except:
                        pass

            # Try White only move
            match = re.match(white_pattern, text[pos:])
            if match and not waiting_for_black:
                num = int(match.group(1))
                if num == expected_num:
                    white_move = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    white_ann = match.group(3) or ''

                    between = text[last_end:pos].strip()
                    immediate = text[max(0, pos-80):pos].lower()
                    if 'instead' in immediate or ' or ' in immediate or 'after' in immediate:
                        pos += 1
                        continue

                    try:
                        w = board.parse_san(white_move)
                        board.push(w)

                        if between:
                            comments[len(moves)] = between

                        moves.append(f"{num}. {white_move}{white_ann}")
                        waiting_for_black = True
                        last_end = pos + match.end()
                        pos = last_end
                        continue
                    except:
                        pass

            pos += 1

        # Add remaining text as final comment
        remaining = text[last_end:].strip()
        if remaining:
            comments[len(moves)] = remaining

        return {
            'moves': moves,
            'comments': comments,
            'last_position': board.fen(),
            'move_count': expected_num - 1,
            'board': board
        }

    @staticmethod
    def _find_branch_points(text: str, main_fen: str, main_move_count: int, main_moves: List[str] = None, main_comments: Dict[int, str] = None) -> List[Dict]:
        """Find major variations that branch from the main line."""
        import chess

        branches = []
        move_chars = r'[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O-O|O-O|0-0-0|0-0'

        # Look for explicit Black alternatives: "N...move" where N <= main_move_count
        black_alt_pattern = rf'(\d+)\.{{2,3}}\s*({move_chars})([!?]*)'

        seen_branches = set()

        for match in re.finditer(black_alt_pattern, text):
            num = int(match.group(1))
            move_str = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')

            # Only consider branches from positions we've passed
            if num > main_move_count or num < 3:
                continue

            branch_key = f"{num}...{move_str}"
            if branch_key in seen_branches:
                continue

            # Check context - is this presented as an alternative?
            pre_context = text[max(0, match.start()-100):match.start()].lower()
            if not any(marker in pre_context for marker in ['instead', 'better', 'also', 'alternative', ' or ']):
                continue

            seen_branches.add(branch_key)

            # Try to trace this variation
            branch_result = NotationParser._trace_branch(text, match.start(), num, move_str, main_moves, main_comments)
            if branch_result and len(branch_result['moves']) >= 4:
                branches.append({
                    'name': f"With {num}...{move_str}",
                    'moves': branch_result['moves'],
                    'comments': branch_result['comments']
                })

        # Limit to top 5 branches to avoid too many chapters
        return branches[:5]

    @staticmethod
    def _trace_branch(text: str, start_pos: int, start_num: int, first_move: str, main_moves: List[str] = None, main_comments: Dict[int, str] = None) -> Optional[Dict]:
        """Trace a variation from a given starting point."""
        import chess

        move_chars = r'[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O-O|O-O|0-0-0|0-0'
        seq_pattern = rf'(\d+)\.\s*({move_chars})([!?]*)\s+({move_chars})([!?]*)'
        white_pattern = rf'(\d+)\.\s*({move_chars})([!?]*)'
        black_pattern = rf'(\d+)\.{{2,3}}\s*({move_chars})([!?]*)'

        # Find the actual match to get precise position
        first_match = re.search(rf'{start_num}\.{{2,3}}\s*{re.escape(first_move)}', text[start_pos:start_pos+50])
        if not first_match:
            return None

        moves = []
        comments = {}

        # Include main line moves up to the branch point, with their comments
        if main_moves:
            # Calculate how many half-moves to include
            # Branch at move N for Black means we need moves 1 through N for White
            half_moves_needed = (start_num - 1) * 2 + 1  # Up to White's move N

            move_idx = 0
            while move_idx < len(main_moves) and move_idx < half_moves_needed:
                # Include comment from main line if available
                if main_comments and move_idx in main_comments:
                    comments[len(moves)] = main_comments[move_idx]

                m = main_moves[move_idx]
                moves.append(m)
                move_idx += 1

        # Now add the branch move
        moves.append(f"{start_num}... {first_move}")

        # Get context before this branch point for the branch move
        pre_context = text[max(0, start_pos-200):start_pos].strip()
        if pre_context:
            last_period = pre_context.rfind('.')
            if last_period > len(pre_context) - 150:
                pre_context = pre_context[last_period+1:].strip()
            if pre_context:
                comments[len(moves)-1] = pre_context[-200:]

        expected_num = start_num + 1
        actual_start = start_pos + first_match.end()
        pos = actual_start
        last_end = actual_start

        # Trace forward - look for more moves in this variation
        max_search = min(len(text), start_pos + 5000)  # Increased search range

        while pos < max_search:
            # Try White+Black sequence
            match = re.match(seq_pattern, text[pos:])
            if match:
                num = int(match.group(1))
                if num == expected_num:
                    white_move = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    white_ann = match.group(3) or ''
                    black_move = match.group(4).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    black_ann = match.group(5) or ''

                    between = text[last_end:pos].strip()
                    if between:
                        comments[len(moves)] = between

                    moves.append(f"{num}. {white_move}{white_ann} {black_move}{black_ann}")
                    expected_num += 1
                    last_end = pos + match.end()
                    pos = last_end
                    continue
                elif num > expected_num + 1:
                    # Sequence broken, stop
                    break

            # Try White only
            match = re.match(white_pattern, text[pos:])
            if match:
                num = int(match.group(1))
                if num == expected_num:
                    white_move = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    white_ann = match.group(3) or ''

                    between = text[last_end:pos].strip()
                    if between:
                        comments[len(moves)] = between

                    moves.append(f"{num}. {white_move}{white_ann}")
                    last_end = pos + match.end()
                    pos = last_end
                    continue

            # Try explicit Black move
            match = re.match(black_pattern, text[pos:])
            if match:
                num = int(match.group(1))
                if num == expected_num - 1:  # Black's response to last White move
                    black_move = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    black_ann = match.group(3) or ''

                    between = text[last_end:pos].strip()
                    if between:
                        comments[len(moves)] = between

                    moves.append(f"{black_move}{black_ann}")
                    last_end = pos + match.end()
                    pos = last_end
                    continue

            pos += 1

        # Add trailing commentary
        if last_end < max_search:
            trailing = text[last_end:min(last_end+500, max_search)].strip()
            # Cut at next major break
            for marker in ['\n\n', 'Game ', 'Theory ']:
                idx = trailing.find(marker)
                if idx > 0:
                    trailing = trailing[:idx]
                    break
            if trailing:
                comments[len(moves)] = trailing

        return {'moves': moves, 'comments': comments} if len(moves) > 1 else None

    @staticmethod
    def _build_pgn(title: str, moves: List[str], comments: Dict[int, str]) -> str:
        """Build PGN string from moves and comments."""
        pgn = f'[Event "{title}"]\n'
        pgn += '[Site "Chess Book"]\n'
        pgn += '[White "Study"]\n'
        pgn += '[Black "Analysis"]\n'
        pgn += '[Result "*"]\n\n'

        parts = []
        for i, move in enumerate(moves):
            if i in comments:
                comment = re.sub(r'\s+', ' ', comments[i])
                comment = comment.replace('{', '(').replace('}', ')')
                # Allow longer comments for better context
                if len(comment) > 2000:
                    comment = comment[:1997] + "..."
                parts.append(f'{{{comment}}}')
            parts.append(move)

        # Add final comment if present
        if len(moves) in comments:
            comment = re.sub(r'\s+', ' ', comments[len(moves)])
            comment = comment.replace('{', '(').replace('}', ')')
            if len(comment) > 3000:
                comment = comment[:2997] + "..."
            parts.append(f'{{{comment}}}')

        pgn += ' '.join(parts) + ' *'
        return pgn

    @staticmethod
    def extract_games(text: str) -> List[str]:
        """
        Extract PGN-style notation sequences from text.

        Args:
            text: Text containing chess notation

        Returns:
            List of game notation strings
        """
        games = []
        lines = text.split('\n')
        current_game = []

        for line in lines:
            moves = re.findall(NotationParser.MOVE_PATTERN, line)
            if len(moves) >= 3:  # At least 3 moves to be considered a game
                current_game.append(line)
            elif current_game and not moves:
                # End of game sequence
                games.append('\n'.join(current_game))
                current_game = []

        if current_game:
            games.append('\n'.join(current_game))

        return games

    @staticmethod
    def text_to_pgn(text: str, chapter_title: str) -> str:
        """
        Convert book text to PGN format.

        Handles "1.c4 Nf6 2.Nc3 d6" format where Black's moves follow
        White's without explicit move numbers.

        Args:
            text: Chapter text content
            chapter_title: Title for the PGN Event header

        Returns:
            Valid PGN string
        """
        import chess

        # Build PGN with headers
        pgn = f'[Event "{chapter_title}"]\n'
        pgn += '[Site "Chess Book"]\n'
        pgn += '[White "Study"]\n'
        pgn += '[Black "Analysis"]\n'
        pgn += '[Result "*"]\n\n'

        move_chars = r'[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O-O|O-O|0-0-0|0-0'

        # Patterns for moves
        # White+Black together: "N.move move"
        seq_pattern = rf'(\d+)\.\s*({move_chars})([!?]*)\s+({move_chars})([!?]*)'
        # White only: "N.move"
        white_pattern = rf'(\d+)\.\s*({move_chars})([!?]*)'
        # Black explicit: "N...move"
        black_pattern = rf'(\d+)\.{{2,3}}\s*({move_chars})([!?]*)'

        board = chess.Board()
        parts = []
        last_end = 0
        expected_num = 1
        waiting_for_black = False

        pos = 0
        while pos < len(text):
            # If waiting for Black's move
            if waiting_for_black:
                # Try explicit Black move "N...move"
                match = re.match(black_pattern, text[pos:])
                if match:
                    num = int(match.group(1))
                    move_str = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    ann = match.group(3) or ''

                    if num == expected_num:
                        try:
                            move = board.parse_san(move_str)
                            between = text[last_end:pos].strip()
                            if between:
                                comment = re.sub(r'\s+', ' ', between)
                                comment = comment.replace('{', '(').replace('}', ')')
                                parts.append(f'{{{comment}}}')

                            parts.append(f'{move_str}{ann}')
                            board.push(move)
                            expected_num += 1
                            waiting_for_black = False
                            last_end = pos + match.end()
                            pos = last_end
                            continue
                        except:
                            pass

            # Try White+Black sequence
            match = re.match(seq_pattern, text[pos:])
            if match:
                num = int(match.group(1))
                if num == expected_num:
                    white_move = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    white_ann = match.group(3) or ''
                    black_move = match.group(4).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    black_ann = match.group(5) or ''

                    between = text[last_end:pos].strip()
                    # Skip if immediate context suggests variation (check last 80 chars)
                    immediate = text[max(0, pos-80):pos].lower()
                    if 'instead' in immediate or ' or ' in immediate or 'after' in immediate:
                        pos += 1
                        continue

                    try:
                        w = board.parse_san(white_move)
                        board.push(w)
                        b = board.parse_san(black_move)
                        board.push(b)

                        if between:
                            comment = re.sub(r'\s+', ' ', between)
                            comment = comment.replace('{', '(').replace('}', ')')
                            parts.append(f'{{{comment}}}')

                        parts.append(f'{num}. {white_move}{white_ann} {black_move}{black_ann}')
                        expected_num += 1
                        waiting_for_black = False
                        last_end = pos + match.end()
                        pos = last_end
                        continue
                    except:
                        pass

            # Try White only move
            match = re.match(white_pattern, text[pos:])
            if match and not waiting_for_black:
                num = int(match.group(1))
                if num == expected_num:
                    white_move = match.group(2).replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                    white_ann = match.group(3) or ''

                    between = text[last_end:pos].strip()
                    # Skip if immediate context suggests variation
                    immediate = text[max(0, pos-80):pos].lower()
                    if 'instead' in immediate or ' or ' in immediate or 'after' in immediate:
                        pos += 1
                        continue

                    try:
                        w = board.parse_san(white_move)
                        board.push(w)

                        if between:
                            comment = re.sub(r'\s+', ' ', between)
                            comment = comment.replace('{', '(').replace('}', ')')
                            parts.append(f'{{{comment}}}')

                        parts.append(f'{num}. {white_move}{white_ann}')
                        waiting_for_black = True
                        last_end = pos + match.end()
                        pos = last_end
                        continue
                    except:
                        pass

            pos += 1

        # Add remaining text
        remaining = text[last_end:].strip()
        if remaining:
            comment = re.sub(r'\s+', ' ', remaining)
            comment = comment.replace('{', '(').replace('}', ')')
            if comment:
                parts.append(f'{{{comment}}}')

        content = ' '.join(parts)

        if content and expected_num > 1:
            pgn += content + ' *'
        else:
            comment = re.sub(r'\s+', ' ', text)
            comment = comment.replace('{', '(').replace('}', ')')
            pgn += f'{{{comment[:45000]}}}\n\n*'

        return pgn


class LichessStudyUploader:
    """Upload chapters to Lichess study using berserk API."""

    def __init__(self, api_token: str):
        """
        Initialize with Lichess API token.

        Args:
            api_token: Lichess API token with study:write scope
        """
        if not DEPS_AVAILABLE:
            raise ImportError(f"Missing dependency: {MISSING_DEP}\n"
                            "Install with: pip install berserk python-chess PyPDF2 ebooklib beautifulsoup4")

        self.session = berserk.TokenSession(api_token)
        self.client = berserk.Client(session=self.session)

    def add_chapters(self, study_id: str, chapters: List[Dict], book_name: str) -> int:
        """
        Add chapters to existing Lichess study.

        Args:
            study_id: Existing Lichess study ID
            chapters: List of {'title': ..., 'pgn': ...}
            book_name: Name to prefix chapters with

        Returns:
            Number of successfully uploaded chapters
        """
        import time

        # Lichess has a 64 chapter limit per study
        MAX_CHAPTERS = 64
        if len(chapters) > MAX_CHAPTERS:
            print(f"Warning: {len(chapters)} chapters found, but Lichess limits studies to {MAX_CHAPTERS}.")
            print(f"Only the first {MAX_CHAPTERS} chapters will be uploaded.")
            chapters = chapters[:MAX_CHAPTERS]

        print(f"\nUploading '{book_name}' to study {study_id}")
        print(f"   {len(chapters)} chapters to add\n")

        success_count = 0
        for i, chapter in enumerate(chapters, 1):
            chapter_name = f"{book_name} - {chapter['title']}"
            # Lichess chapter names have a max length
            if len(chapter_name) > 100:
                chapter_name = chapter_name[:97] + "..."

            try:
                # Use import_pgn to add chapter to study
                self.client.studies.import_pgn(
                    study_id=study_id,
                    chapter_name=chapter_name,
                    pgn=chapter['pgn'],
                    orientation='white'
                )
                print(f"   [OK] [{i}/{len(chapters)}] {chapter_name}")
                success_count += 1
                
                # Small delay to avoid hitting rate limits (1 second)
                if i < len(chapters):
                    time.sleep(1.0)
                    
            except berserk.exceptions.ResponseError as e:
                print(f"   [FAIL] [{i}/{len(chapters)}] {chapter_name}: {e}")
                if "Rate limit" in str(e) or "429" in str(e):
                    print("   Rate limit hit. Waiting 60 seconds...")
                    time.sleep(60)
            except Exception as e:
                print(f"   [FAIL] [{i}/{len(chapters)}] {chapter_name}: {e}")

        print(f"\nDone! {success_count}/{len(chapters)} chapters uploaded")
        print(f"View at: https://lichess.org/study/{study_id}")
        return success_count


class ConfigManager:
    """Manage configuration like saved study IDs."""

    CONFIG_FILE = Path.home() / ".chess_transfer_config.json"

    @classmethod
    def load(cls) -> dict:
        """Load config from file."""
        if cls.CONFIG_FILE.exists():
            with open(cls.CONFIG_FILE) as f:
                return json.load(f)
        return {}

    @classmethod
    def save(cls, config: dict):
        """Save config to file."""
        with open(cls.CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)

    @classmethod
    def get_study_id(cls) -> Optional[str]:
        """Get saved default study ID."""
        return cls.load().get('default_study_id')

    @classmethod
    def set_study_id(cls, study_id: str):
        """Save study ID as default."""
        config = cls.load()
        config['default_study_id'] = study_id
        cls.save(config)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Convert chess books to Lichess study chapters',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m chess_transfer.book_to_study --pdf book.pdf --study-id abc123
  python -m chess_transfer.book_to_study --epub book.epub --study-id abc123 --save-study
  python -m chess_transfer.book_to_study --pdf book.pdf  # uses saved study ID
        """
    )
    parser.add_argument('--pdf', metavar='FILE', help='Path to PDF file')
    parser.add_argument('--epub', metavar='FILE', help='Path to EPUB file')
    parser.add_argument('--study-id', metavar='ID', help='Lichess study ID')
    parser.add_argument('--token', metavar='TOKEN', help='Lichess API token (or set LICHESS_TOKEN env var)')
    parser.add_argument('--book-name', metavar='NAME', help='Name for the book (auto-detected from filename if not provided)')
    parser.add_argument('--save-study', action='store_true', help='Save study ID as default for future runs')
    parser.add_argument('--dry-run', action='store_true', help='Parse and show chapters without uploading')
    parser.add_argument('--debug', action='store_true', help='Show extracted text sample for debugging')

    args = parser.parse_args()

    # Check dependencies
    if not DEPS_AVAILABLE:
        print(f"Error: Missing dependency: {MISSING_DEP}")
        print("\nInstall required packages:")
        print("  pip install berserk python-chess PyPDF2 ebooklib beautifulsoup4 lxml")
        return 1

    # Validate input file
    if not (args.pdf or args.epub):
        parser.error("Provide --pdf or --epub")

    book_path = args.pdf or args.epub
    if not Path(book_path).exists():
        print(f"Error: File not found: {book_path}")
        return 1

    # Get study ID (from args or saved config)
    study_id = args.study_id or ConfigManager.get_study_id()
    if not study_id and not args.dry_run:
        print("Error: No study ID provided")
        print("\nSetup:")
        print("  1. Create study at https://lichess.org/study")
        print("  2. Copy study ID from URL (e.g., https://lichess.org/study/abc123)")
        print("  3. Run: python -m chess_transfer.book_to_study --pdf book.pdf --study-id abc123 --save-study")
        return 1

    # Get API token
    token = args.token or os.getenv('LICHESS_TOKEN')
    if not token and not args.dry_run:
        print("Error: No API token provided")
        print("\nProvide --token or set LICHESS_TOKEN environment variable")
        print("Get token at: https://lichess.org/account/oauth/token (needs study:write scope)")
        return 1

    # Save study ID if requested
    if args.save_study and study_id:
        ConfigManager.set_study_id(study_id)
        print(f"Saved study ID: {study_id}")

    # Parse book
    print("Parsing book...")
    book_name = args.book_name or Path(book_path).stem

    try:
        if args.pdf:
            text = BookParser.parse_pdf(args.pdf)
        else:
            text = BookParser.parse_epub(args.epub)
    except Exception as e:
        print(f"Error parsing file: {e}")
        return 1

    print(f"   Extracted {len(text):,} characters")

    # Debug: show sample of extracted text
    if args.debug:
        print("\n--- DEBUG: First 2000 chars of extracted text ---")
        print(text[:2000])
        print("\n--- END DEBUG ---\n")

    # Split into chapters
    print("\nExtracting chapters...")
    raw_chapters = BookParser.extract_chapters(text)
    print(f"   Found {len(raw_chapters)} chapters")

    if args.debug and raw_chapters:
        print("\n--- DEBUG: Detected chapter titles ---")
        for i, ch in enumerate(raw_chapters, 1):
            print(f"   {i}. {ch['title'][:60]}")
        print("--- END DEBUG ---\n")

    # Convert to PGN (with branch detection)
    print("\nConverting to PGN and detecting branches...")
    chapters = []
    for chapter in raw_chapters:
        # Extract main line and any major branches
        lines = NotationParser.extract_lines_from_chapter(
            chapter['content'],
            chapter['title']
        )
        chapters.extend(lines)
        if len(lines) > 1:
            print(f"   {chapter['title']}: {len(lines)} lines (main + {len(lines)-1} branches)")

    # Dry run: show chapters without uploading
    if args.dry_run:
        print("\n--- DRY RUN: Chapters to upload ---")
        for i, chapter in enumerate(chapters, 1):
            print(f"\n[{i}] {chapter['title']}")
            print("-" * 40)
            # Show first 300 chars of PGN
            preview = chapter['pgn'][:300]
            if len(chapter['pgn']) > 300:
                preview += "..."
            print(preview)
        print("\n--- End of dry run ---")
        return 0

    # Upload to Lichess
    try:
        uploader = LichessStudyUploader(token)
        success = uploader.add_chapters(study_id, chapters, book_name)
        return 0 if success > 0 else 1
    except Exception as e:
        print(f"Error uploading: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
