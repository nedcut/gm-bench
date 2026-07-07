"""Tests for repeat runs and the sign-flip permutation test."""

from __future__ import annotations

from typing import Any

from gm_bench.agents import Agent, ValueAgent
from gm_bench.benchmark_config import BenchmarkConfig, config_from_dict
from gm_bench.runner import _sign_flip_p_value, evaluate_against_baselines, run_many, summarize_episodes


class NoisyAgent(Agent):
    """Deterministic across runs, but behaves differently on each repeat.

    Signs the top free agent only on even-numbered calls, so the two repeats
    of a seed produce different scores — a stand-in for model sampling noise.
    """

    name = "noisy"

    def __init__(self) -> None:
        self.inner = ValueAgent()
        self.calls = 0

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls += 1
        if self.calls % 2 == 0:
            return self.inner.act(observation)
        return [{"type": "noop"}]


def test_repeats_produce_one_episode_per_seed_per_repeat() -> None:
    payload = run_many(ValueAgent(), seeds=[1, 2], seasons=1, repeats=3, workers=1)
    assert payload["repeats"] == 3
    assert len(payload["episodes"]) == 6
    assert sorted({episode["repeat"] for episode in payload["episodes"]}) == [1, 2, 3]
    # The simulator is deterministic, so a scripted agent's repeats are identical.
    for seed in (1, 2):
        scores = {ep["final_score"] for ep in payload["episodes"] if ep["seed"] == seed}
        assert len(scores) == 1
    assert payload["summary"]["within_seed_score_stddev"] == 0.0


def test_within_seed_stddev_captures_repeat_noise() -> None:
    payload = run_many(NoisyAgent(), seeds=[1], seasons=1, repeats=2, workers=1)
    scores = [episode["final_score"] for episode in payload["episodes"]]
    assert scores[0] != scores[1]
    assert payload["summary"]["within_seed_score_stddev"] > 0.0


def test_paired_analysis_uses_per_seed_mean_across_repeats() -> None:
    result = evaluate_against_baselines(
        ValueAgent(),
        seeds=[1, 2],
        seasons=1,
        baseline_names=["random"],
        repeats=2,
        use_baseline_cache=False,
    )
    assert len(result["candidate"]["episodes"]) == 4
    # Baselines are deterministic and run once per seed.
    assert all(len(baseline["episodes"]) == 2 for baseline in result["baselines"])
    per_seed = {row["seed"]: row for row in result["paired"]["per_seed"]}
    assert set(per_seed) == {1, 2}
    # With a deterministic candidate the repeat-mean equals the single-run score.
    single = evaluate_against_baselines(
        ValueAgent(),
        seeds=[1, 2],
        seasons=1,
        baseline_names=["random"],
        use_baseline_cache=False,
    )
    assert result["paired"]["paired_lift_mean"] == single["paired"]["paired_lift_mean"]


def test_sign_flip_p_value_exact_small_sample() -> None:
    # All five lifts share a sign and magnitude: only the identity flip and the
    # full flip reach |mean| >= observed, so p is exactly 2 / 2^5.
    assert _sign_flip_p_value([1.0, 1.0, 1.0, 1.0, 1.0]) == 2 / 32
    # A perfectly balanced sample is maximally insignificant.
    assert _sign_flip_p_value([1.0, -1.0]) == 1.0
    # Undefined below two samples.
    assert _sign_flip_p_value([1.0]) is None
    assert _sign_flip_p_value([]) is None


def test_sign_flip_p_value_is_deterministic_when_sampled() -> None:
    lifts = [float(i % 7 - 3) + 0.1 for i in range(20)]
    assert _sign_flip_p_value(lifts) == _sign_flip_p_value(lifts)


def test_evaluate_reports_sign_flip_p_value() -> None:
    result = evaluate_against_baselines(
        ValueAgent(),
        seeds=[1, 2, 3],
        seasons=1,
        baseline_names=["random"],
        use_baseline_cache=False,
    )
    p_value = result["paired"]["sign_flip_p_value"]
    assert p_value is not None
    assert 0.0 < p_value <= 1.0
    # Three seeds can never beat the exact floor of 2 / 2^3.
    assert p_value >= 0.25


def test_score_stddev_uses_per_seed_means_not_flattened_episodes() -> None:
    episodes = [
        {
            "seed": 1,
            "final_score": 100.0,
            "strategy_score": 0.0,
            "protocol_penalty": 0.0,
            "wins": 0,
            "championships": 0,
            "illegal_actions": 0,
            "repeat": 1,
        },
        {
            "seed": 1,
            "final_score": 200.0,
            "strategy_score": 0.0,
            "protocol_penalty": 0.0,
            "wins": 0,
            "championships": 0,
            "illegal_actions": 0,
            "repeat": 2,
        },
        {
            "seed": 2,
            "final_score": 100.0,
            "strategy_score": 0.0,
            "protocol_penalty": 0.0,
            "wins": 0,
            "championships": 0,
            "illegal_actions": 0,
            "repeat": 1,
        },
        {
            "seed": 2,
            "final_score": 200.0,
            "strategy_score": 0.0,
            "protocol_penalty": 0.0,
            "wins": 0,
            "championships": 0,
            "illegal_actions": 0,
            "repeat": 2,
        },
    ]
    summary = summarize_episodes(episodes)
    assert summary["score_stddev"] == 0.0
    assert summary["within_seed_score_stddev"] > 0.0


def test_config_from_args_rejects_zero_repeats() -> None:
    from argparse import Namespace

    from gm_bench.cli import _config_from_args

    try:
        _config_from_args(Namespace(repeats=0, seeds=[1], seasons=5))
    except ValueError as exc:
        assert "repeats" in str(exc)
    else:
        raise AssertionError("repeats=0 should fail validation")


def test_config_accepts_repeats() -> None:
    config = config_from_dict({"repeats": 3, "seeds": [1], "provider": "openai"})
    assert config.repeats == 3
    bad = BenchmarkConfig(repeats=0)
    try:
        bad.validate()
    except ValueError as exc:
        assert "repeats" in str(exc)
    else:
        raise AssertionError("repeats=0 should fail validation")
