# claude_chess wiki — index

Agent-maintained knowledge base (Karpathy-style "LLM Wiki"): raw sources are read once,
distilled into interlinked pages here, and kept current. Every agent working on this repo
reads this index first and writes back what it learns. Pages are small and single-topic.

## Rules for agents
1. Read this index; open only the pages you need.
2. When you learn something non-obvious (a gotcha, a decision, a result), write/update a page
   in `pages/`, add a one-line link below, and append a dated line to `log.md`.
3. Prefer updating an existing page to creating a near-duplicate. Link pages with `[[page-name]]`.
4. Record *why*, not just *what*. Code structure lives in the code; the wiki holds reasoning.

## Pages
- [architecture](pages/architecture.md) — the pipeline, module ownership, data flow
- [decisions](pages/decisions.md) — design decisions log with rationale
- [llm-backend](pages/llm-backend.md) — how we call Claude (CLI vs SDK), latency, cost
- [illegal-moves](pages/illegal-moves.md) — policy for illegal LLM moves + prior art (research agent)
- [prior-art](pages/prior-art.md) — input format (FEN/PGN/ASCII) & prompt-design findings (research agent)
- [context-builder](pages/context-builder.md) — what features we extract and why (context agent)
- [engine](pages/engine.md) — prompts, proposer, evaluator, search (engine agent)
- [match-and-analysis](pages/match-and-analysis.md) — runner, adjudication, metrics (match agent)
- [results](pages/results.md) — experiment results
- [infra-failures](pages/infra-failures.md) — rate limits / backend errors abort games; never scored as illegal moves
- [computer-chess-principles](pages/computer-chess-principles.md) — hybrid search: quiescence, full-width tactical veto, batched positional eval
- [board-vision](pages/board-vision.md) — `--board-read`: Claude reports pieces/threats, scored vs the real board
- [reasoning-dataset](pages/reasoning-dataset.md) — traces of every agent call + engine-verified facts → SFT/DPO dataset for a move-explainer
- [context-research](pages/context-research.md) — how to get MORE RELEVANT context: data (coverage vs salience), literature, ranked plan
- [cloud-environment](pages/cloud-environment.md) — rebuilding Stockfish/lc0 in the cloud sandbox, blocked hosts, agent gotchas
- [maia-calibration](pages/maia-calibration.md) — Maia (human-like lc0 nets) as opponents, Lichess rating table, performance-rating stats (maia agent)
