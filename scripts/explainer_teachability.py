"""Schut et al.'s teachability filter for discovered concepts:
uv run --extra ml python scripts/explainer_teachability.py [MIN_SIM]

For each named dynamic SAE feature with simulation accuracy >= MIN_SIM: take a WEAKER student
(enc_v1 at step 2000), fine-tune one copy on the feature's top-activating train positions
(prototypes) and one copy on the same number of random train positions, then compare Stockfish
top-move accuracy on held-out prototypes (test split). teachability = concept − control.
Writes experiments/explainer/teachability.json.
"""

from __future__ import annotations

import json
import sys
from functools import partial
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from claude_chess.explainer import data as D
from claude_chess.explainer import encoder as E
from claude_chess.explainer import sae as S

ENC = Path("data/models/enc_v1")


def subset(data: dict, idx: np.ndarray) -> dict:
    out = {k: v[idx] for k, v in data.items() if k not in ("legal_idx", "legal_off")}
    off = data["legal_off"]
    parts = [data["legal_idx"][off[i]:off[i + 1]] for i in idx]
    out["legal_idx"] = np.concatenate(parts)
    out["legal_off"] = np.cumsum([0] + [len(p) for p in parts])
    return out


def finetune(model: E.ChessEncoder, bt: E.Batcher, idx: np.ndarray, steps: int, bs: int, lr: float,
             seed: int) -> None:
    rng = np.random.default_rng(seed)
    opt = optim.Adam(learning_rate=lr)

    def loss_fn(m, b):
        L = E.losses(m(b["tokens"], b["castle"], b["ep"]), b)
        return L["policy"] + L["value"]

    for _ in range(steps):
        b = bt.batch(rng.choice(idx, size=min(bs, len(idx)), replace=False))
        loss, g = nn.value_and_grad(model, loss_fn)(model, b)
        opt.update(model, g)
        mx.eval(model.parameters(), opt.state)


def top1(model: E.ChessEncoder, bt: E.Batcher, idx: np.ndarray) -> float:
    return E.evaluate(model, bt, idx)["policy_top1"]


def main(min_sim: float = 0.7, n_proto: int = 300, n_test: int = 100, steps: int = 40, bs: int = 64,
         lr: float = 1e-4, seeds: tuple[int, ...] = (0, 1)) -> None:
    disc = json.loads(Path("datasets/explainer_v1/discovered_concepts.json").read_text())
    feats = [f for f in disc["views"]["dynamic"]["features"]
             if f.get("simulation", {}).get("balanced_accuracy", 0) >= min_sim]
    data = D.load(("eval",))
    rng = np.random.default_rng(0)
    pool_tr = rng.choice(np.flatnonzero((data["split"] == 0) & (data["has_alt"] == 1)), 40000, replace=False)
    pool_te = rng.choice(np.flatnonzero((data["split"] == 2) & (data["has_alt"] == 1)), 12000, replace=False)
    teacher_model, ck = E.load(ENC)
    sae, norm = S.load_sae(ENC / "sae_dynamic.pt")
    acts = {}
    for name, pool in (("tr", pool_tr), ("te", pool_te)):
        lat = S.collect(teacher_model, data, pool)
        acts[name] = S.activations(sae, norm, lat["dynamic"])
        acts[name + "_idx"] = lat["dyn_idx"]
    del teacher_model
    results = []
    for f in feats:
        j = f["feature"]
        tr_order = np.argsort(-acts["tr"][:, j])
        te_order = np.argsort(-acts["te"][:, j])
        proto_tr = acts["tr_idx"][tr_order[:n_proto]][acts["tr"][tr_order[:n_proto], j] > 0]
        proto_te = acts["te_idx"][te_order[:n_test]][acts["te"][te_order[:n_test], j] > 0]
        if len(proto_tr) < 50 or len(proto_te) < 30:
            continue
        ctrl_tr = rng.choice(pool_tr, size=len(proto_tr), replace=False)
        rand_te = rng.choice(pool_te, size=len(proto_te), replace=False)
        sub_idx = np.concatenate([proto_tr, ctrl_tr, proto_te, rand_te])
        sub = subset(data, sub_idx)
        bt = E.Batcher(sub, {}, list(ck["cfg"].get("themes") or []))
        bt.c_mean, bt.c_std = ck["c_mean"], ck["c_std"]
        a, b_, c_, d_ = len(proto_tr), len(ctrl_tr), len(proto_te), len(rand_te)
        i_proto, i_ctrl = np.arange(a), np.arange(a, a + b_)
        i_test, i_rand = np.arange(a + b_, a + b_ + c_), np.arange(a + b_ + c_, a + b_ + c_ + d_)
        rows = []
        for seed in seeds:
            base, _ = E.load(ENC, "step2000")
            before = top1(base, bt, i_test)
            concept, _ = E.load(ENC, "step2000")
            finetune(concept, bt, i_proto, steps, bs, lr, seed)
            control, _ = E.load(ENC, "step2000")
            finetune(control, bt, i_ctrl, steps, bs, lr, seed)
            rows.append({"before": before, "concept": top1(concept, bt, i_test), "control": top1(control, bt, i_test),
                         "concept_on_random": top1(concept, bt, i_rand), "control_on_random": top1(control, bt, i_rand)})
        avg = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
        avg["teachability"] = avg["concept"] - avg["control"]
        name = f.get("interpretation", {}).get("name", "")
        results.append({"feature": j, "name": name, "sim": f["simulation"]["balanced_accuracy"],
                        "n_proto": int(a), "n_test": int(c_), **{k: round(v, 3) for k, v in avg.items()}})
        print(json.dumps(results[-1]), flush=True)
    Path("experiments/explainer/teachability.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main(*(float(a) for a in sys.argv[1:]))
