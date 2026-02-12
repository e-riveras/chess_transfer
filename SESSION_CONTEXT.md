# Chess Transfer - Book to Study Parser Session Context

## Project Overview
Converting chess books (EPUB/PDF) to Lichess studies using Python. Main file: `chess_transfer/book_to_study.py`

## Current Problem
The parser fails when chess books have:
1. **Analysis Branches** - Text discusses deep variations then jumps back to main line (e.g., move 12 back to move 9)
2. **Ambiguity Conflicts** - Same move is legal on multiple branches, parser picks wrong one

## Example Problem Text
```
1.c4 Nf6 2.Nc3 d6 3.g3 g6
Instead, 3...e5 4.Bg2 Nbd7 5.d3 Be7 would resemble the Old Indian.
4.Bg2 Bg7 5.e4 e5 6.Nge2 Nc6 7.0-0 0-0...
```

**Issue**: The variation `3...e5 4.Bg2 Nbd7 5.d3 Be7` appears BEFORE the main line continuation `4.Bg2 Bg7 5.e4`. Parser incorrectly puts `Nbd7` on main line instead of `Bg7`.

## Architecture Attempted: Stack-Based Tree Builder with Lookahead

### Current Implementation (in book_to_study.py)
1. **Tokenizer**: Converts text to MoveToken and TextToken list
   - Handles sticky notation: `6.Nge2`, `11...Ne8`, `7.0-0` (no spaces)
   - Captures implicit Black moves: `1.e4 e5` format

2. **Tree Builder**:
   - Maintains `node_registry` of all created nodes
   - For each move, finds ALL valid parent nodes
   - Uses lookahead to disambiguate multiple valid parents
   - Tracks `main_line_leaf` and `current_node`

### The Core Bug
When tokenized, variation moves appear BEFORE main line continuation:
```
Tokens: [1.c4, Nf6, 2.Nc3, d6, 3.g3, g6, TEXT, 3...e5, 4.Bg2, Nbd7, 5.d3, Be7, TEXT, 4.Bg2, Bg7, 5.e4...]
```

When processing first `4.Bg2`, valid parents are:
- After `3...g6` (main line)
- After `3...e5` (variation)

Lookahead to `Nbd7` is legal on BOTH (knight b8 can go to d7 in either position), so parser picks wrong branch.

## Proposed Solutions (Not Yet Implemented)

### Option 1: Context-Aware Disambiguation
When multiple valid parents exist:
1. Check immediate text context for variation markers ("Instead", "After", "would", "should")
2. If current token follows variation markers, attach to variation branch
3. Otherwise prefer main line

### Option 2: Two-Pass Approach
1. First pass: Build main line only (skip tokens in "commentary context")
2. Second pass: Add variations where they branch from main line

### Option 3: Track "Expected Next Move"
1. After each main line move, track what move number/color we expect next
2. Only moves matching expectation go on main line
3. Non-matching moves become variations

## Key Code Sections

### Tokenizer Pattern (Sticky Regex)
```python
explicit_move = re.compile(
    r'(\d+)(\.{1,3})\s*'
    r'([KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O-O|O-O|0-0-0|0-0)'
    r'([!?]*)'
)
```

### Valid Parent Search
```python
for node in node_registry:
    board = node.board()
    if board.fullmove_number == token.move_num and board.turn == expected_turn:
        try:
            move = board.parse_san(san_clean)
            valid_parents.append((node, move))
        except:
            pass
```

## Test Files
- Test EPUB: `chess_transfer/annas-arch-dab3647cdba4.epub` (Iron English opening repertoire)
- Unit tests: `tests/test_book_to_study.py` (15 tests, 14 passing)
- Lichess Study ID: `zz3KrBvL`

## Commands
```bash
# Run tests
PYTHONPATH=$PYTHONPATH:$(pwd) pytest tests/test_book_to_study.py -v

# Dry run (parse only)
python -m chess_transfer.book_to_study --epub chess_transfer/annas-arch-dab3647cdba4.epub --dry-run

# Full run with clear
python -m chess_transfer.book_to_study --epub chess_transfer/annas-arch-dab3647cdba4.epub --clear
```

## Environment
- Lichess API token in `.env` as `LICHESS_TOKEN`
- Saved study ID in `~/.chess_transfer_config.json`

## What Works
- EPUB/PDF parsing
- Chapter extraction (by "Chapter N" markers)
- Game slicing (by "Game N" markers)
- Sticky regex (handles no-space notation)
- Stack-Based Tree Builder with Lookahead
- Main line vs variation disambiguation (current branch preference)
- Lichess upload with rate limiting
- All 15 unit tests passing

## Fixed (Previously Broken)
- Main line vs variation disambiguation when variation text appears before main line continuation
- Solution: "Current branch preference" - when multiple valid parents exist, prefer continuing on current branch (`current_node`), with lookahead disambiguation as fallback
