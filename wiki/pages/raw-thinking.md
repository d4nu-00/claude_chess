# Raw thinking player (`raw-text` / `raw-image`)

Reproduces https://openfill.ai/blog/adventures-in-astra-and-chess with Opus 5.5: no harness,
no search, no context builder. One stateless prompt per move, max reasoning effort, move read
from a final `make_move <UCI>` line. Code: `engine/raw.py`, `ClaudeCLIStream` in `llm.py`.

## Setup (from the blog)
- System: "You are a precise chess engine. You always reply with a single legal move."
- User: colour, `Board:`, FEN, legal moves (UCI), "reply ... FINAL line, exactly as: make_move <UCI>".
- Opponent: Maia-3 79M at Elo 2400 (`maia3:2400:79m`, argmax; blog gives no temperature). No openings, 200-ply cap.
- Our differences: one extra prompt line asking for a short justification before the final line;
  illegal reply -> re-prompt (2 retries) then forfeit; SF resign at ±1000cp for 6 plies (saves usage).

## Two conditions
`raw-text` shows the Unicode board (mover at bottom); `raw-image` replaces it with a PNG
(python-chess SVG -> ImageMagick `magick`, needs `brew install imagemagick`). FEN and legal
moves stay in both, so the only difference is the board rendering.

## Reasoning capture (the point of the run)
- `decisions.jsonl` row `search`: `reasoning` (text before the final line), `thinking_tokens`, `thinking`.
  Full prompt/response per call in `traces.jsonl` (role `raw`). Readable dump:
  `uv run python scripts/reasoning_report.py RUN_DIR` -> `reasoning.md`.
- **Raw CoT is not obtainable via the CLI.** Default thinking blocks come back empty.
  `--settings '{"showThinkingSummaries":true}'` returns a *summary* on Haiku, but on Opus 5.5
  the thinking text stayed empty (usage still reports `thinking_tokens`, ~3-6k in the opening).
  So the saved "why" is the model's own written justification, not its hidden reasoning.

## Gotchas
- Image input needs `--input-format stream-json` (base64 image block); plain `-p` can't take images.
- Cost/latency (2026-09-25): opening move ≈ $0.04-0.13, 15-65 s at `--effort max`.

## Random openings (`--random-openings`)
Skips the first plies so the model isn't spending tokens on 1.e4-type moves and games diverge.
Random walk over ECO **main-line** continuations (`context/book.py`), `--opening-plies N` (default 8),
`--opening-seed S` (reproducible). One opening per game pair, both colours play it. Replaces the
fixed 8-opening rotation (which gave games 0/1 the Ruy Lopez every time); the skipped plies are
"book" so ACPL/analysis cover only played moves. Main-line weighting repeats popular lines
(Ruy, QGD) — raise `--opening-plies` (10-12) for more variety.

## Live broadcast page (`scripts/broadcast.py` + `broadcast.html`)
Lichess-broadcast-style viewer: game tabs, board, eval bar, Stockfish eval-over-time graph (click to jump),
move list with ?!/?/?? swing marks, Opus's written reasoning for the selected move, and a live "thinking for
m:ss" timer for the move in progress. `uv run python scripts/broadcast.py` serves http://<LAN-IP>:8765
(polls `runs/*raw-*/decisions.jsonl` every 3 s; evals cached in `runs/_broadcast_evals.json`, display only).
`--export FILE.html` writes a static snapshot. Game status comes from running `claude-chess match --label`
processes; decision rows now carry `ts` (older rows fall back to the file mtime). Games are merged across
original + resumed runs, so a resumed game is one continuous game.
