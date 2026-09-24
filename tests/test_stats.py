"""Experiment statistics on synthetic runs (no engines, no LLM)."""

import json

from claude_chess.match.stats import elo_mle, lr_test, mann_whitney, permutation_test, report


def _run(root, name, spec, level, results, cost):
    rd = root / name
    rd.mkdir()
    (rd / "meta.json").write_text(json.dumps({"white_spec": spec, "black_spec": f"maia:{level}",
                                              "model": "claude-haiku-4-5-20251001"}))
    games, decs = [], []
    for i, r in enumerate(results):
        white, black = (spec, f"maia-{level}") if i % 2 == 0 else (f"maia-{level}", spec)
        games.append({"game": i, "white": white, "black": black, "result": r})
        decs.append({"game": i, "player": spec, "cost": cost})
    (rd / "games.jsonl").write_text("".join(json.dumps(g) + "\n" for g in games))
    (rd / "decisions.jsonl").write_text("".join(json.dumps(d) + "\n" for d in decs))


def test_elo_mle_sensible():
    games = [{"level": 1500, "score": s} for s in (1, 0, 1, 0)]
    assert abs(elo_mle(games) - 1500) <= 10
    assert elo_mle([{"level": 1500, "score": 1.0}] * 4) >= 3000  # all wins -> boundary


def test_tests_detect_big_difference():
    a = [{"level": 1100 + 200 * (i % 3), "color": "white", "score": 1.0} for i in range(12)]
    b = [{"level": 1100 + 200 * (i % 3), "color": "white", "score": 0.0} for i in range(12)]
    d, p = permutation_test(a, b, n=2000)
    assert d == 1.0 and p < 0.01
    assert lr_test(a, b)[1] < 0.01
    assert mann_whitney([10, 20, 30, 40], [100, 110, 120, 130])[1] < 0.05


def test_report_writes_crosstable_with_cost(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _run(runs, "x_exp_h1100", "hybrid-ctx", 1100, ["1-0", "0-1", "1/2-1/2", "0-1"], 0.01)
    _run(runs, "x_exp_n1100", "naive", 1100, ["0-1", "1-0", "0-1", "1-0"], 0.002)
    summary = report(runs, "exp", tmp_path / "out")
    table = (tmp_path / "out" / "crosstable.md").read_text()
    assert "haiku-harness" in table and "haiku-naive" in table and "$/game" in table
    assert summary["configs"]["haiku-harness"]["score"] == 3.5
    assert summary["configs"]["haiku-naive"]["score"] == 0.0
    assert abs(summary["configs"]["haiku-harness"]["usd_per_game"] - 0.01) < 1e-9
    assert "haiku" in summary["tests"]
