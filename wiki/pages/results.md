# Results

## 2026-09-24 — Haiku 4.5 vs Maia-1100: naive vs hybrid (thinking off, --board-read)
Runs `20260924_203947_{naive,hybrid-ctx}-haiku-vs-maia1100` (in `db/games.sqlite`; runs/ is
gitignored). 4 games each, colours alternate, 6-ply book openings, SF depth-12 analysis.

| player | score | ACPL | blunders | calls/move | $ total (4 games) | s/move |
|---|---|---|---|---|---|---|
| naive Haiku | 0/4 (4 mated) | 220 | 16 | 1.05 | 0.22 | 6 |
| hybrid-ctx Haiku | 1.5/4 (3 draws, 1 loss) | 113 | 14 | 1.69 | 0.96 | 12.5 |

- All 3 hybrid draws were repetitions from level/worse positions (SF −73, −196, and one
  where Maia was mating and repeated checks) — no won games thrown away.
- Remaining hybrid blunders cluster in (a) **checks** Claude proposes (Bb4+, Bxb3+, Qf2+,
  Rd5+ — materially "safe" at depth 2 but positionally/tactically bad deeper) and
  (b) **lost-endgame king walks** into mating nets beyond depth 2.
- Board vision ([[board-vision]]): piece placement 91% (naive) / 97% (hybrid) correct;
  threat detection only 14/90 (naive) and 42/111 (hybrid) — seeing attacks is the gap.
- n=4 per arm: direction is clear (0 vs 1.5, ACPL halved), magnitude is not.

## 2026-09-24 — hybrid v2 (context v2 + threat agent) vs Maia-1100, 8 games
Run `20260924_210922_hybrid2-haiku-vs-maia1100`, Haiku 4.5, thinking off, --board-read,
--threat-agent, one game per opening in the 8-opening rotation.

| player | score | ACPL | blunders | calls/move | $ total (8 games) | s/move |
|---|---|---|---|---|---|---|
| hybrid v2 Haiku | **6/8** (6 W, 2 L; 1 L was a forfeit bug) | **63** | 7 | 2.33 | 2.82 | 14 |

- vs v1 (1.5/4, ACPL 113) and naive (0/4, ACPL 220). Same opponent/settings.
- The forfeit was a harness bug, not chess: compare + threat calls ran in parallel on the
  SAME board and the context builder push/pops on it → corrupted board → exception.
  Fixed (each thread gets `board.copy()`). The game was otherwise ongoing.
- Decision anatomy over 264 moves: candidates vetoed in 187, "only tactically sound
  candidate" (no compare call) 73, forcing moves injected 30, fail-low re-search 31,
  mates found 9, **threat agent verified refutation changed scores 9×**, forced moves 5.
- Remaining ≥300cp errors: 7 in 8 games; 3 in an already-lost K+P ending (tablebase
  unavailable in the sandbox — would have been exact on a normal machine).
- Tablebase + Lichess unreachable here; K+P rules in context were the only endgame help.

## 2026-09-24 — offline suite A/B: context v2 vs v3 (Haiku, 100 positions)
Suite `suites/v1.jsonl` (100 positions from our games, half "hard"; SF depth 14 labels; built by
`claude-chess suite build`). One decision per position, paired. (Code on branch `ctx-v3`,
merged after exp1.)

| player | mean cp loss | SF best played | blunders ≥200 | proposer recall (SF best among Claude's candidates) | $/position |
|---|---|---|---|---|---|
| naive Haiku | 471 | 14% | 66% | 14% | 0.0019 |
| harness, context v2 | 177 | 39% | 23% | 49% | 0.0082 |
| harness, context v3 | **160** | 40% | **17%** | **68%** | 0.0093 |

- Harness vs naive: −294 cp/position, paired permutation p = 5e-5.
- v3 vs v2: −17 cp (p = 0.35, n.s.); blunders 10 fixed vs 4 new (McNemar p = 0.18, n.s.);
  **proposer recall 22 gained vs 3 lost (McNemar p = 0.0002)** — the legal-move material check
  and last-move/relations context make Claude propose the right move far more often.
- Cost +13%/position. Next: a larger suite to resolve blunder rate, then v3 in games.

## 2026-09-24 — hybrid v3 alpha-beta (`--search alphabeta`) vs Maia-1100, 8 games
Run `20260924_213321_hybrid-ab-haiku-vs-maia1100`, same settings as v2 (Haiku, thinking off,
--board-read; threat agent supplies replies).

| player | score | ACPL | blunders | calls/move | $ total (8 games) | s/move |
|---|---|---|---|---|---|---|
| hybrid v2 compare+threat | **6/8** | **63** | 7 | 2.33 | 2.82 | 14 |
| hybrid v3 alpha-beta | 3.5/8 (2W 3D 3L) | 114 | 38 | 3.7 | 4.96 | 18 |

- Alpha-beta pruned ~40% of leaves (e.g. 3/7) but is **worse and dearer** than v2.
- Why (inspected every ≥300cp error; no search bug):
  1. Most blunders were decided before any search: every Haiku candidate lost material and
     the veto picked the least bad ("only tactically sound candidate"); the Stockfish best
     move was never proposed. Fail-low only fires below −tac_margin (−100), so "all lose a
     pawn" cases never widen to all legal moves. → lower the fail-low threshold to 0.
  2. **Pointwise positional scores are noisy**: independent leaf calls scored a king walk
     (Kd2, +45) above O-O-O (+45 tie → prior) etc. v2's single *listwise* compare call ranks
     siblings on one scale — consistent with LLM-as-judge findings (comparative > absolute).
  3. Lost endgames: depth-2 + ±150 positional can't see king-walk mating nets.
- Verdict: keep `compare` as the default harness; alpha-beta over LLM leaves needs a
  comparative leaf evaluator (e.g. batch all leaves under one root) to pay off.

## Earlier
- Sonnet naive vs Maia-1100 (2 finished games, others aborted by spend limit): 0/2, both mated.
  Stockfish: 9/53 moves lost ≥200cp, all short tactics — see [[computer-chess-principles]].
