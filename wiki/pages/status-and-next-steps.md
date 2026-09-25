# Status & next steps (handoff, 2026-09-25)

Read this first when resuming. Details live in the linked pages; PR: d4nu-00/claude_chess#1.

## Where things stand
- **Best player:** `hybrid-ctx --threat-agent --ctx-version 3` (Claude proposes + judges;
  Python tactical search in `engine/tactical.py` verifies material/mate). Default compare
  mode, not alpha-beta. See [[computer-chess-principles]].
- **Headline results** ([[results]]): naive Claude lost all 36 games vs Maia (Haiku 0/24,
  Sonnet 0/12). Harness: Haiku 6.5/12 (ctx v2), 7.5/12 (ctx v3); Sonnet 10.5/20; harness vs
  naive p ≤ 0.012 both models. Opus 5.5 + harness beat Maia-1900 in its one game (ACPL 20).
- **Context v3** ([[context-builder]], [[context-research]]): same game strength as v2 at
  n=12, but Claude's own #1 move is played 65% (v2 41%) and the search adds only 2% of moves
  (v2 13%). Suite: proposer recall 49%→68% (p=0.0002).
- **Dataset** ([[reasoning-dataset]]): `datasets/reasoning_v1/` — 2,384 positions, SFT +
  DPO pairs, all Stockfish-labelled. Newer runs (exp2, Opus) are NOT yet exported:
  re-run `claude-chess dataset --out datasets/reasoning_v2`.
- **Spend so far** ≈ $50 API (Haiku ≈ $0.37/game, Sonnet ≈ $1.3, Opus ≈ $5.5 with harness).

## Key lessons (the non-obvious ones)
1. LLM chess losses are tactical and happen *before* search: the right move is often never
   proposed (61% of Haiku blunders). Improve proposal recall, not evaluation.
2. Context must be move/change-conditioned (what the last move and each candidate change);
   pre-move context contained the refutation only 9% of the time.
3. Listwise (batched) comparison of candidates beats pointwise LLM leaf evals — alpha-beta
   over Claude leaves was worse and dearer (3.5/8 vs 6/8).
4. Claude reads piece placement ~97% right but misses what pieces attack; it describes
   recaptures as "wins outright". Trust only `[verified]` facts in training data.
5. Track **reliance on the tactical search** (`claude-chess report`): gains that come from
   "moves added by search" are Python playing chess, not Claude.
6. Use the 100-position suite (`claude-chess suite`) before paying for games; games at n=12
   cannot detect modest differences.
7. `claude -p` defaults to extended thinking — always pass `--thinking 0` (or a cap).

## Resume checklist
- Mac: Stockfish/lc0 via Homebrew; tablebases (Lichess API) work there.
- Cloud: follow [[cloud-environment]] (apt Stockfish at /usr/games, build lc0, fetch Maia).
- `uv run pytest -q` (91 pass). Live dashboard: `scripts/live_status.py`; game viewer:
  `scripts/game_viewer.py RUN_DIR`.

## Next steps (cheapest first)
1. Export dataset v2 (free). 2. Grow the suite to 200–300 positions and re-test v3 vs v2
   (~$3). 3. Deeper verification along the threat agent's named line (would have caught
   Sonnet's 10.f4). 4. Context ideas F–H in [[context-research]] (master-game retrieval,
   Claude asks questions, learned relevance). 5. Opus arm (~$65 for 12 games) when budget allows.
