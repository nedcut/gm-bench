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
from statistics import pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.agentic.publication import (  # noqa: E402
    AGENTIC_PUBLICATION_FORMAT,
    is_agentic_artifact,
    validate_agentic_artifact,
)
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
# GM-Bench 2.0 rows (docs/bench_v2_spec.md): the model's own harness driving
# the simulator through MCP tools. A different contract from everything above,
# so its rows go to their own ``agentic_lane`` block and never into ``models``
# or ``decision_lane_models``. Only panel-grade rows are published; smoke rows
# are committed for reproducibility and skipped here.
AGENTIC_ARTIFACTS_DIR = ROOT / "results" / "agentic"
AGENTIC_LANE = "agentic"
AGENTIC_LANE_CONFIG = Path("config") / "bench_v2_lane.json"


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


def _agentic_lane_rows(
    source: Path,
    *,
    lane: dict[str, Any],
    v1_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Panel-grade GM-Bench 2.0 rows, one per committed artifact.

    Every file under ``results/agentic/`` must be a 2.0 artifact. Smoke rows
    are skipped (the spec commits them for reproducibility, not display). A
    panel row must pass :func:`validate_agentic_artifact` against this
    checkout's contract and ``lane``, which pins it to the frozen 32-seed
    private panel. The artifacts carry no seeds, so a row publishes its own
    mean and spread over per-seed means, plus the one inference the spec
    supports: the artifact's ``reference`` block, the predeclared pick-trader
    contrast computed at redaction on the row's own seeds and seasons
    (pick-trader and random means, paired lift with its CI, sign-flip p,
    seed win rate; never per-seed values). Nothing is paired across rows,
    harnesses, or models, and no 1.0 row's score is attached; a 1.0 row on
    the same model is linked by id only.

    A row is ``unpinned`` unless ``lane["model_pinning"]["pinned_models"]``
    names its model with the pin that makes it reproducible (spec, Row
    identity and eligibility). Rows are ordered by pinning, then model and
    harness, never by score: 2.0 ranks nothing.
    """
    if not source.is_dir():
        return []
    pinned_models = _agentic_pinned_models(lane)
    rows: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for path in sorted(source.glob("*.json")):
        payload = _read(path)
        if not is_agentic_artifact(payload):
            raise ValueError(f"{path.name} is not a {AGENTIC_PUBLICATION_FORMAT} artifact")
        if payload.get("grade") != "panel":
            continue
        report = validate_agentic_artifact(payload, lane=lane)
        if not report["ok"]:
            raise ValueError(f"{path.name} does not validate as a panel-grade 2.0 row: {report['errors']}")
        row = _agentic_row(payload, path, pinned_models=pinned_models, v1_rows=v1_rows)
        if row["id"] in seen:
            raise ValueError(f"{path.name} repeats agentic row {row['id']!r} already published from {seen[row['id']]}")
        seen[row["id"]] = path.name
        rows.append(row)
    _require_one_reference_per_season_count(rows)
    rows.sort(
        key=lambda item: (
            item["unpinned"],
            item["model"],
            item["harness"]["name"],
            item["harness"]["version"],
            item["harness"]["variant"] or "",
        )
    )
    return rows


def _require_one_reference_per_season_count(rows: list[dict[str, Any]]) -> None:
    """pick-trader and random are deterministic on the one frozen panel, so rows at a season count share their means.

    ``validate_agentic_artifact`` pins them to ``reference_scores`` in the lane
    config once recorded; this also catches a hand-shifted reference while
    they are not.
    """
    by_seasons: dict[Any, tuple[Any, Any, str]] = {}
    for row in rows:
        reference = row["reference"]
        means = (reference["mean_score"], reference["floor"]["mean_score"])
        first = by_seasons.setdefault(row["seasons"], (*means, row["id"]))
        if means != first[:2]:
            raise ValueError(
                f"agentic row {row['id']!r} has pick-trader/random means {means} but {first[2]!r} has {first[:2]} "
                f"at {row['seasons']} seasons; on one frozen panel every row's reference must agree"
            )


def _agentic_pinned_models(lane: dict[str, Any]) -> dict[str, str]:
    """Model id -> the served version or provider pin that makes a row on it reproducible."""
    pinning = lane.get("model_pinning") or {}
    pinned = pinning.get("pinned_models") or {}
    if not isinstance(pinned, dict) or not all(
        isinstance(model, str) and isinstance(pin, str) and pin.strip() for model, pin in pinned.items()
    ):
        raise ValueError(f"{AGENTIC_LANE_CONFIG} model_pinning.pinned_models must map model ids to non-empty pins")
    return dict(pinned)


def _agentic_row(
    payload: dict[str, Any],
    path: Path,
    *,
    pinned_models: dict[str, str],
    v1_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    harness = payload.get("harness") or {}
    contract = payload.get("contract") or {}
    panel = payload.get("panel") or {}
    publication = payload.get("publication") or {}
    episodes = payload.get("episodes") or []
    by_group: dict[int, list[float]] = {}
    for episode in episodes:
        by_group.setdefault(int(episode["seed_group"]), []).append(float(episode["final_score"]))
    seed_means = [sum(scores) / len(scores) for scores in by_group.values()]
    name, version, model = str(harness["name"]), str(harness["version"]), str(harness["model"])
    variant = harness.get("variant")
    # Row identity is model + harness + harness version (+ variant): two
    # harnesses on one model are two rows, never one row with two scores.
    row_id = f"{AGENTIC_LANE}:{name}-{version}:{model}" + (f":{variant}" if variant else "")
    summary = payload.get("summary") or {}
    return {
        "id": row_id,
        "lane": AGENTIC_LANE,
        "grade": payload.get("grade"),
        "agent": payload.get("agent"),
        "model": model,
        "harness": {"name": name, "version": version, "model": model, "variant": variant},
        # Spec: a row whose model version or provider is not pinnable is
        # published with an ``unpinned`` flag and may not be reproducible.
        "unpinned": model not in pinned_models,
        "pin": pinned_models.get(model),
        "isolation": payload.get("isolation"),
        "panel": {
            "distinct_seeds": len(by_group),
            "episodes": len(episodes),
            "sha256": panel.get("sha256"),
        },
        "seasons": payload.get("seasons"),
        "phase_guard_seconds": payload.get("phase_guard_seconds"),
        "max_nudges": payload.get("max_nudges"),
        "mean_score": round(sum(seed_means) / len(seed_means), 3),
        "score_stddev": round(pstdev(seed_means), 3) if len(seed_means) > 1 else 0.0,
        "seed_mean_min": round(min(seed_means), 3),
        "seed_mean_max": round(max(seed_means), 3),
        "illegal_actions": summary.get("illegal_actions"),
        "failed_decisions": summary.get("failed_decisions"),
        "reference": _agentic_reference(payload.get("reference") or {}),
        "contract": {
            key: contract.get(key)
            for key in (
                "benchmark_version",
                "agentic_fingerprint",
                "base_benchmark_version",
                "base_contract_fingerprint",
                "tool_surface",
                "brief",
                "scoring_version",
                "simulator_version",
            )
        },
        "telemetry": _agentic_telemetry(episodes),
        "agreement": _agentic_agreement(episodes),
        "v1_row_id": _v1_row_for(model, v1_rows),
        "artifact_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name,
        "raw_artifact_sha256": publication.get("raw_artifact_sha256"),
        "compacted_at_utc": publication.get("compacted_at_utc"),
    }


def _agentic_reference(reference: dict[str, Any]) -> dict[str, Any]:
    """The pick-trader contrast on the row's own panel, aggregates only (per_seed is never carried)."""
    floor = reference.get("floor") or {}
    return {
        "agent": reference.get("agent"),
        "mean_score": reference.get("mean_score"),
        "floor": {"agent": floor.get("agent"), "mean_score": floor.get("mean_score")},
        "seasons": reference.get("seasons"),
        "num_seeds": reference.get("num_seeds"),
        "paired_lift_mean": reference.get("paired_lift_mean"),
        "paired_lift_stddev": reference.get("paired_lift_stddev"),
        "paired_lift_ci95": list(reference.get("paired_lift_ci95") or []),
        "sign_flip_p_value": reference.get("sign_flip_p_value"),
        "significant_at_95": reference.get("significant_at_95"),
        "candidate_seed_win_rate": reference.get("candidate_seed_win_rate"),
    }


def _agentic_telemetry(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Budgets are reported, not capped. Tokens and cost are the harness's own
    accounting and count only episodes whose harness reported telemetry; with
    none, they are unmeasured (``None``), never zero."""
    by_tool: dict[str, int] = {}
    ended_by: dict[str, int] = {}
    tool_calls = nudges = guard_kills = provider_stalls = silent_kills = scout_points = compactions = 0
    wall_seconds = provider_stall_wait = 0.0
    reported = [e for e in episodes if ((e.get("usage") or {}).get("harness") or {}).get("telemetry_reported")]
    for episode in episodes:
        agentic = episode.get("agentic") or {}
        tool_calls += int(agentic.get("tool_calls") or 0)
        scout_points += int(agentic.get("scout_points_used") or 0)
        for tool, count in (agentic.get("tool_calls_by_tool") or {}).items():
            by_tool[tool] = by_tool.get(tool, 0) + int(count)
        for who, count in (agentic.get("phases_ended_by") or {}).items():
            ended_by[who] = ended_by.get(who, 0) + int(count)
        harness_run = episode.get("harness_run") or {}
        nudges += int(harness_run.get("nudges_used") or 0)
        guard_kills += int(harness_run.get("guard_kills") or 0)
        provider_stalls += int(harness_run.get("provider_stalls") or 0)
        provider_stall_wait += float(harness_run.get("provider_stall_wait_seconds") or 0.0)
        silent_kills += int(harness_run.get("silent_kills") or 0)
        wall_seconds += float(harness_run.get("wall_seconds") or 0.0)
        compactions += int(((episode.get("usage") or {}).get("harness") or {}).get("compactions") or 0)

    def _reported_values(key: str) -> list[float]:
        # Only episodes whose harness reported this key count; a missing value
        # stays unmeasured (None), never zero.
        values = [(e.get("usage") or {}).get(key) for e in reported]
        return [float(v) for v in values if v is not None]

    def _reported_sum(key: str) -> float | None:
        values = _reported_values(key)
        return sum(values) if values else None

    count = len(episodes) or 1
    cost_values = _reported_values("cost_usd")
    cost = sum(cost_values) if cost_values else None
    return {
        "episodes": len(episodes),
        "tool_calls": tool_calls,
        "tool_calls_per_episode": round(tool_calls / count, 2),
        "tool_calls_by_tool": dict(sorted(by_tool.items())),
        "scout_points_used": scout_points,
        "phases_ended_by": dict(sorted(ended_by.items())),
        "nudges_used": nudges,
        "nudges_per_episode": round(nudges / count, 2),
        "guard_kills": guard_kills,
        "provider_stalls": provider_stalls,
        "provider_stall_wait_seconds": round(provider_stall_wait, 1),
        "silent_harness_kills": silent_kills,
        "compactions": compactions,
        "wall_seconds": round(wall_seconds, 1),
        "wall_seconds_per_episode": round(wall_seconds / count, 1),
        "telemetry_episodes": len(reported),
        "input_tokens": _int_or_none(_reported_sum("input_tokens")),
        "output_tokens": _int_or_none(_reported_sum("output_tokens")),
        "reasoning_tokens": _int_or_none(_reported_sum("reasoning_tokens")),
        "cached_input_tokens": _int_or_none(_reported_sum("cached_input_tokens")),
        "cost_usd": None if cost is None else round(cost, 4),
        "cost_per_episode_usd": None if cost is None else round(cost / len(cost_values), 4),
    }


def _agentic_agreement(episodes: list[dict[str, Any]]) -> dict[str, int]:
    """The server ledger is authoritative; this is how often the harness's own tool-event count matched it."""
    agreements = [(e.get("harness_run") or {}).get("tool_call_agreement") or {} for e in episodes]
    return {
        "episodes": len(episodes),
        "episodes_agreeing": sum(1 for a in agreements if a.get("agree") is True),
        "ledger_tool_calls": sum(int(a.get("ledger") or 0) for a in agreements),
        "harness_tool_calls": sum(int(a.get("harness") or 0) for a in agreements),
    }


def _v1_row_for(model: str, v1_rows: list[dict[str, Any]]) -> str | None:
    """The 1.0 row for the same model, matched by model id exactly or as ``provider/model``."""
    for row in v1_rows:
        if model in {str(row.get("model")), f"{row.get('provider')}/{row.get('model')}"}:
            return str(row["id"])
    return None


def _int_or_none(value: float | None) -> int | None:
    return None if value is None else int(round(value))


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
    agentic_dir: Path | None = None,
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
    headroom = {
        "oracle": None,
        "pick_trader": next((row["mean_score"] for row in baselines if row["agent"] == "pick-trader"), None),
        "best_model": max((row["mean_score"] for row in models), default=None),
        "random": next((row["mean_score"] for row in baselines if row["agent"] == "random"), None),
    }
    agentic_source = agentic_dir or root / AGENTIC_ARTIFACTS_DIR.relative_to(ROOT)
    if not agentic_source.is_absolute():
        agentic_source = root / agentic_source
    agentic_lane = _agentic_lane_rows(
        agentic_source,
        lane=_read(root / AGENTIC_LANE_CONFIG),
        v1_rows=[*models, *(row for row in current_rows if row.get("lane") == "cli-harness"), *decision_lane_models],
    )
    v1_ids = headline_ids | {row["id"] for row in decision_lane_models}
    if any(row["id"] in v1_ids for row in agentic_lane):
        raise ValueError("an agentic-lane row shares an id with a 1.0 row")
    timestamps = [str((p.get("run_info") or {}).get("timestamp_utc") or "") for p in payloads]
    timestamps += [str(row.get("timestamp_utc") or "") for row in decision_lane_models]
    timestamps += [str(row.get("compacted_at_utc") or "") for row in agentic_lane]
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
        "agentic_lane": agentic_lane,
        "excluded_models": [],
        "publication": publication,
        "headroom": headroom,
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
    parser.add_argument("--agentic-dir", type=Path)
    args = parser.parse_args()
    result = build_study(
        output_path=args.output,
        artifacts_dir=args.artifacts_dir,
        decision_lane_dir=args.decision_lane_dir,
        agentic_dir=args.agentic_dir,
    )
    print(
        f"wrote {args.output or V5_OUTPUT_PATH} "
        f"({len(result['models'])} model(s), {len(result['decision_lane_models'])} decision-lane row(s), "
        f"{len(result['agentic_lane'])} agentic panel row(s))"
    )
