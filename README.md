# Chess.com to Lichess Sync

This project automatically syncs your games played on [Chess.com](https://www.chess.com) to your [Lichess.org](https://lichess.org) account. It is designed to run periodically using GitHub Actions, ensuring your Lichess profile always has your latest games for analysis.

## Features

- **Automatic Sync:** Runs every hour via GitHub Actions.
- **Smart Imports:** Checks your latest game on Lichess to avoid re-importing old games.
- **Duplicate Prevention:** Skips games that have already been imported.

## Setup

1.  **Fork or Clone** this repository.
2.  **Generate a Lichess API Token:**
    -   Go to [Lichess API Access Token](https://lichess.org/account/oauth/token).
    -   Create a new token with `web:mod` (or sufficient scope to import games). *Note: Standard import might not strictly require scopes if just using the public import endpoint, but `berserk` usually authenticates.*
3.  **Configure GitHub Secrets:**
    -   Go to your repository settings -> `Secrets and variables` -> `Actions`.
    -   Create a new repository secret named `LICHESS_TOKEN` and paste your token there.
4.  **Configure Username:**
    -   The script defaults to `erivera90`. You can change this in `.github/workflows/sync.yml` by updating the `CHESSCOM_USERNAME` environment variable.

## Local Development

1.  Clone the repo.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Create a `.env` file with your credentials:
    ```
    LICHESS_TOKEN=your_token_here
    CHESSCOM_USERNAME=erivera90
    ```
4.  Run the script:
    ```bash
    python src/sync_games.py
    ```

## Technologies

-   Python
-   [Berserk](https://github.com/rhgrant10/berserk) (Lichess Client)
-   Requests
-   GitHub Actions
