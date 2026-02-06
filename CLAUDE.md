# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Chess.com to Lichess sync and analysis system. Automatically imports games from Chess.com to Lichess, organizes Rapid games into monthly Lichess Studies, and generates analysis reports using Stockfish + Google Gemini LLM.

## Commands

### Testing
```bash
export PYTHONPATH=$PYTHONPATH:$(pwd)
pytest --cov=src --cov-report=term-missing tests/
```

### Running Locally
```bash
# Full sync pipeline (imports games, adds to studies, analyzes)
python run_sync.py

# Standalone analysis (analyzes PGN or fetches latest Lichess game)
python run_analysis.py [pgn_file]
```

### Dependencies
```bash
pip install -r requirements.txt
```

## Architecture

### Two Main Pipelines

1. **Sync Pipeline** (`run_sync.py` → `src/pipelines/sync.py`)
   - Fetches Chess.com archives → imports new games to Lichess
   - Adds Rapid games (>20 moves) to monthly Lichess Studies
   - Triggers analysis for transferred games
   - Maintains state in `data/history.json`

2. **Analysis Pipeline** (`run_analysis.py` → `src/pipelines/analysis.py`)
   - Runs Stockfish engine analysis to find "crucial moments" (blunders/missed wins)
   - Gets LLM explanations via Google Gemini
   - Generates markdown reports with SVG board diagrams in `analysis/`

### Key Modules

- `src/api/lichess.py` - Lichess API client (imports, StudyManager)
- `src/api/chesscom.py` - Chess.com public API client
- `src/analysis/engine.py` - Stockfish wrapper (`ChessAnalyzer` context manager)
- `src/analysis/narrator.py` - LLM integration (abstract base + Gemini implementation)
- `src/analysis/report.py` - Markdown report generation
- `src/data/history.py` - JSON state management for tracking imported/analyzed games
- `src/models.py` - `CrucialMoment` dataclass for analysis results
- `src/utils.py` - Logging setup, env var validation, project path utilities

### Data Flow

```
Chess.com archives → Import to Lichess → Add to Study → Stockfish analysis → LLM narration → Markdown report
```

State tracked in `data/history.json`: imported_ids, studied_ids, monthly_studies mapping, last_analyzed_id

## Environment Variables

Required in `.env` (see `.env.example`):
- `STOCKFISH_PATH` - Path to Stockfish binary
- `GEMINI_API_KEY` - Google Gemini API key
- `LICHESS_TOKEN` - Lichess API token (username derived automatically)
- `CHESSCOM_USERNAME` - Chess.com username

Optional:
- `ANALYSIS_TIME_LIMIT` - Engine analysis time per position (default: 0.1)
- `LOG_LEVEL` - Logging level

## Key Patterns

- **Context managers**: `ChessAnalyzer` uses `with` statement for engine lifecycle
- **Narrator abstraction**: `AnalysisNarrator` base class allows pluggable LLM providers
- **Smart filter**: Skips blunders in already-decided positions to reduce noise
- **Tactical alerts**: Detects if blunder allows immediate capture of hanging pieces
- **Rate limit handling**: 429 errors trigger backoff retry in Lichess client

## Monthly Studies

Lichess Studies must be manually created with exact naming: `Rapid Games - [Month] [Year]` (e.g., `Rapid Games - February 2026`). The sync pipeline finds and populates them automatically.
