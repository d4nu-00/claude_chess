"""Live "Lichess broadcast"-style viewer for the raw-player games.

  uv run python scripts/broadcast.py                 # serve http://0.0.0.0:8765 (open on the LAN IP from a phone)
  uv run python scripts/broadcast.py --export f.html # one self-contained snapshot page (no server needed)

Reads runs/*raw-*/decisions.jsonl (every move is appended as it is played), merges each game across
its original + resumed runs, and evaluates every position with Stockfish (depth 12, cached in
runs/_broadcast_evals.json). Stockfish is used for display only. The page is scripts/broadcast.html.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import chess
import chess.engine

from claude_chess.match.baselines import open_stockfish

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
HTML = Path(__file__).with_name("broadcast.html")
CACHE_PATH = RUNS / "_broadcast_evals.json"
DEPTH = 12
STALE_S = 900  # no new move for this long and no live process -> "stopped"

_cache: dict[str, int] = {}
_cache_lock = threading.Lock()
_seen: dict[tuple, float] = {}  # (run, game, ply) -> time this server first saw the row (rows without ts)
_seen_lock = threading.Lock()


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:  # half-written last line
            pass
    return out


def _live_labels() -> list[str]:
    cmds = subprocess.run(["ps", "-eo", "command"], capture_output=True, text=True).stdout
    return [m.group(1) for m in re.finditer(r"claude-chess match .*?--label (\S+)", cmds)]


def _run_dirs() -> list[str]:
    dirs = set(glob.glob(str(RUNS / "2*raw-*")))
    for d in glob.glob(str(RUNS / "2*")):  # harness runs carry arbitrary labels: look at the player specs
        try:
            meta = json.loads((Path(d) / "meta.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if "hybrid-" in f"{meta.get('white_spec', '')}|{meta.get('black_spec', '')}" and "opus" in meta.get("model", ""):
            dirs.add(d)
    return sorted(d for d in dirs if os.path.isdir(d))


def _hybrid_reasoning(r: dict) -> str:
    """Harness players have no free-text rationale: show the candidate table the search produced."""
    s = (r.get("search") or {}).get("candidates") or {}
    lines = [f"Chose {r['san']}  ({r.get('calls', 0)} Claude calls)", ""]
    for c in r.get("candidates") or []:
        d = s.get(c["san"], {})
        flag = " VETOED" if d.get("vetoed") else ""
        lines.append(f"{'→' if c['san'] == r['san'] else ' '} {c['san']:<7} prior {c.get('prior', 0):.2f}  "
                     f"tactical {d.get('tactical_cp', '?')}  positional {d.get('positional_cp', '?')}  "
                     f"final {d.get('final_cp', c.get('score_cp', '?'))}{flag}")
        if c.get("reason"):
            lines.append(f"     {c['reason']}")
    return "\n".join(lines)


def build_state() -> dict:
    now = time.time()
    labels = _live_labels()
    games: dict[tuple, dict] = {}
    for rd in sorted(d for d in _run_dirs() if os.path.isdir(d)):
        rd = Path(rd)
        rows = _load(rd / "decisions.jsonl")
        cond = next((m.group(1) or m.group(2) for r in rows if (m := re.match(r"(?:raw-(\w+?)|(hybrid-\w+?))\(", r["player"]))), None)
        if cond is None:
            continue
        label = rd.name[16:]
        live_run = label in labels
        mtime = (rd / "decisions.jsonl").stat().st_mtime
        records = {int(g["game"]): g for g in _load(rd / "games.jsonl")}
        last_row_of_file = rows[-1] if rows else None
        for r in rows:
            key0 = rd.name if cond.startswith("hybrid") else cond  # harness games: one entry per run, not merged
            g = games.setdefault((key0, int(r["game"])), {"cond": cond, "game": int(r["game"]), "moves": {}, "run": rd.name})
            ts = r.get("ts")
            if ts is None:
                key = (rd.name, int(r["game"]), r["ply"])
                with _seen_lock:
                    # legacy row: the file's newest row was written at its mtime; older ones are unknown
                    ts = _seen.setdefault(key, mtime if r is last_row_of_file else 0.0)
            g["moves"][r["ply"]] = {**r, "_ts": ts}
            g["run"], g["live_run"], g["record"] = rd.name, live_run, records.get(int(r["game"]))
    # A live run that has not logged a move yet (e.g. a just-restarted resume) still owns its games.
    for rd in sorted(d for d in _run_dirs() if os.path.isdir(d)):
        rd = Path(rd)
        if rd.name[16:] not in labels or not (rd / "meta.json").exists():
            continue
        meta = json.loads((rd / "meta.json").read_text())
        m = re.match(r"(?:raw-(\w+)|(hybrid-\w+))", meta.get("white_spec", ""))
        m = m and re.match(r"(.*)", m.group(1) or m.group(2))
        argv = meta.get("argv") or []
        only = [int(x) for x in argv[argv.index("--only-games") + 1].split(",")] if "--only-games" in argv else None
        for gi in only if only is not None else range(meta.get("games", 0)):
            if m and (m.group(1), gi) in games and not any(r["game"] == gi for r in _load(rd / "decisions.jsonl")):
                games[(m.group(1), gi)].update(live_run=True, record=None,
                                               pending_since=(rd / "meta.json").stat().st_mtime)
    out = []
    for (key0, gi), g in sorted(games.items()):
        cond = g["cond"]
        first = min(g["moves"]) if g["moves"] else 1
        # games that start from an opening book log only the moves after it: begin at the first logged position
        board, moves, opus_white = chess.Board(g["moves"][first]["fen"]) if first > 1 else chess.Board(), [], None
        start_fen = board.fen()
        for ply in sorted(g["moves"]):
            r = g["moves"][ply]
            if ply != first + len(moves):
                break
            info = r.get("search") or {}
            is_opus = r["player"].startswith(("raw", "hybrid"))
            if is_opus:
                opus_white = board.turn == chess.WHITE
            board.push(chess.Move.from_uci(r["uci"]))
            moves.append({"ply": ply, "san": r["san"], "uci": r["uci"], "fen": board.fen(), "opus": is_opus,
                          "seconds": r["seconds"], "cost": r["cost"], "tokens": info.get("thinking_tokens", 0),
                          "reasoning": _hybrid_reasoning(r) if r["player"].startswith("hybrid") else info.get("reasoning", ""), "ts": r["_ts"]})
        rec = g.get("record")
        if rec and rec["result"] != "*":
            status = "finished"
        elif g["live_run"] and not (rec and rec["result"] == "*"):
            status = "live"
        else:
            status = "stopped"
        last_ts = max((m["ts"] for m in moves), default=0)
        if g.get("pending_since"):  # restarted run still on its first move: the clock starts at launch
            last_ts = max(last_ts, g["pending_since"])
        harness = cond.startswith("hybrid")
        opus_name = "Claude Opus 5.5 · harness" if harness else f"Claude Opus 5.5 · {cond} board"
        maia = "Maia-3 23M · 2400" if harness else "Maia-3 79M · 2400"
        white, black = (maia, opus_name) if opus_white is False else (opus_name, maia)
        out.append({"id": f"{key0}-g{gi}", "run": g["run"], "series": g["run"][16:], "start_fen": start_fen, "cond": cond, "label": "harness" if harness else f"{cond} board", "game": gi, "status": status,
                    "result": rec["result"] if rec else "*", "termination": (rec or {}).get("termination", ""),
                    "white": white, "black": black, "opus_white": opus_white, "last_ts": last_ts,
                    "to_move": "white" if board.turn == chess.WHITE else "black", "moves": moves,
                    "cost": round(sum(m["cost"] for m in moves), 2)})
    with _cache_lock:
        cache = dict(_cache)
    for g in out:
        start = g["start_fen"]
        g["evals"] = [cache.get(start)] + [cache.get(m["fen"]) for m in g["moves"]]  # White view, cp
    order = {"live": 0, "stopped": 1, "finished": 2}
    out.sort(key=lambda g: (order[g["status"]], g["id"]))
    return {"server_time": now, "games": out}


def eval_worker(stop: threading.Event) -> None:
    """Evaluate positions newest-first so a live game's current eval appears quickly."""
    if CACHE_PATH.exists():
        try:
            _cache.update(json.loads(CACHE_PATH.read_text()))
        except json.JSONDecodeError:
            pass
    sf, dirty = open_stockfish(), 0
    sf.configure({"Threads": 2, "Hash": 128})
    lim = chess.engine.Limit(depth=DEPTH)
    try:
        while not stop.is_set():
            state = build_state()
            todo = []
            for g in state["games"]:
                fens = [g["start_fen"]] + [m["fen"] for m in g["moves"]]
                todo += [f for f in reversed(fens) if f not in _cache]
            if not todo:
                if dirty:
                    CACHE_PATH.write_text(json.dumps(_cache))
                    dirty = 0
                stop.wait(2)
                continue
            for fen in todo[:8]:
                b = chess.Board(fen)
                if b.is_checkmate():
                    cp = -10000 if b.turn == chess.WHITE else 10000
                else:
                    cp = sf.analyse(b, lim)["score"].white().score(mate_score=10000)
                with _cache_lock:
                    _cache[fen] = cp
                dirty += 1
            if dirty >= 20:
                CACHE_PATH.write_text(json.dumps(_cache))
                dirty = 0
    finally:
        sf.quit()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/state"):
            body, ctype = json.dumps(build_state()).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
            body, ctype = HTML.read_bytes(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def export(path: str) -> None:
    """Evaluate every position once, then write a self-contained HTML snapshot."""
    if CACHE_PATH.exists():
        _cache.update(json.loads(CACHE_PATH.read_text()))
    state = build_state()
    sf, lim = open_stockfish(), chess.engine.Limit(depth=DEPTH)
    for g in state["games"]:
        for fen in [g["start_fen"]] + [m["fen"] for m in g["moves"]]:
            if fen not in _cache:
                b = chess.Board(fen)
                _cache[fen] = (-10000 if b.turn == chess.WHITE else 10000) if b.is_checkmate() else \
                    sf.analyse(b, lim)["score"].white().score(mate_score=10000)
    sf.quit()
    CACHE_PATH.write_text(json.dumps(_cache))
    state = build_state()
    html = HTML.read_text().replace("/*__SNAPSHOT__*/null", json.dumps(state))
    Path(path).write_text(html)
    print(f"{path}: {len(state['games'])} games, {len(html) // 1024} KB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--bind", default=None,
                    help="bind address (default: the Wi-Fi/en0 IP if found, else all interfaces — "
                         "binding to a specific IP avoids reply packets going out the wrong NIC "
                         "when the Mac has more than one active interface on the same LAN)")
    ap.add_argument("--export", metavar="FILE", help="write a static snapshot page and exit")
    a = ap.parse_args()
    if a.export:
        export(a.export)
    else:
        stop = threading.Event()
        threading.Thread(target=eval_worker, args=(stop,), daemon=True).start()
        wifi_ip = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True).stdout.strip()
        bind = a.bind or wifi_ip or "0.0.0.0"
        print(f"broadcast bound to {bind}:{a.port}  (open http://{wifi_ip or bind}:{a.port} on the phone)")
        try:
            ThreadingHTTPServer((bind, a.port), Handler).serve_forever()
        finally:
            stop.set()
