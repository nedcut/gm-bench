"""The "How it works" walkthrough is derived from the public demo game and the 2.0 contract."""

import json

from gm_bench.agentic.brief import task_brief
from gm_bench.agentic.tools import TOOLS
from scripts import build_walkthrough as walkthrough


def test_committed_walkthrough_matches_its_source():
    built = json.dumps(walkthrough.build(json.loads(walkthrough.SOURCE.read_text())), indent=1, sort_keys=True) + "\n"
    assert walkthrough.DESTINATION.read_text() == built, "run scripts/build_walkthrough.py"


def test_walkthrough_carries_the_contract_brief_and_every_tool():
    data = json.loads(walkthrough.DESTINATION.read_text())
    assert data["brief"] == task_brief(5, data["team"]["name"], data["team"]["id"])
    assert [tool["name"] for tool in data["tools"]] == [tool["name"] for tool in TOOLS]
    assert [step["phase"] for step in data["steps"]] == ["preseason", "midseason", "trade_deadline", "draft"]
    assert data["source"]["seed_scope"] == "public-dev"


def test_every_move_is_a_valid_2_0_tool_call():
    from gm_bench.agentic.tools import validate_arguments

    data = json.loads(walkthrough.DESTINATION.read_text())
    for step in data["steps"]:
        for call in step["queries"] + step["moves"]:
            assert validate_arguments(call["tool"], call["arguments"]) is None, call
