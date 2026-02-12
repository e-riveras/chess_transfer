# Chess Book Reader Webapp

This is a standalone web application for reading PGN chess books with an interactive board.

## How to Use

### Locally
1. Open `index.html` in any modern web browser.
2. Click "Choose File" to upload a `.pgn` file.
3. Use the navigation buttons or arrow keys to browse the game.
4. Click on moves in the text or variations to jump to that position.

### GitHub Pages
This folder (`docs/`) is configured to be served via GitHub Pages.
Once pushed to the `main` branch, ensure your repository settings for Pages are set to serve from the `/docs` folder.

## Features
- **PGN Parsing**: Handles multiple games, comments, and recursive variations.
- **Interactive Board**: Visualizes the game state.
- **Move Synchronization**: Automatically scrolls the move text to match the board position.
- **Dark Mode**: Easy-on-the-eyes interface for reading.
