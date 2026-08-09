from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gm_bench.agents import Agent
from gm_bench.providers import ProtocolRepairAgent, ProviderSpendGuardAgent, build_provider_agent


class _MeteredAgent(Agent):
    name = "metered"

    def __init__(self, responses: list[tuple[list[dict[str, Any]], dict[str, Any] | None]]) -> None:
        self.responses = responses
        self.calls = 0

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, _usage = self.act_with_usage(observation)
        return actions

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        response = self.responses[self.calls]
        self.calls += 1
        return response


def _guard(wrapped: Agent, state_path: Path, *, ceiling: float = 0.085) -> ProviderSpendGuardAgent:
    return ProviderSpendGuardAgent(
        wrapped,
        state_path=state_path,
        ceiling_usd=ceiling,
        measured_spend_floor_usd=0.0,
        prompt_rate_usd=0.000001,
        completion_rate_usd=0.00001,
        output_token_cap=4096,
        contingency_multiplier=1.0,
    )


def test_guard_checks_primary_repair_and_later_interaction_before_launch(tmp_path: Path) -> None:
    base = _MeteredAgent(
        [
            ([{"type": "noop", "model_error": "protocol_error: invalid json"}], {"api_calls": 1, "cost_usd": 0.01}),
            ([{"type": "end_turn"}], {"api_calls": 1, "cost_usd": 0.01}),
        ]
    )
    guarded = _guard(base, tmp_path / "guard.json")
    repaired = ProtocolRepairAgent(guarded, attempts=1)

    actions, usage = repaired.act_with_usage({"phase": "draft"})
    assert actions == [{"type": "end_turn"}]
    assert usage is not None and usage["cost_usd"] == pytest.approx(0.02)
    assert base.calls == 2, "both the primary and repair call passed through the guard"

    blocked, blocked_usage = repaired.act_with_usage({"phase": "draft", "interaction_round": 1})
    assert "spend_guard" in blocked[0]["error"]
    assert blocked_usage is None
    assert base.calls == 2, "the next interaction was blocked before launching the provider"


def test_guard_keeps_unknown_call_cost_reserved_and_fails_closed(tmp_path: Path) -> None:
    base = _MeteredAgent([([{"type": "end_turn"}], {"api_calls": 1})])
    state_path = tmp_path / "guard.json"
    guarded = _guard(base, state_path, ceiling=1.0)

    actions, usage = guarded.act_with_usage({"phase": "draft"})
    assert "authoritative finite cost telemetry" in actions[0]["error"]
    assert usage is None
    assert base.calls == 1
    state = json.loads(state_path.read_text())
    assert state["active_call_reservation_usd"] > 0
    assert state["blocked_reason"]

    actions, _usage = guarded.act_with_usage({"phase": "preseason"})
    assert "spend_guard" in actions[0]["error"]
    assert base.calls == 1


def test_guard_counts_full_observation_bytes_in_the_next_call_bound(tmp_path: Path) -> None:
    base = _MeteredAgent([])
    guarded = _guard(base, tmp_path / "guard.json", ceiling=1.0)
    small, _ = guarded._maximum_call_cost_usd({"phase": "draft"})
    large, _ = guarded._maximum_call_cost_usd({"phase": "draft", "payload": "x" * 50_000})

    assert large > small


def test_guard_uses_expensive_side_when_input_bound_straddles_price_tier(tmp_path: Path) -> None:
    base = _MeteredAgent([])
    untiered = _guard(base, tmp_path / "untiered.json", ceiling=1.0)
    tiered = ProviderSpendGuardAgent(
        base,
        state_path=tmp_path / "tiered.json",
        ceiling_usd=1.0,
        measured_spend_floor_usd=0.0,
        prompt_rate_usd=0.000001,
        completion_rate_usd=0.00001,
        output_token_cap=4096,
        contingency_multiplier=1.0,
        long_context_threshold=1,
        long_context_prompt_rate_usd=0.0000005,
        long_context_completion_rate_usd=0.000005,
    )

    ordinary, _ = untiered._maximum_call_cost_usd({"phase": "draft"})
    straddled, _ = tiered._maximum_call_cost_usd({"phase": "draft"})
    assert straddled == pytest.approx(ordinary)


def test_openrouter_build_places_guard_inside_protocol_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "GM_BENCH_OPENROUTER_SPEND_GUARD_"
    values = {
        "STATE_PATH": str(tmp_path / "guard.json"),
        "CEILING_USD": "100",
        "MEASURED_SPEND_FLOOR_USD": "0",
        "PROMPT_RATE_USD": "0.000001",
        "COMPLETION_RATE_USD": "0.00001",
        "OUTPUT_TOKEN_CAP": "4096",
        "REASONING_RATE_USD": "0",
        "REASONING_TOKEN_CAP": "0",
        "CONTINGENCY_MULTIPLIER": "1.2",
    }
    for suffix, value in values.items():
        monkeypatch.setenv(f"{prefix}{suffix}", value)

    agent = build_provider_agent("openrouter", model="test/model")

    assert isinstance(agent, ProtocolRepairAgent)
    assert isinstance(agent.wrapped, ProviderSpendGuardAgent)
