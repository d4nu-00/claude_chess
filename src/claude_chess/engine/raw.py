"""RawPlayer: no harness, just prompt the model and let it think.

Reproduces the setup from https://openfill.ai/blog/adventures-in-astra-and-chess: a stateless
single-turn prompt (colour, board, FEN, legal UCI moves), max reasoning effort, the move read
from a final `make_move <UCI>` line. Conditions differ only in how the board is shown:
Unicode text, ASCII text, or a rendered PNG. See wiki/pages/raw-thinking.md.

Deviation from the blog prompt: one extra line asks for a short justification before the final
line, because the CLI does not always return thinking text and the *why* is the point of the run.
"""

from __future__ import annotations

import random
import re
import subprocess
import time

import chess
import chess.svg

from claude_chess.llm import LLMError, LLMUnavailable
from claude_chess.types import MoveDecision

SYSTEM = "You are a precise chess engine. You always reply with a single legal move."

_MOVE_RE = re.compile(r"make_move\s+`?([a-h][1-8][a-h][1-8][qrbn]?)`?", re.I)


def render_board_png(board: chess.Board, size: int = 640) -> bytes:
    """PNG of the board from the mover's side, via python-chess SVG + ImageMagick."""
    svg = chess.svg.board(board, size=size, orientation=board.turn, coordinates=True)
    try:
        proc = subprocess.run(["magick", "-background", "none", "svg:-", "png:-"],
                              input=svg.encode(), capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"board rendering needs ImageMagick (`brew install imagemagick`): {e}") from e
    return proc.stdout


def build_prompt(board: chess.Board, style: str, feedback: str = "") -> str:
    """style: "unicode" | "ascii" | "image" — how the board is shown; everything else is identical."""
    color = "white" if board.turn == chess.WHITE else "black"
    if style == "image":
        shown = f"see the attached image ({color} pieces at the bottom)."
    elif style == "ascii":
        rows = str(board).split("\n")
        files = "  a b c d e f g h"
        if board.turn == chess.BLACK:
            rows = [" ".join(r.split(" ")[::-1]) for r in reversed(rows)]
            files = "  h g f e d c b a"
        ranks = range(8, 0, -1) if board.turn == chess.WHITE else range(1, 9)
        shown = "\n".join([f"{n} {r}" for n, r in zip(ranks, rows)] + [files])
    else:
        shown = board.unicode(borders=True, orientation=board.turn)
    legal = ", ".join(m.uci() for m in board.legal_moves)
    prompt = (
        f"You are playing chess as {color}. Choose the strongest legal move.\n\n"
        f"Board:\n{shown}\n\n"
        f"FEN: {board.fen()}\n\n"
        f"Legal moves (UCI): {legal}\n\n"
        "Before your final line, explain in a short paragraph why you chose this move "
        "(the ideas and threats you saw, and the alternatives you rejected).\n"
        "Reply with your move as the FINAL line, exactly as: make_move <UCI>"
    )
    return prompt + (f"\n\n{feedback}" if feedback else "")


def parse_reply(board: chess.Board, text: str) -> tuple[chess.Move | None, str, str]:
    """(move, why-not, reasoning): last `make_move <UCI>` in the reply; reasoning = text before it."""
    matches = list(_MOVE_RE.finditer(text or ""))
    if not matches:
        return None, "no `make_move <UCI>` line", (text or "").strip()
    m = matches[-1]
    reasoning = text[:m.start()].strip()
    try:
        mv = chess.Move.from_uci(m.group(1).lower())
    except ValueError:
        return None, f"{m.group(1)}: not valid UCI", reasoning
    if mv not in board.legal_moves:
        return None, f"{m.group(1)}: illegal in this position", reasoning
    return mv, "", reasoning


class RawPlayer:
    def __init__(self, llm, style: str = "unicode", illegal_policy: str = "random",
                 max_retries: int = 2, seed: int | None = None, name: str | None = None) -> None:
        assert illegal_policy in ("random", "forfeit")
        self.llm = llm
        assert style in ("unicode", "ascii", "image")
        self.style = style
        self.illegal_policy = illegal_policy
        self.max_retries = max_retries
        self.rng = random.Random(seed)
        self.name = name or f"raw-{self.style}({getattr(llm, 'model', '?')})"

    def choose_move(self, board: chess.Board) -> MoveDecision:
        t0 = time.monotonic()
        image = render_board_png(board) if self.style == "image" else None
        illegal: list[str] = []
        traces: list[dict] = []
        feedback, cost, calls = "", 0.0, 0
        for _ in range(self.max_retries + 1):
            prompt = build_prompt(board, self.style, feedback)
            try:
                resp = self.llm.complete(SYSTEM, prompt, images=[image] if image else None)
            except LLMUnavailable:
                raise
            except LLMError as e:
                illegal.append(f"backend error: {e}")
                continue
            calls += 1
            cost += resp.cost_usd
            mv, why, reasoning = parse_reply(board, resp.text)
            traces.append({
                "role": "raw", "model": getattr(self.llm, "model", "?"), "fen": board.fen(),
                "board_style": self.style, "system": SYSTEM, "prompt": prompt, "response": resp.text,
                "thinking": resp.thinking, "thinking_tokens": resp.thinking_tokens,
                "cost_usd": resp.cost_usd, "seconds": round(resp.seconds, 3),
                "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            })
            info = {"reasoning": reasoning, "thinking": resp.thinking,
                    "thinking_tokens": resp.thinking_tokens, "board_style": self.style,
                    "output_tokens": resp.output_tokens}
            if mv is not None:
                return MoveDecision(move=mv, san=board.san(mv), illegal_attempts=illegal,
                                    llm_calls=calls, cost_usd=cost, seconds=time.monotonic() - t0,
                                    search_info=info, traces=traces)
            illegal.append(why)
            feedback = f"Your previous reply was rejected ({why}). Reply again with a legal move."
        dec = MoveDecision(move=None, san=None, illegal_attempts=illegal, llm_calls=calls,
                           cost_usd=cost, seconds=time.monotonic() - t0, traces=traces)
        if self.illegal_policy == "random":
            mv = self.rng.choice(list(board.legal_moves))
            dec.move, dec.san, dec.forced_random = mv, board.san(mv), True
            dec.note = f"random legal move after exhausting retries ({illegal[-1] if illegal else '?'})"
        else:
            dec.forfeit_reason = f"no legal move after retries ({illegal[-1] if illegal else '?'})"
        return dec
