#!/usr/bin/env python3
"""Replace selected rules in a hash-pinned Semgrep registry snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

RULES_REPLACED_BY_LOCAL_OVERRIDES = frozenset(
    {
        "python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected",
        "python.lang.security.audit.formatted-sql-query.formatted-sql-query",
        "python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query",
        "html.security.audit.missing-integrity.missing-integrity",
    }
)


def without_replaced_rules(text: str) -> str:
    """Remove exact top-level rule blocks; the input bytes are pinned by CI."""
    output: list[str] = []
    removed: set[str] = set()
    skip = False
    for line in text.splitlines(keepends=True):
        if line.startswith("- id: "):
            rule_id = line.removeprefix("- id: ").strip()
            skip = rule_id in RULES_REPLACED_BY_LOCAL_OVERRIDES
            if skip:
                removed.add(rule_id)
        if not skip:
            output.append(line)
    missing = RULES_REPLACED_BY_LOCAL_OVERRIDES - removed
    if missing:
        raise ValueError(f"pinned ruleset is missing expected override targets: {sorted(missing)!r}")
    return "".join(output)


def semantic_ruleset_sha256(text: str) -> str:
    """Hash executable rule content independent of YAML formatting and order."""
    try:
        from ruamel.yaml import YAML
    except ImportError as exc:  # pragma: no cover - installed with Semgrep in CI
        raise RuntimeError("ruamel.yaml is required to validate the downloaded Semgrep ruleset") from exc

    payload = YAML(typ="safe").load(text)
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list) or not rules:
        raise ValueError("downloaded Semgrep ruleset must contain a non-empty rules list")
    executable_rules: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            raise ValueError("every downloaded Semgrep rule must be an object with an id")
        rule_id = rule["id"]
        if rule_id in seen_ids:
            raise ValueError(f"downloaded Semgrep ruleset contains duplicate id {rule_id!r}")
        seen_ids.add(rule_id)
        executable_rules.append({key: value for key, value in rule.items() if key != "metadata"})
    executable_rules.sort(key=lambda rule: rule["id"])
    canonical = json.dumps(executable_rules, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-semantic-sha256", required=True)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.source.read_text()
    actual_hash = semantic_ruleset_sha256(source)
    if actual_hash != args.expected_semantic_sha256:
        raise ValueError(
            "downloaded Semgrep rule semantics do not match the pinned snapshot: "
            f"expected {args.expected_semantic_sha256}, got {actual_hash}"
        )
    args.output.write_text(without_replaced_rules(source))


if __name__ == "__main__":
    main()
