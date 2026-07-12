from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gm_bench.agents import Agent, ValueAgent
from gm_bench.model_runs import FailFastAgent, ModelRunAborted, run_resumable_candidate
from gm_bench.runner import run_many


class FailAfterAgent(Agent):
    name = "test:model"

    def __init__(self, successful_calls: int) -> None:
        self.successful_calls = successful_calls
        self.calls = 0
        self.value = ValueAgent()

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls += 1
        if self.calls > self.successful_calls:
            return [{"type": "noop", "model_error": "provider quota exhausted"}]
        return self.value.act(observation)


class CountingValueAgent(Agent):
    name = "test:model"

    def __init__(self) -> None:
        self.calls = 0
        self.value = ValueAgent()

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls += 1
        return self.value.act(observation)


def test_fail_fast_agent_aborts_after_consecutive_failures() -> None:
    agent = FailFastAgent(FailAfterAgent(successful_calls=0), threshold=2)
    observation = {"unused": True}
    actions, _usage = agent.act_with_usage(observation)
    assert actions[0]["model_error"] == "provider quota exhausted"
    with pytest.raises(ModelRunAborted, match="2 consecutive model failures"):
        agent.act_with_usage(observation)


def test_resumable_run_checkpoints_completed_repeats_before_abort(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    # One one-season episode is four decisions. Seed 1 completes, then seed 2
    # trips the circuit breaker on its second decision.
    agent = FailAfterAgent(successful_calls=4)
    with pytest.raises(ModelRunAborted):
        run_resumable_candidate(
            agent,
            seeds=[1, 2],
            seasons=1,
            repeats=1,
            checkpoint_path=checkpoint,
            fail_fast=2,
        )

    saved = json.loads(checkpoint.read_text())
    assert saved["status"] == "aborted"
    assert saved["completed"] == [{"repeat": 1, "seed": 1}]
    assert len(saved["episodes"]) == 1
    assert agent.calls == 6


def test_resume_source_reuses_only_zero_failure_seed_repeats(tmp_path: Path) -> None:
    source = tmp_path / "prior.json"
    prior = run_many(ValueAgent(), seeds=[13], seasons=1, repeats=3, workers=1)
    prior["agent"] = "test:model"
    prior["candidate"] = prior.copy()
    prior["candidate"]["agent"] = "test:model"
    prior["candidate"]["episodes"][2]["failed_decisions"] = 1
    source.write_text(json.dumps(prior))

    agent = CountingValueAgent()
    result = run_resumable_candidate(
        agent,
        seeds=[13],
        seasons=1,
        repeats=3,
        checkpoint_path=tmp_path / "checkpoint.json",
        resume_sources=[source],
    )

    # Repeats 1 and 2 came from the prior result; only failed repeat 3 reran.
    assert agent.calls == 4
    assert [episode["repeat"] for episode in result["episodes"]] == [1, 2, 3]
    assert result["summary"]["failed_decisions"] == 0


def test_resume_rejects_mismatched_agent(tmp_path: Path) -> None:
    source = tmp_path / "wrong.json"
    source.write_text(json.dumps({"agent": "other:model", "seasons": 1, "episodes": []}))
    with pytest.raises(ModelRunAborted, match="expected test:model"):
        run_resumable_candidate(
            CountingValueAgent(),
            seeds=[1],
            seasons=1,
            repeats=1,
            checkpoint_path=tmp_path / "checkpoint.json",
            resume_sources=[source],
        )
