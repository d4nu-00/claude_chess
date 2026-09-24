"""Map Maia weight classes onto Lichess's rating scale, and estimate a player's
Lichess-calibrated performance rating from match results against Maia opponents.

See wiki/pages/maia-calibration.md for the full write-up, caveats, and how to read
these numbers (Lichess != FIDE, bots are rated against humans at fast time controls,
`nodes=1` play, and how wide the confidence interval is for small game counts).
"""

from __future__ import annotations

import math

# Ratings fetched 2026-09-24 via https://lichess.org/api/user/<bot> (perf.games.rating,
# rounded). Bot -> weight mapping confirmed from the CSSLab/maia-chess README ("maia1 is
# targeting ELO 1100, maia5 is targeting ELO 1500, maia9 is targeting ELO 1900").
MAIA_LICHESS: dict[int, dict[str, object]] = {
    1100: {"bot": "maia1", "blitz": 1387, "rapid": 1494, "classical": 1651, "blitz_games": 438_000},
    1500: {"bot": "maia5", "blitz": 1453, "rapid": 1625, "classical": 1720},
    1900: {"bot": "maia9", "blitz": 1612, "rapid": 1773, "classical": 1731},
}

# Only these three weight classes have a Lichess bot (and therefore a measured
# calibration point); the other weight files (1200..1800 minus 1500) are real Maia
# nets but were never deployed as a public bot, so we only have an interpolated guess.
POOLS = ("blitz", "rapid", "classical")

_EPS_SCORE = 0.01  # clip score fractions to [EPS, 1-EPS] before mapping through the Elo curve


def _expected_score(rating_diff: float) -> float:
    """Standard Elo expected score for `rating_diff = own - opponent`."""
    return 1.0 / (1.0 + 10.0 ** (-rating_diff / 400.0))


def _score_to_diff(p: float) -> float:
    """Inverse of `_expected_score`: the rating diff implied by score fraction p."""
    p = min(max(p, _EPS_SCORE), 1.0 - _EPS_SCORE)
    return -400.0 * math.log10(1.0 / p - 1.0)


def performance_rating(results: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Iterative (FIDE-style) performance rating from a list of (opponent_rating, score).

    `score` is 1/0.5/0 (win/draw/loss) or any fractional score in [0, 1]. Returns
    `(estimate, lo95, hi95)`.

    The point estimate solves `sum(expected_score(R - opp_i)) == sum(score_i)` for R,
    with one extra half-weight "drawn game" against the average opponent rating mixed
    in — this is the standard fix for the raw formula's estimate going to +-infinity
    on a perfect or zero score (a single loss would otherwise put you at -inf).

    The confidence interval comes from the binomial standard error of the overall
    score fraction (treating games as iid Bernoulli/ternary trials, which is a
    simplification — see caveats in the wiki page), continuity-corrected the same
    way, then mapped through the Elo curve around the average opponent rating and
    clipped to a score fraction in [0.01, 0.99] so it stays finite.
    """
    if not results:
        raise ValueError("performance_rating needs at least one (opp_rating, score) pair")
    n = len(results)
    total_score = sum(s for _, s in results)
    avg_opp = sum(r for r, _ in results) / n

    # Data points as (opp_rating, score, weight); add a half-weight drawn pseudo-game
    # against the average opponent so perfect/zero scores don't blow up.
    points: list[tuple[float, float, float]] = [(opp, score, 1.0) for opp, score in results]
    points.append((avg_opp, 0.5, 0.5))

    def imbalance(rating: float) -> float:
        return sum(w * (_expected_score(rating - opp) - score) for opp, score, w in points)

    lo, hi = avg_opp - 1200.0, avg_opp + 1200.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if imbalance(mid) > 0:  # expected score too high at `mid` -> true rating is lower
            hi = mid
        else:
            lo = mid
    estimate = (lo + hi) / 2.0

    # Binomial SE on the (continuity-corrected) score fraction, mapped through the Elo curve.
    p_adj = (total_score + 0.5) / (n + 1)
    se = math.sqrt(max(p_adj * (1 - p_adj), 1e-9) / n)
    p_lo = min(max(p_adj - 1.96 * se, _EPS_SCORE), 1.0 - _EPS_SCORE)
    p_hi = min(max(p_adj + 1.96 * se, _EPS_SCORE), 1.0 - _EPS_SCORE)
    lo95 = avg_opp + _score_to_diff(p_lo)
    hi95 = avg_opp + _score_to_diff(p_hi)
    return estimate, lo95, hi95


def interpolated_rating(maia_weight: int, pool: str = "rapid") -> dict[str, object]:
    """Estimate the Lichess `pool` rating of a Maia weight class that has no bot.

    Weight classes 1100/1500/1900 have a real Lichess bot (maia1/maia5/maia9) and are
    returned as measured, `estimated=False`. Everything else (1200..1800 excluding
    1500) is linearly interpolated between the two nearest measured anchors and
    flagged `estimated=True` -- there is no ground truth for these; treat them as a
    rough guess only, per [[maia-calibration]].
    """
    if pool not in POOLS:
        raise ValueError(f"pool must be one of {POOLS}, got {pool!r}")
    anchors = sorted(MAIA_LICHESS.keys())
    if maia_weight in MAIA_LICHESS:
        return {"weight": maia_weight, "pool": pool, "rating": float(MAIA_LICHESS[maia_weight][pool]),
                "estimated": False, "note": f"measured from lichess bot {MAIA_LICHESS[maia_weight]['bot']}"}
    if maia_weight < anchors[0] or maia_weight > anchors[-1]:
        raise ValueError(f"{maia_weight} is outside the interpolation range {anchors[0]}..{anchors[-1]}")
    lo_w = max(a for a in anchors if a < maia_weight)
    hi_w = min(a for a in anchors if a > maia_weight)
    lo_r = float(MAIA_LICHESS[lo_w][pool])
    hi_r = float(MAIA_LICHESS[hi_w][pool])
    frac = (maia_weight - lo_w) / (hi_w - lo_w)
    rating = lo_r + frac * (hi_r - lo_r)
    return {"weight": maia_weight, "pool": pool, "rating": rating, "estimated": True,
            "note": f"linearly interpolated between maia-{lo_w} ({lo_r:.0f}) and maia-{hi_w} ({hi_r:.0f})"}
