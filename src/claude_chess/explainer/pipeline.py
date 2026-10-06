"""End-to-end: FEN -> score, best/alternative lines, concepts, discovered features, condensed idea.

Two analysis sources produce the same `facts` block, so one student LM serves both:
- engine mode: local Stockfish, multipv 2 (the ground truth the student was trained on);
- engine-free mode: our encoder's own value + policy, lines by greedy policy rollouts. The
  concept facts are still computed exactly on the board by `concepts.py` — only the move
  choice and score come from the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import chess
import chess.engine

from claude_chess.explainer import concepts as C
from claude_chess.explainer import data as D
from claude_chess.explainer import facts as F

DEFAULT_LM = "mlx-community/Qwen3-1.7B-bf16"


@dataclass
class Analysis:
    fen: str
    best_line: list[str]
    alt_line: list[str]
    value: float  # mover's win prob after the best move
    value_alt: float
    source: str  # "stockfish" | "encoder"


def stockfish_lines(fen: str, depth: int = 18, plies: int = 10, path: str | None = None) -> Analysis:
    from claude_chess.match.baselines import open_stockfish

    b = chess.Board(fen)
    eng = open_stockfish(path)
    try:
        eng.configure({"Threads": 4, "Hash": 128})
        infos = eng.analyse(b, chess.engine.Limit(depth=depth), multipv=2)
    finally:
        eng.quit()
    lines, vals = [], []
    for info in infos[:2]:
        pv = info.get("pv") or []
        lines.append([m.uci() for m in pv[:plies]])
        vals.append(info["score"].pov(b.turn).wdl(model="lichess").expectation())
    if len(lines) < 2:  # only one legal move: the alternative is the same move
        lines.append(lines[0])
        vals.append(vals[0])
    return Analysis(fen, lines[0], lines[1], vals[0], vals[1], "stockfish")


class EncoderAnalyst:
    """Engine-free analysis from the trained encoder (value + policy heads)."""

    def __init__(self, ckpt: str | Path):
        import numpy as np

        from claude_chess.explainer import encoder as E

        self.E, self.np = E, np
        self.model, self.ck = E.load(Path(ckpt))

    def _eval(self, boards: list[chess.Board]) -> dict:
        np = self.np
        tk, ca, ep = zip(*(D.encode_board(b) for b in boards))
        return self.E.forward_np(self.model, np.asarray(tk), np.asarray(ca), np.asarray(ep))

    def value(self, board: chess.Board) -> float:
        return float(self.E.expected_value_np(self._eval([board])["value_logits"])[0])

    def top_moves(self, board: chess.Board, k: int = 2) -> list[chess.Move]:
        pol = self._eval([board])["policy"][0]
        legal = list(board.legal_moves)
        scored = sorted(legal, key=lambda m: -float(pol[D.encode_move(board, m)]))
        return scored[:k]

    def concepts(self, board: chess.Board) -> dict[str, float]:
        """Predicted concept values (de-standardized) from the probe head."""
        c = self._eval([board])["concepts"][0]
        vals = c * self.ck["c_std"] + self.ck["c_mean"]
        return {k: float(v) for k, v in zip(C.KEYS, vals)}

    def rollout(self, board: chess.Board, first: chess.Move, plies: int = 8) -> list[str]:
        b = board.copy(stack=False)
        line = [first.uci()]
        b.push(first)
        while len(line) < plies and not b.is_game_over():
            mv = self.top_moves(b, 1)[0]
            line.append(mv.uci())
            b.push(mv)
        return line

    def analyse(self, fen: str, plies: int = 8) -> Analysis:
        b = chess.Board(fen)
        moves = self.top_moves(b, 2)
        if len(moves) == 1:
            moves = moves * 2
        vals = []
        for m in moves:  # value of the move = 1 - opponent's value after it (mate = 1)
            nb = b.copy(stack=False)
            nb.push(m)
            vals.append(1.0 if nb.is_checkmate() else 0.5 if nb.is_game_over() else 1.0 - self.value(nb))
        order = sorted(range(len(moves)), key=lambda i: -vals[i])
        m1, m2 = moves[order[0]], moves[order[-1]]
        return Analysis(fen, self.rollout(b, m1, plies), self.rollout(b, m2, plies), vals[order[0]],
                        vals[order[-1]], "encoder")


@dataclass
class Explanation:
    analysis: Analysis
    facts: F.PositionFacts
    facts_text: str
    text: str = ""
    parsed: dict = field(default_factory=dict)
    predicted_concepts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        pf = self.facts
        return {"fen": pf.fen, "source": self.analysis.source, "best": pf.best_san[0], "alt": pf.alt_san[0],
                "eval": F.eval_words(pf.value, chess.Board(pf.fen).turn),
                "salient_concepts": [{"concept": C.describe(k), "key": k, "z": z, "favours_best": g > 0}
                                     for k, z, g in pf.sal],
                "explanation": self.parsed, "text": self.text}


def _scale() -> dict[str, float]:
    p = D.DATA_DIR / "stats.json"
    return json.loads(p.read_text())["delta_scale"] if p.exists() else {}


class Explainer:
    def __init__(self, lm: str = DEFAULT_LM, adapter: str | None = None, encoder_ckpt: str | None = None):
        from claude_chess.explainer.lm import Student

        self.student = Student(lm, adapter)
        self.analyst = EncoderAnalyst(encoder_ckpt) if encoder_ckpt else None
        self.scale = _scale()

    def explain(self, fen: str, engine_free: bool = False, depth: int = 18) -> Explanation:
        if engine_free:
            if self.analyst is None:
                raise ValueError("engine-free mode needs an encoder checkpoint")
            an = self.analyst.analyse(fen)
        else:
            an = stockfish_lines(fen, depth=depth)
        pf = F.compute(fen, an.best_line, an.alt_line, an.value, an.value_alt, self.scale)
        text = F.render(pf, board_diagram=False)
        raw, parsed = self.student.explain(text, pf.best_san[0], pf.alt_san[0])
        ex = Explanation(an, pf, text, raw, parsed)
        if self.analyst is not None:
            ex.predicted_concepts = self.analyst.concepts(chess.Board(fen))
        return ex
