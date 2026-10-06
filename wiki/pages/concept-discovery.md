# Concept discovery: SAE features in our chess encoder (Schut-style)

Code: `explainer/sae.py`, `explainer/discover.py`; run `python -m claude_chess.explainer discover`.
Outputs: `experiments/explainer/discovered.md`, `datasets/explainer_v1/discovered_concepts.json`.
Context: [[explainer-model]].

## Method (why this shape)
- Encoder `enc_v1` (7.5M, trained only on Stockfish value/policy; concept heads are stop-grad
  probes so the trunk is unbiased by our labels). Representation = [CLS ‖ mean of squares], 512-d.
- **Static view**: rep(position). **Dynamic view**: rep(end of best line) − rep(end of
  alternative line), both after an even number of plies (≤6) so the POV matches the root —
  the latent analogue of Schut et al.'s chosen-vs-rejected MCTS rollouts.
- TopK SAE (k=16, 1024 latents, inputs standardized, dead-latent resampling), 120k train
  positions, analysed on 30k held-out. Static FVE 0.89 (736 alive), dynamic FVE 0.76 (1003 alive).
- Each feature is correlated with 93 hand-written concepts (+41 puzzle themes for static,
  concept deltas + move facts for dynamic). Pick 8 least-explained + 4 best-explained features
  per view (dynamic: among the third most correlated with the win-prob gap).
- Claude Opus 5.5 names a feature from 8 top-activating, structurally diverse positions (with best
  vs alternative lines for dynamic), then a fresh call predicts which of 10 held-out positions
  (5 top, 5 zero activation) fire from the name alone → balanced accuracy (Bills et al. 2023).
  Cost ≈ $1.6 for 24 features.

## Results (2026-10-03)
- **Almost nothing aligns with one hand-written concept**: 3% of static and 0% of dynamic
  features have |r| ≥ 0.5 with any single detector (the exceptions are material-balance
  features: "major piece vs bare king" mop-ups, simulation 0.8-1.0). SAE features are
  combinations/specialisations, so naming them needs examples, not correlations.
- **Dynamic features are coach-level decisions** (simulation accuracy, n=10 each):
  get the king out of the centre (1.0), castle short where the alternative doesn't (0.9),
  avoid the queen trade (0.9), grab hanging material and don't give it back (0.8),
  simplify by trading the heavy pieces (0.7), win the enemy queen while keeping yours (0.6).
  These are exactly the "vague ideas" the user wants the explainer to produce — found in the
  network's own coordinates, not in our concept list.
- **Static features are context**: open middlegame with both sides castled short (0.8), heavy
  pieces against a thin king shield (0.8), opponent king tucked in a corner (0.8), rook-pawn /
  wrong-bishop minor-piece endings (0.8), enemy minor piece invading our half (0.7).
- Failures (≤0.5): "intact queenside vs advanced c-pawn", "opponent knight on f3/f6",
  "accepting rook checks", "minor piece just kicked by a pawn", "rook trade into pawn ending".
  Claude's own confidence (0.25-0.45 on these) was a fair predictor of failure.

## Caveats / next
- n=10 per simulation is noisy; scale to 40+ held-out positions before trusting a single feature.
- Teachability (Schut's filter, `scripts/explainer_teachability.py`): the step-2000 checkpoint
  fine-tuned 40 steps on a feature's 300 top prototypes vs 300 random positions; top-move accuracy
  on 100 held-out prototypes (2 seeds). King out of the centre +7.5 pts, castle short +5.5; queen-
  trade / hanging-queen +1.5; simplification −1.0; grab hanging material −10.9 (n=46). Only the
  king-safety concepts look teachable — like Schut, most discovered concepts don't pass. n=100 and
  2 seeds: ±5 pts is noise; rerun with more seeds/positions before trusting one feature.
- Dynamic features could become *new vocabulary ids* for the teacher (with their prototypes as
  examples) — closing the loop from discovered concept to explanation text.
