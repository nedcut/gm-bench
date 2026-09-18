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
# Rows measured under the sota-v5 contract on the same private panel but in a
# lane the registry does not cover: a decision model answering a host-written
# question set (docs/typesafe_jev_lane.md). They live beside, never inside,
# the eleven headline artifacts, so the sota-v5 directory keeps meaning "the
# registered headline family" for the robustness script, the reproduction
# guide, and the Holm family size.
DECISION_LANE_ARTIFACTS_DIR = ROOT / "results" / "leaderboard" / "decision-lane"
DECISION_LANE = "decision-api"


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


def _decision_lane_rows(source: Path, *, contract: dict[str, Any], seed_panel: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows for the decision-model lane: same contract and panel, own bucket.

    Each artifact must validate under the sota-v5 policy, declare the
    ``decision-api`` transport, and carry the headline study's contract
    fingerprint and private seed-panel hash, so a row here is a run of the
    same benchmark under the same conditions and differs only in the lane. It
    never enters ``models``: the Holm family, the eligible-headline count, and
    every "N of M above the bar" claim on the site are about the registered
    chat-lane family alone.
    """
    if not source.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for path in sorted(source.glob("*.json")):
        payload = _read(path)
        run_info = payload.get("run_info") or {}
        agent = str(payload.get("agent") or "")
        if agent in seen:
            raise ValueError(f"{path.name} repeats decision-lane id {agent!r} already published from {seen[agent]}")
        seen[agent] = path.name
        if run_info.get("transport") != DECISION_LANE:
            raise ValueError(f"{path.name} is not a {DECISION_LANE} row; it does not belong in the decision lane")
        row_contract = run_info.get("benchmark_contract") or {}
        if row_contract.get("contract_fingerprint") != contract.get("contract_fingerprint"):
            raise ValueError(f"{path.name} was not run under the published contract fingerprint")
        row_panel = run_info.get("seed_panel") or {}
        if row_panel.get("sha256") != seed_panel.get("sha256") or row_panel.get("name") != seed_panel.get("name"):
            raise ValueError(f"{path.name} was not run on the published private seed panel")
        row = model_row(payload, None, policy=POLICIES["sota-v5"])
        if not row.get("sota_v2_eligible"):
            raise ValueError(f"{path.name} does not pass the sota-v5 result policy: {row.get('sota_v2_issues')}")
        if row.get("lane") != DECISION_LANE:
            raise ValueError(f"{path.name} did not map to the {DECISION_LANE} lane")
        options = run_info.get("provider_options") or {}
        usage = (payload.get("candidate") or {}).get("summary", {}).get("usage") or {}
        row["route"] = _decision_route(run_info, options, usage)
        row["timestamp_utc"] = run_info.get("timestamp_utc")
        row["scaffold_fingerprint"] = run_info.get("scaffold_fingerprint")
        row["provider_options"] = {key: str(value) for key, value in sorted(options.items()) if key.startswith("JEV_")}
        row["artifact_path"] = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name
        rows.append(row)
    rows.sort(key=lambda item: -float(item["mean_score"]))
    return rows


def _decision_route(run_info: dict[str, Any], options: dict[str, Any], usage: dict[str, Any]) -> str:
    provider = str(run_info.get("provider") or "")
    route = str(options.get("JEV_ROUTE") or "")
    upstream = str(usage.get("upstream_provider") or "")
    if route == "openrouter":
        return f"{provider} → OpenRouter decisions endpoint" + (f" ({upstream})" if upstream else "")
    if route:
        return f"{provider} → {route}"
    return provider


def build_study(
    *,
    root: Path = ROOT,
    output_path: Path | None = None,
    artifacts_dir: Path | None = None,
    decision_lane_dir: Path | None = None,
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
    decision_source = decision_lane_dir or root / DECISION_LANE_ARTIFACTS_DIR.relative_to(ROOT)
    if not decision_source.is_absolute():
        decision_source = root / decision_source
    decision_lane_models = _decision_lane_rows(
        decision_source,
        contract=dict(POLICIES["sota-v5"].expected_contract or {}),
        seed_panel=seed_panel,
    )
    headline_ids = {row["id"] for row in models}
    if any(row["id"] in headline_ids for row in decision_lane_models):
        raise ValueError("a decision-lane row shares an id with a headline row")
    timestamps = [str((p.get("run_info") or {}).get("timestamp_utc") or "") for p in payloads]
    timestamps += [str(row.get("timestamp_utc") or "") for row in decision_lane_models]
    dataset = {
        "updated": max(timestamps, default="")[:10],
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
        "decision_lane_models": decision_lane_models,
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
    parser.add_argument("--decision-lane-dir", type=Path)
    args = parser.parse_args()
    result = build_study(
        output_path=args.output, artifacts_dir=args.artifacts_dir, decision_lane_dir=args.decision_lane_dir
    )
    print(
        f"wrote {args.output or V5_OUTPUT_PATH} "
        f"({len(result['models'])} model(s), {len(result['decision_lane_models'])} decision-lane row(s))"
    )
