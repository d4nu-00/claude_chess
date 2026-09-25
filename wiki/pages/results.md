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

## 2026-09-25 — exp3: context v4 (named tactical motifs) in games (Haiku, Maia 1100/1500/1900, 4 games each)
Report `experiments/exp3/`. Same openings/colours/settings as exp1/exp2 (paired), played locally
via `claude -p`. Harness also includes the new declared-sacrifice path (see [[engine]]).

| Haiku config | 1100 | 1500 | 1900 | total | Elo (95% CI) | ACPL | blunder rate | $/game | s/move |
|---|---|---|---|---|---|---|---|---|---|
| harness ctx v3 (exp2) | 3.5/4 | 1/4 | 3/4 | 7.5/12 | 1659 (1321–2043) | 72 | 4.8% | 0.37 | 12.4 |
| harness ctx v4 (exp3) | 3/4 | 1/4 | 2/4 | 6/12 | 1500 (1233–1833) | 64 | 3.6% | 0.38 | 9.7 |

- v4 vs v3, paired by opening/colour/level: −0.125 points/game (p = 0.62); per-game ACPL −8
  (p = 0.67); 6/12 identical results → **no measurable difference at n = 12**. Directionally:
  fewer ≥300cp blunders (4.8% → 3.6%), faster moves (12.4 → 9.7 s), same cost.
- Reliance: Claude's #1 played 55% (v3 65%), overruled 17% (16%), fail-low 18% (15%).
- **Sacrifice path barely matters with Haiku**: 39 declared "sacrifices" survived the veto, but
  Haiku labels loosely (e.g. Kxa6, Rgd8) and its own compare step awarded too little
  compensation for 38 of them; 1 was played (55…Rxe6, −800 material in a fail-low position,
  −415cp by SF). Watch this with Opus, which declares sacrifices more deliberately.
- To separate motifs from sacrifices and get power: ≥40 paired games per arm, or the offline
  position suite (paired, much cheaper) — see [[context-research]].

## 2026-09-24 — showcase: Opus 5.5 + harness (ctx v3, threat agent) vs Maia-1900, 1 game
Run `20260924_225106_opus-harness-vs-maia1900`; viewer `experiments/opus/game_opus_vs_maia1900.html`
(`scripts/game_viewer.py`). Opus as White, Ruy Lopez Exchange, **won** (resign adjudication at
+38 after 55.g4). **ACPL 19.7**, 0 blunders, one mistake (24.Nd2, −2.2); cost **$5.53** (52
moves × $0.106, 2.8 calls/move, 23 s/move — ≈17× Haiku per game).
Reliance on the tactical search: Claude's #1 played 38/52 (73%), overruled **1/52**, moves added
by search **0**, fail-low **0** — Opus played essentially all of its own chess; the harness only
checked. Key moments: 9.Qg3 double attack (e5+g7) → 10.Qxe5 wins a pawn; 18.Ra7 invasion (+1.9);
26.Qxc7 into a won ending; passed d-pawn 36.d5–39.d6; 41–44 wins the bishop; Maia's 52...h5?? ends it.
n = 1: a showcase, not a measurement.

## 2026-09-24 — exp2: context v3 in games (Haiku, Maia 1100/1500/1900, 4 games each)
Reports: `experiments/exp2/`, combined with exp1 in `experiments/exp1_exp2_combined/`
(`claude-chess report exp`). Same openings/colours/settings as exp1; 24 games, ≈ $4.7.

| Haiku config | 1100 | 1500 | 1900 | total | Elo (95% CI) | ACPL | $/game | s/move |
|---|---|---|---|---|---|---|---|---|
| harness ctx v2 (exp1) | 2/4 | 2.5/4 | 2/4 | 6.5/12 | 1552 (1153–1960) | 72 | 0.31 | 15.1 |
| harness ctx v3 (exp2) | 3.5/4 | 1/4 | 3/4 | 7.5/12 | 1659 (1321–2043) | 72 | 0.37 | 12.4 |
| naive (exp1+exp2) | 0/8 | 0/8 | 0/8 | 0/24 | – | 212 | 0.02 | 4.1 |

- v3 vs v2: +0.08 points/game, permutation p = 0.85 → **no measurable strength change in
  games** at n=12 (ACPL identical, 72).
- v3 vs naive: +0.62/game, p < 0.0001. Naive Haiku now 0/24.
- **Big shift in WHO plays the moves** (reliance on the Python tactical search):

| | Claude's #1 played | #1 overruled by search | move added by search | no Claude value call |
|---|---|---|---|---|
| ctx v2 | 41% | 42% | 13% | 39% |
| ctx v3 | **65%** | **16%** | **2%** | 26% |

  With the material check / relations / last-move context, Claude proposes safe moves itself;
  the same strength is now reached with far less Python override — more of the chess is
  Claude's (also better training data for [[reasoning-dataset]]). Slightly dearer per game
  (+19%) but faster per move (fewer vetoes → fewer extra calls).

## 2026-09-24 — exp1: harness vs no harness × Haiku/Sonnet × Maia ladder (FINAL)
Full report: `experiments/exp1/crosstable.md` (+ `games.csv`, `stats.json`); script
`scripts/exp_harness_vs_naive.sh`; report `claude-chess report exp1`. Thinking off for all;
resign adjudication ±1000cp × 6 plies; openings paired by Maia level. Budget-trimmed (user):
Sonnet-harness at 5 levels, other arms at 1100/1500/1900. 8 games that failed at engine
start-up were re-run with `--only-games` (same opening/colour). 56 games, ≈ $32 API.

| config | 1100 | 1300 | 1500 | 1700 | 1900 | total | Elo (95% CI) | ACPL | $/game | s/move |
|---|---|---|---|---|---|---|---|---|---|---|
| haiku-harness | 2/4 | – | 2.5/4 | – | 2/4 | 6.5/12 | 1552 (1153–1960) | 72 | 0.31 | 15 |
| haiku-naive | 0/4 | – | 0/4 | – | 0/4 | 0/12 | – (all lost) | 201 | 0.02 | 4.5 |
| sonnet-harness | 3/4 | 2.5/4 | 2.5/4 | 1.5/4 | 1/4 | 10.5/20 | 1528 (1332–1716) | 46 | 1.32 | 19 |
| sonnet-naive | 0/4 | – | 0/4 | – | 0/4 | 0/12 | – (all lost) | 115 | 0.13 | 4.2 |

Harness vs no harness (levels both arms played, 12 vs 12 games each):
- Haiku: +0.54 points/game, stratified permutation p = 0.012, LR p = 5e-5, ACPL 201→72
  (Mann-Whitney p = 1e-4); $0.54 extra per extra point.
- Sonnet: +0.54 points/game, permutation p = 0.001, LR p = 5e-5, ACPL 115→46 (p = 2e-4);
  $1.97 extra per extra point.
- **Naive Claude lost all 24 games** (both models, all levels). The harness is significantly
  better for both models.
- Haiku-harness ≈ Sonnet-harness in score (Elo CIs overlap heavily). Sonnet is more accurate
  (ACPL 46 vs 72) and leans less on the tactical search (#1 overruled 27% vs 42%, moves added
  by search 5% vs 13%) but costs ~4× per game. Haiku's 2/4 vs Maia-1900 (Sonnet 1/4) = two
  comebacks after Maia blunders (Maia is policy-only, blunders tactically) vs Sonnet saving two
  lost games by repetition — noise at n=4.
- Maia's nominal ratings are used for Elo; treat absolute Elo as rough ([[maia-calibration]]).

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
