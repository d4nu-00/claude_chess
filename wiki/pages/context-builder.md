# Context builder

`claude_chess.context.build_context(board, include_legal_moves=True) -> PositionContext` and
`render_context(ctx, include_legal_moves=True) -> str`. Pure python-chess, no LLM, ~1-7ms
per position (test asserts <50ms avg). Code: `src/claude_chess/context/`, data: `knowledge/`.

## Features (module -> what, why)
- `openings.py` — ECO lookup against lichess-org/chess-openings TSVs (CC0, ~3.6k lines) in
  `knowledge/openings/`. Matched **by EPD** over every ply of `board.move_stack` from
  `board.root()`, so transpositions work; the deepest hit is kept after leaving book
  ("... (out of book since move 9)"). Parsing the PGNs costs ~1s, so a derived
  `epd_index.tsv` is cached next to them (auto-rebuilt if missing/stale; safe to delete).
- `features.py` — material + imbalances (bishop pair, exchange, minor vs pawns, opposite
  bishops), phase (npm-based endgame; opening = early move or ≥3 undeveloped minors), pawn
  structure (isolated/doubled/backward/passed with protected/connected, islands, open and
  half-open files, wing majorities, **named structures** with plans: IQP, hanging pawns,
  Carlsbad (+reversed), Maroczy, Hedgehog, Scheveningen, Najdorf/Boleslavsky, French chain,
  KID locked centre, Benoni, Stonewall), king safety (shield, open files near king,
  pieces hitting the king zone, opposite-side castling), activity (mobility, outposts,
  rooks on open files/7th, bad bishop, undeveloped minors, free outpost squares).
- `tactics.py` — mate-in-1 for side to move, en prise pieces for both sides, captures with
  SEE, all checks, absolute pins, and opponent threats via a **null move** (what they'd
  capture/mate if it were their move). Tactics come first in the render: LLMs miss
  one-movers far more than strategy.
- `concepts.py` — features emit tags; pages in `knowledge/concepts/*.md` (front matter
  `title`, `tags: [primary, ...]`, `## Summary` ≤4 bullets) are ranked by tag weights.
  Top 3 go into `ctx.concepts` plus the opening-family plan from
  `knowledge/openings_plans.md` (`match:` name prefixes, longest wins) and named-structure plans.

- `character.py` (middlegame/opening only) — **centre type** (open / closed / dynamic /
  mobile / semi-open, Pachman-Silman) with its standard plan; for closed centres the
  **pawn-chain direction** (which wing to play on); **pawn breaks** (levers) for both sides;
  opposite-wing kings race; **imbalances**: bishops vs knights judged against the
  structure, **space** (pawn-controlled squares in the enemy half, diff ≥3), development lead.
- `endgame.py` (endgame only) — **ending type** (pawn / rook / queen / knight / B-vs-N /
  same- or opposite-coloured bishops / mixed) + textbook guidance; **K+P rules** computed
  exactly: rule of the square (who can catch each passer, side to move counted), **key
  squares** (rook-pawn special case), **opposition** (direct/distant/diagonal, who holds it),
  outside passed pawns; lone-minor-can't-win; **tablebase** verdict + best moves.
- `tablebase.py` — ≤7 pieces: local Syzygy (`$SYZYGY_PATH` or `engines/syzygy`) then the
  Lichess API (`CLAUDE_CHESS_TB_ONLINE=0` disables; one failure disables for the process).
  **Blocked in the cloud sandbox** (egress policy) — works on a normal machine. Tests force
  it offline via `tests/conftest.py`.

## Why these choices
- Everything is phrased as short sentences naming the colour ("White isolated pawn(s): d4")
  so the prompt is unambiguous regardless of side to move.
- "En prise" = the opponent has a capture on that square with SEE > 0, not raw
  attacker/defender counts (counts produced lots of false alarms on defended pawns).
- A concept page is eligible only if its **primary** (first) tag is present; secondary tags
  only rank. Otherwise e.g. `bad-bishop` dragged in the Stonewall page.

## Gotchas
- SEE is a simple swap-off with least-valuable legal recapture; ignores x-ray subtleties
  beyond what re-computing attackers after each push gives (it does handle batteries).
- Bad bishop requires ≥2 of its own central pawns *fixed by enemy pawns*; otherwise every
  opening bishop is "bad".
- Null-move threats are skipped when in check (the check is the threat).
- Named-structure detectors are exact-square patterns; near-miss structures aren't named.
- Opening lookup of a board set from FEN (no move stack) only checks that one position.

## How to extend
- New concept: add `knowledge/concepts/<slug>.md`; ensure some feature emits its primary
  tag (add weight in `concepts.TAG_WEIGHTS`).
- New named structure: add a detector in `features._named_structures` calling `add(...)`
  with a tag + plan; add a matching concept page.
- New opening family plan: add a `## Family` + `match:` section to `openings_plans.md`.
- Tests: `tests/test_context.py` (Berlin, transposition, IQP, Carlsbad, passer, hanging
  piece, threats, mate-in-1, SEE, timing, render, random-game fuzz).
