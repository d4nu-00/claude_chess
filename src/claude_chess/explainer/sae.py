"""Concept discovery (Schut et al. 2023-style) with TopK sparse autoencoders on encoder latents.

Two views of the trained encoder:
- static:  rep(position) — what the network sees in a position;
- dynamic: rep(end of best line) − rep(end of alternative line), both after an even number of
  plies so the side to move (and the POV) matches the root. This is the latent version of
  Schut's chosen-vs-rejected rollout contrast: what the best move achieves, in the network's
  own coordinates.

A TopK SAE (Gao et al. 2024) splits each view into sparse features. Every feature is then
compared with the 93 hand-written concepts and the Lichess puzzle themes: high correlation =
a rediscovered human concept; low correlation + high usefulness = a candidate new concept,
which Claude names from its top examples and is then scored on predicting held-out
activations (simulation score, Bills et al. 2023).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import chess
import numpy as np
import torch
import torch.nn as nn

from claude_chess.explainer import concepts as C
from claude_chess.explainer import data as D
from claude_chess.explainer import encoder as E


# ── latents ──────────────────────────────────────────────────────────────────


def _board_arrays(boards: list[chess.Board]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    enc = [D.encode_board(b) for b in boards]
    return (np.asarray([e[0] for e in enc], dtype=np.int64), np.asarray([e[1] for e in enc], dtype=np.float32),
            np.asarray([e[2] for e in enc], dtype=np.int64))


def device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cpu"


def reps_for_boards(model: E.ChessEncoder, boards: list[chess.Board], bs: int = 1024) -> np.ndarray:
    out = []
    for s in range(0, len(boards), bs):
        tk, ca, ep = _board_arrays(boards[s:s + bs])
        out.append(E.forward_np(model, tk, ca, ep)["rep"].astype(np.float32))
    return np.concatenate(out) if out else np.zeros((0, 2 * model.cfg.d), dtype=np.float32)


def line_end(fen: str, line: str, plies: int = 6) -> chess.Board:
    b = chess.Board(fen)
    moves = line.split()[:plies]
    moves = moves[: len(moves) - (len(moves) % 2)]  # even: same side to move as the root
    for u in moves:
        b.push(chess.Move.from_uci(u))
    return b


def collect(model: E.ChessEncoder, data: dict, idx: np.ndarray, plies: int = 6) -> dict[str, np.ndarray]:
    """static reps for idx, and dynamic (best-end − alt-end) reps for the idx that have an alt line."""
    roots = [chess.Board(str(data["fen"][i])) for i in idx]
    static = reps_for_boards(model, roots)
    dyn_idx = np.asarray([i for i in idx if data["has_alt"][i]], dtype=np.int64)
    best = reps_for_boards(model, [line_end(str(data["fen"][i]), str(data["best_line"][i]), plies) for i in dyn_idx])
    alt = reps_for_boards(model, [line_end(str(data["fen"][i]), str(data["alt_line"][i]), plies) for i in dyn_idx])
    return {"idx": idx, "static": static, "dyn_idx": dyn_idx, "dynamic": best - alt}


# ── TopK SAE ─────────────────────────────────────────────────────────────────


class TopKSAE(nn.Module):
    def __init__(self, m: int, n: int, k: int):
        super().__init__()
        self.k = k
        self.b_pre = nn.Parameter(torch.zeros(m))
        self.enc = nn.Linear(m, n)
        self.dec = nn.Parameter(self.enc.weight.data.clone())  # [n, m]: tied init, untied training
        self.normalize_dec()

    @torch.no_grad()
    def normalize_dec(self) -> None:
        self.dec.data /= self.dec.data.norm(dim=1, keepdim=True).clamp_min(1e-8)

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        pre = torch.relu(self.enc(x - self.b_pre))
        top = pre.topk(self.k, dim=-1)
        return torch.zeros_like(pre).scatter_(-1, top.indices, top.values)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        z = self.encode(x)
        return z @ self.dec + self.b_pre, z


def train_sae(x: np.ndarray, n_latents: int = 1024, k: int = 16, epochs: int = 8, bs: int = 2048,
              lr: float = 4e-4, seed: int = 0, log=print) -> tuple[TopKSAE, dict]:
    """x is standardized (per-dim mean/std) before training; returns the SAE and the norm stats."""
    torch.manual_seed(seed)
    dev = device()
    mu, sd = x.mean(0), x.std(0) + 1e-6
    xs = torch.from_numpy(((x - mu) / sd).astype(np.float32))
    sae = TopKSAE(xs.shape[1], n_latents, k).to(dev)
    opt = torch.optim.Adam(sae.parameters(), lr=lr)
    n = len(xs)
    fired = torch.zeros(n_latents, device=dev)
    for ep in range(epochs):
        perm = torch.randperm(n)
        tot = 0.0
        for s in range(0, n, bs):
            xb = xs[perm[s:s + bs]].to(dev)
            xh, z = sae(xb)
            loss = ((xh - xb) ** 2).sum(-1).mean() / xb.shape[1]
            opt.zero_grad()
            loss.backward()
            opt.step()
            sae.normalize_dec()
            fired += (z > 0).float().sum(0)
            tot += loss.item() * len(xb)
        dead = int((fired == 0).sum())
        # resample dead latents onto badly reconstructed inputs (keeps the dictionary in use)
        if dead and ep < epochs - 2:
            with torch.no_grad():
                xb = xs[torch.randperm(n)[:8192]].to(dev)
                err = ((sae(xb)[0] - xb) ** 2).sum(-1)
                worst = xb[err.topk(dead).indices]
                dead_ix = (fired == 0).nonzero().squeeze(1)
                sae.dec.data[dead_ix] = worst / worst.norm(dim=1, keepdim=True)
                sae.enc.weight.data[dead_ix] = worst / worst.norm(dim=1, keepdim=True) * 0.2
                sae.enc.bias.data[dead_ix] = 0.0
        log(f"[sae] epoch {ep + 1}/{epochs} mse/dim {tot / n:.4f} dead {dead}")
        fired.zero_()
    with torch.no_grad():
        xb = xs[:20000].to(dev)
        fve = 1 - ((sae(xb)[0] - xb) ** 2).sum() / ((xb - xb.mean(0)) ** 2).sum()
    return sae, {"mu": mu, "sd": sd, "fve": float(fve)}


@torch.no_grad()
def activations(sae: TopKSAE, norm: dict, x: np.ndarray, bs: int = 4096) -> np.ndarray:
    dev = next(sae.parameters()).device
    out = []
    for s in range(0, len(x), bs):
        xb = torch.from_numpy(((x[s:s + bs] - norm["mu"]) / norm["sd"]).astype(np.float32)).to(dev)
        out.append(sae.encode(xb).cpu().numpy().astype(np.float32))
    return np.concatenate(out)


# ── feature analysis ─────────────────────────────────────────────────────────


def _corr_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pearson correlation between every column of a [N,F] and b [N,K] -> [F,K]."""
    a = a - a.mean(0)
    b = b - b.mean(0)
    na = np.sqrt((a ** 2).sum(0)) + 1e-9
    nb = np.sqrt((b ** 2).sum(0)) + 1e-9
    return (a.T @ b) / na[:, None] / nb[None, :]


def analyse(acts: np.ndarray, labels: np.ndarray, label_names: list[str], extra: dict[str, np.ndarray] | None = None,
            top: int = 3) -> list[dict]:
    """Per feature: firing rate, best-matching known labels (by |corr|), corr with extras."""
    freq = (acts > 0).mean(0)
    corr = _corr_matrix(acts, labels)
    corr = np.nan_to_num(corr)
    ext = {k: np.nan_to_num(_corr_matrix(acts, v[:, None]))[:, 0] for k, v in (extra or {}).items()}
    feats = []
    for f in range(acts.shape[1]):
        order = np.argsort(-np.abs(corr[f]))[:top]
        feats.append({"feature": f, "freq": round(float(freq[f]), 4),
                      "match": [(label_names[j], round(float(corr[f, j]), 3)) for j in order],
                      "max_abs_corr": round(float(np.abs(corr[f]).max()), 3),
                      **{f"corr_{k}": round(float(v[f]), 3) for k, v in ext.items()}})
    return feats


def top_examples(acts: np.ndarray, f: int, n: int = 10, diverse_keys: list | None = None) -> list[int]:
    order = np.argsort(-acts[:, f])
    out, seen = [], set()
    for j in order:
        if acts[j, f] <= 0:
            break
        key = diverse_keys[j] if diverse_keys is not None else j
        if key in seen:
            continue
        seen.add(key)
        out.append(int(j))
        if len(out) >= n:
            break
    return out


def save_sae(sae: TopKSAE, norm: dict, path: Path) -> None:
    torch.save({"state": sae.state_dict(), "k": sae.k, "m": sae.dec.shape[1], "n": sae.dec.shape[0],
                "mu": norm["mu"], "sd": norm["sd"], "fve": norm["fve"]}, path)


def load_sae(path: Path) -> tuple[TopKSAE, dict]:
    ck = torch.load(path, map_location=device(), weights_only=False)
    sae = TopKSAE(ck["m"], ck["n"], ck["k"]).to(device())
    sae.load_state_dict(ck["state"])
    return sae, {"mu": ck["mu"], "sd": ck["sd"], "fve": ck["fve"]}


# ── auto-interpretation with Claude ──────────────────────────────────────────

INTERP_SYSTEM = """You are a chess master helping interpret a neural network. You are shown positions where one
internal feature of a chess network fires strongly. Find the single chess concept they share. It may be a
known idea (passed pawn, weak back rank, opposite-side castling...) or something more specific or unusual.
Be concrete about what is on the board. Reply with one JSON object only."""

SIM_SYSTEM = """You are a chess master. You get a description of a chess concept and a list of positions.
For each position, decide whether the concept is clearly present. Reply with one JSON object only."""


def _example_block(data: dict, i: int, dynamic: bool) -> str:
    from claude_chess.explainer import facts as F

    b = chess.Board(str(data["fen"][i]))
    s = f"FEN: {data['fen'][i]} ({'White' if b.turn else 'Black'} to move)\n{F.ascii_board(b)}"
    if dynamic and data["has_alt"][i]:
        _, best = C.play_line(b, str(data["best_line"][i]).split()[:6])
        _, alt = C.play_line(b, str(data["alt_line"][i]).split()[:6])
        s += f"\nBest line: {F.numbered(b, best)}\nAlternative: {F.numbered(b, alt)}"
    return s


def interpret(llm, data: dict, ex_idx: list[int], dynamic: bool, known_hint: str = "") -> dict:
    from claude_chess.llm import extract_json

    what = ("The feature measures what the BEST line achieves compared with the ALTERNATIVE line "
            "(it fires on the difference between their end positions)." if dynamic else
            "The feature fires on the position itself.")
    blocks = "\n\n".join(f"Example {n + 1}:\n{_example_block(data, i, dynamic)}" for n, i in enumerate(ex_idx))
    prompt = (f"{what}\n{known_hint}\n\n{blocks}\n\nReturn JSON: {{\"name\": \"<=6 words\", "
              f"\"description\": \"<=40 words: what is on the board when it fires, for the side to move\", "
              f"\"human_concept\": \"closest standard chess concept or 'novel'\", \"confidence\": 0-1}}")
    resp = llm.complete(INTERP_SYSTEM, prompt, max_tokens=600)
    try:
        out = extract_json(resp.text)
    except ValueError:
        out = {"name": "?", "description": resp.text[:200]}
    out["cost_usd"] = resp.cost_usd
    return out


def simulate(llm, data: dict, description: str, pos_idx: list[int], neg_idx: list[int], dynamic: bool,
             seed: int = 0) -> dict:
    """Claude predicts which held-out positions activate the feature from the description alone."""
    from claude_chess.llm import extract_json

    rng = np.random.default_rng(seed)
    items = [(i, 1) for i in pos_idx] + [(i, 0) for i in neg_idx]
    rng.shuffle(items)
    blocks = "\n\n".join(f"Position {n + 1}:\n{_example_block(data, i, dynamic)}" for n, (i, _) in enumerate(items))
    prompt = (f"Concept: {description}\n\n{blocks}\n\nReturn JSON: {{\"present\": [list of position numbers "
              f"where the concept is clearly present]}}")
    resp = llm.complete(SIM_SYSTEM, prompt, max_tokens=400)
    try:
        chosen = {int(x) for x in extract_json(resp.text).get("present", [])}
    except (ValueError, TypeError):
        chosen = set()
    pred = [1 if (n + 1) in chosen else 0 for n in range(len(items))]
    truth = [y for _, y in items]
    tp = sum(p and t for p, t in zip(pred, truth))
    tn = sum((not p) and (not t) for p, t in zip(pred, truth))
    bal_acc = 0.5 * (tp / max(1, sum(truth)) + tn / max(1, len(truth) - sum(truth)))
    return {"balanced_accuracy": round(bal_acc, 3), "tp": tp, "tn": tn, "n": len(items), "cost_usd": resp.cost_usd}
