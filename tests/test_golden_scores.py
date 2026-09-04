"""Regression tests with fixed golden scores."""

from __future__ import annotations

from gm_bench.agents import RandomAgent, ValueAgent
from gm_bench.runner import run_episode, run_many

# Re-pinned for the v6 draft lottery: draft order is now drawn from the seeded
# RNG instead of following inverse standings, and traded picks carry their
# original team's identity, so every draft (and everything downstream of it)
# re-rolled. Re-pinned again for v6 free-agent willingness: every signing
# (user and opponent) now carries the signing_appeal multiplier, so salaries
# and rosters re-rolled league-wide. Re-pinned again for v6 lineup
# construction: every forward now draws a center-or-wing sub_position at
# generation, consuming an extra RNG draw per forward, so every generated
# league (and everything downstream) re-rolled again. Re-pinned again for v6
# expiring contracts: an unresigned expiring incumbent now risks an immediate
# rival scramble at season end, so ValueAgent (which does not extend every
# eligible veteran) loses real talent it previously always got to re-sign.
# Re-pinned again for v6 dead-field removal: Team no longer draws two RNG
# values (market, patience) at generation, so every generated league (and
# everything downstream) re-rolled again.
# The values remain exact replay pins: identical seeds must reproduce them
# byte-for-byte.
GOLDEN_VALUE_SCORES_5_SEASONS = {
    1: 168.625,
    2: 151.302,
    3: 218.596,
}


def test_value_agent_golden_scores_five_seasons() -> None:
    for seed, expected in GOLDEN_VALUE_SCORES_5_SEASONS.items():
        result = run_episode(ValueAgent(), seed=seed, seasons=5)
        assert result.final_score == expected
        assert result.illegal_actions == 0


def test_value_agent_beats_random_on_shared_seeds() -> None:
    value = run_many(ValueAgent(), seeds=[1, 2, 3], seasons=3)
    random = run_many(RandomAgent(), seeds=[1, 2, 3], seasons=3)
    assert value["summary"]["mean_score"] > random["summary"]["mean_score"]
    assert random["summary"]["illegal_actions"] == 0
