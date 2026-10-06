"""Joint model: ONE language model chooses the move and states its idea.

Input (no engine anywhere): the position spelled out for a small LM (pieces, material, both
sides' winning captures / threats, optionally who-attacks-what), then k candidate moves from
the encoder's policy, each with its prior and VERIFIED consequences (what it captures, what it
then attacks, what it leaves en prise, the opponent's winning replies — `relations.move_delta`).

Output, reason-first:   Idea: ... / Move: <SAN> / Plan: ... / Concepts: a, b
        or move-first:  Move: <SAN> / Idea: ... / Plan: ... / Concepts: ...

Training mixes (a) teacher explanations (Claude's idea/plan/concepts for Stockfish's move) and
(b) cheap move-only examples (Stockfish's move, no LLM cost) under a different system prompt.
Stockfish's move is injected into the candidate list at training time if the encoder missed it;
at inference the model can only pick among the encoder's candidates (recall@6 ≈ 70% / 90%).
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import chess
import numpy as np

from claude_chess.context.relations import move_delta, relations
from claude_chess.explainer import concepts as C
from claude_chess.explainer import data as D
from claude_chess.explainer import facts as F

SYS_EXPLAIN = ("You are a chess player and coach. Choose the best of the candidate moves using the verified "
               "facts, and state your idea in a few plain words a club player can reuse.")
SYS_MOVE = "You are a chess player. Choose the best of the candidate moves using the verified facts."
K = 6


@dataclass
class Cand:
    move: chess.Move
    san: str
    prior: float


def encoder_candidates(model, board: chess.Board, k: int = K) -> list[Cand]:
    from claude_chess.explainer import encoder as E

    tk, ca, ep = D.encode_board(board)
    pol = E.forward_np(model, np.array([tk]), np.array([ca]), np.array([ep]))["policy"][0]
    legal = list(board.legal_moves)
    logits = np.array([pol[D.encode_move(board, m)] for m in legal])
    p = np.exp(logits - logits.max())
    p /= p.sum()
    order = np.argsort(-p)[:k]
    return [Cand(legal[i], board.san(legal[i]), float(p[i])) for i in order]


def outcome_text(board: chess.Board, v) -> str:
    """The verified result of the forcing play after a candidate (2-ply full width + quiescence,
    material only — engine/tactical.py; no Stockfish)."""
    if v.mate > 0:
        return f"forcing play: we mate in {v.mate} plies"
    if v.mate < 0:
        return f"forcing play: we get mated in {-v.mate} plies" + (f" (after {v.refutation})" if v.refutation else "")
    pawns = v.score / 100
    if abs(pawns) < 0.5:
        return "forcing play: material holds"
    verb = "wins" if pawns > 0 else "loses"
    return f"forcing play: {verb} ~{abs(pawns):.0f}" + (f" (best reply {v.refutation})" if v.refutation else "")


def cand_line(board: chess.Board, c: Cand, verdict=None) -> str:
    f = C.move_facts(board, c.move)
    desc = F._move_desc(board, c.move.uci(), f)
    extra = move_delta(board, c.move, limit=4)
    line = f"- {c.san} (instinct {100 * c.prior:.0f}%): {desc}" + (f"; {'; '.join(extra)}" if extra else "")
    return line + (f"; {outcome_text(board, verdict)}" if verdict is not None else "")


def render(board: chess.Board, cands: list[Cand], with_relations: bool = True, with_tactics: bool = False,
           tactics_depth: int = 2) -> str:
    us = board.turn
    root = C.static(board)
    mat = root["us.material"] - root["them.material"]
    lines = [f"Position: {F.CN[us]} to move. FEN: {board.fen()}",
             f"Pieces: {F.piece_list(board)}.",
             f"Material: {'equal' if mat == 0 else (F.CN[us] if mat > 0 else F.CN[not us]) + f' is up {abs(mat):g}'} "
             f"(pawn units). Phase: {root['g.phase']:.2f} of non-pawn material left."]
    lines += F.threats(board)
    if with_relations:
        rel = relations(board, limit=6)
        if rel:
            lines += ["", "Who attacks what:"] + [f"- {r}" for r in rel]
    imb = F.imbalances(root, limit=4)
    if imb:
        lines += ["", f"Imbalances (us = {F.CN[us]}):"] + [f"- {x}" for x in imb]
    lines += ["", f"Candidate moves (instinct = a neural network's first impression, not a guarantee):"]
    verdicts = [None] * len(cands)
    if with_tactics:
        from claude_chess.engine.tactical import score_moves
        verdicts = score_moves(board, [c.move for c in cands], depth=tactics_depth,
                               node_limit=60_000 if tactics_depth <= 2 else 2_000_000)
    lines += [cand_line(board, c, v) for c, v in zip(cands, verdicts)]
    return "\n".join(lines)


def target(order: str, move_san: str, label: dict | None) -> str:
    if label is None:
        return f"Move: {move_san}"
    cons = ", ".join(label.get("concepts") or [])
    parts = {"idea": f"Idea: {str(label.get('idea', '')).strip()}", "move": f"Move: {move_san}",
             "plan": f"Plan: {str(label.get('plan', '')).strip()}", "concepts": f"Concepts: {cons}"}
    seq = ("idea", "move", "plan", "concepts") if order == "reason_first" else ("move", "idea", "plan", "concepts")
    return "\n".join(parts[s] for s in seq)


def parse(text: str, board: chess.Board, cands: list[Cand]) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    out: dict = {"raw": text}
    for line in text.splitlines():
        if ":" in line:
            h, v = line.split(":", 1)
            key = h.strip().lower()
            if key in ("idea", "move", "plan", "concepts"):
                out[key] = v.strip()
    mv = None
    san = out.get("move", "").split()[0] if out.get("move") else ""
    for c in cands:
        if san and c.san.rstrip("+#") == san.rstrip("+#"):
            mv = c.move
    if mv is None:
        try:
            mv = board.parse_san(san)
            out["off_list"] = True
        except ValueError:
            mv = cands[0].move  # unparseable / illegal: fall back to the instinct (recorded)
            out["fallback"] = True
    out["uci"] = mv.uci()
    out["san"] = board.san(mv)
    if "concepts" in out:
        out["concepts"] = [c.strip() for c in out["concepts"].split(",") if c.strip()]
    return out


def _with_best(cands: list[Cand], board: chess.Board, best_uci: str, rng: random.Random) -> list[Cand]:
    """Training-time candidate list that contains Stockfish's move (inserted if the encoder missed it)."""
    if any(c.move.uci() == best_uci for c in cands):
        return cands
    mv = chess.Move.from_uci(best_uci)
    out = list(cands[:-1])
    out.insert(rng.randrange(len(out) + 1), Cand(mv, board.san(mv), 0.0))
    return out


def build_sft(out_dir: Path, enc_dir: Path, order: str = "reason_first", with_relations: bool = True,
              n_move_only: int = 2000, teacher_repeat: int = 2, n_valid_teacher: int = 40, seed: int = 0,
              log=print, with_tactics: bool = False,
              teacher_paths: tuple[str, ...] = ("datasets/explainer_v1/teacher.jsonl",)) -> dict:
    from claude_chess.explainer import encoder as E
    from claude_chess.explainer import teacher as T

    rng = random.Random(seed)
    model, _ = E.load(enc_dir)
    teacher, seen = [], set()
    for tp in teacher_paths:  # several label files; one label per position (first wins)
        for ln in Path(tp).read_text().splitlines():
            r = json.loads(ln)
            if r["fen"] not in seen:
                seen.add(r["fen"])
                teacher.append(r)
    rows: dict[str, list] = {"train": [], "valid": [], "test": []}

    def example(fen: str, best_uci: str, label: dict | None, inject: bool) -> dict:
        b = chess.Board(fen)
        cands = encoder_candidates(model, b)
        if inject:
            cands = _with_best(cands, b, best_uci, rng)
        san = b.san(chess.Move.from_uci(best_uci))
        return {"messages": [{"role": "system", "content": SYS_EXPLAIN if label else SYS_MOVE},
                             {"role": "user", "content": render(b, cands, with_relations, with_tactics)},
                             {"role": "assistant", "content": target(order, san, label)}]}

    n_val = 0
    for r in teacher:
        if not r["label"]:
            continue
        pf = F.compute(r["fen"], r["best_line"].split(), r["alt_line"].split(), r["value"], r["value_alt"])
        if not T.verify(r["label"], pf)["ok"]:
            continue
        split = {0: "train", 1: "valid", 2: "test"}[r["split"]]
        if split == "valid":
            n_val += 1
            if n_val > n_valid_teacher:
                split = "train"
        best = r["best_line"].split()[0]
        ex = example(r["fen"], best, r["label"], inject=split != "test")
        rows[split] += [ex] * (teacher_repeat if split == "train" else 1)
    # cheap move-only examples (no LLM): cloud-eval + puzzle train positions, Stockfish's move as target
    data = D.load(("eval", "puzzle"))
    nr = np.random.default_rng(seed)
    for split_id, name, n in ((0, "train", n_move_only), (1, "valid", 40)):
        idx = nr.choice(np.flatnonzero(data["split"] == split_id), size=n, replace=False)
        for i in idx:
            rows[name].append(example(str(data["fen"][i]), str(data["best_line"][i]).split()[0], None, inject=True))
    rng.shuffle(rows["train"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rs in rows.items():
        with (out_dir / f"{name}.jsonl").open("w") as fh:
            for x in rs:
                fh.write(json.dumps(x) + "\n")
    stats = {k: len(v) for k, v in rows.items()}
    (out_dir / "joint_config.json").write_text(json.dumps({"order": order, "relations": with_relations,
                                                           "tactics": with_tactics}))
    log(f"[joint] sft {out_dir}: {stats}")
    return stats


class JointPlayer:
    """Encoder candidates + one LM that picks and explains. `play(board)` -> dict."""

    def __init__(self, lm: str, adapter: str | None, enc_dir: str = "data/models/enc_v1", with_relations: bool = True,
                 max_tokens: int = 160, with_tactics: bool = False, tactics_depth: int = 2):
        from mlx_lm import load

        from claude_chess.explainer import encoder as E

        self.enc, _ = E.load(Path(enc_dir))
        self.model, self.tok = load(lm, adapter_path=adapter)
        self.with_relations, self.with_tactics = with_relations, with_tactics
        cfg = Path(adapter or "", "joint_config.json")  # the input format the adapter was trained on
        if adapter and cfg.exists():
            c = json.loads(cfg.read_text())
            self.with_relations, self.with_tactics = c.get("relations", True), c.get("tactics", False)
        self.max_tokens = max_tokens
        self.tactics_depth = tactics_depth  # deeper = sees more (depth 4 ≈ 10 s/move); same text format
        self._facts: dict[str, str] = {}  # fen -> rendered facts (the search is the slow part)

    def facts(self, board: chess.Board, cands: list[Cand]) -> str:
        key = board.fen()
        if key not in self._facts:
            self._facts[key] = render(board, cands, self.with_relations, self.with_tactics, self.tactics_depth)
        return self._facts[key]

    def prompt(self, board: chess.Board, cands: list[Cand], explain: bool = True) -> str:
        msgs = [{"role": "system", "content": SYS_EXPLAIN if explain else SYS_MOVE},
                {"role": "user", "content": self.facts(board, cands)}]
        return self.tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False, enable_thinking=False)

    def play(self, board: chess.Board, explain: bool = True, stream=None) -> dict:
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        cands = encoder_candidates(self.enc, board)
        text = ""
        for resp in stream_generate(self.model, self.tok, self.prompt(board, cands, explain),
                                    max_tokens=self.max_tokens if explain else 12, sampler=make_sampler(temp=0.0)):
            text += resp.text
            if stream:
                stream(text)
        out = parse(text, board, cands)
        out["candidates"] = [{"san": c.san, "prior": round(c.prior, 3)} for c in cands]
        return out
