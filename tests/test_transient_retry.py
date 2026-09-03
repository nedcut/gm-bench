from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gm_bench.agents import Agent
from gm_bench.model_runs import (
    FailFastAgent,
    ModelRunAborted,
    TransientRetryAgent,
    transient_retry_agent,
)

UNKNOWN_COST = "provider call did not return authoritative finite cost telemetry"


class ScriptedAgent(Agent):
    """Return scripted (actions, usage) results in order, then repeat the last."""

    name = "test:model"
    pays_for_calls = True

    def __init__(self, results: list[tuple[list[dict[str, Any]], dict[str, Any] | None]]) -> None:
        self.results = list(results)
        self.calls = 0

    def act(self, observation):
        actions, _usage = self.act_with_usage(observation)
        return actions

    def act_with_usage(self, observation):
        index = min(self.calls, len(self.results) - 1)
        self.calls += 1
        return self.results[index]


def _rate_limited() -> tuple[list[dict[str, Any]], None]:
    return [{"type": "noop", "error": "api_error: HTTP 429 Too Many Requests; provider=Together"}], None


def _ok() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return [{"type": "noop"}], {"api_calls": 1, "cost_usd": 0.001, "output_tokens": 10}


def test_retries_a_rate_limited_decision_and_returns_only_the_paid_call() -> None:
    delays: list[float] = []
    inner = ScriptedAgent([_rate_limited(), _rate_limited(), _ok()])
    agent = TransientRetryAgent(inner, attempts=4, base_seconds=10, sleep=delays.append, log=lambda _m: None)

    actions, usage = agent.act_with_usage({"unused": True})

    assert actions == [{"type": "noop"}]
    assert usage["api_calls"] == 1
    assert usage["transient_retries"] == 2
    assert inner.calls == 3
    # Exponential base with bounded jitter: 10..12.5 then 20..25.
    assert 10 <= delays[0] <= 12.5 and 20 <= delays[1] <= 25


def test_gives_up_after_the_bounded_attempts_so_fail_fast_still_counts_it() -> None:
    inner = ScriptedAgent([_rate_limited()])
    agent = FailFastAgent(
        TransientRetryAgent(inner, attempts=2, base_seconds=0, sleep=lambda _s: None, log=lambda _m: None),
        threshold=2,
    )

    actions, _usage = agent.act_with_usage({"unused": True})
    assert "HTTP 429" in actions[0]["error"]
    assert inner.calls == 3  # first try plus two retries
    with pytest.raises(ModelRunAborted, match="2 consecutive model failures"):
        agent.act_with_usage({"unused": True})


@pytest.mark.parametrize(
    "error",
    [
        "protocol_error: null content",
        "api_error: HTTP 400 Bad Request",
        "model produced no usable actions",
        "spend_guard: next-call bound $1.0 would exceed ceiling",
    ],
)
def test_non_transient_errors_are_not_retried(error: str) -> None:
    inner = ScriptedAgent([([{"type": "noop", "error": error}], None)])
    agent = TransientRetryAgent(inner, attempts=3, base_seconds=0, sleep=lambda _s: None, log=lambda _m: None)

    actions, usage = agent.act_with_usage({"unused": True})

    assert actions[0]["error"] == error
    assert usage is None
    assert inner.calls == 1


def test_reconciles_the_spend_guard_block_before_retrying(tmp_path: Path) -> None:
    state_path = tmp_path / "guard.json"
    state_path.write_text(
        json.dumps(
            {
                "reported_spend_usd": 0.50,
                "active_call_reservation_usd": 0.0167,
                "active_call_input_token_bound": 91216,
                "blocked_reason": UNKNOWN_COST,
                "telemetry_error": "api_error: HTTP 503 Service Unavailable; provider=OpenAI",
                "ceiling_usd": 100.0,
            }
        )
    )
    blocked = ([{"type": "noop", "error": f"spend_guard: {UNKNOWN_COST}"}], None)
    inner = ScriptedAgent([blocked, _ok()])
    agent = TransientRetryAgent(
        inner, attempts=2, base_seconds=0, guard_state_path=state_path, sleep=lambda _s: None, log=lambda _m: None
    )

    actions, usage = agent.act_with_usage({"unused": True})

    assert actions == [{"type": "noop"}]
    assert usage["transient_retries"] == 1
    state = json.loads(state_path.read_text())
    assert "blocked_reason" not in state and "telemetry_error" not in state
    assert state["active_call_reservation_usd"] == 0.0
    assert state["reported_spend_usd"] == pytest.approx(0.5167)
    assert state["transient_retries"][0]["absorbed_reservation_usd"] == pytest.approx(0.0167)
    assert "HTTP 503" in state["transient_retries"][0]["error"]


def test_a_guard_block_for_any_other_reason_is_not_retried(tmp_path: Path) -> None:
    state_path = tmp_path / "guard.json"
    reason = "next-call bound $2.0 would exceed ceiling"
    state_path.write_text(json.dumps({"blocked_reason": reason, "active_call_reservation_usd": 0.0}))
    inner = ScriptedAgent([([{"type": "noop", "error": f"spend_guard: {reason}"}], None)])
    agent = TransientRetryAgent(
        inner, attempts=2, base_seconds=0, guard_state_path=state_path, sleep=lambda _s: None, log=lambda _m: None
    )

    agent.act_with_usage({"unused": True})

    assert inner.calls == 1
    assert json.loads(state_path.read_text())["blocked_reason"] == reason


def test_factory_reads_env_and_leaves_session_agents_and_disabled_lanes_alone(tmp_path: Path) -> None:
    from gm_bench.session import PersistentProcessAgent

    inner = ScriptedAgent([_ok()])
    wrapped = transient_retry_agent(
        inner,
        {
            "GM_BENCH_TRANSIENT_RETRY_ATTEMPTS": "3",
            "GM_BENCH_TRANSIENT_RETRY_BASE_SECONDS": "5",
            "GM_BENCH_OPENROUTER_SPEND_GUARD_STATE_PATH": str(tmp_path / "guard.json"),
        },
    )
    assert isinstance(wrapped, TransientRetryAgent)
    assert wrapped.attempts == 3 and wrapped.base_seconds == 5.0
    assert wrapped.guard_state_path == tmp_path / "guard.json"
    assert wrapped.pays_for_calls is True

    assert transient_retry_agent(inner, {"GM_BENCH_TRANSIENT_RETRY_ATTEMPTS": "0"}) is inner
    session = PersistentProcessAgent("true", timeout_seconds=1, env={}, name="session:model")
    assert transient_retry_agent(session, {}) is session
