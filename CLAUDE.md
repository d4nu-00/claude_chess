# claude_chess

Harness where Claude plays chess like an engine: a context builder describes the
position, Claude proposes candidate moves, a search layer plays them out on a real
board and Claude evaluates the leaves. Experiment: does context improve play?

**Start here: read `wiki/index.md`.** It is the shared, agent-maintained knowledge base
(LLM-Wiki pattern). If you learn something non-obvious, add or update a page in
`wiki/pages/`, link it from `wiki/index.md`, and append one line to `wiki/log.md`.

- Run tests: `uv run pytest -q`
- Contracts every module codes against: `src/claude_chess/types.py`
- LLM backend: `claude -p` CLI by default (no API key needed); Anthropic SDK if `ANTHROPIC_API_KEY` set.
- Stockfish (`/opt/homebrew/bin/stockfish`, or `$STOCKFISH_PATH`) is used ONLY as an opponent
  and for post-game analysis — never inside a Claude player's decision.
- Current best player: `hybrid-ctx` (Claude + Python material search) — see
  `wiki/pages/computer-chess-principles.md` and `wiki/pages/results.md`.
- Cloud sandbox (no Homebrew): setup steps in `wiki/pages/cloud-environment.md`.
- Every experiment: record results in `wiki/pages/results.md` and commit `db/games.sqlite`.
