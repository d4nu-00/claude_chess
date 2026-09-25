"""Export every Claude player's reasoning into a training dataset for a move-explainer model.

Reads run directories (decisions.jsonl, traces.jsonl, move_analysis.jsonl, games.pgn,
games.jsonl) and writes, under `out_dir`:

  positions.jsonl   one row per Claude decision — the canonical, lossless-ish record:
                    position, history, every agent's parsed output, the engine's verified
                    facts, Stockfish labels, game outcome, split.
  calls.jsonl.gz    every raw LLM call (role, prompt, response) keyed to its position — lets
                    you re-template later or train one model per role.
  sft.jsonl         chat-format supervised examples: position -> reasoning -> move.
  preferences.jsonl DPO-style pairs: explanation of a sound move (chosen) vs Claude's own
                    case for a move the engine PROVED bad (rejected), with the refutation.
  README.md         dataset card: schema, splits, counts, caveats.

Design notes (see wiki/pages/reasoning-dataset.md):
- Splits are by GAME (hash of run+game), never by position: positions from one game are
  near-duplicates and would leak between train and test.
- Targets put analysis BEFORE the move (threats -> candidates -> refutations -> decision),
  so a causal transformer learns to reason first, answer last.
- Every claim is tagged by provenance: `[verified]` = checked on a real board by the search
  (material outcome, refutation line, mate), plain text = Claude's unverified opinion.
- Quality labels (Stockfish cp loss, classification, game result) are stored, never used to
  rewrite text, so consumers can filter (e.g. drop cp_loss >= 100) and re-weight.
- Moves are SAN; positions are FEN; plain ASCII only — tokenizer friendly.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable

import chess
import chess.pgn

from claude_chess.llm import extract_json

SYSTEM_PROMPT = ("You are a chess analyst. Given a position, identify the threats, weigh the "
                 "candidate moves with concrete reasons, and name the best move.")


# ── loading ──────────────────────────────────────────────────────────────────


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _split(run_id: str, game: int) -> str:
    h = int(hashlib.sha1(f"{run_id}:{game}".encode()).hexdigest(), 16) % 10
    return "test" if h == 0 else "val" if h == 1 else "train"


def _games(run_dir: Path) -> dict[int, chess.pgn.Game]:
    out: dict[int, chess.pgn.Game] = {}
    pgn = run_dir / "games.pgn"
    if not pgn.exists():
        return out
    f = io.StringIO(pgn.read_text())
    while (g := chess.pgn.read_game(f)) is not None:
        try:
            out[int(g.headers.get("Round", "0"))] = g
        except ValueError:
            continue
    return out


def _parse(text: str) -> dict:
    try:
        return extract_json(text)
    except Exception:
        return {}


def _is_claude(player: str) -> bool:
    return any(k in player for k in ("naive", "engine", "hybrid"))


def _result_for(result: str | None, color: str) -> float | None:
    if result == "1/2-1/2":
        return 0.5
    if result in ("1-0", "0-1"):
        return 1.0 if (result == "1-0") == (color == "white") else 0.0
    return None


# ── building position rows ───────────────────────────────────────────────────


def _agents(traces: list[dict], decision: dict) -> dict[str, Any]:
    """Parsed output of every agent call for one decision."""
    agents: dict[str, Any] = {}
    for t in traces:
        role, data = t["role"], _parse(t.get("response", ""))
        if role == "proposer" and "proposer" not in agents:  # first = root proposal
            agents["proposer"] = {k: data.get(k) for k in ("thinking", "candidates", "board",
                                                           "threats", "hanging") if k in data}
        elif role == "proposer":
            agents.setdefault("opponent_proposer", []).append({"fen": t.get("fen"), **data})
        elif role in ("positional", "evaluator"):
            agents.setdefault(role, []).append({"fen": t.get("fen"), **data})
        else:
            agents[role] = data
    if "proposer" not in agents and "naive" not in agents and decision.get("candidates"):
        # Older runs without traces: fall back to the candidates logged in decisions.jsonl.
        agents["proposer"] = {"candidates": [{"move": c["san"], "reason": c.get("reason", ""),
                                              "prior": c.get("prior")} for c in decision["candidates"]]}
    return agents


def build_rows(run_dir: Path) -> tuple[list[dict], list[dict]]:
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text()) if (run_dir / "meta.json").exists() else {}
    run_id = run_dir.name
    games = _games(run_dir)
    results = {int(g["game"]): g.get("result") for g in _jsonl(run_dir / "games.jsonl")}
    # move_analysis.jsonl stores "game" as a string, decisions/traces as an int: normalise.
    analysis = {(int(a["game"]), a["ply"]): a for a in _jsonl(run_dir / "move_analysis.jsonl")}
    traces: dict[tuple, list[dict]] = {}
    for t in _jsonl(run_dir / "traces.jsonl"):
        traces.setdefault((int(t["game"]), t["ply"]), []).append(t)
    rows, calls = [], []
    for d in _jsonl(run_dir / "decisions.jsonl"):
        if not _is_claude(d["player"]) or not d.get("san"):
            continue
        key = (int(d["game"]), d["ply"])
        tr = sorted(traces.get(key, []), key=lambda t: t.get("call", 0))
        g = games.get(d["game"])
        history = []
        if g is not None:
            history = [m.uci() for m in list(g.mainline_moves())[: d["ply"] - 1]]
        a = analysis.get(key, {})
        rid = f"{run_id}:{d['game']}:{d['ply']}"
        board = chess.Board(d["fen"])
        row = {
            "id": rid, "run_id": run_id, "game": d["game"], "ply": d["ply"],
            "split": _split(run_id, d["game"]),
            "fen": d["fen"], "side": d["color"], "history_uci": history,
            "legal_moves_san": sorted(board.san(m) for m in board.legal_moves),
            "player": d["player"], "model": meta.get("model"),
            "pipeline": {k: meta.get(k) for k in ("depth", "tac_depth", "tac_margin", "search",
                                                  "threat_agent", "thinking", "board_read")
                         if k in meta},
            "board_read": d.get("board_read"),
            "agents": _agents(tr, d),
            "engine": d.get("search") or {},
            "decision": {"san": d["san"], "uci": d.get("uci"), "note": d.get("note", ""),
                         "llm_calls": d.get("calls"), "cost_usd": d.get("cost"),
                         "forced_random": d.get("forced_random", False),
                         "illegal_attempts": d.get("illegal_attempts", [])},
            "labels": {"sf_eval_before": a.get("eval_before"), "sf_eval_after": a.get("eval_after"),
                       "sf_best_move": a.get("best_move"), "cp_loss": a.get("cpl"),
                       "game_result": _result_for(results.get(d["game"]), d["color"])},
        }
        rows.append(row)
        for t in tr:
            calls.append({"position_id": rid, **{k: t.get(k) for k in (
                "call", "role", "model", "fen", "prompt", "response", "cost_usd", "seconds",
                "input_tokens", "output_tokens")}})
    return rows, calls


# ── rendering training text ──────────────────────────────────────────────────


def _mover_cp(v: int | None) -> str:
    if v is None:
        return "?"
    if v >= 9000:
        return "mates"
    if v <= -9000:
        return "gets mated"
    return "material level" if v == 0 else f"{'wins' if v > 0 else 'loses'} {abs(v) / 100:.1f} pawns"


def user_text(row: dict, context: str | None = None) -> str:
    b = chess.Board(row["fen"])
    hist = ""
    if row["history_uci"]:
        root = chess.Board()
        moves = [chess.Move.from_uci(u) for u in row["history_uci"]]
        try:  # keep inputs short: last 6 full moves only
            for m in moves[:-12]:
                root.push(m)
            hist = ("... " if len(moves) > 12 else "") + root.variation_san(moves[-12:])
        except (ValueError, AssertionError):
            hist = ""
    side = "White" if b.turn == chess.WHITE else "Black"
    parts = [f"FEN: {row['fen']}", f"Side to move: {side}"]
    if hist:
        parts.append(f"Recent moves: {hist}")
    if context:
        parts.append(context)
    parts.append("Analyse the position and choose the best move.")
    return "\n".join(parts)


def assistant_text(row: dict) -> str | None:
    """Reasoning-first target: threats -> candidates (reasons + verified verdicts) -> move."""
    ag, eng = row["agents"], row["engine"].get("candidates", {}) if row["engine"] else {}
    lines: list[str] = []
    prop = ag.get("proposer") or {}
    naive = ag.get("naive") or {}
    threats = prop.get("threats")
    br = row.get("board_read") or {}
    real = br.get("threats_real")
    if real is not None:  # verified threats beat Claude's claimed ones
        lines.append("Threats [verified]: " + (", ".join(real) if real else "none"))
    elif threats:
        lines.append("Threats: " + ", ".join(map(str, threats)))
    thinking = prop.get("thinking") or naive.get("thinking")
    if thinking:
        lines.append(f"Assessment: {thinking}")
    cands = prop.get("candidates") or []
    if cands:
        lines.append("Candidates:")
    for c in cands:
        if not isinstance(c, dict):
            continue
        san = str(c.get("move", ""))
        e = eng.get(san, {})
        reason = str(c.get("reason", "")).strip()
        verdict = ""
        if e.get("threat_verified"):
            verdict = f" [verified: rejected, {e['threat_reply']} {_mover_cp(e.get('threat_cp'))}]"
        elif e.get("vetoed"):
            rep = f" after {e['engine_reply']}" if e.get("engine_reply") else ""
            verdict = f" [verified: rejected{rep}, {_mover_cp(e.get('tactical_cp'))}]"
        elif "tactical_cp" in e:
            verdict = f" [verified: {_mover_cp(e.get('tactical_cp'))}]"
        lines.append(f"- {san}: {reason}{verdict}")
    for san, e in eng.items():  # tactics the search found that Claude didn't propose
        if e.get("source") == "engine":
            lines.append(f"- {san}: tactic found by search [verified: {_mover_cp(e.get('tactical_cp'))}]")
    decided = row["engine"].get("decided_by") if row["engine"] else None
    if decided and decided not in ("hybrid", "alpha-beta"):
        lines.append(f"Decision: {decided}.")
    move = row["decision"]["san"]
    if not lines:
        return None
    lines.append(f"Best move: {move}")
    return "\n".join(lines)


def sft_example(row: dict, with_context: bool = False) -> dict | None:
    target = assistant_text(row)
    if target is None:
        return None
    ctx = None
    if with_context:
        from claude_chess.context import build_context, render_context
        ctx = render_context(build_context(chess.Board(row["fen"]), include_legal_moves=False),
                             include_legal_moves=False)
    lab = row["labels"]
    return {"id": row["id"], "split": row["split"],
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": user_text(row, ctx)},
                         {"role": "assistant", "content": target}],
            "quality": {"cp_loss": lab["cp_loss"], "game_result": lab["game_result"],
                        "forced_random": row["decision"]["forced_random"]}}


def preference_pairs(row: dict) -> list[dict]:
    """(chosen = the played move's reasoning, rejected = a candidate the engine refuted)."""
    eng = row["engine"].get("candidates", {}) if row["engine"] else {}
    cands = {str(c.get("move")): c for c in (row["agents"].get("proposer") or {}).get("candidates") or []
             if isinstance(c, dict)}
    played = row["decision"]["san"]
    cp = row["labels"]["cp_loss"]
    if played not in cands or (cp is not None and cp >= 100):
        return []
    out = []
    for san, e in eng.items():
        if san == played or not (e.get("vetoed") or e.get("threat_verified")) or san not in cands:
            continue
        refut = e.get("threat_reply") if e.get("threat_verified") else e.get("engine_reply")
        score = e.get("threat_cp") if e.get("threat_verified") else e.get("tactical_cp")
        out.append({
            "id": f"{row['id']}:{san}", "split": row["split"],
            "prompt": [{"role": "system", "content": SYSTEM_PROMPT},
                       {"role": "user", "content": user_text(row)}],
            "chosen": f"{played}: {cands[played].get('reason', '')}\nBest move: {played}",
            "rejected": f"{san}: {cands[san].get('reason', '')}\nBest move: {san}",
            "refutation": {"reply": refut, "material": score},
        })
    return out


# ── export ───────────────────────────────────────────────────────────────────


def export(run_dirs: Iterable[Path], out_dir: Path, with_context: bool = False) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, calls = [], []
    for rd in run_dirs:
        r, c = build_rows(Path(rd))
        rows += r
        calls += c
    sft = [e for e in (sft_example(r, with_context) for r in rows) if e]
    prefs = [p for r in rows for p in preference_pairs(r)]
    with (out_dir / "positions.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with gzip.open(out_dir / "calls.jsonl.gz", "wt") as f:
        for c in calls:
            f.write(json.dumps(c) + "\n")
    with (out_dir / "sft.jsonl").open("w") as f:
        for e in sft:
            f.write(json.dumps(e) + "\n")
    with (out_dir / "preferences.jsonl").open("w") as f:
        for p in prefs:
            f.write(json.dumps(p) + "\n")
    stats = {
        "positions": len(rows), "calls": len(calls), "sft": len(sft), "preference_pairs": len(prefs),
        "runs": sorted({r["run_id"] for r in rows}),
        "splits": {s: sum(1 for r in rows if r["split"] == s) for s in ("train", "val", "test")},
        "positions_with_full_traces": len({c["position_id"] for c in calls}),
        "sft_cp_loss_lt_100": sum(1 for e in sft if (e["quality"]["cp_loss"] or 0) < 100),
    }
    (out_dir / "README.md").write_text(_card(stats))
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2))
    return stats


def _card(stats: dict) -> str:
    return f"""# Claude chess reasoning dataset

Generated by `claude-chess dataset` from match runs (Claude players only). Positions are from
games against Maia / other engines; reasoning comes from Claude agents (proposer, threat
agent, positional evaluator, compare, naive) and is annotated with facts VERIFIED on a real
board by the harness's material search, plus Stockfish labels from post-game analysis.

## Counts
```
{json.dumps(stats, indent=2)}
```

## Files
- `positions.jsonl` — one row per decision. Keys: id, run_id, game, ply, split, fen, side,
  history_uci, legal_moves_san, player, model, pipeline, board_read (Claude's reported
  pieces/threats scored vs truth), agents (parsed output per agent role), engine
  (per-candidate verified facts: tactical_cp, engine_reply, vetoed, threat_reply,
  threat_verified, positional_cp, ab_value, decided_by), decision, labels (sf_eval_before/
  after — mover's view, sf_best_move, cp_loss, game_result for the mover).
- `calls.jsonl.gz` — raw LLM calls (position_id, role, prompt, response, tokens, cost).
- `sft.jsonl` — `messages` = system / user (FEN, side, last 6 moves) / assistant
  (Threats -> Assessment -> Candidates with [verified] verdicts -> Best move) + `quality`.
- `preferences.jsonl` — prompt / chosen / rejected / refutation (DPO-style), only where the
  played move had cp_loss < 100 and the rejected move was refuted by the search.

## Splits
By game (sha1(run_id:game) mod 10: 0 test, 1 val, else train) — never split one game
across train and test.

## Caveats
- Claude's reasons are opinions; only `[verified]` annotations are ground truth.
- Filter on `quality.cp_loss` (e.g. < 100) before training a "best move" explainer; keep
  poor moves only if you train the model to critique.
- Opponent is Maia-1100, so positions skew toward club-level games.
"""
