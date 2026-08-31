"""Regression tests with fixed golden scores."""

from __future__ import annotations

from gm_bench.agents import RandomAgent, ValueAgent
from gm_bench.runner import run_episode, run_many

# Re-pinned for the v6 draft lottery: draft order is now drawn from the seeded
# RNG instead of following inverse standings, and traded picks carry their
# original team's identity, so every draft (and everything downstream of it)
# re-rolled. Re-pinned again for v6 free-agent willingness: every signing
# (user and opponent) now carries the signing_appeal multiplier, so salaries
# and rosters re-rolled league-wide. The values remain exact replay pins:
# identical seeds must reproduce them byte-for-byte.
GOLDEN_VALUE_SCORES_5_SEASONS = {
    1: 196.025,
    2: 200.161,
    3: 264.465,
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
