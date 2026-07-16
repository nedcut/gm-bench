#!/usr/bin/env python3
"""Replace selected rules in a hash-pinned Semgrep registry snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

RULES_REPLACED_BY_LOCAL_OVERRIDES = frozenset(
    {
        "python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected",
        "python.lang.security.audit.formatted-sql-query.formatted-sql-query",
        "python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query",
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(without_replaced_rules(args.source.read_text()))


if __name__ == "__main__":
    main()
