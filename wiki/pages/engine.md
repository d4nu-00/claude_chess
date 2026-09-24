# Engine (prompts, proposer, evaluator, search)

Code: `src/claude_chess/engine/{prompts,players}.py`, backend `src/claude_chess/llm.py`.
Claude = policy + value; python-chess = search on a real board (see [[architecture]]).

## Public API
- `make_llm(model="sonnet", backend="auto"|"cli"|"sdk")` -> `ClaudeCLI` / `AnthropicLLM`
  (each has `.counters.snapshot()`: calls, cost, tokens; thread-safe).
- `NaiveClaudePlayer(llm, show_legal_moves=True, illegal_policy="random", max_retries=2)`
- `ClaudeEnginePlayer(llm, use_context=True, depth=0|1|2, n_candidates=4, n_replies=2,
  show_legal_moves=True, illegal_policy="random", max_retries=2, max_workers=8)`
- `extract_json(text)`, `parse_move(board, s)` (SAN then UCI), `terminal_score(board)`.

## Prompts
- Every prompt: FEN, side to move, `str(board)` ASCII, SAN move history (`variation_san`).
- `use_context` adds `render_context(build_context(board, include_legal_moves=False))`
  (imported lazily). The legal list is appended by us iff `show_legal_moves` — independent
  of context, per [[decisions]]. Evaluator never gets the legal list.
- Proposer: JSON `{"thinking": <=2 sentences, "candidates":[{move,reason,prior}]}`; told to
  check hanging pieces/threats first and to include forcing moves (diversity matters —
  search can only pick among what's proposed).
- Evaluator: JSON `{"eval_cp": int WHITE's view, "reason"}`; told to check tactics first,
  remembering the side to move acts first.
- Naive: JSON `{"thinking", "move"}`. "thinking" fields are capped short for token cost.

## Search and scores
- Evaluator boundary: centipawns from **White's** view, clamped to ±9999.
- `Candidate.score_cp` is from the **mover's** view (`sign = +1 white / -1 black`).
- Terminal nodes (`board.outcome(claim_draw=True)`): mate ±10000, draw 0 — never sent to
  Claude, and no opponent-proposer call on a terminal child.
- d0: highest-prior legal candidate. d1: evaluate each child in parallel, pick max
  (tie -> higher prior). d2: phase 1 opponent-proposer on every child (parallel, same
  `use_context`, opponent to move, 1 retry), phase 2 evaluate every leaf (parallel);
  candidate score = min over replies (mover's view); `line = [cand, worst reply]`.
  If the opponent proposer yields no legal reply, the child itself is evaluated.

## Calls per move (no illegal retries, no terminal nodes)
| depth | calls | N=4, K=2 |
|---|---|---|
| 0 | 1 | 1 |
| 1 | 1 + N | 5 |
| 2 | 1 + N + N·K | 13 |
Wall time ≈ 3 sequential rounds at d2 (propose, replies, leaves) thanks to the thread pool.

## Illegal moves (follows [[illegal-moves]])
- Illegal/unparseable candidates dropped, logged in `MoveDecision.illegal_attempts`
  as `"<move>: <reason>"`. Re-ask only if **no** candidate is legal, with the reason +
  full legal list; up to `max_retries` (default 2 → 3 attempts).
- Exhaustion: `"random"` (default) plays a uniform-random legal move, sets
  `MoveDecision.forced_random=True` (added field) + note; `"forfeit"` -> `move=None`,
  `forfeit_reason` set. Opponent-proposer illegal replies at d2 only go in `note`.

## Gotchas
- `claude -p` accepts the prompt on **stdin** (verified) — avoids argv length limits.
  `max_tokens` can't be set via CLI; brevity is requested in the prompt instead.
- Each `ClaudeCLI` runs in its own neutral temp cwd (no CLAUDE.md/hook leakage).
- Smoke 2026-09-24: `NaiveClaudePlayer(ClaudeCLI("haiku"))` start pos -> `e4`, 1 call,
  $0.0027, 5.9 s wall (CLI startup dominates).
- Tests use a FakeLLM keyed on (system prompt, FEN) because calls are parallel and
  order-scripted fakes would be nondeterministic.
