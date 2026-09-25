"""Prompt builders for the proposer, evaluator and naive player.

Every prompt contains FEN + ASCII board + move history. Strategic context
(render_context) only when use_context=True; the legal-move list is a
separate toggle (show_legal_moves) — see wiki/pages/decisions.md.
"""

from __future__ import annotations

import chess

PROPOSER_SYSTEM = """You are the move-proposal module of a chess engine. A separate search \
module will play out your candidates on a real board and evaluate them, so propose a \
DIVERSE set of plausible, strong moves (include forcing moves: checks, captures, threats).
Before proposing, briefly check: which pieces are hanging (both sides)? what does the \
opponent threaten? any checks/captures available?
Reply with ONLY a JSON object, no prose outside it:
{"thinking": "<= 2 short sentences", "candidates": [{"move": "<SAN>", "reason": "<few words>", "prior": <0.0-1.0>}]}
Moves must be legal in Standard Algebraic Notation (e.g. Nf3, exd5, O-O, e8=Q+). \
Priors are your confidence each move is best; they should roughly sum to 1.
Material is not everything. If you deliberately give up material because you judge the \
compensation to be enough (attack on the king, initiative, passed pawn, lasting bind), add \
"sacrifice": true and "compensation": "<what you get>" to that candidate — the engine's \
material counter will otherwise treat it as a blunder."""

EVALUATOR_SYSTEM = """You are the evaluation module of a chess engine. Judge the given \
position statically as a strong grandmaster would.
FIRST check tactics: pieces that are hanging or can be won by the side to move, checks, \
forks, pins, mate threats. Remember the side to move can act first. THEN weigh material \
(pawn=100, knight/bishop≈300-325, rook=500, queen=900), king safety, activity and structure.
Reply with ONLY a JSON object, no prose outside it:
{"eval_cp": <integer, centipawns from WHITE's point of view: positive = White better>, "reason": "<one short sentence>"}"""

COMPARE_SYSTEM = """You are the positional-evaluation module of a chess engine. The engine's \
tactical search has ALREADY resolved captures, checks and short forcing lines for every option \
below, and has removed moves that lose material or allow mate. Material is counted exactly by \
the engine — do NOT re-count it. Your job is only what the search cannot see: compare the \
options on positional merit (piece activity and coordination, king safety, pawn structure, \
plans, initiative, long-term weaknesses, whether the engine's shown reply is really harmless).
Score every option relative to the others, from the point of view of the side to move: \
-150 (clearly worst) .. +150 (clearly best).
Options marked SACRIFICE give up material on purpose; the engine counts only the material. \
For each of them also give "compensation_cp": how much of the material given up you judge \
is really paid back (initiative, attack, structure) — 0 if the sacrifice is unsound, up to \
the full amount if it is fully justified. Be honest: most speculative sacrifices are unsound.
Reply with ONLY a JSON object, no prose outside it:
{"thinking": "<= 2 short sentences", "scores": [{"move": "<SAN exactly as listed>", "score": <int -150..150>, "compensation_cp": <int, sacrifices only>, "reason": "<few words>"}]}"""

THREAT_SYSTEM = """You are the tactical watchdog of a chess engine: the OPPONENT's advocate. \
For each candidate move, find the opponent's MOST DANGEROUS reply in the position after it. \
The engine's shallow material search has already checked plain captures, so hunt for what it \
misses: quiet killer moves, mating nets, forks, pins and skewers, discovered attacks, \
deflection/decoy, trapped pieces, pawn promotions, 2-3 move combinations.
The reply must be a LEGAL move for the opponent in the position AFTER the candidate (use \
the board shown for that candidate). If a candidate is genuinely safe, give the opponent's \
best reply anyway.
Also give "alt": the opponent's most NATURAL reply (what a strong player would most likely \
play), which may differ from the most dangerous one.
Reply with ONLY a JSON object, no prose outside it:
{"replies": [{"move": "<candidate SAN exactly as listed>", "reply": "<opponent SAN>", "idea": "<few words>", "alt": "<opponent SAN>"}]}"""

POSITIONAL_SYSTEM = """You are the positional-evaluation module of a chess engine. Material \
and short forcing tactics are counted exactly by the engine's search — do NOT count material. \
Judge only positional factors: king safety, piece activity and coordination, pawn structure, \
space, initiative, long-term weaknesses and plans.
Reply with ONLY a JSON object, no prose outside it:
{"positional_cp": <integer -150..150 from WHITE's point of view: positive = White better positionally>, "reason": "<one short sentence>"}"""

NAIVE_SYSTEM = """You are a strong chess player. Choose the best move for the side to move.
Reply with ONLY a JSON object, no prose outside it:
{"thinking": "<= 2 short sentences", "move": "<SAN>"}
The move must be legal, in Standard Algebraic Notation (e.g. Nf3, exd5, O-O, e8=Q+)."""


def move_history_san(board: chess.Board, last: int | None = None) -> str:
    """Moves played so far as numbered SAN (from the board's move stack); `last` keeps only
    the final N plies (prefixed with "...")."""
    if not board.move_stack:
        return "(none — starting position)" if board.fen() == chess.STARTING_FEN else "(none given)"
    root = board.root()
    stack = board.move_stack
    if last is None or len(stack) <= last:
        return root.variation_san(stack)
    for mv in stack[:-last]:
        root.push(mv)
    return "... " + root.variation_san(stack[-last:])


def legal_moves_san(board: chess.Board) -> list[str]:
    return [board.san(m) for m in board.legal_moves]


COMPACT_HISTORY_PLIES = 10


def _context_block(board: chess.Board, include_legal_moves: bool, compact: bool = False,
                   v: int = 2) -> str:
    from claude_chess.context import build_context, render_context  # lazy: owned by another module

    ctx = (build_context(board, include_legal_moves=include_legal_moves, version=v) if v != 2
           else build_context(board, include_legal_moves=include_legal_moves))
    if compact:
        ctx.concepts = []  # generic "Guidance" (~500 tokens) is only useful to the proposer
    return render_context(ctx, include_legal_moves=include_legal_moves)


def position_block(board: chess.Board, use_context: bool, show_legal_moves: bool,
                   compact: bool = False, v: int = 2) -> str:
    """`compact` (secondary roles: compare/threat/positional): no generic guidance, only the
    last COMPACT_HISTORY_PLIES of history — ~25% fewer input tokens per call."""
    side = "White" if board.turn == chess.WHITE else "Black"
    hist = move_history_san(board, COMPACT_HISTORY_PLIES if compact else None)
    parts = [
        f"FEN: {board.fen()}",
        f"Side to move: {side}",
        "Board (uppercase = White, lowercase = Black, rank 8 at top):",
        str(board),
        f"Moves so far: {hist}",
    ]
    if use_context:
        # Legal moves are appended by us below, so the context never carries them itself.
        parts.append("## Position analysis\n" + _context_block(board, include_legal_moves=False,
                                                                compact=compact, v=v))
    if show_legal_moves:
        parts.append("Legal moves: " + " ".join(legal_moves_san(board)))
        if v >= 3:
            parts.append(material_check(board))
    return "\n".join(parts)


def material_check(board: chess.Board) -> str:
    """v3 proposer aid: every legal move checked by the material search (opponent's best reply
    + captures). Tells Claude which moves drop material BEFORE it proposes them."""
    from claude_chess.engine import tactical

    verdicts = tactical.score_moves(board, list(board.legal_moves), depth=1, node_limit=4000)
    win = sorted((v for v in verdicts if v.score >= 100 or v.mate > 0), key=lambda v: -v.score)
    lose = sorted((v for v in verdicts if v.score <= -100 or v.mate < 0), key=lambda v: v.score)

    def fmt(v):
        if v.mate > 0:
            return f"{board.san(v.move)} (mates)"
        if v.mate < 0:
            return f"{board.san(v.move)} (allows mate)"
        return f"{board.san(v.move)} ({v.score / 100:+.0f})"
    lines = ["Engine material check of every legal move (opponent's best reply + captures; pawns):"]
    lines.append("- wins material: " + (", ".join(fmt(v) for v in win[:8]) or "none"))
    if len(lose) * 2 > len(verdicts):  # most moves lose: listing the safe ones is shorter/clearer
        safe = [board.san(v.move) for v in verdicts if v.score > -100 and v.mate >= 0]
        lines.append(f"- {len(lose)} of {len(verdicts)} moves LOSE material; the only ones that don't: "
                     + (", ".join(safe) or "none"))
    else:
        lines.append("- LOSES material (avoid unless you see why the check is wrong): "
                     + (", ".join(fmt(v) for v in lose) if lose else "none"))
    return "\n".join(lines)


def proposer_prompt(board: chess.Board, n: int, use_context: bool, show_legal_moves: bool,
                    feedback: str = "", v: int = 2) -> str:
    side = "White" if board.turn == chess.WHITE else "Black"
    p = position_block(board, use_context, show_legal_moves, v=v)
    p += f"\n\nPropose the {n} best candidate moves for {side}."
    if feedback:
        p += "\n\n" + feedback
    return p


def evaluator_prompt(board: chess.Board, use_context: bool, v: int = 2) -> str:
    # Evaluator never needs the legal-move list: it judges, it doesn't move.
    p = position_block(board, use_context, show_legal_moves=False, v=v)
    return p + "\n\nEvaluate this position (eval_cp from WHITE's point of view)."


def _deltas(board: chess.Board, san: str) -> str:
    from claude_chess.context.relations import move_delta

    facts = move_delta(board, board.parse_san(san))
    return ("; what it changes: " + "; ".join(facts)) if facts else "; what it changes: nothing notable"


def compare_prompt(board: chess.Board, options: list[tuple[str, int, str, str]],
                   use_context: bool, v: int = 2, sacrifices: dict[str, str] | None = None) -> str:
    """options: (san, material swing for the mover in cp, engine's best reply SAN, FEN after move).
    sacrifices: {san: claimed compensation} for moves the proposer declared as sacrifices."""
    sacrifices = sacrifices or {}
    side = "White" if board.turn == chess.WHITE else "Black"
    p = position_block(board, use_context, show_legal_moves=False, compact=True, v=v)
    lines = []
    for i, (san, swing, reply, fen) in enumerate(options, 1):
        mat = f"{swing:+d}cp" if swing else "level"
        rep = f"; engine's best reply {reply}" if reply else ""
        delta = _deltas(board, san) if v >= 3 else ""
        sac = (f" — SACRIFICE (gives up {-swing}cp; claimed compensation: {sacrifices[san]})"
               if san in sacrifices and swing < 0 else "")
        lines.append(f"{i}. {san}{sac} — material after forcing play: {mat}{rep}{delta}; FEN after {san}: {fen}")
    return (p + f"\n\nCandidate moves for {side} (all tactically checked by the engine):\n"
            + "\n".join(lines) + f"\n\nScore each option for {side}.")


def threat_prompt(board: chess.Board, options: list[tuple[str, str, chess.Board]],
                  use_context: bool, v: int = 2) -> str:
    """options: (candidate SAN, engine's shallow best reply SAN or "", board after candidate)."""
    side = "White" if board.turn == chess.WHITE else "Black"
    opp = "Black" if board.turn == chess.WHITE else "White"
    p = position_block(board, use_context, show_legal_moves=False, compact=True, v=v)
    parts = [p, f"\n{side} is considering these moves. For each, find {opp}'s most dangerous reply."]
    for i, (san, eng, after) in enumerate(options, 1):
        hint = f" (engine's shallow search expects {eng})" if eng else ""
        if v >= 3:
            hint += _deltas(board, san)
        parts.append(f"\n### {i}. {side} plays {san}{hint}\nFEN: {after.fen()}\n{after}")
    return "\n".join(parts)


def positional_prompt(board: chess.Board, use_context: bool, v: int = 2) -> str:
    p = position_block(board, use_context, show_legal_moves=False, compact=True, v=v)
    return p + "\n\nScore the POSITIONAL balance (positional_cp from WHITE's point of view)."


def naive_prompt(board: chess.Board, show_legal_moves: bool, feedback: str = "") -> str:
    side = "White" if board.turn == chess.WHITE else "Black"
    p = position_block(board, use_context=False, show_legal_moves=show_legal_moves)
    p += f"\n\nYou play {side}. Choose your move."
    if feedback:
        p += "\n\n" + feedback
    return p


def illegal_feedback(board: chess.Board, errors: list[str]) -> str:
    return (
        "Your previous answer contained no legal move:\n- " + "\n- ".join(errors)
        + "\nThe complete list of legal moves is: " + " ".join(legal_moves_san(board))
        + "\nPick only from that list."
    )


# Role name for every system prompt: used to label logged LLM calls (dataset traces).
ROLES = {
    PROPOSER_SYSTEM: "proposer",
    EVALUATOR_SYSTEM: "evaluator",
    COMPARE_SYSTEM: "compare",
    THREAT_SYSTEM: "threat",
    POSITIONAL_SYSTEM: "positional",
    NAIVE_SYSTEM: "naive",
}
