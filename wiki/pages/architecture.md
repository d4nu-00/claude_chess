# Architecture

Claude as a chess engine = **policy** (Claude proposes candidates) + **value** (Claude
evaluates positions) + **search** (Python minimax over a tiny tree on a *real* board).
Context (opening, pawn structure, concepts) is injected into both policy and value prompts.
The experiment toggles context on/off and compares.

## Per-move pipeline (ClaudeEnginePlayer)
1. `context.build_context(board) -> PositionContext` — pure Python, no LLM. Opening lookup
   (ECO table), material, pawn structure (isolated/doubled/passed/backward, islands, named
   structures e.g. IQP, Carlsbad), king safety, activity, tactical flags (hanging pieces,
   checks, captures), phase, and retrieved concept notes from `knowledge/`.
2. `render_context(ctx)` -> markdown block for the prompt.
3. **Proposer** (Claude): returns JSON `{candidates:[{move, reason, prior}]}` (N≈3-4).
4. **Validator** (python-chess): parse SAN/UCI; drop illegal ones; if none legal, re-ask with
   the error + legal move list (see [[illegal-moves]]).
5. **Search** (depth configurable):
   - d0: pick highest-prior legal candidate (1 call/move).
   - d1: push each candidate on a real board copy, **Evaluator** (Claude) scores each child.
   - d2: for each candidate, opponent-proposer suggests K replies, evaluator scores leaves,
     minimax backs up (worst reply for us). Calls run in parallel threads.
   Terminal positions (mate/stalemate/draw) are scored exactly, never sent to Claude.
6. Return `MoveDecision` (move, candidates with scores + PV, illegal attempts, cost).

## Hybrid pipeline (current best; `ClaudeEnginePlayer(tactical=True)`, CLI `hybrid-ctx`)
Claude proposes → Python material search (alpha-beta + quiescence, `engine/tactical.py`)
scores every candidate + all forcing moves → tablebase / mate / veto / fail-low shortcuts →
either one batched positional **compare** call (+ optional threat agent), or depth-2
**alpha-beta** over Claude positional leaves (`--search alphabeta`). Details and rationale:
[[computer-chess-principles]]. Every call is traced for the [[reasoning-dataset]].

## Players
- `NaiveClaudePlayer` — one call: FEN + move list -> move. The "plain Claude" baseline.
- `ClaudeEnginePlayer(use_context=bool, depth=0|1|2)` — the original LLM-only search.
- `ClaudeEnginePlayer(tactical=True, search="compare"|"alphabeta", threat_agent=bool)` — hybrid.
- `StockfishPlayer(elo|skill)`, `RandomPlayer` — reference opponents.

## Match layer
`match.runner` plays games (alternating colours, ply cap -> Stockfish adjudication), writes
`runs/<id>/games.pgn`, `decisions.jsonl`, then `match.analysis` computes per-player ACPL,
blunders, illegal-move rate, cost, and `report.md`.

## Module ownership
| Area | Files |
|---|---|
| contracts | `src/claude_chess/types.py` |
| context | `src/claude_chess/context/*`, `knowledge/*` |
| LLM + engine | `src/claude_chess/llm.py`, `src/claude_chess/engine/*` |
| match + CLI | `src/claude_chess/match/*`, `src/claude_chess/cli.py` |
