"""Regression tests with fixed golden scores."""

from __future__ import annotations

from gm_bench.agents import RandomAgent, ValueAgent
from gm_bench.runner import run_episode, run_many

# Re-pinned after midseason became part of the default episode (P3+P5+P6):
# seasons*4 decision points and a partial-season break change every score.
GOLDEN_VALUE_SCORES_5_SEASONS = {
    1: 319.261,
    2: 471.201,
    3: 332.695,
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
