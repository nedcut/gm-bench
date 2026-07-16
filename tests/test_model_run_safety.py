from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gm_bench import model_runs
from gm_bench.agents import Agent, ValueAgent
from gm_bench.model_runs import (
    FailFastAgent,
    FailFastSessionAgent,
    ModelRunAborted,
    _checkpoint_lock,
    evaluate_resumable_candidate,
    fail_fast_agent,
    preflight_provider,
    run_resumable_candidate,
)
from gm_bench.runner import run_many
from gm_bench.session import PersistentProcessAgent


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


class ProviderCountingAgent(CountingValueAgent):
    metadata = {
        "provider": "claude",
        "model": "sonnet",
        "profile": "compact",
        "session": False,
    }


class MetadataCountingAgent(CountingValueAgent):
    def __init__(self, metadata: dict[str, Any]) -> None:
        super().__init__()
        self.metadata = metadata


def _write_resume_source(path: Path, metadata: dict[str, Any]) -> None:
    prior = run_many(ValueAgent(), seeds=[1], seasons=1, workers=1)
    prior["agent"] = "test:model"
    prior["candidate"] = prior.copy()
    prior["candidate"]["agent"] = "test:model"
    prior["run_info"] = {**metadata, **model_runs._resume_provenance(metadata)}
    path.write_text(json.dumps(prior))


def test_fail_fast_agent_aborts_after_consecutive_failures() -> None:
    agent = FailFastAgent(FailAfterAgent(successful_calls=0), threshold=2)
    observation = {"unused": True}
    actions, _usage = agent.act_with_usage(observation)
    assert actions[0]["model_error"] == "provider quota exhausted"
    with pytest.raises(ModelRunAborted, match="2 consecutive model failures"):
        agent.act_with_usage(observation)


def test_fail_fast_agent_preserves_protocol_failures_as_model_behavior() -> None:
    class ProtocolFailureAgent(Agent):
        name = "protocol-failure"

        def act(self, observation):
            return [{"type": "noop", "model_error": "protocol_error: null content"}]

    agent = FailFastAgent(ProtocolFailureAgent(), threshold=2)
    for _ in range(5):
        actions, _usage = agent.act_with_usage({"unused": True})
        assert actions[0]["model_error"].startswith("protocol_error:")
    assert agent.consecutive_failures == 0


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


def test_resume_rejects_missing_expected_profile(tmp_path: Path) -> None:
    source = tmp_path / "missing-profile.json"
    expected_metadata = {
        "provider": "claude",
        "model": "sonnet",
        "profile": "compact",
        "session": False,
    }
    source_metadata = dict(expected_metadata)
    del source_metadata["profile"]
    _write_resume_source(source, source_metadata)

    with pytest.raises(ModelRunAborted, match="missing profile"):
        run_resumable_candidate(
            MetadataCountingAgent(expected_metadata),
            seeds=[1],
            seasons=1,
            repeats=1,
            checkpoint_path=tmp_path / "checkpoint.json",
            resume_sources=[source],
        )


def test_resume_rejects_differing_provider_option(tmp_path: Path) -> None:
    source = tmp_path / "different-provider-option.json"
    expected_metadata = {
        "provider": "claude",
        "model": "sonnet",
        "profile": "compact",
        "session": False,
        "provider_options": {"OPENROUTER_MAX_TOKENS": "2048"},
    }
    source_metadata = {
        **expected_metadata,
        "provider_options": {"OPENROUTER_MAX_TOKENS": "1024"},
    }
    _write_resume_source(source, source_metadata)

    with pytest.raises(ModelRunAborted, match="OPENROUTER_MAX_TOKENS"):
        run_resumable_candidate(
            MetadataCountingAgent(expected_metadata),
            seeds=[1],
            seasons=1,
            repeats=1,
            checkpoint_path=tmp_path / "checkpoint.json",
            resume_sources=[source],
        )


def test_resume_rejects_missing_provider_options(tmp_path: Path) -> None:
    source = tmp_path / "missing-provider-options.json"
    expected_metadata = {
        "provider": "claude",
        "model": "sonnet",
        "profile": "compact",
        "session": False,
        "provider_options": {"OPENROUTER_MAX_TOKENS": "2048"},
    }
    source_metadata = {key: value for key, value in expected_metadata.items() if key != "provider_options"}
    _write_resume_source(source, source_metadata)

    with pytest.raises(ModelRunAborted, match="OPENROUTER_MAX_TOKENS"):
        run_resumable_candidate(
            MetadataCountingAgent(expected_metadata),
            seeds=[1],
            seasons=1,
            repeats=1,
            checkpoint_path=tmp_path / "checkpoint.json",
            resume_sources=[source],
        )


def test_resume_accepts_string_normalized_provider_options(tmp_path: Path) -> None:
    source = tmp_path / "normalized-provider-options.json"
    expected_metadata = {
        "provider": "claude",
        "model": "sonnet",
        "profile": "compact",
        "session": False,
        "provider_options": {"OPENROUTER_MAX_TOKENS": "1024"},
    }
    source_metadata = {
        **expected_metadata,
        "provider_options": {"OPENROUTER_MAX_TOKENS": 1024},
    }
    _write_resume_source(source, source_metadata)
    agent = MetadataCountingAgent(expected_metadata)

    result = run_resumable_candidate(
        agent,
        seeds=[1],
        seasons=1,
        repeats=1,
        checkpoint_path=tmp_path / "checkpoint.json",
        resume_sources=[source],
    )

    assert agent.calls == 0
    assert len(result["episodes"]) == 1


def test_default_checkpoint_path_separates_profile_and_session_lanes() -> None:
    default = model_runs.default_checkpoint_path("openrouter:openai/gpt-5.6-luna")
    compact = model_runs.default_checkpoint_path(
        "openrouter:openai/gpt-5.6-luna",
        {"profile": "compact", "session": False},
    )
    compact_session = model_runs.default_checkpoint_path(
        "openrouter:openai/gpt-5.6-luna",
        {"profile": "compact", "session": True},
    )

    assert default.name == "openrouter-openai-gpt-5.6-luna.json"
    assert compact.name == "openrouter-openai-gpt-5.6-luna--compact.json"
    assert compact_session.name == "openrouter-openai-gpt-5.6-luna--compact--session.json"
    assert len({default, compact, compact_session}) == 3


def test_resume_rejects_mismatched_contract(tmp_path: Path) -> None:
    source = tmp_path / "stale.json"
    prior = run_many(ValueAgent(), seeds=[1], seasons=1, workers=1)
    prior["agent"] = "test:model"
    prior["candidate"] = prior.copy()
    prior["candidate"]["agent"] = "test:model"
    prior["run_info"] = {
        **ProviderCountingAgent.metadata,
        "benchmark_contract": {"contract_fingerprint": "stale"},
        "scaffold_fingerprint": "stale",
    }
    source.write_text(json.dumps(prior))

    with pytest.raises(ModelRunAborted, match="current benchmark contract"):
        run_resumable_candidate(
            ProviderCountingAgent(),
            seeds=[1],
            seasons=1,
            repeats=1,
            checkpoint_path=tmp_path / "checkpoint.json",
            resume_sources=[source],
        )


def test_resume_rejects_conflicting_successful_duplicates(tmp_path: Path) -> None:
    prior = run_many(ValueAgent(), seeds=[1], seasons=1, workers=1)
    prior["agent"] = "test:model"
    prior["candidate"] = prior.copy()
    prior["candidate"]["agent"] = "test:model"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(prior))
    prior["candidate"]["episodes"][0]["final_score"] += 1
    second.write_text(json.dumps(prior))

    with pytest.raises(ModelRunAborted, match="conflicting successful episodes"):
        run_resumable_candidate(
            CountingValueAgent(),
            seeds=[1],
            seasons=1,
            repeats=1,
            checkpoint_path=tmp_path / "checkpoint.json",
            resume_sources=[first, second],
        )


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        '{"candidate": []}',
        '{"agent": "test:model", "seasons": "bad", "episodes": []}',
        '{"agent": "test:model", "seasons": 1, "metadata": [], "episodes": []}',
        '{"agent": "test:model", "seasons": 1, "episodes": {}}',
        '{"agent": "test:model", "seasons": 1, "episodes": [{}]}',
    ],
)
def test_resume_rejects_malformed_payloads(tmp_path: Path, payload: str) -> None:
    source = tmp_path / "malformed.json"
    source.write_text(payload)

    with pytest.raises(ModelRunAborted, match="resume source"):
        run_resumable_candidate(
            CountingValueAgent(),
            seeds=[1],
            seasons=1,
            repeats=1,
            checkpoint_path=tmp_path / "checkpoint.json",
            resume_sources=[source],
        )


def test_checkpoint_lock_rejects_a_concurrent_writer(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.json"

    with _checkpoint_lock(checkpoint):
        with pytest.raises(ModelRunAborted, match="already in use"):
            run_resumable_candidate(
                CountingValueAgent(),
                seeds=[1],
                seasons=1,
                repeats=1,
                checkpoint_path=checkpoint,
            )


def test_claude_preflight_normalizes_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_runs.shutil, "which", lambda executable: None)

    with pytest.raises(ModelRunAborted, match="not installed"):
        preflight_provider("claude")


def test_claude_preflight_normalizes_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_runs.shutil, "which", lambda executable: "/usr/bin/claude")

    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("claude", 15)

    monkeypatch.setattr(model_runs.subprocess, "run", timeout)

    with pytest.raises(ModelRunAborted, match="timed out"):
        preflight_provider("claude")


def test_uncached_scripted_baselines_keep_normal_parallel_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = run_many(ValueAgent(), seeds=[1], seasons=1, workers=1)
    seen_workers: list[int | None] = []
    original = model_runs.run_many

    def capture(*args: object, **kwargs: object) -> dict[str, Any]:
        seen_workers.append(kwargs.get("workers"))
        return original(*args, **kwargs)

    monkeypatch.setattr(model_runs, "run_many", capture)

    evaluate_resumable_candidate(candidate, ["value"], use_baseline_cache=False)

    assert seen_workers == [None]


class ScriptedSessionAgent(PersistentProcessAgent):
    """In-process session agent double: real class, no subprocess."""

    def __init__(self) -> None:
        super().__init__(command="true", name="test:session")
        self.started: list[tuple[int, int]] = []
        self.ended = 0
        self.value = ValueAgent()

    def start_episode(self, seed: int, seasons: int) -> None:
        self.started.append((seed, seasons))

    def end_episode(self) -> None:
        self.ended += 1

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        return self.value.act(observation), None

    def act_on_results_with_usage(
        self,
        results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        return [{"type": "noop"}], None

    def clone(self) -> "ScriptedSessionAgent":
        return self


class FailingSessionAgent(ScriptedSessionAgent):
    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        return [{"type": "noop", "model_error": "session boom"}], None

    def act_on_results_with_usage(
        self,
        results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        return [{"type": "noop", "model_error": "session boom"}], None


def test_fail_fast_factory_picks_session_wrapper_for_persistent_agents() -> None:
    session_wrapped = fail_fast_agent(ScriptedSessionAgent(), 2)
    plain_wrapped = fail_fast_agent(FailAfterAgent(successful_calls=0), 2)
    # The frozen runner dispatches episode lifecycle on this isinstance check;
    # losing it means the adapter process is never spawned.
    assert isinstance(session_wrapped, PersistentProcessAgent)
    assert isinstance(session_wrapped, FailFastSessionAgent)
    assert isinstance(plain_wrapped, FailFastAgent)
    assert not isinstance(plain_wrapped, PersistentProcessAgent)


def test_wrapped_session_agent_still_gets_episode_lifecycle_from_runner() -> None:
    inner = ScriptedSessionAgent()
    wrapped = fail_fast_agent(inner, 2)
    run_many(wrapped, seeds=[1], seasons=1, workers=1)
    assert inner.started == [(1, 1)]
    assert inner.ended == 1


def test_session_fail_fast_counts_multi_round_results_and_shares_state_across_clones() -> None:
    wrapped = fail_fast_agent(FailingSessionAgent(), 2)
    actions, _usage = wrapped.act_with_usage({})
    assert actions[0]["model_error"] == "session boom"
    clone = wrapped.clone()
    with pytest.raises(ModelRunAborted, match="2 consecutive model failures"):
        clone.act_on_results_with_usage([])


def test_session_fail_fast_wrapper_covers_the_whole_persistent_agent_surface() -> None:
    # FailFastSessionAgent subclasses PersistentProcessAgent for the runner's
    # isinstance dispatch but skips super().__init__(), so it owns none of the
    # process state its inherited methods assume. Every public method must
    # therefore be explicitly overridden to delegate to ``inner``. This test
    # fails the moment someone adds a method to PersistentProcessAgent without
    # overriding it here -- which would otherwise surface as an AttributeError
    # mid-run, after the quota is spent.
    inherited = {
        name
        for name in vars(PersistentProcessAgent)
        if not name.startswith("_") and callable(getattr(PersistentProcessAgent, name))
    }
    overridden = set(vars(FailFastSessionAgent))
    missing = inherited - overridden
    assert not missing, (
        f"FailFastSessionAgent inherits {sorted(missing)} from PersistentProcessAgent without overriding them; "
        "they would run against process state this wrapper never initialized"
    )


def test_session_fail_fast_wrapper_delegates_unknown_attributes_to_inner() -> None:
    # Backstop for the above: even an un-overridden attribute resolves against
    # the real agent rather than exploding.
    inner = ScriptedSessionAgent()
    inner.transport = "stdio"
    wrapped = fail_fast_agent(inner, 2)
    assert wrapped.transport == "stdio"
    with pytest.raises(AttributeError):
        _ = wrapped.definitely_not_a_real_attribute
