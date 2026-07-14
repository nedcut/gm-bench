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
import pytest

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


def _build_examples() -> list[dict[str, Any]]:
    prompt = build_prompt(League.new(seed=42).observation("preseason"))
    examples = _extract_action_examples(prompt)
    # Guard the guard: if extraction silently found nothing, the schema assertion
    # below would vacuously pass. The prompt lists well over a dozen actions.
    assert len(examples) >= 15, f"expected many extracted examples, got {len(examples)}"
    types = {example["type"] for example in examples}
    assert "scout" in types
    return examples


def test_every_prompt_example_validates_against_action_schema() -> None:
    for example in _build_examples():
        jsonschema.validate(example, _ACTION_SCHEMA)


def test_one_year_extension_is_rejected_by_the_action_schema() -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"type": "extend_contract", "player_id": 1, "years": 1, "salary": 2.0},
            _ACTION_SCHEMA,
        )


def test_scout_prompt_examples_are_accepted_by_the_simulator() -> None:
    """Each scout example, with its id adapted to a real target, must be accepted."""
    scout_examples = [example for example in _build_examples() if example["type"] == "scout"]
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
