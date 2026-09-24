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

## Earlier
- Sonnet naive vs Maia-1100 (2 finished games, others aborted by spend limit): 0/2, both mated.
  Stockfish: 9/53 moves lost ≥200cp, all short tactics — see [[computer-chess-principles]].
