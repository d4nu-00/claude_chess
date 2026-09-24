import json
import shutil

import chess
import pytest

from claude_chess.match.analysis import analyze_game, analyze_run
from claude_chess.match.baselines import RandomPlayer, StockfishPlayer
from claude_chess.match.runner import play_game, play_match
from claude_chess.types import MoveDecision

needs_sf = pytest.mark.skipif(
    shutil.which("stockfish") is None and not __import__("os").path.exists("/opt/homebrew/bin/stockfish"),
    reason="stockfish not installed")


class ForfeitAfter:
    """Plays random moves, then forfeits on its Nth move."""

    def __init__(self, n: int, name="forfeiter"):
        self.n, self.name, self.rng = n, name, RandomPlayer(0)

    def choose_move(self, board):
        self.n -= 1
        if self.n <= 0:
            return MoveDecision(move=None, san=None, illegal_attempts=["Qxz9"], forfeit_reason="gave up")
        return self.rng.choose_move(board)


def test_random_vs_random_terminates():
    rec = play_game(RandomPlayer(1), RandomPlayer(2), max_plies=1000)
    board = rec.game.end().board()
    assert rec.result in ("1-0", "0-1", "1/2-1/2")
    assert rec.termination.split()[0] in {
        "checkmate", "stalemate", "insufficient", "repetition", "fifty", "adjudication"}
    if rec.termination == "checkmate":
        assert board.is_checkmate()
    assert rec.game.headers["Result"] == rec.result
    assert len(rec.decisions) == board.ply()


def test_forfeit_is_loss():
    rec = play_game(RandomPlayer(3), ForfeitAfter(3), max_plies=200)
    assert rec.result == "1-0"
    assert rec.termination.startswith("forfeit")
    assert rec.decisions[-1]["uci"] is None
    assert rec.decisions[-1]["illegal_attempts"] == ["Qxz9"]
    # exceptions in a player also forfeit
    class Boom:
        name = "boom"
        def choose_move(self, board):
            raise RuntimeError("x")
    rec = play_game(Boom(), RandomPlayer(0))
    assert rec.result == "0-1" and "exception" in rec.termination


@needs_sf
def test_adjudication_at_ply_cap():
    # ply cap reached inside the book -> adjudicated immediately, no decisions
    rec = play_game(RandomPlayer(0), RandomPlayer(1), max_plies=4,
                    opening_moves=["e4", "d5", "exd5", "Qxd5"])
    assert rec.termination.startswith("adjudication")
    assert rec.result in ("1-0", "0-1", "1/2-1/2")
    assert rec.book_plies == 4 and rec.decisions == []

    rec = play_game(RandomPlayer(0), RandomPlayer(1), max_plies=0,
                    opening_moves=None)
    assert rec.result == "1/2-1/2"  # start position is balanced
    # Black missing a queen -> white win
    board_moves = ["e4", "e5", "Qh5", "Nc6", "Qxf7+", "Kxf7"]  # White gave away queen
    rec = play_game(RandomPlayer(0), RandomPlayer(1), max_plies=6, opening_moves=board_moves)
    assert rec.result == "0-1"


@needs_sf
def test_analysis_acpl_on_short_game():
    rec = play_game(RandomPlayer(5), RandomPlayer(6), max_plies=16)
    rows = analyze_game(rec.game, depth=8)
    assert len(rows) == 16
    assert all(0 <= r["cpl"] <= 1000 for r in rows)
    assert sum(r["cpl"] for r in rows) > 0  # random moves lose something


@needs_sf
def test_stockfish_vs_random_match(tmp_path):
    rd = play_match(lambda: StockfishPlayer(skill=5, time=0.01), lambda: RandomPlayer(7),
                    games=2, max_plies=40, runs_root=tmp_path, label="t", parallel=2,
                    analysis_depth=6, quiet=True)
    summary = json.loads((rd / "summary.json").read_text())
    sf, rnd = summary["players"]["stockfish(skill5)"], summary["players"]["random"]
    assert sf["games"] == rnd["games"] == 2
    assert sf["score"] >= 1.5
    assert sf["acpl"] is not None and rnd["acpl"] > sf["acpl"]
    assert (rd / "report.md").exists() and (rd / "games.pgn").exists()
    lines = (rd / "decisions.jsonl").read_text().splitlines()
    row = json.loads(lines[0])
    assert {"fen", "player", "san", "candidates", "illegal_attempts", "calls", "cost", "seconds"} <= row.keys()
    # re-analysis is idempotent
    assert analyze_run(rd, depth=6, quiet=True)["players"]["random"]["games"] == 2


def test_cli_parse_position():
    from claude_chess.cli import parse_position
    assert parse_position("1. e4 e5 2. Nf3").fen() == chess.Board(
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2").fen()
    assert parse_position(chess.STARTING_FEN).fen() == chess.STARTING_FEN
