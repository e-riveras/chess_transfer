"""Tests for chess_transfer/book_to_study.py"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from chess_transfer.book_to_study import (
    BookParser,
    NotationParser,
    LichessStudyUploader,
    ConfigManager,
)


class TestBookParser:
    """Tests for BookParser class."""

    def test_extract_chapters_with_chapter_markers(self):
        """Test chapter extraction with standard chapter headers."""
        text = """Introduction text here.

Chapter 1
This is chapter one content with moves 1.e4 e5.

Chapter 2
This is chapter two content with moves 1.d4 d5.
"""
        chapters = BookParser.extract_chapters(text)

        assert len(chapters) == 2
        assert chapters[0]['title'] == 'Chapter 1'
        assert '1.e4 e5' in chapters[0]['content']
        assert chapters[1]['title'] == 'Chapter 2'
        assert '1.d4 d5' in chapters[1]['content']

    def test_extract_chapters_no_markers(self):
        """Test fallback when no chapter markers found."""
        text = "Just some text without chapter headers."
        chapters = BookParser.extract_chapters(text)

        assert len(chapters) == 1
        assert chapters[0]['title'] == 'Full Book'
        assert chapters[0]['content'] == text

    def test_extract_chapters_uppercase(self):
        """Test extraction with uppercase CHAPTER markers."""
        text = """CHAPTER 1
First chapter content.

CHAPTER 2
Second chapter content.
"""
        chapters = BookParser.extract_chapters(text)

        assert len(chapters) == 2
        assert chapters[0]['title'] == 'CHAPTER 1'
        assert chapters[1]['title'] == 'CHAPTER 2'

    def test_parse_pdf_file_not_found(self):
        """Test PDF parsing with nonexistent file."""
        with pytest.raises(FileNotFoundError):
            BookParser.parse_pdf('/nonexistent/file.pdf')

    def test_parse_epub_file_not_found(self):
        """Test EPUB parsing with nonexistent file."""
        with pytest.raises(FileNotFoundError):
            BookParser.parse_epub('/nonexistent/file.epub')


class TestNotationParser:
    """Tests for NotationParser class."""

    def test_text_to_pgn_basic(self):
        """Test basic PGN conversion."""
        text = "1.e4 e5 2.Nf3 Nc6"
        pgn = NotationParser.text_to_pgn(text, "Test Chapter")

        assert '[Event "Test Chapter"]' in pgn
        assert '[Site "Chess Book"]' in pgn
        assert '1. e4 e5 2. Nf3 Nc6' in pgn

    def test_text_to_pgn_with_intro(self):
        """Test PGN conversion with introduction text."""
        text = """This is an introduction.
1.e4 e5 2.Nf3 Nc6"""
        pgn = NotationParser.text_to_pgn(text, "Opening Study")

        assert '[Event "Opening Study"]' in pgn
        assert 'This is an introduction.' in pgn
        assert '1. e4 e5 2. Nf3' in pgn

    def test_text_to_pgn_no_moves(self):
        """Test PGN conversion with no recognizable moves."""
        text = "Just descriptive text without any chess notation."
        pgn = NotationParser.text_to_pgn(text, "No Moves")

        assert '[Event "No Moves"]' in pgn
        # Full text should be in comment
        assert 'Just descriptive text' in pgn

    def test_text_to_pgn_long_intro_preserved(self):
        """Test that long introductions are preserved."""
        long_intro = "A" * 1000
        text = f"{long_intro}\n1.e4 e5"
        pgn = NotationParser.text_to_pgn(text, "Long Intro")

        # Text should be in comment (may be normalized)
        assert 'AAAA' in pgn
        assert '1. e4 e5' in pgn

    def test_extract_games_finds_move_sequences(self):
        """Test game extraction from text."""
        text = """Some intro text.

1.e4 e5 2.Nf3 Nc6 3.Bb5 a6

More descriptive text here.

1.d4 d5 2.c4 e6 3.Nc3 Nf6
"""
        games = NotationParser.extract_games(text)

        assert len(games) >= 1
        assert '1.e4' in games[0] or '1.d4' in games[0]


class TestConfigManager:
    """Tests for ConfigManager class."""

    def test_save_and_load_config(self):
        """Test saving and loading config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test_config.json"

            # Patch the config file path
            with patch.object(ConfigManager, 'CONFIG_FILE', config_path):
                ConfigManager.set_study_id("test123")
                loaded = ConfigManager.get_study_id()

                assert loaded == "test123"

    def test_load_nonexistent_config(self):
        """Test loading when config file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nonexistent.json"

            with patch.object(ConfigManager, 'CONFIG_FILE', config_path):
                result = ConfigManager.get_study_id()
                assert result is None


class TestLichessStudyUploader:
    """Tests for LichessStudyUploader class."""

    @patch('chess_transfer.book_to_study.berserk')
    def test_add_chapters_success(self, mock_berserk):
        """Test successful chapter upload."""
        mock_client = MagicMock()
        mock_berserk.Client.return_value = mock_client
        mock_berserk.TokenSession.return_value = MagicMock()

        uploader = LichessStudyUploader("fake_token")
        chapters = [
            {'title': 'Chapter 1', 'pgn': '1.e4 e5'},
            {'title': 'Chapter 2', 'pgn': '1.d4 d5'},
        ]

        result = uploader.add_chapters("study123", chapters, "Test Book")

        assert result == 2
        assert mock_client.studies.import_pgn.call_count == 2

    @patch('chess_transfer.book_to_study.berserk')
    def test_add_chapters_partial_failure(self, mock_berserk):
        """Test handling of partial upload failure."""
        mock_client = MagicMock()
        mock_berserk.Client.return_value = mock_client
        mock_berserk.TokenSession.return_value = MagicMock()
        mock_berserk.exceptions.ResponseError = Exception

        # First call succeeds, second fails
        mock_client.studies.import_pgn.side_effect = [
            None,
            Exception("API error"),
        ]

        uploader = LichessStudyUploader("fake_token")
        chapters = [
            {'title': 'Chapter 1', 'pgn': '1.e4 e5'},
            {'title': 'Chapter 2', 'pgn': '1.d4 d5'},
        ]

        result = uploader.add_chapters("study123", chapters, "Test Book")

        assert result == 1  # Only one succeeded

    @patch('chess_transfer.book_to_study.berserk')
    def test_chapter_name_truncation(self, mock_berserk):
        """Test that long chapter names are truncated."""
        mock_client = MagicMock()
        mock_berserk.Client.return_value = mock_client
        mock_berserk.TokenSession.return_value = MagicMock()

        uploader = LichessStudyUploader("fake_token")
        long_title = "A" * 150
        chapters = [{'title': long_title, 'pgn': '1.e4 e5'}]

        uploader.add_chapters("study123", chapters, "Book")

        call_args = mock_client.studies.import_pgn.call_args
        chapter_name = call_args.kwargs.get('chapter_name')
        assert len(chapter_name) <= 100
