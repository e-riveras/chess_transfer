# Chess.com to Lichess Sync & Analysis

Automatically syncs games played on [Chess.com](https://www.chess.com) to [Lichess.org](https://lichess.org) and generates AI-powered analysis reports. Runs on a schedule via GitHub Actions.

## Features

- **Automatic Sync:** Imports new Chess.com games to Lichess hourly via GitHub Actions.
- **Duplicate Prevention:** Skips games that have already been imported.
- **Game Analysis:** Runs Stockfish engine analysis on the latest game to identify blunders and missed opportunities.
- **AI Narration:** Uses Google Gemini to explain mistakes in plain English.
- **HTML Reports:** Generates visual reports with board diagrams, eval charts, and direct links to the Lichess analysis board.

## Setup

1. **Fork or Clone** this repository.
2. **Generate a Lichess API Token:**
   - Go to [Lichess API Access Token](https://lichess.org/account/oauth/token).
   - Create a token with game import scope.
3. **Configure GitHub Secrets:**
   - Go to your repository settings → `Secrets and variables` → `Actions`.
   - Add `LICHESS_TOKEN` (your Lichess API token).
   - Add `STOCKFISH_PATH` (path to Stockfish binary on the runner).
   - Add `GEMINI_API_KEY` (Google Gemini API key for narration).
4. **Configure Username:**
   - Update `CHESSCOM_USERNAME` in `.github/workflows/sync.yml`.

## Local Development

1. Clone the repo.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file:
   ```
   LICHESS_TOKEN=your_token_here
   CHESSCOM_USERNAME=your_chesscom_username
   STOCKFISH_PATH=/path/to/stockfish
   GEMINI_API_KEY=your_gemini_key
   ```
4. Run the full sync + analysis pipeline:
   ```bash
   python run_sync.py
   ```
5. Or run standalone analysis on a PGN file:
   ```bash
   python run_analysis.py [pgn_file]
   ```

## Technologies

- Python
- [Berserk](https://github.com/rhgrant10/berserk) (Lichess API client)
- [python-chess](https://python-chess.readthedocs.io/) + Stockfish
- Google Gemini API
- GitHub Actions
