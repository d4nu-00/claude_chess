# LLM backend

- No `ANTHROPIC_API_KEY` on the dev machine, so the default backend shells out to the
  Claude Code CLI in headless mode:
  `claude -p <prompt> --model sonnet --output-format json --tools "" --system-prompt <sys>
   --no-session-persistence --setting-sources "" --strict-mcp-config`
- Run it from a neutral cwd (scratch dir) so project CLAUDE.md / hooks don't leak into prompts.
  `--setting-sources ""` also suppresses user plugins/hooks (e.g. superpowers SessionStart).
- Measured 2026-09-24: ~2.4 s wall per trivial call, ~$0.001; model resolves to `claude-sonnet-5`.
  JSON output has `result`, `total_cost_usd`, `usage.input_tokens/output_tokens`, `is_error`.
- Calls are independent processes → parallelise with a thread pool (search fans out).
- If `ANTHROPIC_API_KEY` is set, `AnthropicLLM` uses the SDK directly (faster, same prompts).
