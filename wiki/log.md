# wiki log (append-only, newest last)

- 2026-09-24 orchestrator: created project skeleton, contracts in types.py, wiki scaffolding.
- 2026-09-24 research agent: surveyed prior art (Game Arena, ChessArena, llm_chess, Carlini, Dynomight, TCEC) for illegal-move handling and input format; wrote illegal-moves.md and prior-art.md. Recommend 2 retries + error/legal-list feedback + random-move fallback (no forfeit) so games finish and illegal-rate stays measurable.
- 2026-09-24 match agent: built match/ (baselines, openings, runner, analysis), cli.py (match/analyze/context), tests/test_match.py; see [[match-and-analysis]].
- 2026-09-24 engine agent: llm.py (CLI via stdin + SDK), engine prompts/players (d0/d1/d2 search, illegal-move retries per [[illegal-moves]], added MoveDecision.forced_random); wiki/pages/engine.md; haiku smoke OK.
- 2026-09-24 context agent: built context builder (openings by EPD from lichess ECO TSVs, pawn structures incl. named ones, king safety, activity, SEE tactics + null-move threats, concept KB of 25 pages + opening plans); see [[context-builder]].
