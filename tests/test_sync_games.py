import unittest
from unittest.mock import MagicMock, patch, Mock
import datetime
from src.sync_games import (
    get_lichess_client,
    get_latest_lichess_game_date,
    get_chesscom_archives,
    get_games_from_archive,
    import_game_to_lichess,
    main
)
import berserk
import requests

class TestSyncGames(unittest.TestCase):

    @patch('src.sync_games.time.sleep')
    @patch('src.sync_games.import_game_to_lichess')
    @patch('src.sync_games.get_games_from_archive')
    @patch('src.sync_games.get_chesscom_archives')
    @patch('src.sync_games.get_existing_lichess_games')
    @patch('src.sync_games.get_lichess_client')
    @patch('src.sync_games.LICHESS_TOKEN', 'fake_token')
    def test_main_sync_flow(self, mock_get_client, mock_get_existing, mock_get_archives, mock_get_games, mock_import, mock_sleep):
        # Setup mocks
        # Return existing signatures (empty set) and latest date
        mock_get_existing.return_value = (set(), datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc))
        
        # Return one archive
        mock_get_archives.return_value = ['https://api.chess.com/pub/player/erivera90/games/2023/01']
        
        # Return two games in that archive
        # Game 1: Older than latest (attempted but likely duplicate)
        # Game 2: Newer (attempted and imported)
        mock_get_games.return_value = [
            {
                'end_time': 1672531200, 
                'pgn': '1. e4 e5', 
                'white': {'username': 'erivera90'}, 
                'black': {'username': 'opponent1'}
            }, # 2023-01-01 00:00:00 UTC
            {
                'end_time': 1672617600, 
                'pgn': '1. d4 d5', 
                'white': {'username': 'erivera90'}, 
                'black': {'username': 'opponent2'}
            }  # 2023-01-02 00:00:00 UTC
        ]
        
        # First call (old_game) -> DUPLICATE
        # Second call (new_game) -> IMPORTED
        mock_import.side_effect = ["DUPLICATE", "IMPORTED"]

        main()

        # Verify interactions
        mock_get_client.assert_called_once()
        mock_get_existing.assert_called_once()
        mock_get_archives.assert_called_once()
        mock_get_games.assert_called_once()
        
        # Should attempt to import BOTH games
        self.assertEqual(mock_import.call_count, 2)
        
        # Should sleep:
        # 1. sleep(1) for the DUPLICATE result
        # 2. sleep(6) for the IMPORTED result
        # Check calls in any order or specific order.
        from unittest.mock import call
        mock_sleep.assert_has_calls([call(1), call(6)], any_order=True)

    def test_import_game_to_lichess_rate_limit(self):
        mock_client = MagicMock()
        
        # Define a mock exception for 429 using subclass to avoid init issues
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
            
            # Should return IMPORTED after retry
            self.assertEqual(status, "IMPORTED")
            
            # Should have slept for 60 seconds
            mock_sleep.assert_called_with(60)
            
            # Should have called import_game twice
            self.assertEqual(mock_client.games.import_game.call_count, 2)

    def test_import_game_to_lichess_rate_limit_fail(self):
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
        
        # Side effect: Always raises 429
        mock_client.games.import_game.side_effect = mock_429
        
        with patch('src.sync_games.time.sleep') as mock_sleep:
            status = import_game_to_lichess(mock_client, 'pgn_data')
            
            # Should return ERROR after retry fails
            self.assertEqual(status, "ERROR")
             # Should have slept for 60 seconds
            mock_sleep.assert_called_with(60)
            self.assertEqual(mock_client.games.import_game.call_count, 2)

    @patch('src.sync_games.berserk.Client')
    @patch('src.sync_games.berserk.TokenSession')
    @patch('src.sync_games.LICHESS_TOKEN', 'fake_token')
    def test_get_lichess_client(self, mock_session, mock_client):
        client = get_lichess_client()
        mock_session.assert_called_with('fake_token')
        mock_client.assert_called_once()

    def test_get_latest_lichess_game_date_no_games(self):
        mock_client = MagicMock()
        mock_client.account.get.return_value = {'username': 'testuser'}
        mock_client.games.export_by_player.return_value = [] # No games

        date = get_latest_lichess_game_date(mock_client)
        self.assertIsNone(date)

    def test_get_latest_lichess_game_date_with_games(self):
        mock_client = MagicMock()
        mock_client.account.get.return_value = {'username': 'testuser'}
        
        expected_date = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        # Mock generator return
        mock_client.games.export_by_player.return_value = iter([{'createdAt': expected_date}])

        date = get_latest_lichess_game_date(mock_client)
        self.assertEqual(date, expected_date)

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
                    pass # Skip original init
                def __str__(self):
                    return "Game already imported"
            
            mock_client.games.import_game.side_effect = MockResponseError()
    
            status = import_game_to_lichess(mock_client, 'pgn_data')
            self.assertEqual(status, "DUPLICATE")
    def test_import_game_to_lichess_error(self):
        mock_client = MagicMock()
        mock_client.games.import_game.side_effect = Exception("Random error")
        
        status = import_game_to_lichess(mock_client, 'pgn_data')
        self.assertEqual(status, "ERROR")

if __name__ == '__main__':
    unittest.main()
