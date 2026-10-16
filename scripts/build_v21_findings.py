#!/usr/bin/env python3
"""Export the 2.1 behaviour findings for the site's Findings page.

The only source is the committed diagnostic
``results/diagnostics/v21_behavior/behavior.json`` (written by
``scripts/diagnose_v21_behavior.py``, aggregates only). This script selects the
numbers the page shows and checks them against the committed 2.1 rows each
model came from: the row's contract, harness, episode count, mean score and
empty-phase count must agree, so the page cannot drift from the evidence.

    python3 scripts/build_v21_findings.py [--check]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "results/diagnostics/v21_behavior/behavior.json"
SCRIPT = "scripts/diagnose_v21_behavior.py"
DESTINATION = ROOT / "web/src/data/v21-findings.json"
SCHEMA = "gm-bench-v21-findings-v1"
# Display order and label of each score-v2 term group in family_gap.terms.
TERMS = [
    ("end_roster", "End-of-run roster", "total assets, young assets and roster depth"),
    ("winning", "Winning", "season wins, expected playoff rounds and expected titles"),
    ("current_strength", "Lineup strength", "current strength at the end"),
    ("future_picks", "Future picks", "draft picks held at the end"),
    ("penalty", "Illegal moves", "minus the protocol penalty"),
    ("cap_room", "Cap room", "cap room at the end, clamped"),
]
RUN_MODEL = re.compile(r"^[a-z]+-[\d.]+-(?P<model>.+)-panel-\d+x\d+-v21$")


def model_entry(name: str, stats: dict[str, Any], row_path: str) -> dict[str, Any]:
    row = json.loads((ROOT / row_path).read_text())
    if row["contract"]["benchmark_version"] != "gm-bench-2.1":
        raise SystemExit(f"{row_path} is not a 2.1 row")
    empty, drafts, status, end = stats["empty_phases"], stats["drafts"], stats["status_habit"], stats["end_of_run"]
    episodes = stats["episodes"]
    checks = {
        "episodes": (episodes, len(row["episodes"])),
        "mean score": (stats["mean_final_score"], round(row["summary"]["mean_score"], 3)),
        "empty phases": (empty["count"], row["empty_phases"]["count"]),
        "phases": (empty["phases"], row["empty_phases"]["phases"]),
        "model": (name, row["harness"]["model"].split("/")[-1]),
    }
    for label, (diagnostic, committed) in checks.items():
        if diagnostic != committed:
            raise SystemExit(f"{SOURCE}: {name} {label} {diagnostic} disagrees with {row_path} ({committed})")
    return {
        "model": name,
        "artifact": row_path,
        "harness": row["harness"]["name"],
        "episodes": episodes,
        "phases": empty["phases"],
        "empty_phases": empty["count"],
        "empty_rate": empty["rate"],
        "empty_drafts_with_no_pick": empty["drafts_with_no_pick"],
        "share_empty_drafts_with_no_pick": empty["share_drafts_with_no_pick"],
        "empty_without_status_read": empty["without_status_read"],
        "drafts": drafts["count"],
        "drafts_closed_holding_unused_pick": drafts["closed_holding_unused_pick"],
        "phases_ended_without_status_read": status["phases_ended_without_status_read"],
        "rate_ended_without_status_read": status["rate_ended_without_status_read"],
        "roster_before_final_rollover": end["roster_before_final_rollover"],
        "roster_at_end": end["roster_at_end"],
        "episodes_ending_with_5_or_fewer": end["episodes_ending_with_5_or_fewer"],
        "season_5_extensions_per_episode": end["season_5_extensions_per_episode"],
        "season_5_signings": end["season_5_signings"],
        "season_5_signings_one_year": end["season_5_signings_one_year"],
        "episodes_final_below_after_season_4": end["episodes_final_below_after_season_4"],
    }


def build(behavior: dict[str, Any]) -> dict[str, Any]:
    if behavior["contract"] != "gm-bench-2.1":
        raise SystemExit(f"{SOURCE} is not a 2.1 diagnostic")
    rows = {source["model"]: source["row"] for source in behavior["sources"]}
    models = [model_entry(name, stats, rows[name]) for name, stats in behavior["models"].items()]
    gap = behavior["family_gap"]
    terms = gap["terms"]
    if abs(sum(terms[key]["mean"] for key, _, _ in TERMS) - terms["final_score"]["mean"]) > 0.01:
        raise SystemExit(f"{SOURCE}: family_gap terms do not sum to final_score")
    if set(terms) != {"final_score", *(key for key, _, _ in TERMS)}:
        raise SystemExit(f"{SOURCE}: unexpected family_gap terms {sorted(terms)}")
    correlations = gap["seed_correlation_extra_empty_vs_score_gap"].values()
    not_covered = []
    for skipped in behavior["skipped_runs"]:
        match = RUN_MODEL.match(skipped["run"])
        if not match:
            raise SystemExit(f"{SOURCE}: cannot name the model of skipped run {skipped['run']}")
        not_covered.append(match["model"])
    return {
        "format": SCHEMA,
        "source": SOURCE,
        "script": SCRIPT,
        "contract": behavior["contract"],
        "family_gap": {
            "openai": gap["openai"],
            "claude": gap["claude"],
            "seeds": gap["seeds"],
            "final_score": {
                "mean": terms["final_score"]["mean"],
                "se": terms["final_score"]["se"],
                "ci95": terms["final_score"]["ci95"],
                "ahead": terms["final_score"]["ahead"],
            },
            "terms": [
                {
                    "key": key,
                    "label": label,
                    "detail": detail,
                    "mean": terms[key]["mean"],
                    "ci95": terms[key]["ci95"],
                    "share": gap["share_of_gap"][key],
                }
                for key, label, detail in TERMS
            ],
            "extra_empty_vs_gap_correlation": [min(correlations), max(correlations)],
        },
        "drafts_closed_holding_unused_pick": sum(m["drafts_closed_holding_unused_pick"] for m in models),
        "drafts": sum(m["drafts"] for m in models),
        "models": models,
        "not_covered": not_covered,
    }


def render() -> str:
    return json.dumps(build(json.loads((ROOT / SOURCE).read_text())), indent=1) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = parser.parse_args()
    built = render()
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text() != built:
            raise SystemExit(f"{DESTINATION.relative_to(ROOT)} is stale; run scripts/build_v21_findings.py")
        return
    DESTINATION.write_text(built)


if __name__ == "__main__":
    main()
