"""Seed-free retrospective audit counts; raw files stay local.

Usage: python -m gm_bench.agentic.audit_compare RAW_ROOT > report.json
Run manifests and orphan ledger.jsonl files are included without eligibility
filtering. Full validation is optional (replays and harness recounts are costly).
Output deliberately omits paths, seeds, IDs, arguments and validator messages.
Run numbers follow sorted manifest paths; keep the local mapping private.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from gm_bench.agentic.audit import PRE_SIGNING_POLICY, SIGNING_POLICY, audit_ledger
from gm_bench.agentic.validate import _evidence_path, validate_run

FINDINGS = ("violations", "suspicious", "guessed_reads", "guessed_draft_picks", "guessed_signings")


def counts(path: Path, policy: str) -> dict[str, Any]:
    report = audit_ledger(path, policy=policy)
    return {
        "status": "pass" if report["clean"] else "fail" if report["auditable"] else "unauditable",
        **{key: len(report.get(key, [])) for key in FINDINGS},
    }


def compare_ledger(path: Path) -> dict[str, Any]:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        old, new = counts(path, PRE_SIGNING_POLICY), counts(path, SIGNING_POLICY)
        return {"sha256": digest, "old": old, "new": new, "changed": old != new}
    except (OSError, ValueError, TypeError):
        return {"old": {"status": "unavailable"}, "new": {"status": "unavailable"}, "changed": False}


def compare_archive(root: Path, *, validate: bool = False) -> dict[str, Any]:
    runs = []
    referenced: set[Path] = set()
    for index, manifest in enumerate(sorted(root.rglob("run.json"))):
        run = json.loads(manifest.read_text())
        episodes = []
        for episode_index, episode in enumerate(run.get("episodes") or []):
            path = _evidence_path((episode.get("harness_run") or {}).get("ledger_path"), manifest.parent)
            if path is not None:
                referenced.add(path.resolve())
            episodes.append({"episode": episode_index, **compare_ledger(path or manifest.parent / "missing-ledger")})
        row = {
            "run": index,
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "episodes": episodes,
        }
        if validate:
            row["validation"] = {}
            for label, policy in (("old", PRE_SIGNING_POLICY), ("new", SIGNING_POLICY)):
                report = validate_run(manifest, audit_policy=policy)
                row["validation"][label] = {
                    "ok": report["ok"],
                    "problems": len(report["problems"]),
                    "warnings": len(report["warnings"]),
                }
        runs.append(row)
    # Include interrupted/excluded episodes that never reached a run manifest.
    paths = set(root.rglob("ledger.jsonl")) | set(root.rglob("*.ledger.jsonl"))
    orphans = [compare_ledger(path) for path in sorted(paths) if path.resolve() not in referenced]
    return {"old_policy": PRE_SIGNING_POLICY, "new_policy": SIGNING_POLICY, "runs": runs, "orphan_ledgers": orphans}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--validate", action="store_true", help="also replay and validate every run under both rules")
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error("root must be an existing directory")
    print(json.dumps(compare_archive(args.root, validate=args.validate), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
