# Computer-chess principles applied to the Claude engine

Code: `src/claude_chess/engine/tactical.py`, `ClaudeEnginePlayer(tactical=True)` in
`engine/players.py`, CLI specs `hybrid-ctx` / `hybrid-noctx`. Tests: `tests/test_hybrid.py`.

## Diagnosis (why the d0/d1/d2 LLM search loses to Maia-1100)
Stockfish review of the two finished naive-Sonnet vs Maia-1100 games (both lost by mate):
9 of 53 moves lost ≥200cp. **Every big one was a one/two-move tactic**: Bxe4?? walking into
…Rxb3 (-580 material), …Kh7?? allowing Qxg7#, f3/g3 allowing mate. A material-only
depth-2 search flagged all of them, and found Stockfish's best move in 6/9 cases.
Board reading was not the problem — see [[board-vision]]: Haiku lists piece placement
~100% right but misses what the pieces *attack*.

So the LLM is a decent *positional* evaluator and move generator, and a terrible
*tactical* calculator — the exact opposite of a classical engine's eval. Split the work.

## Principles adopted (hybrid pipeline, 1–2 Claude calls/move)
1. **Quiescence search** (horizon effect): leaves are never judged mid-exchange; captures
   (+ queen promotions, + all evasions when in check) are played out, stand-pat on material.
2. **Full-width verification** (engines never prune the opponent's reply): after each
   candidate, *every* opponent reply is searched `tac_depth` plies (default 2) + qsearch.
   Claude's d2 only looked at the K=2 replies Claude itself proposed — i.e. the refutation
   it had already missed.
3. **Separate material from positional eval** (engine eval = material + positional terms):
   material is exact (Python); Claude only scores positional merit in ±150cp, *relatively*,
   for all survivors in **one batched call** (consistent scale across siblings, and
   1 call instead of N — independent absolute LLM evals are noisy and not comparable).
4. **Forcing-move generation** (checks/captures/promotions always considered): forcing
   moves Claude didn't propose are injected if they win ≥ `tac_margin` more material.
5. **Tactical veto / pruning**: candidates > `tac_margin` (100cp) materially worse than the
   best are dropped. Mate found → play fastest mate. One survivor → play it, no eval call.
6. **Forced move / easy move** (time management): one legal move → 0 calls.
7. **Transposition table** for Claude's static evals (d1/d2 path) keyed by position.
8. **Move ordering** in the material search: TT move, MVV-LVA captures, promotions.

## What it deliberately is NOT
No Stockfish, no positional heuristics in Python: the search knows only piece values
(100/320/330/500/900) and mate. Positional sacrifices >1 pawn are vetoed by design —
acceptable at this level, revisit if testing stronger models (raise `--tac-margin`).
This muddies "Claude plays chess" vs "Python plays chess": report hybrid results as a
separate arm, and compare `hybrid-ctx` vs `hybrid-noctx` for the context question.

## Cost / speed
Python search ≈ 0.1–0.3 s per scored move (≈1 s per decision for ~10 moves). Haiku,
thinking off: ≈ $0.008/move (propose + compare) vs $0.0024 naive. See [[llm-backend]]
for the thinking-budget gotcha (default CLI thinking made one Haiku call cost $0.09).

## Ideas not yet built
- Null-move threat check in the positional prompt (already in context builder output).
- Aspiration: re-ask Claude for more candidates when every proposal is vetoed.
- Iterative deepening under a per-move node/time budget; deeper tac_depth in endgames.
- Opening book from the ECO table (skip calls for the first moves).
- Syzygy tablebases for ≤5-piece endings (python-chess supports probing).
