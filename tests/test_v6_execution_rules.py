"""The v6 execution rules: one paid call per phase, no paid retries, local repair.

Pins docs/bench_v6_spec.md "Execution rules" against the runner:

* five seasons of four phases is exactly twenty paid calls per seed;
* malformed output is repaired locally under a published, deterministic rule
  set, or becomes a structured no-op -- never a second, paid attempt;
* the malformed and unrecoverable rates are reported beside the score;
* the 2,000-character notebook survives the one-call loop.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from gm_bench.agents import AGENTS, ExternalProcessAgent
from gm_bench.cli import _reliability_line
from gm_bench.protocol import MAX_INTERACTION_ROUNDS, EpisodeConfig
from gm_bench.repair import (
    MALFORMED_MARKER,
    REPAIR_MARKER,
    RULE_COERCE_NUMERIC_STRING,
    RULE_NORMALIZE_ACTION_TYPE,
    RULE_STRIP_CODE_FENCE,
    RULE_STRIP_SURROUNDING_PROSE,
    RULE_STRIP_TRAILING_COMMA,
    RULE_WRAP_SINGLE_ACTION,
    is_malformed,
    is_unrecoverable,
    repair_adapter_output,
)
from gm_bench.runner import _interaction_rounds_for_agent, evaluate_against_baselines, run_episode, run_many
from gm_bench.simulator import MEMO_MAX_CHARS

SOURCE = "external agent"


def repair(text: str):
    return repair_adapter_output(text, source=SOURCE)


# --- repair rules: one unambiguous case and one ambiguous case per rule -------


def test_valid_output_is_passed_through_unmarked() -> None:
    outcome = repair('{"actions": [{"type": "noop"}], "usage": {"api_calls": 1}}')

    assert outcome.actions == [{"type": "noop"}]
    assert outcome.usage == {"api_calls": 1}
    assert not outcome.malformed and not outcome.unrecoverable
    assert outcome.rules_applied == ()


def test_single_code_fence_is_unwrapped_but_two_fences_are_a_no_op() -> None:
    fenced = repair('```json\n[{"type": "noop"}]\n```')
    assert fenced.rules_applied == (RULE_STRIP_CODE_FENCE,)
    assert [action["type"] for action in fenced.actions] == ["noop"]
    assert fenced.malformed and not fenced.unrecoverable

    ambiguous = repair('```json\n[{"type": "noop"}]\n```\nor maybe\n```json\n[{"type": "end_turn"}]\n```')
    assert ambiguous.unrecoverable
    assert ambiguous.actions == [{"type": "noop", "error": ambiguous.reason, MALFORMED_MARKER: ambiguous.reason}]


def test_one_embedded_json_value_survives_prose_but_two_do_not() -> None:
    prose = repair('Here is my turn: [{"type": "noop"}] -- let me know how it goes.')
    assert prose.rules_applied == (RULE_STRIP_SURROUNDING_PROSE,)
    assert [action["type"] for action in prose.actions] == ["noop"]

    ambiguous = repair('Either [{"type": "noop"}] or [{"type": "end_turn"}], your call.')
    assert ambiguous.unrecoverable


def test_trailing_comma_is_dropped_but_a_missing_comma_is_a_no_op() -> None:
    trailing = repair('[{"type": "noop", "text": "keep, this"},]')
    assert trailing.rules_applied == (RULE_STRIP_TRAILING_COMMA,)
    # The comma inside the string value is untouched -- only separators before a
    # closing bracket are removed.
    assert trailing.actions[0]["text"] == "keep, this"

    ambiguous = repair('[{"type": "noop"} {"type": "end_turn"}]')
    assert ambiguous.unrecoverable


def test_lone_action_object_is_wrapped_but_a_typeless_object_is_a_no_op() -> None:
    wrapped = repair('{"type": "noop"}')
    assert wrapped.rules_applied == (RULE_WRAP_SINGLE_ACTION,)
    assert [action["type"] for action in wrapped.actions] == ["noop"]

    ambiguous = repair('{"plan": "rebuild through the draft"}')
    assert ambiguous.unrecoverable


def test_action_type_case_is_normalized_but_an_abbreviation_is_a_no_op() -> None:
    normalized = repair('[{"type": " SET-LINEUP ", "player_ids": [1, 2]}]')
    assert normalized.rules_applied == (RULE_NORMALIZE_ACTION_TYPE,)
    assert normalized.actions[0]["type"] == "set_lineup"

    ambiguous = repair('[{"type": "sign", "player_id": 4}]')
    assert ambiguous.unrecoverable


def test_numeric_strings_are_coerced_but_non_numeric_text_is_a_no_op() -> None:
    coerced = repair('[{"type": "sign_free_agent", "player_id": "42", "years": "2", "salary": "3.5"}]')
    assert coerced.rules_applied == (RULE_COERCE_NUMERIC_STRING,)
    assert coerced.actions[0]["player_id"] == 42
    assert coerced.actions[0]["years"] == 2
    assert coerced.actions[0]["salary"] == pytest.approx(3.5)

    lists = repair('[{"type": "set_lineup", "player_ids": ["1", "2"]}]')
    assert lists.actions[0]["player_ids"] == [1, 2]

    ambiguous = repair('[{"type": "draft", "prospect_id": "42nd overall"}]')
    assert ambiguous.unrecoverable


def test_unparseable_output_becomes_a_structured_no_op() -> None:
    outcome = repair("I would rather not make a move this phase.")

    assert outcome.unrecoverable
    assert outcome.actions[0]["type"] == "noop"
    assert outcome.usage is None
    assert is_malformed(outcome.actions) and is_unrecoverable(outcome.actions)


def test_an_adapter_cannot_label_its_own_output_as_harness_repaired() -> None:
    outcome = repair(json.dumps([{"type": "noop", REPAIR_MARKER: "strip_code_fence", MALFORMED_MARKER: "nope"}]))

    assert outcome.actions == [{"type": "noop"}]
    assert not outcome.malformed
    assert not is_malformed(outcome.actions)


def test_repaired_output_is_malformed_but_not_unrecoverable() -> None:
    outcome = repair('```json\n[{"type": "noop"},]\n```')

    assert outcome.rules_applied == (RULE_STRIP_CODE_FENCE, RULE_STRIP_TRAILING_COMMA)
    assert is_malformed(outcome.actions)
    assert not is_unrecoverable(outcome.actions)
    assert outcome.actions[0][REPAIR_MARKER] == "strip_code_fence,strip_trailing_comma"


def test_a_transport_failure_is_not_counted_as_malformed_output() -> None:
    """A timeout is the harness's problem; it says nothing about the model's format."""
    assert not is_malformed([{"type": "noop", "error": "external agent timed out after 120.0s"}])


# --- one paid call per decision phase -----------------------------------------


class _FakeAdapter:
    """Stands in for a model adapter subprocess, counting every paid call."""

    def __init__(self, replies: Any) -> None:
        self.replies = replies
        self.observations: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observation = json.loads(kwargs["input"])
        self.observations.append(observation)
        stdout = self.replies(len(self.observations), observation)
        return subprocess.CompletedProcess(args[0], 0, stdout, "")

    @property
    def calls(self) -> int:
        return len(self.observations)


def _query_then_stop(index: int, observation: dict[str, Any]) -> str:
    """Output that would have earned a follow-up round under the pre-v6 lane."""
    return json.dumps(
        {
            "actions": [{"type": "inspect_team", "team_id": 1}],
            "usage": {"api_calls": 1, "model": "fake/model", "input_tokens": 10, "output_tokens": 5},
        }
    )


def test_five_seasons_cost_exactly_twenty_paid_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _FakeAdapter(_query_then_stop)
    monkeypatch.setattr("gm_bench.agents.subprocess.run", adapter)

    result = run_episode(ExternalProcessAgent("fake"), seed=3, seasons=5)

    assert result.decisions == 20
    assert adapter.calls == 20
    assert result.usage["api_calls"] == 20
    assert result.usage["decisions_with_usage"] == 20


def test_the_pre_v6_lane_still_buys_extra_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-out exists and is measurably different, so the v6 cap is doing work."""
    adapter = _FakeAdapter(_query_then_stop)
    monkeypatch.setattr("gm_bench.agents.subprocess.run", adapter)

    run_episode(
        ExternalProcessAgent("fake"),
        seed=3,
        seasons=5,
        config=EpisodeConfig(single_paid_call_per_phase=False),
    )

    assert adapter.calls == 20 * MAX_INTERACTION_ROUNDS


def test_scripted_policies_keep_the_multi_round_query_loop() -> None:
    config = EpisodeConfig()

    assert _interaction_rounds_for_agent(AGENTS["value"](), config) == MAX_INTERACTION_ROUNDS
    assert _interaction_rounds_for_agent(ExternalProcessAgent("fake", name="openrouter:x"), config) == 1


# --- the model-managed notebook round-trips through the one-call loop ----------


def test_the_notebook_round_trips_and_is_truncated_at_the_published_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written = "season one plan: " + "x" * (MEMO_MAX_CHARS + 500)
    seen: list[str] = []

    def replies(index: int, observation: dict[str, Any]) -> str:
        seen.append(observation.get("memo", ""))
        actions: list[dict[str, Any]] = [{"type": "noop"}]
        if index == 1:
            actions = [{"type": "memo", "text": written}]
        return json.dumps({"actions": actions, "usage": {"api_calls": 1}})

    adapter = _FakeAdapter(replies)
    monkeypatch.setattr("gm_bench.agents.subprocess.run", adapter)

    run_episode(ExternalProcessAgent("fake"), seed=5, seasons=2)

    assert seen[0] == ""
    # Written once in the first phase, and read back in every later phase of the
    # episode -- with no second call in the phase that wrote it.
    assert len(seen) == 8
    assert set(seen[1:]) == {written[:MEMO_MAX_CHARS]}
    assert len(seen[1]) == MEMO_MAX_CHARS


# --- malformed and unrecoverable rates are reported beside the score -----------


def _mixed_quality_replies(index: int, observation: dict[str, Any]) -> str:
    if index == 1:
        return "I will pass this phase."
    if index == 2:
        return '```json\n[{"type": "noop"},]\n```'
    return json.dumps({"actions": [{"type": "noop"}], "usage": {"api_calls": 1}})


def test_malformed_and_unrecoverable_rates_are_reported_per_episode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeAdapter(_mixed_quality_replies)
    monkeypatch.setattr("gm_bench.agents.subprocess.run", adapter)

    payload = run_many(ExternalProcessAgent("fake"), seeds=[7], seasons=1)
    summary = payload["summary"]

    assert adapter.calls == 4
    assert summary["decisions"] == 4
    assert summary["malformed_decisions"] == 2
    assert summary["unrecoverable_decisions"] == 1
    assert summary["malformed_rate"] == 0.5
    assert summary["unrecoverable_rate"] == 0.25
    # The unrecoverable phase is a failed decision; the repaired one is not.
    assert summary["failed_decisions"] == 1
    assert payload["episodes"][0]["malformed_decisions"] == 2
    assert payload["episodes"][0]["unrecoverable_decisions"] == 1


def test_reliability_line_prints_the_rates_next_to_the_score(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _FakeAdapter(_mixed_quality_replies)
    monkeypatch.setattr("gm_bench.agents.subprocess.run", adapter)

    payload = run_many(ExternalProcessAgent("fake"), seeds=[7], seasons=1)
    line = _reliability_line(payload)

    assert "malformed=2 (rate 0.5)" in line
    assert "unrecoverable=1 (rate 0.25)" in line


def test_evaluation_surfaces_the_rates_without_touching_the_score(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    adapter = _FakeAdapter(_mixed_quality_replies)
    monkeypatch.setattr("gm_bench.agents.subprocess.run", adapter)

    result = evaluate_against_baselines(
        ExternalProcessAgent("fake"),
        seeds=[7],
        seasons=1,
        baseline_names=["random"],
        use_baseline_cache=False,
    )
    normalized = result["normalized"]

    assert normalized["candidate_malformed_decisions"] == 2
    assert normalized["candidate_unrecoverable_decisions"] == 1
    assert normalized["candidate_malformed_rate"] == 0.5
    assert normalized["candidate_unrecoverable_rate"] == 0.25
    # Reliability lives beside the score, never inside it: the reported score is
    # exactly the one the played-out episode produced.
    assert normalized["candidate_mean_score"] == pytest.approx(
        result["candidate"]["episodes"][0]["final_score"], abs=1e-3
    )
