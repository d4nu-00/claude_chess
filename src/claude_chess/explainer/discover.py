"""Run concept discovery end to end: latents -> SAEs -> match to known concepts -> name -> score.

Outputs (small, committed): datasets/explainer_v1/discovered_concepts.json and
experiments/explainer/discovered.md. SAE weights go to data/models/<enc>/sae_*.pt.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from claude_chess.explainer import concepts as C
from claude_chess.explainer import data as D
from claude_chess.explainer import encoder as E
from claude_chess.explainer import sae as S


def _theme_matrix(data: dict, idx: np.ndarray, themes: list[str]) -> np.ndarray:
    tix = {t: j for j, t in enumerate(themes)}
    y = np.zeros((len(idx), len(themes)), dtype=np.float32)
    for r, i in enumerate(idx):
        for t in str(data["themes"][i]).split():
            if t in tix:
                y[r, tix[t]] = 1.0
    return y


def _struct_keys(data: dict, idx: np.ndarray) -> list[str]:
    # positions sharing pawns are near-duplicates; examples should show different games
    return [str(data["fen"][i]).split()[0].translate(str.maketrans("", "", "NBRQKnbrqk12345678"))[:40] for i in idx]


def pick_features(feats: list[dict], n_novel: int, n_known: int, min_freq: float = 0.002,
                  max_freq: float = 0.15, use_key: str | None = None) -> list[dict]:
    pool = [f for f in feats if min_freq <= f["freq"] <= max_freq]
    if use_key:
        pool.sort(key=lambda f: -abs(f.get(use_key, 0.0)))
        pool = pool[: max(60, len(pool) // 3)]  # the more useful third
    novel = sorted(pool, key=lambda f: f["max_abs_corr"])[:n_novel]
    known = sorted(pool, key=lambda f: -f["max_abs_corr"])[:n_known]
    seen, out = set(), []
    for f in novel + known:
        if f["feature"] not in seen:
            seen.add(f["feature"])
            out.append(f)
    return out


def run(enc_dir: Path, llm, n_train: int = 120_000, n_eval: int = 30_000, n_latents: int = 1024, k: int = 16,
        n_novel: int = 8, n_known: int = 4, out_json: Path = Path("datasets/explainer_v1/discovered_concepts.json"),
        out_md: Path = Path("experiments/explainer/discovered.md"), log=print, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    model, ck = E.load(enc_dir)
    themes = list(ck["cfg"].get("themes") or [])
    data = D.load(("eval", "puzzle"))
    tr = np.flatnonzero(data["split"] == 0)
    ev = np.flatnonzero(data["split"] != 0)
    tr = rng.choice(tr, size=min(n_train, len(tr)), replace=False)
    ev = rng.choice(ev, size=min(n_eval, len(ev)), replace=False)
    log(f"[discover] collecting latents for {len(tr)} train + {len(ev)} eval positions")
    lat_tr = S.collect(model, data, tr)
    lat_ev = S.collect(model, data, ev)
    scale = json.loads((D.DATA_DIR / "stats.json").read_text())["delta_scale"]
    sc = np.asarray([scale.get(kk, 1.0) for kk in C.KEYS], dtype=np.float32)
    results: dict = {"encoder": str(enc_dir), "views": {}}
    for view in ("static", "dynamic"):
        x_tr = lat_tr[view]
        sae, norm = S.train_sae(x_tr, n_latents=n_latents, k=k, log=log, seed=seed)
        S.save_sae(sae, norm, enc_dir / f"sae_{view}.pt")
        x_ev = lat_ev[view]
        acts = S.activations(sae, norm, x_ev)
        idx = lat_ev["idx"] if view == "static" else lat_ev["dyn_idx"]
        if view == "static":
            labels = data["root"][idx]
            names = [f"concept:{kk}" for kk in C.KEYS]
            extra = {"value": np.nan_to_num(data["value"][idx], nan=0.5)}
            puz = data["src"][idx] == 1
            if themes and puz.sum() > 200:  # theme labels only exist for puzzle rows
                th = np.zeros((len(idx), len(themes)), dtype=np.float32)
                th[puz] = _theme_matrix(data, idx[puz], themes)
                labels = np.concatenate([labels, th], axis=1)
                names += [f"theme:{t}" for t in themes]
        else:
            labels = (data["d_best"][idx] - data["d_alt"][idx]) / sc
            names = [f"delta:{kk}" for kk in C.KEYS]
            labels = np.concatenate([labels, data["f_best"][idx] - data["f_alt"][idx]], axis=1)
            names += [f"movefact:{kk}" for kk in D.FACT_KEYS]
            extra = {"gap": data["value"][idx] - data["value_alt"][idx]}
        feats = S.analyse(acts, labels, names, extra)
        alive = [f for f in feats if f["freq"] > 0]
        known_share = float(np.mean([f["max_abs_corr"] >= 0.5 for f in alive])) if alive else 0.0
        log(f"[discover] {view}: FVE {norm['fve']:.3f}, alive {len(alive)}/{len(feats)}, "
            f"share with |corr|>=0.5 to a known concept {known_share:.2f}")
        chosen = pick_features(feats, n_novel, n_known, use_key="corr_gap" if view == "dynamic" else None)
        keys = _struct_keys(data, idx)
        named = []

        def name_one(f: dict) -> dict:
            exs = S.top_examples(acts, f["feature"], n=16, diverse_keys=keys)
            show, held = exs[:8], exs[8:13]
            zero = np.flatnonzero(acts[:, f["feature"]] == 0)
            neg = rng.choice(zero, size=min(5, len(zero)), replace=False).tolist() if len(zero) else []
            hint = ("(For reference only, the closest hand-written measures are: " +
                    ", ".join(f"{n} r={c}" for n, c in f["match"]) + ")")
            interp = S.interpret(llm, data, [int(idx[j]) for j in show], view == "dynamic", hint)
            sim = S.simulate(llm, data, f"{interp.get('name', '')}: {interp.get('description', '')}",
                             [int(idx[j]) for j in held], [int(idx[j]) for j in neg], view == "dynamic") \
                if len(held) >= 3 and neg else {}
            return {**f, "interpretation": interp, "simulation": sim,
                    "examples": [str(data["fen"][idx[j]]) for j in show]}

        with ThreadPoolExecutor(4) as ex:
            named = list(ex.map(name_one, chosen))
        results["views"][view] = {"fve": norm["fve"], "alive": len(alive), "n_latents": n_latents, "k": k,
                                  "known_share": known_share, "features": named,
                                  "summary": sorted(({"feature": f["feature"], "freq": f["freq"],
                                                      "max_abs_corr": f["max_abs_corr"], "match": f["match"][:1]}
                                                     for f in alive), key=lambda f: -f["max_abs_corr"])[:40]}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=1, default=float))
    write_report(results, out_md)
    return results


def write_report(results: dict, path: Path) -> None:
    lines = ["# Discovered concepts (SAE on encoder latents, named by Claude)", "",
             f"Encoder: `{results['encoder']}`. Static = features of the position; dynamic = features of "
             "(best-line end − alternative-line end). Simulation = balanced accuracy of Claude predicting "
             "held-out activations from the name alone (0.5 = chance).", ""]
    for view, v in results["views"].items():
        lines += [f"## {view} (FVE {v['fve']:.2f}, {v['alive']}/{v['n_latents']} alive, "
                  f"{100 * v['known_share']:.0f}% match a known concept at |r|>=0.5)", "",
                  "| feat | freq | name | closest known (r) | sim acc | description |", "|---|---|---|---|---|---|"]
        for f in v["features"]:
            it = f.get("interpretation", {})
            m = f["match"][0]
            sim = f.get("simulation", {}).get("balanced_accuracy", "")
            lines.append(f"| {f['feature']} | {f['freq']:.3f} | {it.get('name', '')} | {m[0]} ({m[1]}) | {sim} | "
                         f"{str(it.get('description', '')).replace('|', '/')} |")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
