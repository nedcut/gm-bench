"""Build a separately versioned public study dataset.

The existing ``build_leaderboard.py`` remains the byte-stable sota-v2 builder.
This module is the explicit future-study path: it never changes that file and
refuses to write a v5 dataset until every frozen publication input carries the
same explicit authorization decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRESETS  # noqa: E402
from gm_bench.official import POLICIES, REDACTED_SEEDS_SENTINEL  # noqa: E402
from gm_bench.protocol import PHASES  # noqa: E402
from web.scripts.build_leaderboard import (  # noqa: E402
    model_row,
    publication_gate,
    select_model_payloads,
)

# The site imports ``leaderboard.json``; sota-v5 is what it now publishes.
# The archived v2 dataset stays reproducible at ``leaderboard-sota-v2.json``,
# which ``build_leaderboard.py`` still writes.
V5_OUTPUT_PATH = ROOT / "web" / "src" / "data" / "leaderboard.json"
V5_ARTIFACTS_DIR = ROOT / "results" / "leaderboard" / "sota-v5"


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _require_authorization(*payloads: tuple[str, dict[str, Any]]) -> None:
    issues = [
        f"{label} publication_authorized is not true"
        for label, payload in payloads
        if payload.get("publication_authorized") is not True
    ]
    if issues:
        raise ValueError("sota-v5 site publication is locked: " + "; ".join(issues))


def _baselines(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not payloads:
        return []
    by_agent: dict[str, dict[str, Any]] = {}
    for bucket in payloads[0].get("baselines") or []:
        if not isinstance(bucket, dict):
            continue
        summary = bucket.get("summary") or {}
        if "mean_score" in summary:
            by_agent[str(bucket.get("agent"))] = {
                "agent": str(bucket.get("agent")),
                "mean_score": summary.get("mean_score"),
                "score_stddev": summary.get("score_stddev", 0.0),
            }
    return sorted(by_agent.values(), key=lambda row: row["mean_score"], reverse=True)


def build_study(
    *,
    root: Path = ROOT,
    output_path: Path | None = None,
    artifacts_dir: Path | None = None,
) -> dict[str, Any]:
    """Build v5 only after publication authorization and complete analysis."""

    if "sota-v5" not in POLICIES:
        raise ValueError("no sota-v5 result-validation policy is registered")
    config = root / "config"
    registry = _read(config / "sota_v5_models.json")
    lane = _read(config / "sota_v5_lane.json")
    protocol = _read(config / "sota_v5_publication_protocol.json")
    pricing = _read(config / "sota_v5_pricing_snapshot.json")
    manifest = _read(config / "sota_v5_smoke_manifest.json")
    _require_authorization(
        ("lane", lane),
        ("model registry", registry),
        ("publication protocol", protocol),
        ("pricing snapshot", pricing),
    )
    if manifest.get("accepted_for_panel") is not True:
        raise ValueError("sota-v5 site publication requires an accepted smoke manifest")
    analysis_path = root / "results" / "analysis" / "publication-panel-analysis-v5.json"
    analysis = _read(analysis_path)
    if analysis.get("publication_ready") is not True:
        raise ValueError("sota-v5 site publication requires publication-ready analysis")
    source = artifacts_dir or root / V5_ARTIFACTS_DIR.relative_to(ROOT)
    if not source.is_absolute():
        source = root / source
    artifacts: list[tuple[dict[str, Any], int, str]] = []
    for path in sorted(source.glob("*.json")):
        payload = _read(path)
        version = ((payload.get("run_info") or {}).get("benchmark_contract") or {}).get("benchmark_version")
        if version == "sota-v5":
            artifacts.append((payload, 2, path.name))
    payloads = select_model_payloads(artifacts)
    rows = [model_row(payload, registry, policy=POLICIES["sota-v5"]) for payload in payloads]
    current_rows = [row for row in rows if row.get("benchmark_version") == "sota-v5"]
    protocol_minimum = int(
        (protocol.get("exclusion_policy") or {}).get("minimum_headline_models")
        or lane.get("minimum_headline_models")
        or 0
    )
    models, publication = publication_gate(
        current_rows,
        {"status": "complete"},
        lane,
        registry,
        panel_analysis=analysis,
        smoke_issues=[],
        protocol_minimum=protocol_minimum,
    )
    if not publication.get("publishable_results"):
        raise ValueError("sota-v5 site publication gate is incomplete: " + str(publication.get("reason")))
    preset = PRESETS["leaderboard"]
    seed_panel = lane.get("seed_panel") or {}
    baselines = _baselines(payloads)
    if not baselines:
        raise ValueError("sota-v5 site publication requires a complete baseline panel")
    dataset = {
        "updated": max((str((p.get("run_info") or {}).get("timestamp_utc") or "") for p in payloads), default="")[:10],
        "contract": dict(POLICIES["sota-v5"].expected_contract or {}),
        "preset": {
            "name": seed_panel.get("name"),
            "seeds": REDACTED_SEEDS_SENTINEL,
            "seed_count": seed_panel.get("count"),
            "sha256": seed_panel.get("sha256"),
            "hiding_commitment_sha256": seed_panel.get("hiding_commitment_sha256"),
            "seasons": preset["seasons"],
            "decision_points_per_episode": preset["seasons"] * len(PHASES),
        },
        "baselines": baselines,
        "models": models,
        "cli_harness_models": [row for row in current_rows if row.get("lane") == "cli-harness"],
        "excluded_models": [],
        "publication": publication,
        "headroom": {
            "oracle": None,
            "pick_trader": next((row["mean_score"] for row in baselines if row["agent"] == "pick-trader"), None),
            "best_model": max((row["mean_score"] for row in models), default=None),
            "random": next((row["mean_score"] for row in baselines if row["agent"] == "random"), None),
        },
    }
    destination = output_path or root / V5_OUTPUT_PATH.relative_to(ROOT)
    if not destination.is_absolute():
        destination = root / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(dataset, indent=2, sort_keys=True) + "\n")
    return dataset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifacts-dir", type=Path)
    args = parser.parse_args()
    result = build_study(output_path=args.output, artifacts_dir=args.artifacts_dir)
    print(f"wrote {args.output or V5_OUTPUT_PATH} ({len(result['models'])} model(s))")
