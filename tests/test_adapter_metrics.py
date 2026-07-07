"""Tests for adapter reliability accounting: failed decisions, latency,
memo utilization, and the strict fallback mode."""

from __future__ import annotations

from typing import Any

import pytest

from examples.gm_agent_common import fallback_actions
from gm_bench.agents import Agent, ValueAgent
from gm_bench.runner import evaluate_against_baselines, run_episode, run_many, summarize_episodes
from gm_bench.simulator import League


class AlwaysFailingAgent(Agent):
    """Mimics an external adapter whose model never produces usable output."""

    name = "always-failing"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"type": "noop", "error": "model returned garbage"}]


class FlakyValueAgent(Agent):
    """Fails on every third decision, mimicking an intermittently flaky adapter."""

    name = "flaky-value"

    def __init__(self) -> None:
        self.inner = ValueAgent()
        self.calls = 0

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls += 1
        if self.calls % 3 == 0:
            return [{"type": "noop", "model_error": "intermittent parse failure"}]
        return self.inner.act(observation)


class MemoValueAgent(Agent):
    name = "memo-value"

    def __init__(self) -> None:
        self.inner = ValueAgent()

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"type": "memo", "text": "keep building youth"}, *self.inner.act(observation)]


def test_failed_decisions_counted_for_error_marked_actions() -> None:
    result = run_episode(AlwaysFailingAgent(), seed=1, seasons=2)
    assert result.decisions == 6
    assert result.failed_decisions == 6
    assert result.illegal_actions == 0  # noops are legal; the failure is adapter-level


def test_scripted_agent_reports_zero_failures_and_latency_fields() -> None:
    result = run_episode(ValueAgent(), seed=1, seasons=1)
    assert result.decisions == 3
    assert result.failed_decisions == 0
    assert result.memo_writes == 0
    assert result.mean_decision_seconds >= 0.0
    assert result.max_decision_seconds >= result.mean_decision_seconds


def test_memo_writes_counted_per_episode() -> None:
    result = run_episode(MemoValueAgent(), seed=1, seasons=2)
    assert result.memo_writes == 6
    assert result.failed_decisions == 0


def test_partial_failures_produce_fractional_failure_rate() -> None:
    payload = run_many(FlakyValueAgent(), seeds=[1], seasons=2, workers=1)
    summary = payload["summary"]
    assert summary["decisions"] == 6
    assert summary["failed_decisions"] == 2
    assert summary["decision_failure_rate"] == round(2 / 6, 3)


def test_summary_aggregates_reliability_metrics() -> None:
    payload = run_many(AlwaysFailingAgent(), seeds=[1, 2], seasons=1)
    summary = payload["summary"]
    assert summary["decisions"] == 6
    assert summary["failed_decisions"] == 6
    assert summary["decision_failure_rate"] == 1.0
    assert summary["memo_writes"] == 0


def test_summarize_episodes_tolerates_legacy_episodes_without_new_fields() -> None:
    legacy = {
        "seed": 1,
        "final_score": 10.0,
        "strategy_score": 10.0,
        "protocol_penalty": 0.0,
        "wins": 5,
        "championships": 0,
        "illegal_actions": 0,
    }
    summary = summarize_episodes([legacy])
    assert summary["decisions"] == 0
    assert summary["failed_decisions"] == 0
    assert summary["decision_failure_rate"] == 0.0
    assert summary["memo_writes"] == 0


def test_evaluate_exposes_candidate_failure_rate() -> None:
    result = evaluate_against_baselines(
        AlwaysFailingAgent(),
        seeds=[1],
        seasons=1,
        baseline_names=["random"],
        use_baseline_cache=False,
    )
    normalized = result["normalized"]
    assert normalized["candidate_decisions"] == 3
    assert normalized["candidate_failed_decisions"] == 3
    assert normalized["candidate_decision_failure_rate"] == 1.0
    assert normalized["candidate_memo_writes"] == 0


def test_fallback_actions_always_carry_model_error_marker() -> None:
    observation = League.new(seed=1).observation("draft")
    actions = fallback_actions(observation)
    assert actions
    assert actions[0]["model_error"] == "model produced no usable actions"
    assert any(action["type"] == "set_lineup" for action in actions)


def test_strict_mode_makes_fallback_a_pure_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GM_AGENT_STRICT", "1")
    observation = League.new(seed=1).observation("draft")
    actions = fallback_actions(observation, "api_error: 500")
    assert actions == [{"type": "noop", "model_error": "api_error: 500"}]
