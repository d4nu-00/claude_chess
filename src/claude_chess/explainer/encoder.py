"""Chess encoder (MLX): a small transformer over the 64 squares, trained on Stockfish play targets.

Trunk: [CLS] + 64 square tokens (side-to-move POV, see data.encode_board), pre-norm
transformer. Play heads shape the trunk: value (HL-Gauss over win prob, Ruoss et al. 2024)
and policy (bilinear from-square x to-square logits, legal-masked, soft target over the
multi-PV moves). Concept heads are STOP-GRAD probes by default (`probe_grad=False`): they
read the trunk without shaping it, so we can ask whether play alone produces human concepts
(McGrath et al. 2022) and the SAE discovery sees an unbiased representation.

MLX, not torch: on an M1 Pro a compiled MLX step is ~3.2x faster than torch-MPS for this
model (852 vs 265 positions/s, see wiki/pages/explainer-model.md). Downstream code uses
`forward_np` and never touches MLX arrays.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from claude_chess.explainer import concepts as C

N_BINS = 51
BIN_CENTERS = np.linspace(0, 1, N_BINS).astype(np.float32)


@dataclass
class Config:
    d: int = 256
    layers: int = 8
    heads: int = 8
    ff: int = 1024
    n_concepts: int = len(C.KEYS)
    n_themes: int = 0
    probe_grad: bool = False
    themes: list[str] = field(default_factory=list)


class ChessEncoder(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        d = cfg.d
        self.piece = nn.Embedding(13, d)
        self.pos = mx.random.normal((64, d)) * 0.02
        self.cls = mx.random.normal((1, 1, d)) * 0.02
        self.castle = nn.Linear(4, d)
        self.ep = nn.Embedding(9, d)
        self.trunk = nn.TransformerEncoder(cfg.layers, d, cfg.heads, cfg.ff, dropout=0.0, norm_first=True,
                                           activation=nn.gelu)  # ends with a LayerNorm
        self.value = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, N_BINS))
        self.q = nn.Linear(d, d)
        self.k = nn.Linear(d, d)

        def probe(n: int) -> nn.Module:
            return nn.Sequential(nn.Linear(2 * d, 512), nn.GELU(), nn.Linear(512, n))

        self.concept_head = probe(cfg.n_concepts)
        self.salience_head = probe(cfg.n_concepts)
        self.theme_head = probe(max(1, cfg.n_themes))

    def __call__(self, tokens, castle, ep) -> dict:
        x = self.piece(tokens) + self.pos
        c = self.cls + (self.castle(castle) + self.ep(ep))[:, None, :]
        h = self.trunk(mx.concatenate([c, x], axis=1), None)
        cls, sq = h[:, 0], h[:, 1:]
        pol = (self.q(sq) @ self.k(sq).transpose(0, 2, 1)).reshape(sq.shape[0], 4096) / math.sqrt(self.cfg.d)
        rep = mx.concatenate([cls, sq.mean(axis=1)], axis=-1)
        prep = rep if self.cfg.probe_grad else mx.stop_gradient(rep)
        return {"value_logits": self.value(cls), "policy": pol, "concepts": self.concept_head(prep),
                "salience": self.salience_head(prep), "themes": self.theme_head(prep), "rep": rep}


# ── targets & losses ─────────────────────────────────────────────────────────


def hl_gauss(v: mx.array, sigma_bins: float = 0.75) -> mx.array:
    """Histogram-loss Gaussian target over N_BINS bins on [0,1] (Imani & White 2018)."""
    half = 0.5 / (N_BINS - 1)
    edges = mx.linspace(-half, 1 + half, N_BINS + 1)
    sigma = sigma_bins / (N_BINS - 1)
    cdf = 0.5 * (1 + mx.erf((edges[None, :] - v[:, None]) / (sigma * math.sqrt(2))))
    p = cdf[:, 1:] - cdf[:, :-1]
    return p / mx.maximum(p.sum(axis=1, keepdims=True), 1e-8)


def expected_value_np(logits: np.ndarray) -> np.ndarray:
    z = logits - logits.max(-1, keepdims=True)
    p = np.exp(z)
    p /= p.sum(-1, keepdims=True)
    return (p * BIN_CENTERS).sum(-1)


def _log_softmax(x: mx.array) -> mx.array:
    return x - mx.logsumexp(x, axis=-1, keepdims=True)


def losses(out: dict, b: dict) -> dict[str, mx.array]:
    vmask = b["vmask"]
    lv = -(hl_gauss(b["value"]) * _log_softmax(out["value_logits"])).sum(-1)
    lv = (lv * vmask).sum() / mx.maximum(vmask.sum(), 1)
    logits = mx.where(b["legal"], out["policy"], -1e4)
    lp = -(b["pol_t"] * _log_softmax(logits)).sum(-1).mean()
    lc = ((out["concepts"] - b["concepts"]) ** 2).mean()
    ls = ((out["salience"] - b["salience"]) ** 2).mean(-1)
    ls = (ls * b["has_alt"]).sum() / mx.maximum(b["has_alt"].sum(), 1)
    pz = b["is_puz"]
    lt = nn.losses.binary_cross_entropy(out["themes"], b["themes"], with_logits=True, reduction="none").mean(-1)
    lt = (lt * pz).sum() / mx.maximum(pz.sum(), 1)
    return {"value": lv, "policy": lp, "concepts": lc, "salience": ls, "themes": lt}


class Batcher:
    """Holds the arrays in memory (NumPy); yields MLX batches. Concept targets are standardized
    with train-split statistics; salience target = clip((Δbest − Δalt)/scale, ±4)."""

    def __init__(self, data: dict, scale: dict[str, float], themes: list[str]):
        self.d = data
        tr = data["split"] == 0
        root = data["root"]
        self.c_mean = root[tr].mean(0)
        self.c_std = root[tr].std(0) + 1e-3
        sc = np.asarray([scale.get(k, 1.0) for k in C.KEYS], dtype=np.float32)
        sal = (data["d_best"] - data["d_alt"]) / sc
        sal[:, [C.KEYS.index("us.material"), C.KEYS.index("them.material")]] = 0.0
        self.sal = np.clip(sal, -4, 4).astype(np.float32)
        n = len(data["fen"])
        off = data["legal_off"]
        self.legal_bits = np.zeros((n, 512), dtype=np.uint8)
        for s in range(0, n, 50_000):  # chunked: a full dense mask would be n x 4096 bytes
            e = min(n, s + 50_000)
            rows = np.repeat(np.arange(e - s), np.diff(off[s:e + 1]))
            dense = np.zeros((e - s, 4096), dtype=bool)
            dense[rows, data["legal_idx"][off[s]:off[e]].astype(np.int64)] = True
            self.legal_bits[s:e] = np.packbits(dense, axis=1)
        self.themes = themes
        tix = {t: i for i, t in enumerate(themes)}
        self.theme_y = np.zeros((n, max(1, len(themes))), dtype=np.float32)
        for i, s in enumerate(data["themes"]):
            for t in str(s).split():
                if t in tix:
                    self.theme_y[i, tix[t]] = 1.0

    NEEDED = ("pol_idx", "pol_w", "tokens", "castle", "ep", "value", "root", "has_alt", "src", "split")

    def slim(self) -> None:
        """Drop every array batches don't read (strings, deltas, ragged legal lists): ~1.5 GB of
        a 2.5 GB dataset. On a 16 GB machine random row reads from swapped pages halved speed."""
        for k in list(self.d):
            if k not in self.NEEDED:
                del self.d[k]

    def indices(self, split: int, src: int | None = None) -> np.ndarray:
        m = self.d["split"] == split
        if src is not None:
            m &= self.d["src"] == src
        return np.flatnonzero(m)

    def batch_np(self, idx: np.ndarray) -> dict[str, np.ndarray]:
        d = self.d
        pi, pw = d["pol_idx"][idx].astype(np.int64), d["pol_w"][idx]
        pol_t = np.zeros((len(idx), 4096), dtype=np.float32)
        ok = pi >= 0
        rows = np.broadcast_to(np.arange(len(idx))[:, None], pi.shape)[ok]
        np.add.at(pol_t, (rows, pi[ok]), pw[ok])
        value = d["value"][idx]
        return {
            "tokens": d["tokens"][idx].astype(np.int32), "castle": d["castle"][idx].astype(np.float32),
            "ep": d["ep"][idx].astype(np.int32),
            "legal": np.unpackbits(self.legal_bits[idx], axis=1).astype(bool), "pol_t": pol_t,
            "value": np.nan_to_num(value, nan=0.5).astype(np.float32), "vmask": (~np.isnan(value)).astype(np.float32),
            "concepts": ((d["root"][idx] - self.c_mean) / self.c_std).astype(np.float32),
            "salience": self.sal[idx], "has_alt": d["has_alt"][idx].astype(np.float32),
            "themes": self.theme_y[idx], "is_puz": (d["src"][idx] == 1).astype(np.float32),
            "best": pi[:, 0], "src": d["src"][idx],
        }

    def batch(self, idx: np.ndarray) -> dict[str, mx.array]:
        return {k: mx.array(v) for k, v in self.batch_np(idx).items() if k not in ("best", "src")}


# ── evaluation ───────────────────────────────────────────────────────────────


def forward_np(model: ChessEncoder, tokens: np.ndarray, castle: np.ndarray, ep: np.ndarray) -> dict[str, np.ndarray]:
    out = model(mx.array(tokens.astype(np.int32)), mx.array(castle.astype(np.float32)), mx.array(ep.astype(np.int32)))
    mx.eval(out)
    return {k: np.array(v) for k, v in out.items()}


def evaluate(model: ChessEncoder, bt: Batcher, idx: np.ndarray, bs: int = 1024) -> dict:
    agg: dict[str, list] = {k: [] for k in ("v_err", "top1", "top1_puz", "c_pred", "c_true", "s_pred", "s_true",
                                             "t_pred", "t_true")}
    for s in range(0, len(idx), bs):
        b = bt.batch_np(idx[s:s + bs])
        out = forward_np(model, b["tokens"], b["castle"], b["ep"])
        vm = b["vmask"] > 0
        if vm.any():
            agg["v_err"].append(np.abs(expected_value_np(out["value_logits"])[vm] - b["value"][vm]))
        pred = np.where(b["legal"], out["policy"], -1e4).argmax(-1)
        hit = (pred == b["best"]).astype(np.float32)
        agg["top1"].append(hit[b["src"] == 0])
        agg["top1_puz"].append(hit[b["src"] == 1])
        agg["c_pred"].append(out["concepts"])
        agg["c_true"].append(b["concepts"])
        ha = b["has_alt"] > 0
        agg["s_pred"].append(out["salience"][ha])
        agg["s_true"].append(b["salience"][ha])
        agg["t_pred"].append(out["themes"][b["src"] == 1])
        agg["t_true"].append(b["themes"][b["src"] == 1])
    cat = {k: np.concatenate(v) if v else np.zeros(0) for k, v in agg.items()}
    res: dict = {"n": int(len(idx))}
    if len(cat["v_err"]):
        res["value_mae"] = float(cat["v_err"].mean())
    if len(cat["top1"]):
        res["policy_top1"] = float(cat["top1"].mean())
    if len(cat["top1_puz"]):
        res["puzzle_top1"] = float(cat["top1_puz"].mean())
    # R^2 per concept; the mean skips concepts that (almost) never vary in this sample
    ct, cp = cat["c_true"], cat["c_pred"]
    var = ct.var(0)
    r2 = 1 - ((ct - cp) ** 2).mean(0) / np.maximum(var, 1e-6)
    res["concept_r2_mean"] = float(r2[var > 0.05].mean())
    res["concept_r2"] = {k: round(float(x), 3) for k, x, v in zip(C.KEYS, r2, var) if v > 0.05}
    if len(cat["s_true"]):
        st, sp = cat["s_true"], cat["s_pred"]
        sv = st.var(0)
        s_r2 = 1 - ((st - sp) ** 2).mean(0) / np.maximum(sv, 1e-6)
        res["salience_r2_mean"] = float(s_r2[sv > 0.05].mean())
    if len(cat["t_true"]) and model.cfg.n_themes:
        res["theme_auc"] = mean_auc(cat["t_true"], cat["t_pred"], model.cfg.themes)
    return res


def mean_auc(y: np.ndarray, s: np.ndarray, names: list[str]) -> dict:
    out = {}
    for j, name in enumerate(names):
        pos, neg = s[y[:, j] > 0, j], s[y[:, j] == 0, j]
        if len(pos) < 20 or len(neg) < 20:
            continue
        ranks = np.argsort(np.argsort(np.concatenate([pos, neg])))
        out[name] = round(float((ranks[:len(pos)].sum() - len(pos) * (len(pos) - 1) / 2) / (len(pos) * len(neg))), 3)
    out["_mean"] = round(float(np.mean(list(out.values()))), 3) if out else float("nan")
    return out


# ── training ─────────────────────────────────────────────────────────────────


def train(data: dict, scale: dict[str, float], out_dir: Path, cfg: Config, epochs: float = 5, bs: int = 512,
          lr: float = 6e-4, weight_decay: float = 0.01, warmup: int = 1000, eval_every: int = 2000,
          probe_weight: float = 1.0, log=print, seed: int = 0, max_minutes: float | None = None,
          random_trunk: bool = False, init_from: Path | None = None, start_step: int = 0) -> dict:
    """random_trunk=True: freeze a randomly initialised network and train only the probe heads —
    the baseline that says how much of a concept is readable without any chess training."""
    mx.random.seed(seed)
    rng = np.random.default_rng(seed)
    bt = Batcher(data, scale, cfg.themes)
    bt.slim()
    model = ChessEncoder(cfg)
    if init_from is not None:  # resume: weights from a checkpoint, schedule from start_step (Adam moments restart)
        model.load_weights(str(init_from))
        log(f"[encoder] resumed weights from {init_from} at step {start_step}")
    mx.eval(model.parameters())
    if random_trunk:
        model.freeze()
        for head in (model.concept_head, model.salience_head, model.theme_head):
            head.unfreeze()
    n_params = sum(v.size for _, v in nn.utils.tree_flatten(model.parameters()))
    log(f"[encoder] {n_params / 1e6:.2f}M params (MLX); probe_grad={cfg.probe_grad}")
    tr = bt.indices(0)
    va = bt.indices(1)
    va = va[rng.permutation(len(va))[:20000]]
    steps = int(epochs * len(tr) / bs)
    base = optim.join_schedules([optim.linear_schedule(1e-7, lr, warmup),
                                 optim.cosine_decay(lr, max(1, steps - warmup), lr * 0.02)], [warmup])
    # on resume, a short re-warmup (fresh Adam moments) into the original schedule at start_step
    sched = base if not start_step else (lambda s: mx.minimum(1.0, (s + 1) / 200) * base(s + start_step))
    opt = optim.AdamW(learning_rate=sched, betas=[0.9, 0.95], weight_decay=weight_decay)

    def loss_fn(m, b):
        L = losses(m(b["tokens"], b["castle"], b["ep"]), b)
        total = L["value"] + L["policy"] + probe_weight * (L["concepts"] + L["salience"] + 0.5 * L["themes"])
        return total, L

    state = [model.state, opt.state]

    @partial(mx.compile, inputs=state, outputs=state)
    def step(b):
        (loss, L), g = nn.value_and_grad(model, loss_fn)(model, b)
        g, _ = optim.clip_grad_norm(g, 1.0)
        opt.update(model, g)
        return loss, L

    out_dir.mkdir(parents=True, exist_ok=True)
    history = []
    t0 = time.time()
    n_step = start_step
    best_score = float("inf")
    done = False
    while not done:
        perm = tr[rng.permutation(len(tr))]
        for s in range(0, len(perm) - bs + 1, bs):
            loss, L = step(bt.batch(perm[s:s + bs]))
            mx.eval(state, loss)
            n_step += 1
            if n_step % 200 == 0:
                el = time.time() - t0
                log(f"[encoder] step {n_step}/{steps} loss {loss.item():.3f} " +
                    " ".join(f"{k}={v.item():.3f}" for k, v in L.items()) +
                    f" {(n_step - start_step) * bs / el:.0f} pos/s")
            done = n_step >= steps or (max_minutes is not None and time.time() - t0 > max_minutes * 60)
            if n_step % eval_every == 0 or done:
                ev = evaluate(model, bt, va)
                ev.update(step=n_step, minutes=round((time.time() - t0) / 60, 1))
                history.append({k: v for k, v in ev.items() if k not in ("concept_r2", "theme_auc")})
                log(f"[encoder] eval {json.dumps(history[-1])}")
                save(model, bt, out_dir, "last")
                score = -ev["concept_r2_mean"] if random_trunk else ev.get("value_mae", 0) * 10 - ev.get("policy_top1", 0)
                if score < best_score:
                    best_score = score
                    save(model, bt, out_dir, "best")
            if done:
                break
    (out_dir / "history.json").write_text(json.dumps(history, indent=1))
    return history[-1] if history else {}


def save(model: ChessEncoder, bt: Batcher, out_dir: Path, tag: str) -> None:
    model.save_weights(str(out_dir / f"{tag}.safetensors"))
    (out_dir / "config.json").write_text(json.dumps(asdict(model.cfg)))
    np.savez(out_dir / "norm.npz", c_mean=bt.c_mean, c_std=bt.c_std)


def load(out_dir: Path, tag: str = "best") -> tuple[ChessEncoder, dict]:
    """Load from a run directory (or a path to <tag>.safetensors inside one)."""
    out_dir = Path(out_dir)
    if out_dir.suffix == ".safetensors":
        out_dir, tag = out_dir.parent, out_dir.stem
    cfg = Config(**json.loads((out_dir / "config.json").read_text()))
    model = ChessEncoder(cfg)
    model.load_weights(str(out_dir / f"{tag}.safetensors"))
    model.eval()
    z = np.load(out_dir / "norm.npz")
    return model, {"cfg": json.loads((out_dir / "config.json").read_text()), "c_mean": z["c_mean"],
                   "c_std": z["c_std"]}
