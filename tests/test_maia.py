import os
import shutil

import chess
import pytest

from claude_chess.match.calibration import (
    MAIA_LICHESS,
    interpolated_rating,
    performance_rating,
)
from claude_chess.match.maia import LC0_PATH, WEIGHTS_DIR, MaiaPlayer, weights_path

_lc0_available = shutil.which(LC0_PATH) is not None or os.path.exists(LC0_PATH)
_weights_available = os.path.exists(weights_path(1500))

needs_maia = pytest.mark.skipif(
    not (_lc0_available and _weights_available),
    reason="lc0 and/or Maia weights not available")


# ── MaiaPlayer ───────────────────────────────────────────────────────────────


@needs_maia
def test_maia_player_returns_legal_move():
    p = MaiaPlayer(rating=1500)
    try:
        board = chess.Board()
        decision = p.choose_move(board)
        assert decision.move is not None
        assert decision.move in board.legal_moves
        assert decision.san is not None
        assert decision.forfeit_reason is None
    finally:
        p.close()


@needs_maia
def test_maia_player_name_and_close_idempotent():
    p = MaiaPlayer(rating=1100)
    assert p.name == "maia-1100"
    p.close()
    p.close()  # must not raise


def test_maia_player_rejects_unknown_rating():
    with pytest.raises(ValueError):
        MaiaPlayer(rating=1050)


def test_maia_player_missing_weights_file():
    with pytest.raises(FileNotFoundError):
        MaiaPlayer(rating=1500, weights_dir="/nonexistent/path")


# ── CLI spec parsing ──────────────────────────────────────────────────────────


@needs_maia
def test_cli_spec_parses_maia():
    import argparse

    from claude_chess.cli import make_player_factory
    args = argparse.Namespace(sf_time=0.05)
    factory = make_player_factory("maia:1900", args)
    p = factory()
    try:
        assert p.name == "maia-1900"
        assert p.rating == 1900
    finally:
        p.close()


# ── calibration ───────────────────────────────────────────────────────────────


def test_performance_rating_fifty_percent_equals_opponent_rating():
    estimate, lo, hi = performance_rating([(1500, 0.5)] * 10)
    assert estimate == pytest.approx(1500, abs=1e-6)
    assert lo < estimate < hi


def test_performance_rating_monotonic_in_score():
    lo_score, _, _ = performance_rating([(1500, 0.0)] * 10)
    mid_score, _, _ = performance_rating([(1500, 0.5)] * 10)
    hi_score, _, _ = performance_rating([(1500, 1.0)] * 10)
    assert lo_score < mid_score < hi_score


def test_performance_rating_ci_narrows_with_more_games():
    _, lo4, hi4 = performance_rating([(1500, 0.5)] * 4)
    _, lo40, hi40 = performance_rating([(1500, 0.5)] * 40)
    assert (hi40 - lo40) < (hi4 - lo4)


def test_performance_rating_rejects_empty():
    with pytest.raises(ValueError):
        performance_rating([])


def test_maia_lichess_table_has_the_three_calibrated_weights():
    assert set(MAIA_LICHESS) == {1100, 1500, 1900}
    assert MAIA_LICHESS[1100]["bot"] == "maia1"
    assert MAIA_LICHESS[1500]["bot"] == "maia5"
    assert MAIA_LICHESS[1900]["bot"] == "maia9"
    for weight in (1100, 1500, 1900):
        assert MAIA_LICHESS[weight]["blitz"] < MAIA_LICHESS[weight]["rapid"]


def test_interpolated_rating_matches_anchor_exactly():
    for weight in (1100, 1500, 1900):
        r = interpolated_rating(weight, pool="rapid")
        assert r["estimated"] is False
        assert r["rating"] == MAIA_LICHESS[weight]["rapid"]


def test_interpolated_rating_is_between_neighbours_and_flagged():
    r = interpolated_rating(1300, pool="rapid")
    assert r["estimated"] is True
    assert MAIA_LICHESS[1100]["rapid"] < r["rating"] < MAIA_LICHESS[1500]["rapid"]


def test_interpolated_rating_out_of_range():
    with pytest.raises(ValueError):
        interpolated_rating(500)
    with pytest.raises(ValueError):
        interpolated_rating(2500)
