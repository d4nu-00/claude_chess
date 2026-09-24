"""Experiment report: cross table, performance Elo, and harness-vs-naive significance tests.

Reads every run directory whose name contains `prefix` (one run = one Claude config vs one
Maia level), and writes `crosstable.md`, `games.csv`, `stats.json` to `out_dir`.

Statistics (pure Python, no scipy):
- Elo by maximum likelihood against the Maia ladder: P(score) = 1 / (1 + 10^((R_opp-R)/400)),
  draws as half a win; 95% CI by bootstrap over games.
- Harness effect per model:
  * stratified permutation test on mean game score — harness/naive labels shuffled only
    WITHIN each Maia level (and colour), so opponent strength can't confound the result;
  * likelihood-ratio test: one shared Elo for both configs vs separate Elos (chi-square, 1 df);
  * Mann-Whitney U on per-game ACPL (lower = more accurate), normal approximation.
"""

from __future__ import annotations

import json
import math
import random
import re
from pathlib import Path

MAIA_RE = re.compile(r"maia[:-]?(\d{4})")


RELIANCE_KEYS = ("moves", "top_played", "top_overruled", "claude_proposed", "search_added",
                 "fail_low", "no_claude_value")


def classify_decision(d: dict) -> dict | None:
    """Who decided a harness move: Claude or the Python tactical search? (None if no search info.)

    top_played      Claude's own #1 candidate (highest prior) was played
    top_overruled   Claude's #1 was vetoed by the material search or refuted by a verified threat
    claude_proposed the played move was one of Claude's candidates
    search_added    the played move was NOT proposed by Claude (injected by the search)
    fail_low        every Claude candidate lost material, so all legal moves were searched
    no_claude_value the choice needed no Claude positional judgement (mate, single survivor,
                    tablebase, forced move)
    """
    info = d.get("search") or {}
    cands = info.get("candidates") or {}
    note = d.get("note") or ""
    if not cands and "only legal move" not in note:
        return None
    played = d.get("san")
    claude = {k: v for k, v in cands.items() if v.get("source") == "claude"}
    top = max(claude, key=lambda k: claude[k].get("prior") or 0) if claude else None
    tc = claude.get(top, {}) if top else {}
    decided = info.get("decided_by", "")
    return {
        "moves": 1,
        "top_played": int(top is not None and played == top),
        "top_overruled": int(bool(tc.get("vetoed") or tc.get("threat_verified"))),
        "claude_proposed": int(played in claude),
        "search_added": int(bool(cands) and played in cands and cands[played].get("source") == "engine"),
        "fail_low": int("fail-low" in note),
        "no_claude_value": int("only legal move" in note or decided.startswith(("mate in", "only ", "tablebase"))),
    }


def reliance(decisions: list[dict]) -> dict:
    tot = dict.fromkeys(RELIANCE_KEYS, 0)
    for d in decisions:
        c = classify_decision(d)
        if c:
            for k in RELIANCE_KEYS:
                tot[k] += c[k]
    return tot


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def load_games(runs_root: Path, prefix: str) -> list[dict]:
    games = []
    for rd in sorted(Path(runs_root).iterdir()):
        if not rd.is_dir() or prefix not in rd.name or not (rd / "meta.json").exists():
            continue
        meta = json.loads((rd / "meta.json").read_text())
        specs = (meta.get("white_spec", ""), meta.get("black_spec", ""))
        claude_spec = next(s for s in specs if not s.startswith("maia"))
        m = MAIA_RE.search(" ".join(specs))
        if not m:
            continue
        level = int(m.group(1))
        harness = claude_spec.startswith(("hybrid", "engine"))
        model = meta.get("model", "?")
        model = "haiku" if "haiku" in model else "sonnet" if "sonnet" in model else "opus" if "opus" in model else model
        config = f"{model}-{'harness' if harness else 'naive'}"
        cost: dict = {}
        moves: dict = {}
        secs: dict = {}
        rel: dict = {}
        for d in _jsonl(rd / "decisions.jsonl"):
            if "maia" in d.get("player", ""):
                continue
            gid = int(d["game"])  # analysis files store it as a string, others as int
            cost[gid] = cost.get(gid, 0.0) + (d.get("cost") or 0.0)
            moves[gid] = moves.get(gid, 0) + 1
            secs[gid] = secs.get(gid, 0.0) + (d.get("seconds") or 0.0)
            c = classify_decision(d)
            if c:
                r = rel.setdefault(gid, dict.fromkeys(RELIANCE_KEYS, 0))
                for k in RELIANCE_KEYS:
                    r[k] += c[k]
        acpl = {}
        for a in _jsonl(rd / "move_analysis.jsonl"):
            if "maia" in a.get("player", ""):
                continue
            acpl.setdefault(int(a["game"]), []).append(min(a.get("cpl") or 0, 1000))
        for g in _jsonl(rd / "games.jsonl"):
            if g.get("result") not in ("1-0", "0-1", "1/2-1/2"):
                continue  # aborted (infrastructure) games are excluded, never scored
            color = "white" if "maia" not in g["white"] else "black"
            res = g["result"]
            score = 0.5 if res == "1/2-1/2" else float((res == "1-0") == (color == "white"))
            gid = int(g["game"])
            cp = acpl.get(gid, [])
            games.append({"run": rd.name, "game": g["game"], "config": config, "model": model,
                          "harness": harness, "level": level, "color": color, "score": score,
                          "result": res, "termination": g.get("termination", ""),
                          "plies": g.get("plies"), "acpl": sum(cp) / len(cp) if cp else None,
                          "cost_usd": round(cost.get(gid, 0.0), 5),
                          "claude_moves": moves.get(gid, 0), "claude_seconds": round(secs.get(gid, 0.0), 1),
                          "reliance": rel.get(gid)})
    return games


# ── Elo ─────────────────────────────────────────────────────────────────────


def _loglik(r: float, games: list[dict]) -> float:
    ll = 0.0
    for g in games:
        p = 1.0 / (1.0 + 10 ** ((g["level"] - r) / 400))
        p = min(max(p, 1e-9), 1 - 1e-9)
        ll += g["score"] * math.log(p) + (1 - g["score"]) * math.log(1 - p)
    return ll


def elo_mle(games: list[dict], lo: int = 0, hi: int = 3200) -> float:
    """Grid + refinement MLE; returns a boundary value if all games were won/lost."""
    best = max(range(lo, hi + 1, 10), key=lambda r: _loglik(r, games))
    return max((best + d for d in range(-10, 11)), key=lambda r: _loglik(r, games))


def bootstrap_ci(games: list[dict], n: int = 1000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    vals = sorted(elo_mle([rng.choice(games) for _ in games]) for _ in range(n))
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


# ── tests ───────────────────────────────────────────────────────────────────


def permutation_test(a: list[dict], b: list[dict], n: int = 20000, seed: int = 0) -> tuple[float, float]:
    """Two-sided p for mean score difference, labels permuted within (level, colour) strata."""
    def diff(xa, xb):
        return sum(x["score"] for x in xa) / len(xa) - sum(x["score"] for x in xb) / len(xb)

    obs = diff(a, b)
    strata: dict = {}
    for g in a:
        strata.setdefault((g["level"], g["color"]), [[], []])[0].append(g)
    for g in b:
        strata.setdefault((g["level"], g["color"]), [[], []])[1].append(g)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(n):
        pa, pb = [], []
        for ga, gb in strata.values():
            pool = ga + gb
            rng.shuffle(pool)
            pa += pool[:len(ga)]
            pb += pool[len(ga):]
        if abs(diff(pa, pb)) >= abs(obs) - 1e-12:
            extreme += 1
    return obs, (extreme + 1) / (n + 1)


def lr_test(a: list[dict], b: list[dict]) -> tuple[float, float]:
    """Likelihood-ratio: separate Elos vs one shared Elo. Returns (statistic, p) with 1 df."""
    ll_sep = _loglik(elo_mle(a), a) + _loglik(elo_mle(b), b)
    ll_joint = _loglik(elo_mle(a + b), a + b)
    stat = max(0.0, 2 * (ll_sep - ll_joint))
    return stat, math.erfc(math.sqrt(stat / 2))


def mann_whitney(x: list[float], y: list[float]) -> tuple[float, float]:
    """U statistic for x and two-sided normal-approximation p (tie-corrected ranks)."""
    allv = sorted([(v, 0) for v in x] + [(v, 1) for v in y])
    ranks = [0.0] * len(allv)
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        i = j + 1
    n1, n2 = len(x), len(y)
    r1 = sum(r for r, (_, grp) in zip(ranks, allv) if grp == 0)
    u = r1 - n1 * (n1 + 1) / 2
    mu, sd = n1 * n2 / 2, math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    z = (u - mu) / sd if sd else 0.0
    return u, math.erfc(abs(z) / math.sqrt(2))


# ── report ──────────────────────────────────────────────────────────────────


def report(runs_root: str | Path, prefix: str, out_dir: str | Path) -> dict:
    games = load_games(Path(runs_root), prefix)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    configs = sorted({g["config"] for g in games})
    levels = sorted({g["level"] for g in games})
    by = lambda c, lv=None: [g for g in games if g["config"] == c and (lv is None or g["level"] == lv)]  # noqa: E731

    lines = [f"# Experiment `{prefix}` — Claude vs Maia", "",
             "Cell = score / games (W-D-L) from Claude's side.", "",
             "| config | " + " | ".join(f"maia-{lv}" for lv in levels)
             + " | total | score % | Elo (95% CI) | ACPL | cost $ | $/game | $/move | s/move |",
             "|---|" + "---|" * (len(levels) + 8)]
    summary: dict = {"configs": {}, "tests": {}}
    for c in configs:
        cells = []
        for lv in levels:
            gs = by(c, lv)
            if not gs:
                cells.append("–")
                continue
            w = sum(g["score"] == 1 for g in gs)
            d = sum(g["score"] == 0.5 for g in gs)
            lo = sum(g["score"] == 0 for g in gs)
            cells.append(f"{sum(g['score'] for g in gs):g}/{len(gs)} ({w}-{d}-{lo})")
        gs = by(c)
        tot = sum(g["score"] for g in gs)
        r = elo_mle(gs)
        ci = bootstrap_ci(gs)
        ac = [g["acpl"] for g in gs if g["acpl"] is not None]
        acpl = sum(ac) / len(ac) if ac else None
        usd = sum(g["cost_usd"] for g in gs)
        nmoves = sum(g["claude_moves"] for g in gs)
        spm = sum(g["claude_seconds"] for g in gs) / max(1, nmoves)
        acpl_s = f"{acpl:.0f}" if acpl is not None else "–"
        lines.append(f"| {c} | " + " | ".join(cells) +
                     f" | {tot:g}/{len(gs)} | {100 * tot / len(gs):.0f}% | {r:.0f} ({ci[0]:.0f}–{ci[1]:.0f}) | "
                     f"{acpl_s} | {usd:.2f} | {usd / len(gs):.3f} | {usd / max(1, nmoves):.4f} | {spm:.1f} |")
        summary["configs"][c] = {"games": len(gs), "score": tot, "elo": r, "elo_ci95": ci, "acpl": acpl,
                                 "cost_usd": usd, "usd_per_game": usd / len(gs),
                                 "usd_per_move": usd / max(1, nmoves), "claude_moves": nmoves,
                                 "seconds_per_move": spm}

    lines += ["", "## Harness vs no harness", "",
              "| model (levels both arms played) | Δ mean score | permutation p (stratified) | Elo naive → harness | LR χ² | LR p | ACPL naive → harness | Mann-Whitney p | $/game naive → harness | extra $ per extra point |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for model in sorted({g["model"] for g in games}):
        a, b = by(f"{model}-harness"), by(f"{model}-naive")
        # Paired comparison: only Maia levels BOTH arms played (an unbalanced ladder would
        # confound harness with opponent strength).
        common = {g["level"] for g in a} & {g["level"] for g in b}
        a = [g for g in a if g["level"] in common]
        b = [g for g in b if g["level"] in common]
        if not a or not b:
            continue
        d, p_perm = permutation_test(a, b)
        stat, p_lr = lr_test(a, b)
        xa = [g["acpl"] for g in a if g["acpl"] is not None]
        xb = [g["acpl"] for g in b if g["acpl"] is not None]
        _, p_mw = mann_whitney(xa, xb) if xa and xb else (None, float("nan"))
        def _sub(gs):
            usd = sum(g["cost_usd"] for g in gs)
            ac = [g["acpl"] for g in gs if g["acpl"] is not None]
            return {"elo": elo_mle(gs), "acpl": sum(ac) / len(ac) if ac else None, "score": sum(g["score"] for g in gs),
                    "games": len(gs), "usd_per_game": usd / len(gs)}
        sa, sb = _sub(a), _sub(b)
        fa = lambda v: f"{v:.0f}" if v is not None else "–"  # noqa: E731
        extra_pts = sa["score"] / sa["games"] - sb["score"] / sb["games"]
        extra_usd = sa["usd_per_game"] - sb["usd_per_game"]
        per_pt = f"{extra_usd / extra_pts:.2f}" if extra_pts > 0 else "–"
        lines.append(f"| {model} ({','.join(map(str, sorted(common)))}; {len(a)} vs {len(b)} games) | {d:+.2f} | {p_perm:.4f} | {sb['elo']:.0f} → {sa['elo']:.0f} | {stat:.1f} | "
                     f"{p_lr:.2g} | {fa(sb['acpl'])} → {fa(sa['acpl'])} | {p_mw:.2g} | "
                     f"{sb['usd_per_game']:.3f} → {sa['usd_per_game']:.3f} | {per_pt} |")
        summary["tests"][model] = {"levels": sorted(common), "games": [len(a), len(b)],
                                   "delta_score": d, "p_permutation": p_perm, "lr_stat": stat,
                                   "p_lr": p_lr, "p_mann_whitney_acpl": p_mw}
    rel_rows = []
    for c in configs:
        tot = dict.fromkeys(RELIANCE_KEYS, 0)
        for g in by(c):
            for k in RELIANCE_KEYS:
                tot[k] += (g.get("reliance") or {}).get(k, 0)
        if tot["moves"]:
            summary["configs"][c]["reliance"] = tot
            pc = lambda k: f"{100 * tot[k] / tot['moves']:.0f}%"  # noqa: E731
            rel_rows.append(f"| {c} | {tot['moves']} | {pc('top_played')} | {pc('top_overruled')} | "
                            f"{pc('claude_proposed')} | {pc('search_added')} | {pc('fail_low')} | {pc('no_claude_value')} |")
    if rel_rows:
        lines += ["", "## Reliance on the Python tactical search (harness moves)", "",
                  "| config | moves | Claude's #1 played | #1 overruled by search | played move proposed by Claude "
                  "| played move added by search | fail-low (all Claude ideas lose material) | decided without Claude's positional call |",
                  "|---|---|---|---|---|---|---|---|"] + rel_rows
    lines += ["", "Notes: Elo is a performance rating against Maia's *nominal* ratings (Lichess-ish "
              "scale, see wiki maia-calibration); boundary values (0 or 3200) mean every game was "
              "lost/won. Aborted games (LLM outages) are excluded. Games may end by resign "
              "adjudication (Stockfish referee, never inside a player's decision)."]
    (out / "crosstable.md").write_text("\n".join(lines) + "\n")
    cols = ["run", "game", "config", "model", "harness", "level", "color", "result", "score",
            "termination", "plies", "acpl", "cost_usd", "claude_moves", "claude_seconds"]
    with (out / "games.csv").open("w") as f:
        f.write(",".join(cols) + "\n")
        for g in games:
            f.write(",".join('"' + str(g[k]).replace('"', "'") + '"' if k == "termination" else str(g[k])
                             for k in cols) + "\n")
    (out / "stats.json").write_text(json.dumps(summary, indent=2))
    return summary
