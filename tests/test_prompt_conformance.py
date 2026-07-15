"""Regression test for the scaffold-prompt vs. contract drift class of bug.

The v1 scaffold advertised ``{"type":"scout","prospect_id":...}`` while the
simulator only read ``player_id`` and the JSON schema only required ``player_id``.
Models that copied the prompt's own example got a misleading "no such player"
error. This test extracts every action example embedded in the prompt builder
and asserts each one both validates against the action schema and (for scout
examples) is accepted by a fresh simulator — so re-introducing a prompt example
the contract rejects fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema

from examples.gm_agent_common import build_prompt
from gm_bench.simulator import League

_ACTION_SCHEMA = json.loads(Path("schemas/gm_action_list.schema.json").read_text())["$defs"]["action"]

# The only non-literal placeholder embedded in an example object: set_lineup's
# "[18 unique roster player ids]". Swap it for a valid 18-int list so the example
# parses; the schema still enforces the 18-item constraint on the substitute.
_LINEUP_PLACEHOLDER_RE = re.compile(r"\[[^\]]*\b(?:unique|roster|ids)\b[^\]]*\]")


def _extract_action_examples(prompt: str) -> list[dict[str, Any]]:
    """Pull every ``{...}`` action object out of the prompt's instruction block.

    Objects joined by " or " (e.g. the two scout examples) fall out naturally
    because each brace group is matched independently. The trailing observation
    JSON is excluded so its nested objects don't leak in.
    """
    header = prompt.split("Observation JSON:")[0]
    examples: list[dict[str, Any]] = []
    for candidate in re.findall(r"\{[^{}]*\}", header):
        if '"type"' not in candidate:
            continue  # skip the {"actions":[...]} envelope example
        sanitized = _LINEUP_PLACEHOLDER_RE.sub(json.dumps(list(range(1, 19))), candidate)
        examples.append(json.loads(sanitized))
    return examples


def _build_examples(phase: str = "preseason") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    league = League.new(seed=42)
    if phase == "trade_deadline":
        league.prepare_trade_deadline()
    observation = league.observation(phase)
    prompt = build_prompt(observation)
    examples = _extract_action_examples(prompt)
    # Guard the guard: if extraction silently found nothing, the schema assertion
    # below would vacuously pass. Every phase has a substantial action catalog.
    assert len(examples) >= 10, f"expected many extracted examples, got {len(examples)}"
    types = {example["type"] for example in examples}
    assert "scout" in types
    return observation, examples


def test_every_prompt_example_validates_against_action_schema() -> None:
    for phase in ("preseason", "midseason", "trade_deadline", "draft"):
        _, examples = _build_examples(phase)
        for example in examples:
            jsonschema.validate(example, _ACTION_SCHEMA)


def test_prompt_only_advertises_action_examples_available_in_current_phase() -> None:
    for phase in ("preseason", "midseason", "trade_deadline", "draft"):
        observation, examples = _build_examples(phase)
        advertised = {example["type"] for example in examples}
        assert advertised <= set(observation["available_actions"])


def test_phase_specific_examples_do_not_prime_unavailable_actions() -> None:
    _, preseason = _build_examples("preseason")
    _, midseason = _build_examples("midseason")
    _, draft = _build_examples("draft")

    assert "draft" not in {example["type"] for example in preseason}
    assert "claim_waiver" not in {example["type"] for example in preseason}
    assert "claim_waiver" in {example["type"] for example in midseason}
    assert "draft" in {example["type"] for example in draft}


def test_prompt_states_current_draft_action_limit() -> None:
    league = League.new(seed=42)
    prompt = build_prompt(league.observation("draft"))
    assert "Emit only action types listed in available_actions" in prompt
    assert "emit at most 1 draft action" in prompt

    league.user_team.draft_picks[league.season] = 0
    prompt = build_prompt(league.observation("draft"))
    assert "emit at most 0 draft actions" in prompt


def test_scout_prompt_examples_are_accepted_by_the_simulator() -> None:
    """Each scout example, with its id adapted to a real target, must be accepted."""
    _, examples = _build_examples()
    scout_examples = [example for example in examples if example["type"] == "scout"]
    # The prompt advertises both keys; both must survive execution.
    assert {key for example in scout_examples for key in ("player_id", "prospect_id") if key in example} == {
        "player_id",
        "prospect_id",
    }
    for example in scout_examples:
        league = League.new(seed=42)
        real_prospect = next(iter(league.prospects))
        adapted = dict(example)
        # Keep the advertised key, but point it at a real id in the shared namespace.
        if "prospect_id" in adapted:
            adapted["prospect_id"] = real_prospect
        else:
            adapted["player_id"] = real_prospect
        league.apply_actions([adapted], "preseason")
        transaction = league.transactions[-1]
        assert transaction.accepted, f"simulator rejected prompt scout example {example}: {transaction.message}"
