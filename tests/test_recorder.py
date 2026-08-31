"""Tests for opt-in decision recording.

Two properties are load-bearing:

* Recording must not touch the frozen contract sources, so ``record_episode``
  mirrors ``run_episode``'s loop instead of hooking it. The mirror is only safe
  if it stays faithful, which is what the equivalence test pins.
* A ghost must not leak into the run it is illustrating.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from gm_bench.agents import AGENTS
from gm_bench.contract import contract_fingerprint, scaffold_fingerprint
from gm_bench.model_runs import ModelRunAborted, preflight_provider
from gm_bench.protocol import EpisodeConfig
from gm_bench.recorder import (
    CANONICAL_FLOAT_DECIMALS,
    DEFAULT_GHOSTS,
    IMMEDIATE_METRICS,
    RECORD_SCHEMA,
    DecisionRecorder,
    _ghost_config,
    canonical_state,
    canonical_state_digest,
    canonicalize_state,
    component_delta,
    probe_observation,
    record_episode,
    validate_replay_fixture,
)
from gm_bench.runner import run_episode
from gm_bench.scoring import score_components, score_team
from gm_bench.session import PersistentProcessAgent
from gm_bench.simulator import League


class _SummaryTolerantAgent:
    """Stands in for a model adapter: reads a summary view without crashing."""

    name = "external"

    def act(self, observation: dict) -> list[dict]:
        return [{"type": "noop"}]

    def act_with_usage(self, observation: dict) -> tuple[list[dict], None]:
        return self.act(observation), None


class _CompactModelAgent(_SummaryTolerantAgent):
    name = "fake-model"
    metadata = {"provider": "ollama", "model": "fake-1", "profile": "tiny", "strict_fallback": True}


def _record(tmp_path: Path, agent_name: str, *, seed: int = 11, seasons: int = 2, **kwargs: object) -> list[dict]:
    path = tmp_path / "decisions.jsonl"
    with DecisionRecorder(path, agent_name=agent_name, **kwargs) as recorder:  # type: ignore[arg-type]
        record_episode(AGENTS[agent_name](), seed=seed, recorder=recorder, seasons=seasons)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_recording_leaves_the_frozen_contract_alone(tmp_path: Path) -> None:
    """Importing the recorder must not move the byte-exact contract fingerprint."""
    recorder = DecisionRecorder(tmp_path / "probe.jsonl", agent_name="probe", ghost_agents=None)
    try:
        assert recorder.provenance["contract_fingerprint"] == contract_fingerprint()
    finally:
        recorder.close()


def test_recorded_episode_matches_run_episode() -> None:
    """The mirrored loop plays the same episode the benchmark loop does.

    This is what makes it safe to keep recording outside ``runner.py``. If the
    orchestration in ``run_episode`` changes and the mirror does not, this fails.
    """
    for agent_name in ("conservative", "value", "win-now"):
        for seed in (3, 11):
            expected = run_episode(AGENTS[agent_name](), seed=seed, seasons=2)
            recorder = DecisionRecorder(Path("/dev/null"), agent_name=agent_name, ghost_agents=None)
            try:
                league = record_episode(AGENTS[agent_name](), seed=seed, recorder=recorder, seasons=2)
            finally:
                recorder.close()

            assert round(score_team(league, 0), 3) == expected.final_score, agent_name
            assert [t.__dict__ for t in league.transactions] == expected.transactions, agent_name
            assert league.user_team.championships == expected.championships, agent_name
            assert league.illegal_actions == expected.illegal_actions, agent_name


def test_ghosts_do_not_change_the_recorded_episode(tmp_path: Path) -> None:
    """Four ghosts per decision must leave the subject's episode identical."""
    expected = run_episode(AGENTS["conservative"](), seed=11, seasons=2)
    with DecisionRecorder(tmp_path / "d.jsonl", agent_name="conservative") as recorder:
        league = record_episode(AGENTS["conservative"](), seed=11, recorder=recorder, seasons=2)
    assert round(score_team(league, 0), 3) == expected.final_score
    assert [t.__dict__ for t in league.transactions] == expected.transactions


def test_probe_observation_does_not_disturb_the_league() -> None:
    league = League.new(seed=11)
    before = score_components(league, league.user_team_id)
    observation = probe_observation(league, "preseason", "full")
    assert observation["phase"] == "preseason"
    assert score_components(league, league.user_team_id) == before
    assert league.transactions == []


def test_probe_observation_is_stable() -> None:
    """Two probes of the same state agree, so a record shows what the agent saw."""
    league = League.new(seed=7)
    assert probe_observation(league, "preseason", "full") == probe_observation(league, "preseason", "full")


def test_records_cover_every_decision_window(tmp_path: Path) -> None:
    records = _record(tmp_path, "conservative", seasons=2)
    assert len(records) == 8  # four phases per season
    assert [record["decision_index"] for record in records] == list(range(1, 9))
    assert {record["season"] for record in records} == {1, 2}
    assert all(record["schema"] == RECORD_SCHEMA for record in records)
    assert all(record["seed"] == 11 for record in records)


def test_record_carries_both_sides_of_the_comparison(tmp_path: Path) -> None:
    records = _record(tmp_path, "conservative")
    first = records[0]
    assert first["observation"]["phase"] == "preseason"
    assert [ghost["agent"] for ghost in first["ghosts"]] == list(DEFAULT_GHOSTS)
    for side in (first["delta"], *(ghost["delta"] for ghost in first["ghosts"])):
        for metric in IMMEDIATE_METRICS:
            assert metric in side
            assert f"{metric}_contribution" in side


def test_recorded_actions_are_the_agents_own(tmp_path: Path) -> None:
    """Opponent draft picks share the transaction log and must not leak in."""
    records = _record(tmp_path, "value", seasons=2)
    draft = next(record for record in records if record["phase"] == "draft")
    assert draft["actions"], "the subject acted at the draft"
    assert all(isinstance(action, dict) and "type" in action for action in draft["actions"])
    for ghost in draft["ghosts"]:
        assert all("type" in action for action in ghost["actions"])


def test_ghosts_are_held_to_the_subjects_observation_tier() -> None:
    """A ghost shown more than the subject would confound choice with view."""
    subject_view = EpisodeConfig(observation_tier="summary")
    ghost_view = _ghost_config(subject_view, "summary")
    assert ghost_view.observation_tier == "summary"
    assert ghost_view.builtin_full_observation is False
    # Everything else about the window is untouched.
    assert ghost_view.max_interaction_rounds == subject_view.max_interaction_rounds
    assert ghost_view.include_midseason == subject_view.include_midseason


def test_a_ghost_that_cannot_read_the_view_is_recorded_not_raised(tmp_path: Path) -> None:
    """Scripted policies expect a full observation; a summary-tier subject
    starves them. Losing a card must never cost the episode."""
    path = tmp_path / "d.jsonl"
    config = EpisodeConfig(observation_tier="summary", builtin_full_observation=False)
    with DecisionRecorder(path, agent_name="external", ghost_agents=["pick-trader"]) as recorder:
        league = record_episode(_SummaryTolerantAgent(), seed=11, recorder=recorder, seasons=1, config=config)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 4
    assert all("error" in record["ghosts"][0] for record in records)
    assert league.season == 2, "the episode still finished"


def test_delta_omits_metrics_a_decision_cannot_move() -> None:
    for metric in ("recent_wins", "playoff_rounds", "championships"):
        assert metric not in IMMEDIATE_METRICS


def test_component_delta_is_a_plain_difference() -> None:
    zeros = {name: 0.0 for name in IMMEDIATE_METRICS}
    zeros.update({f"{name}_contribution": 0.0 for name in IMMEDIATE_METRICS})
    delta = component_delta(
        {**zeros, "total_assets": 10.0, "total_assets_contribution": 1.6},
        {**zeros, "total_assets": 12.5, "total_assets_contribution": 2.0},
    )
    assert delta["total_assets"] == 2.5
    assert delta["total_assets_contribution"] == 0.4


def test_observation_can_be_dropped(tmp_path: Path) -> None:
    records = _record(tmp_path, "conservative", include_observation=False)
    assert all("observation" not in record for record in records)


def test_ghosts_can_be_disabled(tmp_path: Path) -> None:
    records = _record(tmp_path, "conservative", ghost_agents=None)
    assert all(record["ghosts"] == [] for record in records)


def test_a_single_ghost_name_is_accepted(tmp_path: Path) -> None:
    records = _record(tmp_path, "conservative", ghost_agents="value")
    assert all([ghost["agent"] for ghost in record["ghosts"]] == ["value"] for record in records)


def test_ghost_order_does_not_change_ghost_results(tmp_path: Path) -> None:
    """Each ghost runs on its own copy, so one cannot bias the next."""
    forward = _record(tmp_path, "conservative", seasons=1, ghost_agents=["pick-trader", "value"])
    reverse = _record(tmp_path, "conservative", seasons=1, ghost_agents=["value", "pick-trader"])
    for ahead, behind in zip(forward, reverse):
        by_name = {ghost["agent"]: ghost["delta"] for ghost in behind["ghosts"]}
        for ghost in ahead["ghosts"]:
            assert ghost["delta"] == by_name[ghost["agent"]]


def test_unknown_ghost_is_rejected(tmp_path: Path) -> None:
    try:
        DecisionRecorder(tmp_path / "d.jsonl", agent_name="probe", ghost_agents=["not-an-agent"])
    except ValueError as exc:
        assert "not-an-agent" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for an unknown ghost agent")


def test_model_records_compact_view_and_provenance(tmp_path: Path) -> None:
    path = tmp_path / "model.jsonl"
    with DecisionRecorder(
        path, agent_name="fake-model", ghost_agents=["value"], agent_metadata=_CompactModelAgent.metadata
    ) as recorder:
        record_episode(_CompactModelAgent(), seed=11, recorder=recorder, seasons=1)
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert first["agent_metadata"]["profile"] == "tiny"
    assert first["provenance"]["contract_fingerprint"] == contract_fingerprint()
    assert first["provenance"]["scaffold_fingerprint"] == scaffold_fingerprint("ollama")
    assert "seed" not in first["observation"]
    # The compact profile makes the scripted ghost use the scaffold view too.
    assert first["ghosts"][0]["interaction_rounds"]


def test_persistent_recording_preserves_lifecycle_and_follow_up_dispatch(tmp_path: Path) -> None:
    class QueryThenEndSession(PersistentProcessAgent):
        def __init__(self) -> None:
            super().__init__("unused", name="test:session")
            self.events: list[object] = []
            self.started = False

        def start_episode(self, seed: int, seasons: int) -> None:
            self.started = True
            self.events.append(("start", seed, seasons))

        def end_episode(self) -> None:
            self.events.append("end")
            self.started = False

        def act_with_usage(self, observation: dict) -> tuple[list[dict], None]:
            assert self.started
            self.events.append("observation")
            return [{"type": "inspect_team", "team_id": 1}], None

        def act_on_results_with_usage(self, results: list[dict]) -> tuple[list[dict], None]:
            assert self.started
            self.events.append(("action_results", results))
            return [{"type": "end_turn"}], None

    path = tmp_path / "session.jsonl"
    agent = QueryThenEndSession()
    with DecisionRecorder(path, agent_name=agent.name, ghost_agents=None) as recorder:
        record_episode(
            agent,
            seed=11,
            recorder=recorder,
            seasons=1,
            config=EpisodeConfig(max_interaction_rounds=2),
        )

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert agent.events[0] == ("start", 11, 1)
    assert agent.events[-1] == "end"
    assert [event if isinstance(event, str) else event[0] for event in agent.events].count("observation") == 4
    assert [event if isinstance(event, str) else event[0] for event in agent.events].count("action_results") == 4
    assert all(len(record["interaction_rounds"]) == 2 for record in records)
    assert all("observation" in record["interaction_rounds"][0] for record in records)
    assert all("action_results" in record["interaction_rounds"][1] for record in records)


def test_replay_fixture_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "decisions.jsonl"
    fixture_path = tmp_path / "decisions.replay.json"
    with DecisionRecorder(path, agent_name="value", ghost_agents=None) as recorder:
        league = record_episode(AGENTS["value"](), seed=11, recorder=recorder, seasons=1)
        recorder.export_replay_fixture(fixture_path, league, config=EpisodeConfig())
    result = validate_replay_fixture(fixture_path)
    assert result["valid"] is True
    assert result["decisions"] == 4


@pytest.mark.parametrize("rounds", [{}, "bad", [None], [1]])
def test_replay_fixture_rejects_malformed_interaction_rounds(tmp_path: Path, rounds: object) -> None:
    path = tmp_path / "decisions.jsonl"
    fixture_path = tmp_path / "decisions.replay.json"
    with DecisionRecorder(path, agent_name="value", ghost_agents=None) as recorder:
        league = record_episode(AGENTS["value"](), seed=11, recorder=recorder, seasons=1)
        recorder.export_replay_fixture(fixture_path, league, config=EpisodeConfig())
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["decisions"][0]["interaction_rounds"] = rounds

    with pytest.raises(ValueError, match="interaction_rounds|interaction rounds"):
        validate_replay_fixture(fixture)


def test_canonical_state_rounds_float_tails_but_preserves_material_changes() -> None:
    base = {"nested": {3: 1.2345678901234}, "zero": -0.0}
    sub_precision = {"nested": {"3": 1.23456789012344}, "zero": 0.0}
    material = {"nested": {"3": 1.2345678901244}, "zero": 0.0}
    assert CANONICAL_FLOAT_DECIMALS == 12
    assert canonical_state_digest(base) == canonical_state_digest(sub_precision)
    assert canonical_state_digest(base) != canonical_state_digest(material)
    assert canonicalize_state(base) == {"nested": {"3": 1.234567890123}, "zero": 0.0}


def test_replay_fixture_expected_state_is_normalized(tmp_path: Path) -> None:
    path = tmp_path / "decisions.jsonl"
    fixture_path = tmp_path / "decisions.replay.json"
    with DecisionRecorder(path, agent_name="value", ghost_agents=None) as recorder:
        league = record_episode(AGENTS["value"](), seed=11, recorder=recorder, seasons=1)
        recorder.export_replay_fixture(fixture_path, league, config=EpisodeConfig())
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["expected"]["state"] == canonical_state(league)
    assert fixture["expected"]["state_digest"] == canonical_state_digest(league)


def test_canonicalize_state_rejects_non_finite_float() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonicalize_state({"bad": float("nan")})


def test_recording_preflight_requires_credentials_without_completion(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ModelRunAborted, match="OPENAI_API_KEY"):
        preflight_provider("openai", require_credentials=True)


def test_recording_provider_defaults_to_strict_fallback(tmp_path: Path, monkeypatch) -> None:
    script = importlib.import_module("scripts.record_decisions")
    seen: dict[str, object] = {}

    monkeypatch.setattr(script, "preflight_provider", lambda provider, **kwargs: seen.update(kwargs))

    def fake_build(provider: str, **kwargs: object):
        seen.update(kwargs)
        return AGENTS["value"]()

    monkeypatch.setattr(script, "build_provider_agent", fake_build)
    assert (
        script.main(
            [
                "--provider",
                "openai",
                "--seeds",
                "1",
                "--seasons",
                "0",
                "--ghosts",
                "value",
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert seen["require_credentials"] is True
    assert seen["strict_fallback"] is True


def test_recording_provider_aborts_repeated_failures_outside_builder_input(tmp_path: Path, monkeypatch) -> None:
    script = importlib.import_module("scripts.record_decisions")
    output = tmp_path / "records"

    class BrokenProvider(_SummaryTolerantAgent):
        name = "openai:broken"
        metadata = {"provider": "openai", "model": "broken", "profile": "compact"}

        def act_with_usage(self, observation: dict) -> tuple[list[dict], None]:
            return [{"type": "noop", "model_error": "backend unavailable"}], None

    monkeypatch.setattr(script, "preflight_provider", lambda provider, **kwargs: None)
    monkeypatch.setattr(script, "build_provider_agent", lambda provider, **kwargs: BrokenProvider())

    with pytest.raises(SystemExit) as exc_info:
        script.main(
            [
                "--provider",
                "openai",
                "--seeds",
                "1",
                "--seasons",
                "1",
                "--ghosts",
                "value",
                "--output",
                str(output),
            ]
        )
    assert exc_info.value.code == 2
    assert not list(output.glob("*.jsonl"))
    assert list(output.glob("*.partial"))


def test_recording_preflight_failure_creates_no_output(tmp_path: Path, monkeypatch) -> None:
    script = importlib.import_module("scripts.record_decisions")
    output = tmp_path / "records"

    def fail_preflight(provider: str, **kwargs: object) -> None:
        raise ModelRunAborted("preflight blocked")

    monkeypatch.setattr(script, "preflight_provider", fail_preflight)
    with pytest.raises(SystemExit) as exc_info:
        script.main(["--provider", "openai", "--seeds", "1", "--output", str(output)])
    assert exc_info.value.code == 2
    assert not output.exists()
