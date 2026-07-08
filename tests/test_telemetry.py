"""Tests for usage/cost/latency telemetry."""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from gm_bench.agents import AGENTS, Agent, ExternalProcessAgent
from gm_bench.runner import run_episode, run_many, summarize_episodes
from gm_bench.telemetry import (
    aggregate_usage,
    estimate_cost_usd,
    normalize_usage,
    price_for,
    pricing_table,
    summarize_usage,
)


class UsageReportingAgent(Agent):
    name = "usage-stub"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"type": "noop"}]

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        return self.act(observation), {
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "api_calls": 1,
            "input_tokens": 1000,
            "output_tokens": 100,
            "total_tokens": 1100,
            "api_latency_ms": 250.0,
        }


def test_normalize_usage_accepts_known_keys_and_derives_total():
    usage = normalize_usage({"input_tokens": 10, "output_tokens": 5, "provider": "openai", "junk": 1})
    assert usage == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "provider": "openai"}


def test_normalize_usage_rejects_garbage():
    assert normalize_usage(None) is None
    assert normalize_usage("tokens") is None
    assert normalize_usage({}) is None
    assert normalize_usage({"input_tokens": -5, "model": ""}) is None
    assert normalize_usage({"api_calls": True}) is None


def test_price_for_exact_prefix_and_provider():
    assert price_for("claude-opus-4-8")["input_per_mtok"] == 5.0
    # date-suffixed / variant ids resolve by longest prefix
    assert price_for("gpt-5.4-mini-2026-05")["input_per_mtok"] == 0.75
    assert price_for("gpt-5.4-2026-05")["input_per_mtok"] == 2.5
    assert price_for("gemma4:e4b", provider="ollama")["input_per_mtok"] == 0.0
    assert price_for("mystery-model-9000") is None


def test_estimate_cost_prefers_reported_cost_and_never_guesses():
    reported = {"model": "mystery", "cost_usd": 0.123}
    assert estimate_cost_usd(reported) == 0.123
    unknown = {"model": "mystery-model-9000", "input_tokens": 1000, "output_tokens": 100}
    assert estimate_cost_usd(unknown) is None
    priced = {"model": "claude-haiku-4-5", "input_tokens": 1_000_000, "output_tokens": 100_000}
    assert estimate_cost_usd(priced) == pytest.approx(1.0 + 0.5)


def test_pricing_override_via_env(tmp_path, monkeypatch):
    override = tmp_path / "pricing.json"
    override.write_text(json.dumps({"models": {"mystery-model-9000": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}}))
    monkeypatch.setenv("GM_BENCH_PRICING", str(override))
    pricing_table.cache_clear()
    try:
        assert estimate_cost_usd({"model": "mystery-model-9000", "input_tokens": 1_000_000}) == pytest.approx(1.0)
        # base table entries survive the merge
        assert price_for("claude-fable-5")["output_per_mtok"] == 50.0
    finally:
        pricing_table.cache_clear()


def test_aggregate_usage_totals_and_cost():
    records = [
        {
            "provider": "openai",
            "model": "gpt-5.4",
            "api_calls": 1,
            "input_tokens": 100,
            "output_tokens": 10,
            "total_tokens": 110,
            "api_latency_ms": 100.0,
        },
        {
            "provider": "openai",
            "model": "gpt-5.4",
            "api_calls": 2,
            "input_tokens": 200,
            "output_tokens": 20,
            "total_tokens": 220,
            "api_latency_ms": 300.0,
        },
    ]
    block = aggregate_usage(records)
    assert block["api_calls"] == 3
    assert block["total_tokens"] == 330
    assert block["api_latency_ms"] == 400.0
    assert block["model"] == "gpt-5.4"
    assert block["cost_usd"] == pytest.approx(300 / 1e6 * 2.5 + 30 / 1e6 * 15.0)
    assert block["cost_decisions"] == 2


def test_aggregate_usage_empty():
    block = aggregate_usage([])
    assert block["decisions_with_usage"] == 0
    assert block["cost_usd"] is None


def test_external_process_agent_parses_envelope(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text(
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'actions': [{'type': 'noop'}],"
        " 'usage': {'provider': 'openai', 'model': 'gpt-5.4', 'input_tokens': 5, 'output_tokens': 2}}))\n"
    )
    agent = ExternalProcessAgent(f"{sys.executable} {script}", timeout_seconds=30)
    actions, usage = agent.act_with_usage({"seed": 1})
    assert actions == [{"type": "noop"}]
    assert usage["total_tokens"] == 7
    assert usage["provider"] == "openai"
    # legacy .act() drops usage but still works
    assert agent.act({"seed": 1}) == [{"type": "noop"}]


def test_external_process_agent_accepts_bare_list(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text("import json, sys\njson.load(sys.stdin)\nprint(json.dumps([{'type': 'noop'}]))\n")
    agent = ExternalProcessAgent(f"{sys.executable} {script}", timeout_seconds=30)
    actions, usage = agent.act_with_usage({"seed": 1})
    assert actions == [{"type": "noop"}]
    assert usage is None


def test_external_process_agent_rejects_envelope_without_actions(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text("import json, sys\njson.load(sys.stdin)\nprint(json.dumps({'usage': {}}))\n")
    agent = ExternalProcessAgent(f"{sys.executable} {script}", timeout_seconds=30)
    actions, usage = agent.act_with_usage({"seed": 1})
    assert actions[0]["type"] == "noop"
    assert "error" in actions[0]
    assert usage is None


def test_run_episode_aggregates_usage():
    result = run_episode(UsageReportingAgent(), seed=1, seasons=1)
    usage = result.usage
    assert usage["decisions_with_usage"] == 3
    assert usage["input_tokens"] == 3000
    assert usage["total_tokens"] == 3300
    assert usage["api_latency_ms"] == pytest.approx(750.0)
    assert usage["harness_latency_ms"] >= 0.0
    assert usage["model"] == "gpt-5.4-mini"
    assert usage["cost_usd"] == pytest.approx(3 * (1000 / 1e6 * 0.75 + 100 / 1e6 * 4.5))
    assert len(usage["per_decision"]) == 3
    assert {record["phase"] for record in usage["per_decision"]} == {"preseason", "trade_deadline", "draft"}


def test_run_many_summary_includes_usage():
    payload = run_many(UsageReportingAgent(), seeds=[1, 2], seasons=1, workers=1)
    usage = payload["summary"]["usage"]
    assert usage["decisions_with_usage"] == 6
    assert usage["total_tokens"] == 6600
    assert usage["provider"] == "openai"
    assert usage["cost_usd"] == pytest.approx(6 * (1000 / 1e6 * 0.75 + 100 / 1e6 * 4.5))


def test_scripted_agents_report_zero_usage():
    result = run_episode(AGENTS["value"](), seed=1, seasons=1)
    assert result.usage["decisions_with_usage"] == 0
    assert result.usage["cost_usd"] is None


def test_summarize_episodes_tolerates_legacy_episodes_without_usage():
    legacy = {
        "seed": 1,
        "final_score": 100.0,
        "strategy_score": 100.0,
        "protocol_penalty": 0.0,
        "wins": 10,
        "championships": 0,
        "illegal_actions": 0,
        "decisions": 3,
        "failed_decisions": 0,
        # no "usage" key — old baseline-cache entry
    }
    summary = summarize_episodes([legacy])
    assert summary["usage"]["decisions_with_usage"] == 0
    assert summary["usage"]["cost_usd"] is None


def test_summarize_usage_merges_episode_blocks():
    episodes = [
        {
            "usage": {
                "decisions_with_usage": 3,
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
                "api_calls": 3,
                "api_latency_ms": 10.0,
                "harness_latency_ms": 20.0,
                "cost_usd": 0.5,
                "model": "m",
                "provider": "p",
            }
        },
        {
            "usage": {
                "decisions_with_usage": 3,
                "input_tokens": 300,
                "output_tokens": 30,
                "total_tokens": 330,
                "api_calls": 3,
                "api_latency_ms": 30.0,
                "harness_latency_ms": 40.0,
                "cost_usd": 1.0,
                "model": "m",
                "provider": "p",
            }
        },
    ]
    merged = summarize_usage(episodes)
    assert merged["total_tokens"] == 440
    assert merged["cost_usd"] == pytest.approx(1.5)
    assert merged["harness_latency_ms"] == pytest.approx(60.0)
    assert merged["mean_tokens_per_decision"] == pytest.approx(440 / 6, abs=0.1)
    assert merged["model"] == "m"
