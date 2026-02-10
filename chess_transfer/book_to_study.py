#!/usr/bin/env python3
"""
chess_transfer/book_to_study.py

Convert chess books (PDF/EPUB) to Lichess study chapters with a Targeted Move Hunter strategy.
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
    import chess
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
        """Extract text from PDF file."""
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
        """Extract text from EPUB file following the reading order (spine)."""
        if not Path(epub_path).exists():
            raise FileNotFoundError(f"File not found: {epub_path}")

        book = epub.read_epub(epub_path)
        text = ""

        # Follow the spine to maintain correct reading order
        for item_id, linear in book.spine:
            item = book.get_item_with_id(item_id)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text += soup.get_text() + "\n\n"

        if not text.strip():
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    text += soup.get_text() + "\n\n"

        return text

    @staticmethod
    def extract_chapters(text: str, min_content_length: int = 20) -> List[Dict]:
        """Split text into logical chapters based on common headers."""
        patterns = [
            r'(?:^|\n)Chapter\s+(?:\d+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve|Thirteen|Fourteen|Fifteen)[^\n]*',
            r'(?:^|\n)CHAPTER\s+(?:\d+|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN)[^\n]*',
            r'(?:^|\n)Part\s+(?:[IVX\d]+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)[^\n]*',
            r'(?:^|\n)\d+\.\s+[A-Z][^\n]{5,100}',
            r'(?:^|\n)#{1,3}\s+[^\n]+',
        ]

        combined_pattern = f"(?:{'|'.join(patterns)})"
        matches = list(re.finditer(combined_pattern, text, flags=re.MULTILINE))
        
        if not matches:
            return [{'title': 'Full Book', 'content': text}]

        chapters = []
        intro_text = text[:matches[0].start()].strip()
        if len(intro_text) > 100:
            chapters.append({'title': 'Introduction', 'content': intro_text})

        for i in range(len(matches)):
            start_pos = matches[i].start()
            header_end = matches[i].end()
            end_pos = matches[i+1].start() if i + 1 < len(matches) else len(text)
            title = text[start_pos:header_end].strip()
            content = text[header_end:end_pos].strip()
            if len(content) >= min_content_length:
                chapters.append({'title': title, 'content': content})
        
        return chapters


class NotationParser:
    """Parse chess notation from text with a Targeted Move Hunter strategy."""

    MOVE_PATTERN = r'(?:\d+\.{1,3}\s*)?(?:[KQRBN]?[a-h1-8]?x?[a-h][1-8](?:=[QRBN])?|O-O-O|O-O|0-0-0|0-0)[+#]?[!?]*'

    @staticmethod
    def extract_lines_from_chapter(text: str, chapter_title: str) -> List[Dict]:
        """Split a chapter into a preamble and multiple distinct games (Game Slicing)."""
        import re
        game_marker_pattern = r'(?P<marker>Game\s+\d+)'
        matches = list(re.finditer(game_marker_pattern, text, flags=re.IGNORECASE))
        
        if not matches:
            return [{'title': chapter_title, 'pgn': NotationParser.text_to_pgn(text, chapter_title)}]

        results = []
        preamble_text = text[:matches[0].start()].strip()
        if preamble_text and len(preamble_text) > 50:
            results.append({
                'title': f"{chapter_title} - Introduction",
                'pgn': NotationParser.text_to_pgn(preamble_text, f"{chapter_title} - Introduction", is_preamble=True)
            })

        for i in range(len(matches)):
            start_pos = matches[i].start()
            end_pos = matches[i+1].start() if i + 1 < len(matches) else len(text)
            segment_text = text[start_pos:end_pos].strip()
            marker_line = text[matches[i].start():matches[i].end()].strip()
            
            pgn = NotationParser.text_to_pgn(segment_text, f"{chapter_title} - {marker_line}")
            results.append({'title': f"{chapter_title} - {marker_line}", 'pgn': pgn})

        return results

    @staticmethod
    def text_to_pgn(text: str, chapter_title: str, is_preamble: bool = False) -> str:
        """
        Targeted Move Hunter Loop.
        Iteratively searches for the specific next sequential move in the main line.
        """
        import re
        import chess
        import chess.pgn

        game = chess.pgn.Game()
        game.headers["Event"] = chapter_title
        game.headers["Site"] = "Chess Book"
        game.headers["Result"] = "*"

        if is_preamble:
            game.headers["White"] = "Study"; game.headers["Black"] = "Introduction"
            game.comment = re.sub(r'\s+', ' ', text.replace('{', '(').replace('}', ')')).strip()
            return str(game)

        # Header Extraction
        header_pattern = r'Game\s+\d+\s+(?P<white>[^-]+)-(?P<black>[^\s]+)\s+(?P<location>.*?)(?P<year>\d{4})'
        match = re.search(header_pattern, text, flags=re.IGNORECASE)
        if match:
            game.headers["White"] = match.group('white').strip()
            game.headers["Black"] = match.group('black').strip()
            game.headers["Date"] = f"{match.group('year')}.??.??"
            text = text[match.end():].strip()
        else:
            game.headers["White"] = "Study"; game.headers["Black"] = "Analysis"

        board = chess.Board()
        current_node = game
        pos = 0
        
        while pos < len(text):
            move_num = board.fullmove_number
            turn = board.turn
            
            found_match = None
            # SCAN FOR TARGET
            for m in re.finditer(rf'({NotationParser.MOVE_PATTERN})', text[pos:]):
                token = m.group(0).strip()
                comp = re.match(r'(?P<num>\d+)?(?P<dots>\.{1,3})?\s*(?P<san>.*)', token)
                c_num = int(comp.group('num')) if comp.group('num') else None
                c_dots = comp.group('dots')
                c_is_black = c_dots and len(c_dots) > 1
                c_san = comp.group('san').strip().replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
                c_san = re.sub(r'^[\d\.]+', '', c_san).strip()

                # Step 1: Target Signature Check
                is_target_sig = False
                if turn == chess.WHITE:
                    # White move: Must match number, must not have dots
                    if c_num == move_num and not c_is_black:
                        is_target_sig = True
                else: # Black
                    # Black move: Correct number with dots OR no number
                    if (c_num == move_num and c_is_black) or (c_num is None):
                        is_target_sig = True
                
                if is_target_sig:
                    try:
                        # Step 3: Legality Check
                        move = board.parse_san(c_san)
                        
                        # Anti-Confusion: If Black raw SAN, don't jump over other move numbers
                        if turn == chess.BLACK and c_num is None:
                            skipped = text[pos : pos + m.start()]
                            if re.search(r'\d+\.', skipped):
                                continue # This move belongs to a different turn
                        
                        found_match = (m, move)
                        break
                    except:
                        pass # Move not legal or invalid SAN
            
            if found_match:
                m, move = found_match
                # Step 3: Execute & Advance
                match_start = pos + m.start()
                match_end = pos + m.end()
                
                # Capture Comment
                comment = text[pos:match_start].strip()
                if comment:
                    comment = re.sub(r'\s+', ' ', comment.replace('{', '(').replace('}', ')'))
                    current_node.comment = (current_node.comment + " " + comment).strip()
                
                current_node = current_node.add_main_variation(move)
                board.push(move)
                pos = match_end
            else:
                # Target not found in remaining text
                break
        
        # Add remaining text as final comment
        remaining = text[pos:].strip()
        if remaining:
            remaining = re.sub(r'\s+', ' ', remaining.replace('{', '(').replace('}', ')'))
            current_node.comment = (current_node.comment + " " + remaining).strip()

        return str(game)

    @staticmethod
    def extract_games(text: str) -> List[str]:
        """Legacy helper."""
        return [NotationParser.text_to_pgn(text, "Extracted Game")]


class LichessStudyUploader:
    """Upload chapters to Lichess study using berserk API."""

    def __init__(self, api_token: str):
        self.session = berserk.TokenSession(api_token)
        self.client = berserk.Client(session=self.session)

    def clear_chapters(self, study_id: str) -> int:
        """Delete all chapters except the first one."""
        import requests
        print(f"Clearing chapters for study {study_id}...")
        r = requests.get(f"https://lichess.org/api/study/{study_id}.pgn")
        if r.status_code != 200: return 0
        chapter_ids = re.findall(rf"study/{study_id}/(\w+)", r.text)
        if not chapter_ids: return 0
        to_delete = chapter_ids[1:]
        deleted_count = 0
        for chapter_id in to_delete:
            dr = requests.delete(f"https://lichess.org/api/study/{study_id}/{chapter_id}", 
                                headers={"Authorization": f"Bearer {self.session.token}"})
            if dr.status_code == 204: deleted_count += 1
        print(f"   Successfully deleted {deleted_count} chapters.")
        return deleted_count

    def add_chapters(self, study_id: str, chapters: List[Dict], book_name: str) -> int:
        """Add chapters to existing Lichess study with rate limiting."""
        import time
        MAX_CHAPTERS = 64
        if len(chapters) > MAX_CHAPTERS:
            print(f"Warning: Truncating to {MAX_CHAPTERS} chapters.")
            chapters = chapters[:MAX_CHAPTERS]

        print(f"\nUploading to study {study_id}...")
        success_count = 0
        for i, chapter in enumerate(chapters, 1):
            name = f"{book_name} - {chapter['title']}"[:100]
            try:
                self.client.studies.import_pgn(study_id=study_id, chapter_name=name, pgn=chapter['pgn'])
                print(f"   [OK] [{i}/{len(chapters)}] {name}")
                success_count += 1
                time.sleep(1.0)
            except Exception as e:
                print(f"   [FAIL] {name}: {e}")
                if "429" in str(e): time.sleep(60)
        return success_count


class ConfigManager:
    """Manage configuration like saved study IDs."""
    CONFIG_FILE = Path.home() / ".chess_transfer_config.json"
    @classmethod
    def load(cls) -> dict:
        if cls.CONFIG_FILE.exists():
            with open(cls.CONFIG_FILE) as f: return json.load(f)
        return {}
    @classmethod
    def get_study_id(cls) -> Optional[str]: return cls.load().get('default_study_id')
    @classmethod
    def set_study_id(cls, study_id: str):
        config = cls.load(); config['default_study_id'] = study_id
        with open(cls.CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='Convert chess books to Lichess study chapters')
    parser.add_argument('--pdf', help='Path to PDF file')
    parser.add_argument('--epub', help='Path to EPUB file')
    parser.add_argument('--study-id', help='Lichess study ID')
    parser.add_argument('--token', help='Lichess API token')
    parser.add_argument('--book-name', help='Name for the book')
    parser.add_argument('--save-study', action='store_true', help='Save study ID')
    parser.add_argument('--dry-run', action='store_true', help='Parse only')
    parser.add_argument('--debug', action='store_true', help='Show debug text')
    parser.add_argument('--clear', action='store_true', help='Clear existing chapters')

    args = parser.parse_args()
    if not (args.pdf or args.epub): parser.error("Provide --pdf or --epub")
    
    study_id = args.study_id or ConfigManager.get_study_id()
    token = args.token or os.getenv('LICHESS_TOKEN')
    if args.save_study and study_id: ConfigManager.set_study_id(study_id)

    print("Parsing book...")
    book_path = args.pdf or args.epub
    text = BookParser.parse_pdf(args.pdf) if args.pdf else BookParser.parse_epub(args.epub)
    
    print("\nExtracting chapters and games...")
    raw_chapters = BookParser.extract_chapters(text)
    chapters = []
    for rc in raw_chapters:
        chapters.extend(NotationParser.extract_lines_from_chapter(rc['content'], rc['title']))

    if args.dry_run:
        for i, ch in enumerate(chapters[:5], 1):
            print(f"\n[{i}] {ch['title']}\n{ch['pgn'][:500]}...")
        return 0

    uploader = LichessStudyUploader(token)
    if args.clear: uploader.clear_chapters(study_id)
    uploader.add_chapters(study_id, chapters, args.book_name or Path(book_path).stem)


if __name__ == '__main__':
    exit(main())
