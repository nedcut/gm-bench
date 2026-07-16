from __future__ import annotations

import pytest

from scripts.prepare_semgrep_ruleset import RULES_REPLACED_BY_LOCAL_OVERRIDES, without_replaced_rules


def _ruleset(*rule_ids: str) -> str:
    return "rules:\n" + "".join(f"- id: {rule_id}\n  languages: [python]\n" for rule_id in rule_ids)


def test_replaces_only_the_reviewed_rules() -> None:
    retained = "example.retained"
    result = without_replaced_rules(_ruleset(retained, *sorted(RULES_REPLACED_BY_LOCAL_OVERRIDES)))

    assert retained in result
    assert all(rule_id not in result for rule_id in RULES_REPLACED_BY_LOCAL_OVERRIDES)


def test_refuses_unexpected_pinned_ruleset_shape() -> None:
    with pytest.raises(ValueError, match="missing expected override targets"):
        without_replaced_rules(_ruleset("example.retained"))
