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

## Earlier
- Sonnet naive vs Maia-1100 (2 finished games, others aborted by spend limit): 0/2, both mated.
  Stockfish: 9/53 moves lost ≥200cp, all short tactics — see [[computer-chess-principles]].
