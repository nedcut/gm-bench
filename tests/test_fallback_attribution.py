"""Fallback attribution: separating model-played decisions from adapter fallbacks."""

from __future__ import annotations

from typing import Any

from gm_bench.agents import AGENTS, Agent
from gm_bench.runner import _is_fallback_response, run_episode, run_many


class TaggedFallbackAgent(Agent):
    """Mimics an external adapter whose model fails at every decision point."""

    name = "tagged-fallback"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"type": "noop", "model_error": "ollama_parse_error: boom"}]


class SometimesFallbackAgent(Agent):
    """Falls back only during the trade deadline."""

    name = "sometimes-fallback"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        if observation["phase"] == "trade_deadline":
            return [{"type": "noop", "error": "external agent timed out after 1s"}]
        return [{"type": "noop"}]


def test_is_fallback_response_detects_adapter_tags() -> None:
    assert _is_fallback_response([{"type": "noop", "model_error": "x"}])
    assert _is_fallback_response([{"type": "noop", "error": "x"}])
    assert _is_fallback_response({"type": "noop"})  # non-list responses were never model decisions
    assert not _is_fallback_response([{"type": "noop"}])
    assert not _is_fallback_response([{"type": "memo", "text": "plan"}])


def test_full_fallback_agent_attributes_every_decision() -> None:
    result = run_episode(TaggedFallbackAgent(), seed=1, seasons=2)
    assert result.decision_points == 6  # 2 seasons x 3 phases
    assert result.fallback_decisions == 6


def test_partial_fallback_agent_counts_only_tagged_decisions() -> None:
    result = run_episode(SometimesFallbackAgent(), seed=1, seasons=2)
    assert result.decision_points == 6
    assert result.fallback_decisions == 2  # one trade deadline per season


def test_scripted_baselines_report_zero_fallbacks() -> None:
    result = run_many(AGENTS["value"](), seeds=[1], seasons=1)
    summary = result["summary"]
    assert summary["decision_points"] == 3
    assert summary["fallback_decisions"] == 0
    assert summary["fallback_decision_rate"] == 0.0


def test_run_many_aggregates_fallback_rate() -> None:
    result = run_many(TaggedFallbackAgent(), seeds=[1, 2], seasons=1)
    summary = result["summary"]
    assert summary["decision_points"] == 6
    assert summary["fallback_decisions"] == 6
    assert summary["fallback_decision_rate"] == 1.0
