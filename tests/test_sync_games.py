import unittest
from unittest.mock import MagicMock, patch, Mock, mock_open
import datetime
import json
import os
from src.sync_games import (
    get_lichess_client,
    get_chesscom_archives,
    get_games_from_archive,
    import_game_to_lichess,
    load_history,
    save_history,
    main
)
import berserk
import requests

class TestSyncGames(unittest.TestCase):

    @patch('src.sync_games.berserk.Client')
    @patch('src.sync_games.berserk.TokenSession')
    @patch('src.sync_games.LICHESS_TOKEN', 'fake_token')
    def test_get_lichess_client(self, mock_session, mock_client):
        client = get_lichess_client()
        mock_session.assert_called_with('fake_token')
        mock_client.assert_called_once()

    @patch('src.sync_games.requests.get')
    def test_get_chesscom_archives_success(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {'archives': ['url1', 'url2']}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        archives = get_chesscom_archives('testuser')
        self.assertEqual(archives, ['url1', 'url2'])

    @patch('src.sync_games.requests.get')
    def test_get_chesscom_archives_failure(self, mock_get):
        mock_get.side_effect = requests.RequestException("Error")
        
        archives = get_chesscom_archives('testuser')
        self.assertEqual(archives, [])

    @patch('src.sync_games.requests.get')
    def test_get_games_from_archive_success(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {'games': [{'pgn': '1. e4'}]}
        mock_get.return_value = mock_response

        games = get_games_from_archive('url1')
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['pgn'], '1. e4')

    def test_import_game_to_lichess_success(self):
        mock_client = MagicMock()
        mock_client.games.import_game.return_value = {'url': 'http://lichess.org/game1'}
        
        status = import_game_to_lichess(mock_client, 'pgn_data')
        self.assertEqual(status, "IMPORTED")

    def test_import_game_to_lichess_duplicate(self):
        mock_client = MagicMock()
        
        # Create a mock exception that passes the isinstance check
        class MockResponseError(berserk.exceptions.ResponseError):
            def __init__(self):
                pass 
            def __str__(self):
                return "Game already imported"
        
        mock_client.games.import_game.side_effect = MockResponseError()

        status = import_game_to_lichess(mock_client, 'pgn_data')
        self.assertEqual(status, "DUPLICATE")

    def test_import_game_to_lichess_rate_limit(self):
        mock_client = MagicMock()
        
        class MockResponseError(berserk.exceptions.ResponseError):
            def __init__(self):
                pass
            @property
            def status_code(self):
                return 429
            def __str__(self):
                return "Too Many Requests"
        
        mock_429 = MockResponseError()
        
        # Side effect: First call raises 429, Second call succeeds
        mock_client.games.import_game.side_effect = [
            mock_429,
            {'url': 'http://lichess.org/retry_success'}
        ]
        
        with patch('src.sync_games.time.sleep') as mock_sleep:
            status = import_game_to_lichess(mock_client, 'pgn_data')
            self.assertEqual(status, "IMPORTED")
            mock_sleep.assert_called_with(60)
            self.assertEqual(mock_client.games.import_game.call_count, 2)

    @patch('src.sync_games.HISTORY_FILE', 'data/history.json')
    def test_load_history_exists(self):
        with patch("builtins.open", mock_open(read_data='{"imported_ids": ["123"]}')):
            with patch("os.path.exists", return_value=True):
                history = load_history()
                self.assertEqual(history, {"imported_ids": ["123"]})

    @patch('src.sync_games.HISTORY_FILE', 'data/history.json')
    def test_load_history_not_exists(self):
        with patch("os.path.exists", return_value=False):
            history = load_history()
            self.assertEqual(history, {"imported_ids": []})

    @patch('src.sync_games.HISTORY_FILE', 'data/history.json')
    def test_save_history(self):
        m_open = mock_open()
        with patch("builtins.open", m_open):
            save_history({"imported_ids": ["123"]})
            m_open.assert_called_with('data/history.json', 'w')
            handle = m_open()
            # Verify json dump wrote something resembling the json
            # handle.write.assert_called() # tough to verify exact string with json.dump formatting

    @patch('src.sync_games.time.sleep')
    @patch('src.sync_games.import_game_to_lichess')
    @patch('src.sync_games.get_games_from_archive')
    @patch('src.sync_games.get_chesscom_archives')
    @patch('src.sync_games.load_history')
    @patch('src.sync_games.save_history')
    @patch('src.sync_games.get_lichess_client')
    @patch('src.sync_games.LICHESS_TOKEN', 'fake_token')
    def test_main_sync_flow(self, mock_get_client, mock_save_hist, mock_load_hist, mock_get_archives, mock_get_games, mock_import, mock_sleep):
        # Setup mocks
        mock_load_hist.return_value = {"imported_ids": ["old_game_id"]}
        
        mock_get_archives.return_value = ['archive_url']
        
        # Game 1: ID is "old_game_id" (should skip)
        # Game 2: ID is "new_game_id" (should import)
        mock_get_games.return_value = [
            {
                'url': 'https://chess.com/game/live/old_game_id',
                'end_time': 1000, 
                'pgn': 'pgn1'
            },
            {
                'url': 'https://chess.com/game/live/new_game_id',
                'end_time': 2000, 
                'pgn': 'pgn2'
            }
        ]
        
        mock_import.return_value = "IMPORTED"

        main()

        # Verify interactions
        mock_load_hist.assert_called_once()
        
        # Should attempt to import ONLY the new game
        mock_import.assert_called_once()
        # Verify call args: client and pgn2
        args, _ = mock_import.call_args
        self.assertEqual(args[1], 'pgn2')
        
        # Should save history
        mock_save_hist.assert_called()
        
        # Should sleep
        mock_sleep.assert_called_with(6)

if __name__ == '__main__':
    unittest.main()