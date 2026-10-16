"""The site's Findings page data is derived from the committed 2.1 behaviour diagnostic."""

import copy
import json

import pytest

from scripts import build_v21_findings as findings


def test_committed_findings_match_the_diagnostic():
    assert findings.DESTINATION.read_text() == findings.render(), "run scripts/build_v21_findings.py"


def test_findings_carry_aggregates_only():
    data = json.loads(findings.DESTINATION.read_text())
    text = json.dumps(data)
    assert "seed" not in text.replace('"seeds"', "")
    assert {m["model"] for m in data["models"]} == set(data["family_gap"]["openai"] + data["family_gap"]["claude"]) | {
        "deepseek-v4.1-flash"
    }
    assert data["not_covered"] == ["haiku-5-5", "mimo-v2.6-flash"]


def test_a_diagnostic_that_disagrees_with_its_row_is_refused():
    behavior = json.loads((findings.ROOT / findings.SOURCE).read_text())
    broken = copy.deepcopy(behavior)
    broken["models"]["claude-opus-5-5"]["empty_phases"]["count"] += 1
    with pytest.raises(SystemExit, match="empty phases"):
        findings.build(broken)
