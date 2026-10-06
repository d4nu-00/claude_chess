"""Evaluate a joint (pick + explain) model: uv run --extra ml python scripts/explainer_joint_eval.py ADAPTER NAME [N]

1. Move accuracy vs Stockfish's best on N held-out cloud-eval positions and N held-out puzzles,
   under both prompts: SYS_EXPLAIN (idea/move/plan) and SYS_MOVE (move only). Baselines on the
   same positions: encoder top-1 (its instinct) and recall@6 (ceiling: best move among candidates).
2. Idea quality on the 100 teacher test positions: a blind Opus judge sees the engine analysis
   and the model's own move + idea -> {true, sound} per item (stored for paired tests).
Writes experiments/explainer/joint/<NAME>.json.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import chess
import numpy as np

from claude_chess.explainer import data as D
from claude_chess.explainer import joint as J
from claude_chess.llm import ClaudeCLIStream, extract_json

JUDGE = """You are a chess master grading a player's stated idea for the move they chose. You get the engine
analysis of the position (ground truth: the engine's best line and an alternative) and the player's move and
idea. Decide (1) "true": the idea says nothing false about the position, and (2) "sound": it is a real, relevant
reason for the player's move (a sound idea for a bad move is still "sound": false). Reply with one JSON object only."""


POS_FILE = Path("experiments/explainer/joint/positions.json")


def positions(n: int) -> dict[str, list[dict]]:
    """Fixed held-out positions for every variant (cached so evals don't load the 2.5 GB arrays)."""
    if POS_FILE.exists():
        cached = json.loads(POS_FILE.read_text())
        if all(len(v) >= n for v in cached.values()):
            return {k: v[:n] for k, v in cached.items()}
    data = D.load(("eval", "puzzle"))
    rng = np.random.default_rng(7)
    out = {}
    for kind, src in (("eval", 0), ("puzzle", 1)):
        idx = rng.choice(np.flatnonzero((data["split"] == 2) & (data["src"] == src)), size=n, replace=False)
        out[kind] = [{"fen": str(data["fen"][i]), "best": str(data["best_line"][i]).split()[0]} for i in idx]
    POS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POS_FILE.write_text(json.dumps(out))
    return out


def move_accuracy(player: J.JointPlayer, items: list[dict], log=print) -> dict:
    res = {"explain": 0, "move_only": 0, "instinct": 0, "recall6": 0, "fallback": 0, "n": len(items)}
    rows = []
    for n, it in enumerate(items):
        b = chess.Board(it["fen"])
        best = it["best"]
        cands = J.encoder_candidates(player.enc, b)
        res["instinct"] += cands[0].move.uci() == best
        res["recall6"] += any(c.move.uci() == best for c in cands)
        a = player.play(b, explain=True)
        m = player.play(b, explain=False)
        res["explain"] += a["uci"] == best
        res["move_only"] += m["uci"] == best
        res["fallback"] += bool(a.get("fallback"))
        rows.append({"fen": b.fen(), "best": best, "explain": a["uci"], "move_only": m["uci"],
                     "instinct": cands[0].move.uci(), "idea": a.get("idea", "")})
        if (n + 1) % 50 == 0:
            log(f"  {n + 1}/{len(items)}: explain {res['explain'] / (n + 1):.3f} move_only "
                f"{res['move_only'] / (n + 1):.3f} instinct {res['instinct'] / (n + 1):.3f}")
    out = {k: (v / res["n"] if k != "n" else v) for k, v in res.items()}
    out["rows"] = rows
    return out


def judge_ideas(recs: list[dict], plays: list[dict]) -> dict:
    llm = ClaudeCLIStream(model="claude-opus-5-5", effort="medium", timeout=600)

    def one(t):
        import time as _time

        from claude_chess.llm import LLMUnavailable
        sys.path.insert(0, str(Path(__file__).parent))
        from explainer_collect import seconds_until_reset

        rec, p = t
        prompt = (f"{rec['facts']}\n\nThe player chose {p['san']} and said: \"{p.get('idea', '')}\"\n\n"
                  'Return JSON: {"true": true/false, "sound": true/false, "reason": "<=20 words"}')
        while True:  # the label collector may be using the same plan: wait out session limits
            try:
                resp = llm.complete(JUDGE, prompt, max_tokens=200)
                break
            except LLMUnavailable as e:
                _time.sleep(seconds_until_reset(str(e)))
        try:
            o = extract_json(resp.text)
        except ValueError:
            o = {}
        return {"true": bool(o.get("true")), "sound": bool(o.get("sound")), "reason": o.get("reason", ""),
                "cost": resp.cost_usd}

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, zip(recs, plays)))
    best = [p["uci"] == r["best_line"].split()[0] for r, p in zip(recs, plays)]
    n = len(res)
    return {"n": n, "true": sum(r["true"] for r in res) / n, "sound": sum(r["sound"] for r in res) / n,
            "picked_best": sum(best) / n,
            "sound_when_best": sum(r["sound"] for r, b in zip(res, best) if b) / max(1, sum(best)),
            "cost_usd": round(sum(r["cost"] for r in res), 3), "items": res}


def main(adapter: str, name: str, n: int = 250, depth: int = 2) -> None:
    out_path = Path("experiments/explainer/joint") / f"{name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pos = positions(n)
    player = J.JointPlayer("mlx-community/Qwen3-1.7B-bf16", adapter, tactics_depth=depth)
    out: dict = {"adapter": adapter}
    for kind in ("eval", "puzzle"):
        print(f"[{name}] move accuracy on {kind}", flush=True)
        out[kind] = move_accuracy(player, pos[kind], log=lambda m: print(m, flush=True))
    recs = [json.loads(ln) for ln in Path("datasets/explainer_v1/teacher.jsonl").read_text().splitlines()]
    s = json.loads(Path("experiments/explainer/eval_lm_samples.json").read_text())
    by_fen = {r["fen"]: r for r in recs}
    test = [by_fen[x["fen"]] for x in s]  # the same 100 positions the v1.1 explainer was judged on
    plays = []
    for r in test:
        p = player.play(chess.Board(r["fen"]), explain=True)
        plays.append(p)
    del player
    out_path.write_text(json.dumps(out, indent=1))
    print(f"[{name}] judging {len(test)} ideas", flush=True)
    out["ideas"] = judge_ideas(test, plays)
    out["ideas"]["plays"] = [{"san": p["san"], "idea": p.get("idea", ""), "plan": p.get("plan", "")} for p in plays]
    out_path.write_text(json.dumps(out, indent=1))
    summary = {k: {kk: round(vv, 3) for kk, vv in v.items() if isinstance(vv, float)} for k, v in out.items()
               if isinstance(v, dict)}
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], *(int(x) for x in a[2:]))
