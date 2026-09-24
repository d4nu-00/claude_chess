"""Play games / matches between Players, logging everything incrementally.

Output layout (runs/<timestamp>_<label>/):
  meta.json        match configuration
  games.pgn        one PGN per finished game (appended)
  games.jsonl      one summary row per finished game (appended)
  decisions.jsonl  one row per non-book move, appended as it is played
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import chess
import chess.engine
import chess.pgn

from claude_chess.llm import LLMUnavailable
from claude_chess.match.baselines import open_stockfish
from claude_chess.match.openings import OPENINGS
from claude_chess.types import MoveDecision, Player

ADJUDICATION_CP = 300
ADJUDICATION_LIMIT = chess.engine.Limit(depth=16, time=1.0)
RESIGN_LIMIT = chess.engine.Limit(depth=12, time=0.2)  # per-ply referee check (resign_cp)

_print_lock = threading.Lock()


def _say(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


@dataclass
class GameRecord:
    white: str
    black: str
    result: str  # "1-0" | "0-1" | "1/2-1/2"
    termination: str  # checkmate/stalemate/insufficient/repetition/fifty/forfeit/adjudication (+detail)
    game: chess.pgn.Game
    decisions: list[dict[str, Any]] = field(default_factory=list)
    opening_name: str | None = None
    book_plies: int = 0
    game_id: int = 0

    @property
    def pgn(self) -> str:
        return str(self.game)

    def summary(self) -> dict[str, Any]:
        return {"game": self.game_id, "white": self.white, "black": self.black,
                "result": self.result, "termination": self.termination,
                "opening": self.opening_name, "book_plies": self.book_plies,
                "plies": len(self.decisions) + self.book_plies}


def decision_row(board: chess.Board, player: str, d: MoveDecision, game_id: int) -> dict[str, Any]:
    """JSON-serialisable log row; `board` is the position BEFORE the move."""
    return {
        "game": game_id, "ply": board.ply() + 1, "fen": board.fen(), "player": player,
        "color": "white" if board.turn == chess.WHITE else "black",
        "san": d.san, "uci": d.move.uci() if d.move else None,
        "candidates": [asdict(c) for c in d.candidates],
        "illegal_attempts": list(d.illegal_attempts), "calls": d.llm_calls,
        "cost": d.cost_usd, "seconds": round(d.seconds, 3),
        "forfeit_reason": d.forfeit_reason, "note": d.note,
        "forced_random": getattr(d, "forced_random", False),
        "board_read": getattr(d, "board_read", None),
        "search": getattr(d, "search_info", None) or None,
    }


def _own_eval(d: MoveDecision) -> float | None:
    """The mover's own score for the move it played (mover's view), if it has one."""
    for c in d.candidates:
        if c.san == d.san and c.score_cp is not None:
            return c.score_cp
    return None


def _termination_from_outcome(outcome: chess.Outcome) -> str:
    t = outcome.termination
    T = chess.Termination
    if t == T.CHECKMATE:
        return "checkmate"
    if t == T.STALEMATE:
        return "stalemate"
    if t == T.INSUFFICIENT_MATERIAL:
        return "insufficient"
    if t in (T.THREEFOLD_REPETITION, T.FIVEFOLD_REPETITION):
        return "repetition"
    if t in (T.FIFTY_MOVES, T.SEVENTYFIVE_MOVES):
        return "fifty"
    return t.name.lower()


def adjudicate(board: chess.Board, stockfish_path: str | None = None) -> tuple[str, str]:
    """Stockfish eval of the final position: |eval| >= 300cp -> win for that side, else draw."""
    try:
        eng = open_stockfish(stockfish_path)
    except Exception as e:  # no Stockfish -> draw
        return "1/2-1/2", f"adjudication (no stockfish: {e}; draw)"
    try:
        info = eng.analyse(board, ADJUDICATION_LIMIT)
        cp = info["score"].white().score(mate_score=10000)
    finally:
        eng.quit()
    if cp >= ADJUDICATION_CP:
        res = "1-0"
    elif cp <= -ADJUDICATION_CP:
        res = "0-1"
    else:
        res = "1/2-1/2"
    return res, f"adjudication (ply cap {board.ply()}, SF eval {cp:+d}cp)"


def play_game(
    white: Player,
    black: Player,
    max_plies: int = 200,
    opening_moves: list[str] | None = None,
    on_move: Callable[[dict[str, Any]], None] | None = None,
    *,
    opening_name: str | None = None,
    game_id: int = 0,
    event: str = "claude_chess match",
    stockfish_path: str | None = None,
    verbose: bool = False,
    resign_cp: int | None = None,
    resign_plies: int = 6,
) -> GameRecord:
    """Play one game. `max_plies` caps total plies (book included); at the cap the
    position is adjudicated by Stockfish. `on_move(row)` is called after every
    non-book move with the decision row (see `decision_row`)."""
    board = chess.Board()
    for san in opening_moves or []:
        board.push_san(san)
    book_plies = board.ply()
    decisions: list[dict[str, Any]] = []
    result, termination = "*", ""
    # Resign adjudication (cutechess/TCEC style): Stockfish is only the referee here — it
    # ends games that are decided, it never sees or influences a player's choice.
    referee = open_stockfish(stockfish_path) if resign_cp else None
    streak_side, streak = None, 0

    while True:
        outcome = board.outcome(claim_draw=True)
        if outcome is not None:
            result, termination = outcome.result(), _termination_from_outcome(outcome)
            break
        if board.ply() >= max_plies:
            result, termination = adjudicate(board, stockfish_path)
            break
        if referee is not None and board.ply() > book_plies:
            cp = referee.analyse(board, RESIGN_LIMIT)["score"].white().score(mate_score=10000)
            side = "1-0" if cp >= resign_cp else "0-1" if cp <= -resign_cp else None
            streak = streak + 1 if side is not None and side == streak_side else (1 if side else 0)
            streak_side = side
            if side is not None and streak >= resign_plies:
                result = side
                termination = f"adjudication (resign: SF {cp:+d}cp for {streak} plies)"
                break
        player = white if board.turn == chess.WHITE else black
        t0 = time.monotonic()
        try:
            d = player.choose_move(board.copy())
        except LLMUnavailable as e:  # backend down / rate-limited: not the player's fault
            result, termination = "*", f"aborted (LLM unavailable: {str(e)[:160]})"
            break
        except Exception as e:  # a crashing player forfeits rather than killing the match
            d = MoveDecision(move=None, san=None, forfeit_reason=f"exception: {type(e).__name__}: {e}")
        if not d.seconds:
            d.seconds = time.monotonic() - t0
        if d.move is not None and d.move not in board.legal_moves:
            d.illegal_attempts.append(d.move.uci())
            d.forfeit_reason = f"returned illegal move {d.move.uci()}"
            d.move, d.san = None, None
        if d.move is not None and not d.san:
            d.san = board.san(d.move)
        row = decision_row(board, player.name, d, game_id)
        row["own_eval"] = _own_eval(d)
        if getattr(d, "traces", None):
            row["_traces"] = d.traces  # popped by the run-dir writer into traces.jsonl
        decisions.append(row)
        if on_move:
            on_move(row)
        if d.move is None:
            result = "0-1" if board.turn == chess.WHITE else "1-0"
            termination = f"forfeit ({player.name}: {d.forfeit_reason or 'no move'})"
            break
        board.push(d.move)

    if referee is not None:
        referee.quit()
    game = chess.pgn.Game.from_board(board)
    h = game.headers
    h["Event"] = event
    h["Site"] = "claude_chess"
    h["Date"] = _dt.date.today().strftime("%Y.%m.%d")
    h["Round"] = str(game_id)
    h["White"], h["Black"] = white.name, black.name
    h["Result"] = result
    h["Termination"] = termination
    h["BookPlies"] = str(book_plies)
    h["PlyCount"] = str(board.ply())
    if opening_name:
        h["Opening"] = opening_name
    # annotate non-book moves with cost / illegal info
    node, i = game, 0
    while node.variations:
        node = node.variations[0]
        i += 1
        if i > book_plies and i - book_plies - 1 < len(decisions):
            r = decisions[i - book_plies - 1]
            bits = []
            if r["own_eval"] is not None:
                bits.append(f"own {r['own_eval']:+.0f}")
            if r["illegal_attempts"]:
                bits.append(f"illegal {r['illegal_attempts']}")
            if r["cost"]:
                bits.append(f"${r['cost']:.4f}")
            if bits:
                node.comment = " ".join(bits)
    rec = GameRecord(white=white.name, black=black.name, result=result, termination=termination,
                     game=game, decisions=decisions, opening_name=opening_name,
                     book_plies=book_plies, game_id=game_id)
    if verbose:
        _say(f"[g{game_id}] {white.name} vs {black.name}: {result} ({termination})")
    return rec


def _close(p: Any) -> None:
    close = getattr(p, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def make_run_dir(label: str, root: str | Path = "runs") -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(root) / f"{ts}_{label}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def play_match(
    player_a_factory: Callable[[], Player],
    player_b_factory: Callable[[], Player],
    games: int,
    max_plies: int = 200,
    *,
    openings: dict[str, list[str]] | list[list[str]] | None = OPENINGS,
    parallel: int = 1,
    label: str = "match",
    run_dir: str | Path | None = None,
    runs_root: str | Path = "runs",
    analyze: bool = True,
    analysis_depth: int = 12,
    meta: dict[str, Any] | None = None,
    quiet: bool = False,
    db_path: str | Path | None = None,
    resign_cp: int | None = None,
    resign_plies: int = 6,
    opening_offset: int = 0,
) -> Path:
    """Play `games` games; A is White in even-numbered games (0, 2, ...). Each opening is
    used twice in a row (once per colour). Factories are called per game so no engine
    process is shared between threads. Returns the run directory."""
    rd = Path(run_dir) if run_dir else make_run_dir(label, runs_root)
    rd.mkdir(parents=True, exist_ok=True)
    if isinstance(openings, dict):
        opening_list = list(openings.items())
    elif openings:
        opening_list = [(None, o) for o in openings]
    else:
        opening_list = []
    file_lock = threading.Lock()
    dec_path, pgn_path, gj_path = rd / "decisions.jsonl", rd / "games.pgn", rd / "games.jsonl"

    names: dict[str, str] = {}
    probe_a, probe_b = player_a_factory(), player_b_factory()
    names["a"], names["b"] = probe_a.name, probe_b.name
    _close(probe_a)
    _close(probe_b)
    if names["a"] == names["b"]:
        names["a"], names["b"] = names["a"] + "#A", names["b"] + "#B"
    (rd / "meta.json").write_text(json.dumps({
        "label": label, "games": games, "max_plies": max_plies, "parallel": parallel,
        "player_a": names["a"], "player_b": names["b"],
        "openings": [n or " ".join(m) for n, m in opening_list], **(meta or {}),
    }, indent=2))

    aborted = threading.Event()  # set once the LLM backend is unavailable: stop scheduling games

    def run_one(i: int) -> GameRecord | None:
        if aborted.is_set():
            _say(f"[g{i}] SKIPPED (LLM backend unavailable earlier in this match)")
            return None
        a, b = player_a_factory(), player_b_factory()
        a.name, b.name = names["a"], names["b"]
        white, black = (a, b) if i % 2 == 0 else (b, a)
        oname, omoves = (opening_list[(i // 2 + opening_offset) % len(opening_list)]
                         if opening_list else (None, None))

        def on_move(row: dict[str, Any]) -> None:
            traces = row.pop("_traces", None)
            with file_lock, dec_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            if traces:
                with file_lock, (rd / "traces.jsonl").open("a") as f:
                    for k, t in enumerate(traces):
                        f.write(json.dumps({"game": row["game"], "ply": row["ply"], "player": row["player"],
                                            "call": k, **t}) + "\n")
            if not quiet:
                ev = f" own={row['own_eval']:+.0f}" if row.get("own_eval") is not None else ""
                ill = f" illegal={len(row['illegal_attempts'])}" if row["illegal_attempts"] else ""
                cost = f" ${row['cost']:.4f}" if row["cost"] else ""
                _say(f"[g{i}] ply {row['ply']:>3} {row['san'] or '--':<7} {row['player']}"
                     f"{ev}{ill}{cost} {row['seconds']:.1f}s")

        try:
            rec = play_game(white, black, max_plies, omoves, on_move, opening_name=oname,
                            game_id=i, event=f"claude_chess {label}",
                            resign_cp=resign_cp, resign_plies=resign_plies)
        finally:
            _close(a)
            _close(b)
        with file_lock:
            with pgn_path.open("a") as f:
                f.write(rec.pgn + "\n\n")
            with gj_path.open("a") as f:
                f.write(json.dumps(rec.summary()) + "\n")
        try:  # live DB hook: base columns now, analysis columns merged in later by analyze_run
            from claude_chess.match.database import insert_game
            kwargs = {"db_path": db_path} if db_path is not None else {}
            insert_game(rd, label, (rd / "meta.json").read_text() if (rd / "meta.json").exists() else None,
                       rec.game, rec.game_id, rec.decisions, **kwargs)
        except Exception as e:
            _say(f"[db] insert_game failed for game {i}: {e!r}")
        if rec.termination.startswith("aborted"):
            aborted.set()
        _say(f"[g{i}] RESULT {rec.white} vs {rec.black}: {rec.result} ({rec.termination})")
        return rec

    if parallel <= 1:
        for i in range(games):
            run_one(i)
    else:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(run_one, i) for i in range(games)]
            for fut in as_completed(futs):
                exc = fut.exception()
                if exc:
                    _say(f"game failed: {exc!r}")

    if analyze:
        from claude_chess.match.analysis import analyze_run
        analyze_run(rd, depth=analysis_depth, db_path=db_path)
    return rd
