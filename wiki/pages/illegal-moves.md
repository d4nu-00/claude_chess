# Illegal moves: policy + prior art

Research pass (2026-09-24) on how other LLM-chess harnesses handle illegal moves,
so we can set our retry/feedback/exhaustion policy deliberately. See also
[[prior-art]] for input-format findings (FEN vs PGN vs ASCII).

## Prior art

| Source | Retries | Feedback given | Legal-move list given? | Exhaustion policy | URL |
|---|---|---|---|---|---|
| Kaggle/DeepMind **Game Arena** chess | up to 3 (4 attempts total) | "previous move was illegal" + optional rule-based reason ("rethink" mode) | not by default; ASCII/dict formats available as alt. representations | model **disqualified / forfeits game** | [github.com/google-deepmind/game_arena](https://github.com/google-deepmind/game_arena) |
| **ChessArena** (arXiv 2509.24239) | 1 | notes the move was illegal | not stated as given | **2nd illegal move = forfeit** (explicitly modeled on FIDE over-the-board rule) | [arxiv.org/html/2509.24239v4](https://arxiv.org/html/2509.24239v4) |
| maxim-saplin **llm_chess** | 3 attempts/turn (agentic, tool-calling) | explicit error string (`Failed to make move: illegal uci`) + FEN | yes, via a `get_legal_moves` tool the model can call | turn/game recorded as **loss** ("too many wrong actions") | [github.com/maxim-saplin/llm_chess](https://github.com/maxim-saplin/llm_chess/blob/main/docs/notes.md) |
| Carlini **chess-llm** (GPT-3.5-turbo-instruct) | 0 (no loop) | none | no | move validated post-hoc; illegal moves were rare enough (~1750 Elo play) that no recovery path was built | [nicholas.carlini.com/writing/2023/chess-llm.html](https://nicholas.carlini.com/writing/2023/chess-llm.html) |
| **Dynomight** LLM-chess experiments | up to 10 (closed models, no grammar constraint) | none described beyond re-sampling | no | falls back to **uniform-random legal move** ("I just chose one randomly") — open models instead used grammar-constrained decoding so illegal moves were structurally impossible | [dynomight.net/chess](https://dynomight.net/chess/), [dynomight.net/more-chess](https://dynomight.net/more-chess/) |
| TCEC / UCI convention (classical engine-vs-engine) | 0 | n/a — engines are deterministic UCI programs, not sampled | n/a | illegal move = **immediate loss**, no replay/adjudication | [wiki.chessdom.org/Rules](https://wiki.chessdom.org/Rules) |

Unverified / could not confirm precisely: Game Arena's exact retry count comes from
secondary reporting (winbuzzer.com) corroborated by the repo's own "limited number of
times" wording in its README — the literal integer isn't pinned down in the source I
could fetch, so treat "3" as approximate. ChessGPT / lichess-bot LLM integrations were
not found with a clearly documented illegal-move policy in this pass.

## Recommendation for claude_chess

Our harness already re-asks once with error + legal-move list (architecture.md step 4).
Based on the above, refine to:

- **Retries: 2 retries (3 attempts total) per move.** This sits between ChessArena's
  minimal 1-retry-then-forfeit (built for a competitive ladder, not diagnostics) and
  Game Arena's ~3-retry "rethink" loop. Two retries is enough to separate a one-off
  parsing slip from genuine confusion, without inflating latency/cost per move.
- **Feedback on retry: the specific illegality reason (from python-chess, e.g. "not a
  legal move in this position" / "ambiguous SAN") + the full legal-move list.** We
  already compute the legal-move list for validation, so handing it back is free and
  maximizes recovery — this also lets us attribute failures to "rule confusion"
  (recovers when given the list) vs "board-state confusion" (doesn't recover), which
  matters since illegal-move rate is one of our headline metrics.
- **Exhaustion policy: do NOT forfeit the game — fall back to a uniform-random legal
  move**, following Dynomight's approach for closed models. Rationale: our two other
  constraints (games must finish; we compare context vs no-context Claude across full
  games for ACPL/blunder-rate) are undermined by early forfeits, which would
  truncate games asymmetrically between conditions and bias downstream metrics
  (a context-off game that forfeits at move 12 isn't comparable to a context-on game
  that plays to move 60). Forfeit-on-illegal is the right call for a competitive
  ladder (Game Arena, ChessArena, TCEC) where the *result* is the product; it is the
  wrong call for us, where the *illegal-move rate itself* is the product.
- **Record forced-random fallbacks as a distinct counter** (not folded into the
  "illegal attempt" count) so `match.analysis` can report, per player/condition:
  illegal-attempt rate (attempts / total moves proposed), and forced-random-move rate
  (moves where all retries failed) separately — mirroring how ChessArena scores an
  illegal move as Q=0 rather than silently dropping it, and how Game Arena logs
  "too many wrong actions" as a distinct failure category from a natural loss.
- **Safety valve:** if a single game accumulates an excessive number of forced-random
  moves (e.g. 5+), consider flagging/adjudicating it as an anomaly rather than letting
  it run to completion on random play — keeps pathological games from dominating
  aggregate stats. (Threshold not validated against data yet — revisit once we have
  real illegal-move-rate numbers.)
