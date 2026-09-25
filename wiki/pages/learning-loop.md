# Learning loop (learned KB)

After a game by the **learner model** (Opus today; `knowledge_learned/config.json →
learner_models`), its Stockfish-verified mistakes become candidate lessons in a separate,
versioned KB `knowledge_learned/`. The hand-written `knowledge/` is never modified.

## Pipeline (`src/claude_chess/learn.py`)
1. **Find mistakes**: learner moves with cp loss ≥ `min_cp` (100) from `move_analysis.jsonl`;
   skip already-decided positions (|eval| ≥ 800); ≤1 per 10-ply window; worst `max_lessons_per_run` (2).
2. **Write lesson** (learner model): position context (same version the game used), its
   candidates + reasoning trace, SF best line and refutation of the played move, position tags,
   existing lessons. Output: title, 1–4 tags (first must be a *position* tag → decides when it
   is shown), ≤3 bullets, or `skip` if not generalisable.
3. **Gate**: replay target position ×`gate_repeats` (3) + up to `gate_controls` (4) control
   positions with baseline KB vs KB+lesson, same player config as the game. Controls are only
   positions where the new lesson would actually be retrieved (elsewhere context is byte-identical).
   Accept iff target cp loss improves ≥ `gate_min_gain` (50) and controls don't worsen by more
   than `gate_max_harm` (25) on average.
4. **Record**: accepted → `lessons/<id>.md` + manifest version bump; rejected → `rejected/`
   (kept for audit). Both logged in `CHANGELOG.md` and the run's `learn_report.json`.

## Using / revisiting
- Off by default. Play with it: `claude-chess match ... --learned-kb default` (or a dir).
  Runs record `learned_kb` + `learned_kb_version` in meta.json → every game is traceable.
- Auto-learn runs after `match` when `--model` is a learner model (disable with `--no-learn`).
  Manual: `claude-chess learn RUN_DIR [--dry-run] [--no-gate]`.
- `claude-chess kb status` · `kb export DIR --version N` (rebuild any past version) ·
  `kb retire ID` (lessons are immutable; retire instead of editing).
- Measuring it: freeze version N (`kb export`), learn over a batch, then A/B vN vs vN+k from the
  same openings, or on the position suite with `CLAUDE_CHESS_LEARNED_KB=<dir> claude-chess suite run ...`.

## Gotchas
- **Stockfish is not deterministic across calls** (hash state): the gate memoises cp loss per
  (FEN, move) so identical moves score identically in both arms; otherwise noise (~40cp seen)
  reads as harm/gain.
- The gate is small-n: a target ×3 and ≤4 controls. It filters bad lessons; it does not prove good ones.
- Keep experiments frozen: never run measured experiments with a KB that's changing.
- Rendered as its own section (cap 1 lesson/position) so it never displaces Guidance lines.

## Slow drift and collapse reviews (2026-09-25)
Single-move mistakes miss games where Claude is slowly outplayed. `find_drifts` adds:
- **collapse**: the game turned for good (learner eval ≤ -300 from some move on) → review from
  the last roughly-equal position (≥ -60) up to that point, bigger mistakes included. Ranked first.
- **drift**: runs of sub-100cp moves summing ≥150cp (split at big mistakes, cut once lost).
The review prompt shows the stretch's moves, engine eval vs Claude's own eval per move, engine
preferences, Claude's stated reasons, engine lines at the costliest moves, start/end context.
Output: narrative ("how it got there"), turning point, misconception, one positional lesson.
Gate: top-3 cp-loss moves of the stretch ×2, min gain 20cp. **Targets are filtered to positions
where the lesson is actually shown** (first run showed a lesson measured partly where it never
appeared). `learn RUN --regate ID` re-gates a stored proposal (proposals.jsonl) without regenerating.

## Provenance
Every lesson and proposal carries its source game: DB game id, full PGN, players, result,
judge (Stockfish version + depth), harness commit, player config, KB version at learning — so
stronger models/engines can re-judge lessons later even though runs/ is git-ignored.
Lesson ids number every proposal (accepted or not): L001, L002, ...

## Caching
`knowledge_learned/cache/cache.sqlite` (git-ignored): Stockfish scores per (FEN, move, depth)
and replayed decisions per (player config, KB-content hash, position+history, sample #). The
baseline arm is reused across lessons gated against the same KB; a re-gate reuses both arms.
