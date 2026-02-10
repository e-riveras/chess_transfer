"""
chess_transfer/book_to_study.py

Extends chess_transfer to convert chess books to Lichess studies.
Integrates with existing transfer infrastructure.

Usage:
    python -m chess_transfer.book_to_study --pdf book.pdf --study-id xyz123
    python -m chess_transfer.book_to_study --epub book.epub --study-id xyz123
"""

import argparse
import re
from pathlib import Path
from typing import List, Dict, Optional
import json

try:
    import berserk
    import chess.pgn
    from PyPDF2 import PdfReader
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False


class BookParser:
    """Parse chess books from various formats"""
    
    @staticmethod
    def parse_pdf(pdf_path: str) -> str:
        """Extract text from PDF"""
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return text
    
    @staticmethod
    def parse_epub(epub_path: str) -> str:
        """Extract text from EPUB"""
        book = epub.read_epub(epub_path)
        text = ""
        
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text += soup.get_text() + "\n\n"
        
        return text
    
    @staticmethod
    def extract_chapters(text: str) -> List[Dict]:
        """
        Split text into logical chapters.
        Assumes chapters start with headers like "Chapter N" or "## Title"
        """
        # Split by common chapter markers
        chapter_pattern = r'(Chapter \d+|CHAPTER \d+|##\s+.+?)(?=\n)'
        
        chapters = []
        parts = re.split(chapter_pattern, text)
        
        # Combine headers with their content
        for i in range(1, len(parts), 2):
            if i+1 < len(parts):
                chapter_title = parts[i].strip()
                chapter_content = parts[i+1].strip()
                
                if chapter_content:  # Skip empty chapters
                    chapters.append({
                        'title': chapter_title,
                        'content': chapter_content
                    })
        
        return chapters if chapters else [{'title': 'Full Book', 'content': text}]


class NotationParser:
    """Parse chess notation from text"""
    
    @staticmethod
    def extract_games(text: str) -> List[str]:
        """
        Extract PGN-style notation from text.
        Handles both inline notation and formal PGN.
        """
        games = []
        
        # Pattern for chess moves
        move_pattern = r'(?:\d+\.+\s*)?(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|O-O-O|O-O)'
        
        # Find sequences of moves
        lines = text.split('\n')
        current_game = []
        
        for line in lines:
            moves = re.findall(move_pattern, line)
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
        Preserves comments and variations.
        """
        # Extract introduction/description
        lines = text.split('\n')
        intro_lines = []
        game_lines = []
        
        for line in lines:
            if re.search(r'\d+\.', line):  # Contains move numbers
                game_lines.append(line)
            else:
                intro_lines.append(line)
        
        intro = ' '.join(intro_lines).strip()
        game_text = ' '.join(game_lines)
        
        # Build PGN
        pgn = f"""[Event "{chapter_title}"]
[Site "Chess Book"]
[White "Study"]
[Black "Analysis"]

"""
        
        if intro:
            pgn += f"{{{intro}}}\n\n"
        
        pgn += game_text
        
        return pgn


class LichessStudyUploader:
    """Upload chapters to Lichess study"""
    
    def __init__(self, api_token: str):
        if not DEPS_AVAILABLE:
            raise ImportError("Install: pip install berserk python-chess")
        
        self.session = berserk.TokenSession(api_token)
        self.client = berserk.Client(session=self.session)
    
    def add_chapters(self, study_id: str, chapters: List[Dict], book_name: str):
        """
        Add chapters to existing study.
        
        Args:
            study_id: Existing Lichess study ID
            chapters: List of {'title': ..., 'pgn': ...}
            book_name: Name to prefix chapters with
        """
        print(f"\n📚 Uploading '{book_name}' to study {study_id}")
        print(f"   {len(chapters)} chapters to add\n")
        
        for i, chapter in enumerate(chapters, 1):
            chapter_name = f"{book_name} - {chapter['title']}"
            
            try:
                self.client.studies.create_chapter(
                    study_id=study_id,
                    name=chapter_name,
                    pgn=chapter['pgn'],
                    orientation='white'
                )
                print(f"   ✓ [{i}/{len(chapters)}] {chapter_name}")
            except Exception as e:
                print(f"   ✗ [{i}/{len(chapters)}] {chapter_name}: {e}")
        
        print(f"\n✓ Done! View at: https://lichess.org/study/{study_id}")


class ConfigManager:
    """Manage configuration like saved study IDs"""
    
    CONFIG_FILE = Path.home() / ".chess_transfer_config.json"
    
    @classmethod
    def load(cls) -> dict:
        if cls.CONFIG_FILE.exists():
            with open(cls.CONFIG_FILE) as f:
                return json.load(f)
        return {}
    
    @classmethod
    def save(cls, config: dict):
        with open(cls.CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    
    @classmethod
    def get_study_id(cls) -> Optional[str]:
        return cls.load().get('default_study_id')
    
    @classmethod
    def set_study_id(cls, study_id: str):
        config = cls.load()
        config['default_study_id'] = study_id
        cls.save(config)


def main():
    parser = argparse.ArgumentParser(
        description='Convert chess books to Lichess study chapters'
    )
    parser.add_argument('--pdf', help='Path to PDF file')
    parser.add_argument('--epub', help='Path to EPUB file')
    parser.add_argument('--study-id', help='Lichess study ID')
    parser.add_argument('--token', help='Lichess API token')
    parser.add_argument('--book-name', help='Name for the book (auto-detected if not provided)')
    parser.add_argument('--save-study', action='store_true', help='Save study ID as default')
    
    args = parser.parse_args()
    
    # Validation
    if not (args.pdf or args.epub):
        parser.error("Provide --pdf or --epub")
    
    # Get study ID (from args or config)
    study_id = args.study_id or ConfigManager.get_study_id()
    if not study_id:
        print("❌ No study ID provided")
        print("\nSetup:")
        print("1. Create study at https://lichess.org/study")
        print("2. Copy study ID from URL")
        print("3. Run: python book_to_study.py --study-id YOUR_ID --save-study")
        return
    
    # Get API token (from args or env)
    token = args.token or os.getenv('LICHESS_TOKEN')
    if not token:
        parser.error("Provide --token or set LICHESS_TOKEN env var")
    
    # Save study ID if requested
    if args.save_study:
        ConfigManager.set_study_id(study_id)
        print(f"✓ Saved study ID: {study_id}")
    
    # Parse book
    print("📖 Parsing book...")
    book_path = args.pdf or args.epub
    book_name = args.book_name or Path(book_path).stem
    
    if args.pdf:
        text = BookParser.parse_pdf(args.pdf)
    else:
        text = BookParser.parse_epub(args.epub)
    
    print(f"   Extracted {len(text)} characters")
    
    # Split into chapters
    print("\n📑 Extracting chapters...")
    raw_chapters = BookParser.extract_chapters(text)
    print(f"   Found {len(raw_chapters)} chapters")
    
    # Convert to PGN
    print("\n♟️  Converting to PGN...")
    chapters = []
    for chapter in raw_chapters:
        pgn = NotationParser.text_to_pgn(
            chapter['content'],
            chapter['title']
        )
        chapters.append({
            'title': chapter['title'],
            'pgn': pgn
        })
    
    # Upload to Lichess
    uploader = LichessStudyUploader(token)
    uploader.add_chapters(study_id, chapters, book_name)


if __name__ == '__main__':
    main()
