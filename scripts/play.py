"""Play against the explainer models in the browser and read their idea after every move.

  uv run --extra ml python scripts/play.py                      # joint model (picks + explains), :8766
  uv run --extra ml python scripts/play.py --player composite   # encoder picks, student explains after
  uv run --extra ml python scripts/play.py --host 0.0.0.0       # reachable from a phone on the LAN

Players (see wiki/pages/explainer-hypotheses.md):
- joint:     ONE language model chooses among the encoder's candidate moves using verified facts
             (incl. each candidate's forcing-play outcome from a depth-4 material search) and then
             explains its decision; no engine in its input. Default model: joint_best (= E).
- composite: the encoder's top policy move is played, then the v1.1 student explains it from
             engine-free facts (encoder rollouts + exact concept detectors).
Stockfish only draws the eval bar and says what it would have played — analysis for you, never
an input to the model. The page is scripts/play.html.
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import chess
import chess.engine

ROOT = Path(__file__).resolve().parent.parent
HTML = Path(__file__).with_name("play.html")
LM = "mlx-community/Qwen3-1.7B-bf16"


class Game:
    def __init__(self, user_color: chess.Color = chess.WHITE):
        self.board = chess.Board()
        self.user = user_color
        self.moves: list[dict] = []
        self.thinking = False
        self.partial = ""
        self.lock = threading.Lock()

    def state(self) -> dict:
        b = self.board
        status = "playing"
        if b.is_game_over():
            status = b.result() + " · " + ("checkmate" if b.is_checkmate() else "draw")
        return {"fen": b.fen(), "turn": "white" if b.turn else "black",
                "user": "white" if self.user else "black", "moves": self.moves, "thinking": self.thinking,
                "partial": self.partial, "status": status,
                "legal": [m.uci() for m in b.legal_moves] if b.turn == self.user and not self.thinking else []}


class Players:
    """Holds the models; every call runs on the single model thread."""

    def __init__(self, kind: str, adapter: str | None, enc_dir: str, depth: int = 4):
        self.kind = kind
        if kind == "mock":  # UI testing without loading any model
            return
        if kind == "joint":
            from claude_chess.explainer.joint import JointPlayer
            self.joint = JointPlayer(LM, adapter, enc_dir, tactics_depth=depth)
        else:
            from claude_chess.explainer import pipeline as P
            self.explainer = P.Explainer(LM, adapter, enc_dir)

    def move(self, board: chess.Board, stream) -> dict:
        if self.kind == "mock":
            mv = sorted(board.legal_moves, key=lambda m: m.uci())[0]
            for i in range(1, 4):
                stream("Idea: (mock) " + "thinking " * i)
                time.sleep(0.3)
            return {"uci": mv.uci(), "idea": "(mock) first legal move", "plan": "test the interface",
                    "concepts": ["development"], "candidates": [{"san": board.san(mv), "prior": 0.5}],
                    "fallback": False, "raw": ""}
        if self.kind == "joint":
            out = self.joint.play(board, explain=True, stream=stream)
            return {"uci": out["uci"], "idea": out.get("idea", ""), "plan": out.get("plan", ""),
                    "concepts": out.get("concepts", []), "candidates": out["candidates"],
                    "fallback": bool(out.get("fallback")), "raw": out.get("raw", "")}
        # composite: play the encoder's instinct now, explain it afterwards
        from claude_chess.explainer import facts as F
        an = self.explainer.analyst.analyse(board.fen())
        mv = chess.Move.from_uci(an.best_line[0])
        pf = F.compute(board.fen(), an.best_line, an.alt_line, an.value, an.value_alt, self.explainer.scale)
        text = F.render(pf, board_diagram=False)
        raw, parsed = self.explainer.student.explain(text, pf.best_san[0], pf.alt_san[0])
        stream(raw)
        cands = [{"san": board.san(m), "prior": None} for m in self.explainer.analyst.top_moves(board, 6)]
        return {"uci": mv.uci(), "idea": parsed.get("idea", ""), "plan": parsed.get("plan", ""),
                "concepts": parsed.get("concepts", []), "candidates": cands, "fallback": False,
                "why": parsed.get("why_best", ""), "raw": raw}


class Analyst:
    """Display-only Stockfish: eval after each move and what it would have played."""

    def __init__(self, depth: int = 12):
        from claude_chess.match.baselines import open_stockfish
        self.eng = open_stockfish()
        self.depth = depth
        self.lock = threading.Lock()

    def look(self, board: chess.Board) -> dict:
        with self.lock:
            info = self.eng.analyse(board, chess.engine.Limit(depth=self.depth))
        sc = info["score"].white()
        pv = info.get("pv") or []
        return {"cp": sc.score(mate_score=10000), "best": board.san(pv[0]) if pv else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", choices=["joint", "composite", "mock"], default="joint")
    ap.add_argument("--adapter", default=None, help="LoRA adapter dir (default: best for the player)")
    ap.add_argument("--encoder", default=str(ROOT / "data/models/enc_v1"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-stockfish", action="store_true")
    ap.add_argument("--depth", type=int, default=4,
                    help="tactical-search depth for the joint player's verified facts (4 ≈ 10 s/move, 2 ≈ 1 s)")
    args = ap.parse_args()
    adapter = args.adapter or str(ROOT / ("data/models/joint_best" if args.player == "joint" else "data/models/lm_v1"))
    print(f"loading {args.player} player ({adapter}) ...", flush=True)
    # MLX streams are thread-local: load AND run the models on the single model thread
    holder: dict = {}
    ready = threading.Event()
    analyst = None if args.no_stockfish else Analyst()
    game = Game()
    jobs: queue.Queue = queue.Queue()

    def annotate(entry: dict, before: chess.Board, after: chess.Board) -> None:
        if analyst is None:
            return
        try:
            entry["sf"] = {"eval_after": analyst.look(after)["cp"], "best_before": analyst.look(before)["best"]}
        except chess.engine.EngineError:
            pass

    def model_turn(g: Game) -> None:
        with g.lock:
            if g.board.is_game_over() or g.board.turn == g.user:
                g.thinking = False
                return
            board = g.board.copy()

        def stream(text: str) -> None:
            g.partial = text

        t0 = time.time()
        out = holder["players"].move(board, stream)
        mv = chess.Move.from_uci(out["uci"])
        with g.lock:
            if g.board.fen() != board.fen():  # new game / undo while thinking
                g.thinking = False
                return
            san = g.board.san(mv)
            g.board.push(mv)
            entry = {"san": san, "uci": mv.uci(), "fen": g.board.fen(), "by": "model",
                     "thought": {**out, "seconds": round(time.time() - t0, 1)}}
            g.moves.append(entry)
            g.thinking = False
            g.partial = ""
        annotate(entry, board, chess.Board(entry["fen"]))

    def worker() -> None:
        holder["players"] = Players(args.player, adapter, args.encoder, args.depth)
        ready.set()
        while True:
            g = jobs.get()
            try:
                model_turn(g)
            except Exception as e:  # keep the server alive; surface the error in the UI
                g.thinking = False
                g.partial = f"[model error: {e}]"

    threading.Thread(target=worker, daemon=True).start()
    ready.wait()

    class _Kind:  # what the page shows as the player name
        kind = args.player
    players = _Kind()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code: int = 200) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            nonlocal game
            if self.path in ("/", "/index.html"):
                body = HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/state":
                self._json({**game.state(), "player": players.kind})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            nonlocal game
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/new":
                game = Game(chess.WHITE if req.get("color", "white") == "white" else chess.BLACK)
                if game.user == chess.BLACK:
                    game.thinking = True
                    jobs.put(game)
                self._json(game.state())
            elif self.path == "/api/move":
                g = game
                with g.lock:
                    try:
                        mv = chess.Move.from_uci(req.get("uci", ""))
                    except ValueError:
                        return self._json({"error": "bad move"}, 400)
                    if g.thinking or g.board.turn != g.user or mv not in g.board.legal_moves:
                        return self._json({"error": "illegal or not your turn"}, 400)
                    before = g.board.copy()
                    san = g.board.san(mv)
                    g.board.push(mv)
                    entry = {"san": san, "uci": mv.uci(), "fen": g.board.fen(), "by": "you"}
                    g.moves.append(entry)
                    g.thinking = not g.board.is_game_over()
                if g.thinking:
                    jobs.put(g)
                threading.Thread(target=annotate, args=(entry, before, chess.Board(entry["fen"])), daemon=True).start()
                self._json(g.state())
            elif self.path == "/api/undo":
                g = game
                with g.lock:
                    if g.thinking:
                        return self._json({"error": "wait for the model"}, 400)
                    while g.moves:  # back to the user's previous turn
                        g.board.pop()
                        last = g.moves.pop()
                        if last["by"] == "you":
                            break
                self._json(g.state())
            else:
                self._json({"error": "not found"}, 404)

    srv = ThreadingHTTPServer((args.host, args.port), H)
    print(f"ready: http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.port}  "
          f"(player: {args.player})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
