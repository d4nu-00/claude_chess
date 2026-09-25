# knowledge_learned/

Lessons the learner model (Opus) wrote about its own Stockfish-verified mistakes, kept only
if they passed a replay gate. Separate from `knowledge/` and **off by default** — play with
`--learned-kb default`. `manifest.json` is the append-only version history; `claude-chess kb
export DIR --version N` rebuilds any past version. See `wiki/pages/learning-loop.md`.
