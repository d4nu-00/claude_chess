# Explainer model: engine lines → concepts → condensed human explanations

Goal (user, 2026-10-02): a model that explains chess moves the way a coach would — not a
20-ply line but a condensed, slightly vague *idea* ("trade the defender of the dark
squares, then go for the king"), plus the named concepts behind it and a score. Inspired by
Schut et al. 2023 (concepts mined from AlphaZero's latents, taught to grandmasters) and
McGrath et al. 2022 (human concepts are linearly readable inside AlphaZero).

Code: `src/claude_chess/explainer/`. Data/checkpoints: `data/` (gitignored, regenerable).
Small curated artifacts (teacher labels, dataset card): `datasets/explainer_v1/`.

## Core principle: each source labels what it is best at
| label | source | why |
|---|---|---|
| which move is best, by how much, the lines | Stockfish (Lichess cloud evals, depth 30-90) | ground truth, free |
| which human concepts are present / change along a line | Python detectors (`explainer/concepts.py`) | exact, cheap, scalable to millions |
| *why*, condensed into one human idea + named concepts | Claude (teacher), only on ~2k positions | the irreducibly linguistic part; expensive |
| concepts nobody named yet | sparse autoencoder on our own encoder's latents, named by Claude | Schut-style discovery |

The LLM is never the source of truth for chess facts (see [[reasoning-dataset]] error list:
"Rxc7 wins the queen" after a recapture, material drift). Its claims are checked by a
verifier against the lines before they become training text.

## Approaches considered
1. **Fine-tune a small LM on FEN → explanation directly.** Rejected: small LMs can't read a
   board (naive Haiku saw 14/90 threats, [[board-vision]]); it would learn to sound right.
2. **Chess encoder + small LM, connected by text (chosen).** The encoder (or Stockfish)
   produces eval, best/alt lines and concept scores; these are rendered as a short text
   block that a LoRA-tuned small LM turns into the explanation. Interpretable interface,
   data-efficient (thousands of examples, not millions), either half replaceable.
3. **Encoder + LM fused by a learned projector (LLaVA-style soft tokens).** Better in the
   limit, but the projector needs far more paired data than we can buy. Future work, once
   approach 2 has produced a large set of verified explanations.

## Pipeline
```
Lichess eval DB (5.5M positions streamed, cp from WHITE's view, up to 5 PVs)
Lichess puzzles (6.2M, human theme labels: fork, pin, hangingPiece, mateIn2 ...)
   │  structure-hash split (pawns+material signature → near-duplicates share a split)
   ▼
concepts.py: static concepts per side (us/them) + line deltas for best line and alt line
   │  salience = Δconcepts(best line) − Δconcepts(alt line), z-scored → "what the best
   │  move achieves that the alternative doesn't" (programmatic version of Schut's
   │  chosen-vs-rejected rollouts)
   ▼
teacher (Claude, ~2k positions): engine lines + verified facts + vocabulary →
   {assessment, idea, why_best, why_not_alt, concepts, novel_concept, plan}
   → verifier (move refs legal / in lines, material claims match line material) → flags
   ▼
encoder (torch, MPS): 64 square tokens, side-to-move POV; heads: value (HL-Gauss win%),
   policy (bilinear from→to), concept + salience heads as STOP-GRAD probes (trunk is shaped
   by play only, so discovery isn't biased by our labels)
   ▼                                   ▼
explainer LM (Qwen-class 1.7-2B,       concept discovery: TopK SAE on encoder latents
 MLX LoRA): rendered facts → text       (static, and best-end minus alt-end differences);
                                         correlate with known concepts + puzzle themes;
                                         Claude names features, simulation-scored
```
Inference has two modes: **engine mode** (Stockfish lines + detector concepts → LM) and
**engine-free mode** (encoder eval/policy/rollouts + predicted concepts → LM).

## Key choices (why)
- **Side-to-move POV everywhere** (board flipped for Black, concepts as us/them): halves
  what the model must learn; standard in Lc0 and searchless-chess.
- **HL-Gauss value bins** over win% (Lichess formula), not MSE on cp: robust to mates and
  huge evals; worked best in Ruoss et al. 2024 (searchless chess).
- **Soft policy target** over the multi-PV moves weighted by win% gap: more signal per
  position than one-hot best move.
- **Stop-grad concept probes by default**: lets us ask McGrath's question (does play alone
  produce human concepts?) and keeps SAE discovery honest. A multi-task variant (gradients
  flow) is the ablation.
- **Split by structure hash**, never random: cloud-eval positions come from the same
  analysis sessions and would leak.
- **Explanation format = one-line idea first**, then why / why-not / concepts / plan — the
  condensation the user asked for is the first thing produced, detail is optional.

## Evaluation
- Encoder: value MAE (win%), policy top-1 vs Stockfish, puzzle first-move accuracy,
  probe AUC/R² per concept (vs a random-init trunk baseline).
- Explainer: verifier pass rate; concept F1 vs teacher; blind pairwise judge (Claude) vs
  teacher text and vs the untuned base LM; **transfer test** — does a reader (Haiku) pick
  the best move over the alternative more often when given the explanation?
- Discovery: auto-interp simulation score per named feature; overlap with known concepts.

## Status (2026-10-03): v1 built end to end — what works, what doesn't
Full numbers in [[results]]; discovery in [[concept-discovery]]; showcase page
`experiments/explainer/showcase.html`; reproduce with `experiments/explainer/README.md`.
- **Works**: data pipeline (550k positions), concept detectors + contrastive salience, Opus
  teacher (93% of ideas judged correct by a blind Opus judge), encoder (puzzles 63%, concept R² 0.47
  vs 0.28 for a random network), SAE discovery (best-minus-alternative features = castle / king out of
  the centre / avoid the queen trade, Claude predicts them 9-10/10; king-safety ones teachable),
  `explain` CLI in engine and engine-free mode.
- **Doesn't (yet)**: the 1.7B student. Format, length and vocabulary are learned; chess content
  isn't — 10% of its one-line ideas judged correct. Errors are board geometry ("Rd8 guards f6").
- **Next, in order of expected value**: attack/defence relations in the student's input;
  5-10× teacher labels (≈340 per plan session window); Qwen3-4B QLoRA or encoder→LM soft-prompt
  fusion (approach 3); a geometry fact checker for filtering and preference pairs; turn teachable
  discovered features into vocabulary ids.

## Round 2 (2026-10-04): a model that picks AND explains
User clarified the goal: one model that selects the move and gives its idea. Built `explainer/joint.py`
(LM chooses among encoder candidates from verified facts) + GUI `scripts/play.py`. Best: model E
(move-first, with each candidate's forcing-play outcome) — 34% / 72-75% vs the instinct's 26% / 63%;
ideas still ≈27% sound. Full story: [[explainer-hypotheses]], numbers in [[results]].

## Gotchas & measurements (2026-10-02)
- **Lichess PVs write some castles king-takes-rook (`e8h8`).** python-chess accepts both forms
  as legal, but they encode to different from→to policy slots, so 1.3% of policy targets landed
  on "illegal" moves (loss ≈ 200). `data.normalize_line` re-parses every PV move.
- **Per-side material is the wrong salience unit**: an even trade shows as "ours −1, theirs −1".
  Salience uses `g.material_balance` (+ `g.checkmate`), with priority weights so a cause
  ("wins the queen") outranks its consequence (their mobility collapses).
- Lichess cloud-eval cp is from **White's** view; we store the mover's win prob.
- Cloud-eval head: ~84% of positions have ≥2 PVs; depth 30-90. Featurizing ≈ 7 ms/position
  (3 concept passes + 2 move-fact passes), ~4 min per 50k on 9 cores.
- Teacher pilot (4 positions each): Opus 5.5 medium effort ≈ $0.03/position, 6-11 s; low effort
  costs the same (input tokens dominate); Sonnet 5.5 ≈ $0.019 but writes longer "ideas" (17+
  words) — Opus condenses better, which is the point. All 12 pilot labels passed the verifier.
- (Superseded: the student is Qwen3-1.7B, see below.) Qwen3.5-2B (`mlx-community/Qwen3.5-2B-bf16`, Apache-2.0, 4.4 GB) loads in mlx-lm in 7 s,
  ~25 tok/s on M1 Pro. Its chat template always emits an empty `<think></think>` block, both for
  training sequences and generation prompts, so prompt masking lines up. Untuned it writes
  verbose, wrong prose ("forces the king to the 7th rank" for a back-rank mate) — the baseline.

- **torch-MPS is slow for this model; MLX is 3.2× faster.** 8-layer d=256 trunk, batch 512×65
  tokens: torch 2.14 MPS ≈ 265 pos/s (stock TransformerEncoderLayer and a hand-written SDPA block
  alike; fp16 autocast no help), MLX fp32 + `mx.compile` ≈ 850 pos/s (bf16 slower, 480). The
  encoder is MLX; the SAE (tiny) stays torch.
- **16 GB unified memory: one GPU job at a time.** LoRA on Qwen3.5-2B while the encoder trains →
  Metal `kIOGPUCommandBufferCallbackErrorOutOfMemory`.
- **`claude -p` on a subscription hits the plan's session limit** ("You've hit your session limit
  · resets 10:10pm") after ~340 Opus teacher calls (~$12 notional) in one window, on top of the
  orchestrating session's own usage. `teacher.run` now halts on `LLMUnavailable` instead of
  cycling through the queue; rerun to resume (it skips labelled FENs). Selection order is
  test → val → train so a cut-off shrinks training data, never the eval sets.

- **Qwen3.5-2B can't be LoRA-trained on 16 GB in mlx-lm.** It's a hybrid (3 of 4 layers are
  gated-delta-net linear attention) and the backward pass through those materialises per-token
  recurrent state — Metal OOM at the first step even at batch 2, seq ≤830, with 80% RAM free.
  Student switched to **Qwen3-1.7B** (dense attention, Apache-2.0): trains at batch 2 + grad
  accumulation 2, ~7 s/iteration, ~105 completion tok/s. Its template also emits an empty
  `<think></think>`; generation uses `enable_thinking=False`, which puts the same block in the prompt.
- **Free the GPU between jobs**: the stalled encoder run (after the OOM) sat in swap for an hour.
  `Batcher.slim()` drops strings/deltas before training (≈1.5 GB) — throughput 387 → 740 pos/s
  under memory pressure. `--resume CKPT --start-step N` restarts from a checkpoint.

- **Distillation gap: the teacher saw the board, the student didn't.** v1 student input was the
  facts block without the ASCII diagram (a 1.7B model can't read one, nor a FEN). Result: perfect
  format and 12-word ideas, but wrong pieces ("take the loose g3-pawn" for a bishop capture).
  Fix (v1.1): student facts now spell out what the teacher could see — piece list, every
  capture in the lines named ("2.Bxd8(takes queen)"), what each candidate move then attacks,
  and winning captures / threats for both sides. Labels unchanged; facts are re-rendered from
  FEN + lines at SFT-build time (`lm.student_facts`). General rule: **anything the teacher
  used must be in the student's input in a form the student can read.**
- LoRA v1 (573 examples, batch 2×2, lr 1e-4): val loss 5.21 → 1.52 (100) → 1.30 (500) → 1.45
  (600): overfits in epoch 3; keep ≈1.5-1.75 epochs and save every 100 iterations.

## Encoder enc_v1 results (test split, 28.5k positions)
7.46M params, 5 epochs over 495k train positions (400k cloud-eval + 150k puzzles, ~34 min of
MLX training after resume). Value MAE 8.8 win-% points; Stockfish top move 29%; puzzle first
move 63%; puzzle-theme AUC 0.83 (stop-grad probe). Concept probe R² 0.47 mean: material, phase,
queens, development, king placement ≈ 0.87-0.99; **tactical motifs barely readable** (discovered
attacks 0.04, overloaded defender 0.04, trapped piece 0.08, IQP 0.07, opponent mate threat 0.10).
A play-trained network knows *what the position is* far better than *which trick is on* — cf.
McGrath et al. Random-trunk baseline: see [[results]]. Discovery: [[concept-discovery]].

## Teacher pilot (2026-10-04): which teacher, how batched
Same 20 new endgame-weighted positions per setup, ideas judged blind by Opus
(`scripts/explainer_teacher_pilot.py`, `experiments/explainer/teacher_pilot.json`):

| setup | $/label | s/label | fact checker | ideas correct |
|---|---|---|---|---|
| Opus, 1 per call | 0.034 | 9.1 | 95% | 20/20 |
| **Opus, 5 per call** | **0.020** | 5.6 | 100% | **20/20** |
| Sonnet, 5 per call | 0.010 | 4.2 | 100% | 15/20 |
| Haiku, 5 per call (effort medium → long thinking) | 0.018 | 26.7 | 100% | 14/20 |

- **Batch 5 positions per call**: rules + vocabulary are paid once → −40% cost, no quality loss.
- **Not Sonnet/Haiku for this**: their wrong ideas pass the fact checker (100%), so they can't be
  filtered cheaply, and wrong ideas are exactly the student's problem. Judge-filtering Sonnet
  costs more than batched Opus.
- Collection: `scripts/explainer_collect.py` (Opus ×5, 20/40/40 opening/middlegame/endgame,
  auto-resumes after each plan session limit by parsing "resets 3:20am"). User chose full speed.

## Teacher labels: what we learned (first 341)
- 96.5% pass the verifier; ideas average 12 words. Difficulty: 72% natural, 20% hard, 8% obvious,
  <1% "computer".
- Verifier false positives fixed by re-verification at SFT-build time (labels kept, flags
  recomputed): "wins a pawn **back**" (a recovery), opponent threats named from the root ("meets
  the threat ...Bxd1" — the null-move board now counts), "escapes the mating net".
- **Vocabulary gaps** — Claude's `novel_concept` field names what the 32-id vocabulary lacks:
  remove the defender (×2), desperado (×3), rook lift, perpetual check, cutting off the king,
  "one pawn holds two", mutual protection against a queen. Candidates for vocab v2.
- Most used ids: king_safety, win_material, defence, piece_activity, hanging_piece,
  passed_pawn, initiative. Concept detectors that are least often "active" when Claude tags
  them (soft flag): overloaded_defender, fork, outpost — our detectors are narrower than the
  human concept.
- Known detector simplification: `bad_bishop` counts central pawns blocked by ANY piece on the
  bishop's colour (a knight on c6 "fixes" c7). Should be enemy pawns only — fix in concepts v2
  (shards v1 were built with the loose version).

## Budgets
Teacher planned at ≈$50 of `claude -p` spend; actual $27.38 (782 labels) because the plan's session
limit, not money, is the binding constraint. All training is local (M1 Pro, 16 GB).
