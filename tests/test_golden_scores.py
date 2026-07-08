"""Regression tests with fixed golden scores."""

from __future__ import annotations

from gm_bench.agents import RandomAgent, ValueAgent
from gm_bench.runner import run_episode, run_many

# Regenerated after the midseason schedule fix: the pre- and post-break legs now
# sum to a full 3-games-per-pairing season instead of the truncated 2, which
# changes standings, morale, and draft order — and therefore these scores.
GOLDEN_VALUE_SCORES_5_SEASONS = {
    1: 279.039,
    2: 374.969,
    3: 305.513,
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
