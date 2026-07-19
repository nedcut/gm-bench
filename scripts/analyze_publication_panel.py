#!/usr/bin/env python3
"""Analyze the pre-registered publication panel without making model calls.

The unit of inference is the seed. Candidate repeats are averaged within each
seed before subtracting that seed's deterministic ``pick-trader`` score. The
bootstrap interval and sign-flip p-value are descriptive, and Holm-Bonferroni
is applied using the full registered family size even when rows are missing.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "sota_v2_models.json"
DEFAULT_ARTIFACT_DIR = ROOT / "data" / "publication-runs" / "raw"
DEFAULT_OUTPUT_PATH = ROOT / "results" / "analysis" / "publication-panel-analysis.json"
BOOTSTRAP_SEED = 20260716
BOOTSTRAP_ITERATIONS = 10_000

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.official import SOTA_V2_POLICY, validate_leaderboard_payload  # noqa: E402
from gm_bench.publication import canonical_sha256  # noqa: E402


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    confidence: float = 0.95,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """Return a deterministic percentile-bootstrap interval for the mean."""
    if not values:
        raise ValueError("bootstrap requires at least one value")
    if len(values) == 1:
        point = float(values[0])
        return point, point
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between zero and one")
    if iterations < 2:
        raise ValueError("iterations must be at least two")

    rng = random.Random(seed)
    count = len(values)
    samples = sorted(mean(values[rng.randrange(count)] for _ in range(count)) for _ in range(iterations))
    tail = (1.0 - confidence) / 2.0
    last = iterations - 1
    return samples[int(tail * last)], samples[int((1.0 - tail) * last)]


def sign_flip_p_value(values: Sequence[float]) -> float | None:
    """Return the exact two-sided sign-flip p-value used for the eight-seed panel."""
    if len(values) < 2:
        return None
    if len(values) > 20:
        raise ValueError("exact sign-flip enumeration is limited to 20 seeds")

    observed = abs(mean(values))
    tolerance = 1e-12
    total = 1 << len(values)
    hits = sum(
        1
        for mask in range(total)
        if abs(sum(value if mask >> index & 1 else -value for index, value in enumerate(values)) / len(values))
        >= observed - tolerance
    )
    return hits / total


def holm_adjust(p_values: Mapping[str, float], *, family_size: int) -> dict[str, float]:
    """Adjust p-values with Holm-Bonferroni against the full registered family."""
    if family_size < len(p_values):
        raise ValueError("family size cannot be smaller than the number of p-values")
    if any(not 0.0 <= value <= 1.0 for value in p_values.values()):
        raise ValueError("p-values must be between zero and one")

    adjusted: dict[str, float] = {}
    running_max = 0.0
    for rank, (model_id, p_value) in enumerate(sorted(p_values.items(), key=lambda item: (item[1], item[0]))):
        running_max = max(running_max, (family_size - rank) * p_value)
        adjusted[model_id] = min(1.0, running_max)
    return adjusted


def assign_tiers(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign tiers by connected overlap of paired-lift intervals.

    Holm-adjusted primary-contrast results travel with every row. Interval
    overlap determines the tier boundary; connected overlaps merge transitively
    so the output never implies an unsupported ordinal model ranking.
    """
    ordered = sorted(rows, key=lambda row: (-float(row["mean_lift"]), str(row["model_id"])))
    tier = 0
    component_low = 0.0
    component_high = 0.0
    result: list[dict[str, Any]] = []
    for row in ordered:
        low, high = (float(value) for value in row["bootstrap_ci95"])
        if low > high:
            raise ValueError(f"model {row['model_id']!r} has an inverted interval")
        if not result or low > component_high or high < component_low:
            tier += 1
            component_low, component_high = low, high
        else:
            component_low = min(component_low, low)
            component_high = max(component_high, high)
        result.append({**row, "tier": tier})
    return result


def _numeric_score(episode: Mapping[str, Any], *, label: str) -> float:
    value = episode.get("final_score")
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{label}.final_score must be a finite number")
    return float(value)


def _pick_trader_by_seed(payload: Mapping[str, Any]) -> dict[int, float]:
    matches = [row for row in payload.get("baselines") or [] if row.get("agent") == "pick-trader"]
    if len(matches) != 1:
        raise ValueError("artifact must contain exactly one pick-trader baseline")
    scores: dict[int, float] = {}
    for episode in matches[0].get("episodes") or []:
        seed = episode.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError("pick-trader episode seed must be an integer")
        if seed in scores:
            raise ValueError(f"pick-trader has duplicate seed {seed}")
        scores[seed] = _numeric_score(episode, label="pick-trader episode")
    if not scores:
        raise ValueError("pick-trader baseline has no episodes")
    return scores


def per_seed_pick_trader_lifts(payload: Mapping[str, Any], *, expected_repeats: int = 3) -> list[dict[str, Any]]:
    """Average candidate repeats per seed and subtract the same-seed pick-trader score."""
    candidate = payload.get("candidate") or {}
    if int(candidate.get("repeats", 0) or 0) != expected_repeats:
        raise ValueError(f"candidate must report exactly {expected_repeats} repeats")

    scores: dict[int, dict[int, float]] = {}
    for episode in candidate.get("episodes") or []:
        seed = episode.get("seed")
        repeat = episode.get("repeat")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError("candidate episode seed must be an integer")
        if not isinstance(repeat, int) or isinstance(repeat, bool):
            raise ValueError("candidate episode repeat must be an integer")
        repeats = scores.setdefault(seed, {})
        if repeat in repeats:
            raise ValueError(f"candidate has duplicate seed/repeat {seed}/{repeat}")
        repeats[repeat] = _numeric_score(episode, label="candidate episode")

    expected_repeat_ids = set(range(1, expected_repeats + 1))
    for seed, repeat_scores in scores.items():
        if set(repeat_scores) != expected_repeat_ids:
            raise ValueError(f"candidate seed {seed} must contain repeats 1 through {expected_repeats}")
    baseline_scores = _pick_trader_by_seed(payload)
    if set(scores) != set(baseline_scores):
        raise ValueError("candidate and pick-trader seed panels must match exactly")

    rows: list[dict[str, Any]] = []
    for seed in sorted(scores):
        candidate_mean = mean(scores[seed].values())
        baseline_score = baseline_scores[seed]
        rows.append(
            {
                "seed": seed,
                "candidate_mean_over_repeats": round(candidate_mean, 6),
                "pick_trader_score": round(baseline_score, 6),
                "lift": round(candidate_mean - baseline_score, 6),
            }
        )
    return rows


def _registry_specs(registry: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    specs: list[dict[str, Any]] = []
    errors: list[str] = []
    if registry.get("selection_status") != "frozen":
        errors.append("model registry selection_status must be frozen")
    if registry.get("contract") != "sota-v2":
        errors.append("model registry contract must be 'sota-v2'")
    if registry.get("preset") != "leaderboard":
        errors.append("model registry preset must be 'leaderboard'")
    shared_fixed_options = registry.get("shared_fixed_options") or {}
    shared_absent_options = registry.get("shared_absent_options") or []
    if not isinstance(shared_fixed_options, Mapping):
        errors.append("model registry shared_fixed_options must be an object")
        shared_fixed_options = {}
    if not isinstance(shared_absent_options, list):
        errors.append("model registry shared_absent_options must be a list")
        shared_absent_options = []
    seen_ids: set[str] = set()
    seen_identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(registry.get("models") or []):
        if not isinstance(raw, Mapping):
            errors.append(f"models[{index}] must be an object")
            continue
        row = dict(raw)
        model_id = str(row.get("id") or "").strip()
        provider = str(row.get("provider") or "").strip()
        model = str(row.get("model") or "").strip()
        transport = str(row.get("transport") or "").strip()
        upstream_provider = str(row.get("upstream_provider") or "").strip()
        upstream_provider_slug = str(row.get("upstream_provider_slug") or "").strip()
        endpoint_tag = str(row.get("endpoint_tag") or "").strip()
        endpoint_name = str(row.get("endpoint_name") or "").strip()
        if not all(
            (
                model_id,
                provider,
                model,
                transport,
                upstream_provider,
                upstream_provider_slug,
                endpoint_tag,
                endpoint_name,
            )
        ):
            errors.append(
                f"models[{index}] requires id, provider, model, transport, upstream provider identity, endpoint tag, and endpoint_name"
            )
            continue
        if model_id in seen_ids:
            errors.append(f"duplicate registered model id: {model_id}")
        if (provider, model) in seen_identities:
            errors.append(f"duplicate registered provider/model identity: {provider}:{model}")
        seen_ids.add(model_id)
        seen_identities.add((provider, model))
        specs.append(
            {
                **row,
                "id": model_id,
                "provider": provider,
                "model": model,
                "transport": transport,
                "upstream_provider": upstream_provider,
                "upstream_provider_slug": upstream_provider_slug,
                "endpoint_tag": endpoint_tag,
                "endpoint_name": endpoint_name,
                "fixed_options": {
                    **dict(shared_fixed_options),
                    **dict(row.get("fixed_options") or {}),
                    "OPENROUTER_PROVIDER_ONLY": upstream_provider_slug,
                    "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER": upstream_provider,
                    "OPENROUTER_EXPECTED_ENDPOINT_NAME": endpoint_name,
                    "OPENROUTER_MAX_TOKENS": str(registry.get("output_token_cap")),
                    "GM_BENCH_OUTPUT_BUDGET_CELL": str(registry.get("output_token_cap")),
                },
                "absent_options": [
                    str(value)
                    for value in [*shared_absent_options, *(row.get("absent_options") or [])]
                    if str(value) not in {**dict(shared_fixed_options), **dict(row.get("fixed_options") or {})}
                ],
            }
        )
    return specs, errors


def _registered_lane_issues(
    payload: Mapping[str, Any],
    registry: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> list[str]:
    """Reject artifacts that are valid in general but not from the frozen route."""
    issues: list[str] = []
    run_info = payload.get("run_info") or {}
    if run_info.get("transport") != spec.get("transport"):
        issues.append("transport does not match the registered route")
    if run_info.get("profile") != registry.get("profile"):
        issues.append("profile does not match the registered lane")
    if run_info.get("preset") != registry.get("preset"):
        issues.append("preset does not match the registered lane")
    contract = run_info.get("benchmark_contract") or {}
    if contract.get("benchmark_version") != registry.get("contract"):
        issues.append("benchmark contract does not match the registered lane")

    options = run_info.get("provider_options") or {}
    if not isinstance(options, Mapping):
        return [*issues, "run_info.provider_options must be an object"]
    for key, expected in (spec.get("fixed_options") or {}).items():
        if str(options.get(key, "")) != str(expected):
            issues.append(f"provider option {key} does not match the registered value")
    for key in spec.get("absent_options") or []:
        if options.get(key) not in (None, ""):
            issues.append(f"provider option {key} must be absent")

    usage = ((payload.get("candidate") or {}).get("summary") or {}).get("usage") or {}
    decisions = ((payload.get("candidate") or {}).get("summary") or {}).get("decisions")
    if not isinstance(decisions, int) or usage.get("cost_decisions") != decisions:
        issues.append("candidate cost telemetry must cover every decision point")
    observed_upstreams = sorted({str(value) for value in usage.get("upstream_providers") or [] if value})
    expected_upstream = str(spec.get("upstream_provider") or "")
    if [value.casefold() for value in observed_upstreams] != [expected_upstream.casefold()]:
        issues.append("observed upstream provider does not match the registered route")
    return issues


def analyze(registry: Mapping[str, Any], payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Analyze valid artifacts matching the registry and report missing/rejected rows."""
    specs, config_errors = _registry_specs(registry)
    specs_by_identity = {(spec["provider"], spec["model"]): spec for spec in specs}
    candidates: dict[str, list[dict[str, Any]]] = {}
    rejected: list[dict[str, Any]] = []

    for index, payload in enumerate(payloads):
        artifact_sha256 = canonical_sha256(dict(payload))
        publication = payload.get("publication") or {}
        raw_artifact_sha256 = publication.get("raw_artifact_sha256") if isinstance(publication, Mapping) else None
        run_info = payload.get("run_info") or {}
        identity = (str(run_info.get("provider") or ""), str(run_info.get("model") or ""))
        spec = specs_by_identity.get(identity)
        if spec is None:
            continue
        reasons: list[str] = []
        report = validate_leaderboard_payload(dict(payload), policy=SOTA_V2_POLICY)
        if not report.ok:
            reasons.extend(report.errors)
        reasons.extend(_registered_lane_issues(payload, registry, spec))
        if raw_artifact_sha256 is not None and (
            not isinstance(raw_artifact_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", raw_artifact_sha256) is None
        ):
            reasons.append("publication.raw_artifact_sha256 must be a 64-character lowercase hex digest")
        try:
            per_seed = per_seed_pick_trader_lifts(
                payload,
                expected_repeats=int(registry.get("repeats", 3) or 3),
            )
        except (TypeError, ValueError) as exc:
            reasons.append(str(exc))
            per_seed = []
        if reasons:
            rejected.append({"artifact_index": index, "model_id": spec["id"], "reasons": reasons})
            continue

        lifts = [float(row["lift"]) for row in per_seed]
        ci_low, ci_high = bootstrap_mean_ci(lifts)
        candidates.setdefault(spec["id"], []).append(
            {
                "model_id": spec["id"],
                "provider": spec["provider"],
                "model": spec["model"],
                "per_seed": per_seed,
                "mean_lift": round(mean(lifts), 6),
                "bootstrap_ci95": [round(ci_low, 6), round(ci_high, 6)],
                "sign_flip_p_value": sign_flip_p_value(lifts),
                "seed_win_rate": round(sum(lift > 0.0 for lift in lifts) / len(lifts), 6),
                "artifact_sha256": artifact_sha256,
                "raw_artifact_sha256": raw_artifact_sha256 or artifact_sha256,
            }
        )

    rows: list[dict[str, Any]] = []
    for model_id, model_rows in candidates.items():
        if len(model_rows) == 1:
            rows.append(model_rows[0])
        else:
            rejected.append(
                {
                    "model_id": model_id,
                    "reasons": [f"found {len(model_rows)} eligible artifacts for one registered model"],
                }
            )

    raw_p_values = {
        str(row["model_id"]): float(row["sign_flip_p_value"]) for row in rows if row["sign_flip_p_value"] is not None
    }
    adjusted = holm_adjust(raw_p_values, family_size=len(specs)) if specs else {}
    rows = [
        {
            **row,
            "holm_adjusted_p_value": round(adjusted[str(row["model_id"])], 6),
            "holm_reject_at_0_05": adjusted[str(row["model_id"])] <= 0.05,
        }
        for row in rows
    ]
    rows = assign_tiers(rows)
    present = {str(row["model_id"]) for row in rows}
    missing = [spec["id"] for spec in specs if spec["id"] not in present]
    eligible_count = len(rows)
    status = "complete" if specs and not missing and not rejected and not config_errors else "partial"
    if eligible_count == 0:
        status = "no-eligible-artifacts"
    return {
        "schema_version": 1,
        "status": status,
        "primary_contrast": "paired lift versus pick-trader",
        "registered_model_count": len(specs),
        "eligible_model_count": eligible_count,
        "holm_family_size": len(specs),
        "bootstrap": {
            "label": "descriptive percentile 95% CI",
            "iterations": BOOTSTRAP_ITERATIONS,
            "seed": BOOTSTRAP_SEED,
        },
        "sign_flip_inference": "descriptive; exact under the symmetry assumption",
        "config_errors": config_errors,
        "missing_models": missing,
        "rejected_artifacts": rejected,
        "models": rows,
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    artifact_paths = args.artifacts or sorted(args.artifacts_dir.glob("*.json"))
    try:
        registry = _read_json(args.registry)
        payloads = [_read_json(path) for path in artifact_paths]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.exit(f"analyze_publication_panel: {exc}")

    result = analyze(registry, payloads)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if result["eligible_model_count"] == 0:
        print(text, end="")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    print(f"wrote {args.output} with {result['eligible_model_count']} eligible model row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
