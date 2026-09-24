# Infrastructure failures ≠ illegal moves

**Incident 2026-09-24:** the Claude session/rate limit was hit mid-match. `claude -p`
returned `is_error` → `LLMError`, which the players caught as "unparseable reply", burned
the illegal-move retries and then played a *forced random move*. Games kept going with
random moves, polluting illegal-move rate, ACPL and results. Those three runs are
quarantined in `runs/_invalid/` — do not use them as data.

**Fix (now in code):**
- `llm.LLMUnavailable` (NOT a subclass of `LLMError`) is raised when the backend fails after
  retries. Limit-looking errors (`limit`, `429`, `overloaded`, `rate`, `quota`) get an extra
  backoff of 30/60/120 s first (`LIMIT_BACKOFF_S`).
- Players re-raise `LLMUnavailable`; only genuinely unparseable/illegal replies count as
  illegal attempts.
- Runner: `LLMUnavailable` → game result `*`, termination `aborted (LLM unavailable…)`, and
  the match stops scheduling further games. Analysis excludes `*` games from W/D/L/score
  (counted as `aborted`) but still analyses the moves that were played.
- Decision rows carry `forced_random` so the analysis can separate true illegal-move
  exhaustion from everything else.

**Rule for agents:** any new failure path must decide explicitly: is this the *model's*
fault (counts against it) or the *harness/infra* (abort, don't score)?
