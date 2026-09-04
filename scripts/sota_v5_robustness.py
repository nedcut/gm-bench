#!/usr/bin/env python3
"""Robustness, power, and efficiency follow-ups for the sota-v5 publication panel.

The committed leaderboard rows are redacted: `paired.per_seed` is emptied and
episode rows are dropped, so leave-one-seed-out work has to be recomputed from
the operator's local raw artifacts.  Everything this script *writes* is
aggregate: no seed identifiers, no per-seed or per-fold vectors, no episode
content.  Leave-one-out results are reported as extremes and counts only,
because a full 29-entry fold vector is an invertible transform of the per-seed
lifts and would re-publish exactly what redaction removed.

Outputs (all regenerable; `--check` recomputes and diffs):
  results/analysis/sota-v5-robustness.json
  results/analysis/sota-v5-robustness.md
  results/analysis/sota-v5-weight-sensitivity.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import mean, stdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# isort: split
from analyze_publication_panel import (  # noqa: E402
    holm_adjust,
    per_seed_pick_trader_lifts,
    sign_flip_p_value,
)
from weight_sensitivity import analyse as weight_sensitivity_analyse  # noqa: E402

LEADERBOARD_DIR = ROOT / "results" / "leaderboard" / "sota-v5"
RAW_DIR = ROOT / "data" / "publication" / "sota-v5-panel" / "raw"
ANALYSIS_PATH = ROOT / "results" / "analysis" / "publication-panel-analysis-v5.json"
OUT_ROBUSTNESS_JSON = ROOT / "results" / "analysis" / "sota-v5-robustness.json"
OUT_ROBUSTNESS_MD = ROOT / "results" / "analysis" / "sota-v5-robustness.md"
OUT_WEIGHTS_JSON = ROOT / "results" / "analysis" / "sota-v5-weight-sensitivity.json"

RAW_SUFFIX = "--4096.json"
ALPHA = 0.05
POWER = 0.8
# Two-sided normal quantiles: z(1 - alpha/2) and z(power).
Z_ALPHA_HALF = 1.959963984540054
Z_POWER = 0.8416212335729143
ASSUMED_MDD = 30.0

# Keys that must never appear anywhere in a published analysis file; mirrors
# PRIVATE_SEED_KEYS in scripts/package_publication_release.py.
PRIVATE_KEYS = frozenset({"seed", "seeds", "per_seed", "seed_identifiers", "episodes"})


def _model_ids() -> list[str]:
    return sorted(path.stem for path in LEADERBOARD_DIR.glob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _contains_private_keys(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key) in PRIVATE_KEYS or _contains_private_keys(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_private_keys(item) for item in value)
    return False


def _mdd(sample_stddev: float, seed_count: int) -> float:
    """Smallest true paired difference detectable at alpha=0.05, power=0.8."""
    return (Z_ALPHA_HALF + Z_POWER) * sample_stddev / math.sqrt(seed_count)


def _lifts_by_model(repeats: int) -> dict[str, list[float]]:
    lifts: dict[str, list[float]] = {}
    for model_id in _model_ids():
        raw_path = RAW_DIR / f"{model_id}{RAW_SUFFIX}"
        if not raw_path.exists():
            raise SystemExit(f"missing raw artifact for {model_id}: {raw_path}")
        rows = per_seed_pick_trader_lifts(_load(raw_path), expected_repeats=repeats)
        lifts[model_id] = [float(row["lift"]) for row in rows]
    return lifts


def _holm_map(lifts: dict[str, list[float]], family_size: int) -> dict[str, float]:
    """Exact sign-flip p-values for every model, Holm-adjusted over the fixed family."""
    raw_p = {model_id: float(sign_flip_p_value(values)) for model_id, values in lifts.items()}
    return holm_adjust(raw_p, family_size=family_size)


def _efficiency_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id in _model_ids():
        payload = _load(LEADERBOARD_DIR / f"{model_id}.json")
        normalized = payload["normalized"]
        usage = normalized["candidate_usage"]
        summary = payload["candidate"]["summary"]
        decisions = int(normalized["candidate_decisions"])
        cost = float(usage["cost_usd"])
        score = float(summary["mean_score"])
        rows.append(
            {
                "model_id": model_id,
                "model": usage["model"],
                "mean_score": round(score, 3),
                "cost_usd": round(cost, 5),
                "cost_usd_per_decision": round(cost / decisions, 6),
                "cost_usd_per_score_point": round(cost / score, 6),
                "decisions": decisions,
                "wall_clock_seconds": round(float(usage["harness_latency_ms"]) / 1000.0, 1),
                "seconds_per_decision": round(float(usage["harness_latency_ms"]) / 1000.0 / decisions, 3),
                "mean_input_tokens_per_decision": float(usage["mean_input_tokens_per_decision"]),
                "mean_output_tokens_per_decision": float(usage["mean_output_tokens_per_decision"]),
                "mean_reasoning_tokens_per_decision": float(usage.get("mean_reasoning_tokens_per_decision") or 0.0),
                "mean_tokens_per_decision": float(usage["mean_tokens_per_decision"]),
                "decision_failure_rate": float(summary["decision_failure_rate"]),
                "illegal_actions": int(summary["illegal_actions"]),
            }
        )
    return rows


def _extremes(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    lowest = min(rows, key=lambda row: row[field])
    highest = max(rows, key=lambda row: row[field])
    return {
        "lowest": {"model_id": lowest["model_id"], "value": lowest[field]},
        "highest": {"model_id": highest["model_id"], "value": highest[field]},
    }


def build_robustness(repeats: int) -> dict[str, Any]:
    analysis = _load(ANALYSIS_PATH)
    family_size = int(analysis["holm_family_size"])
    published = {row["model_id"]: row for row in analysis["models"]}
    lifts = _lifts_by_model(repeats)
    seed_count = len(next(iter(lifts.values())))
    if any(len(values) != seed_count for values in lifts.values()):
        raise SystemExit("model rows do not share a seed panel size")

    full_holm = _holm_map(lifts, family_size)
    full_reject = {model_id: value <= ALPHA for model_id, value in full_holm.items()}

    # One fold per panel position: the same position is dropped for every model
    # so each fold remains a coherent 28-seed panel.
    fold_holm: list[dict[str, float]] = []
    for index in range(seed_count):
        fold_lifts = {model_id: values[:index] + values[index + 1 :] for model_id, values in lifts.items()}
        fold_holm.append(_holm_map(fold_lifts, family_size))

    models: list[dict[str, Any]] = []
    for model_id, values in lifts.items():
        full_mean = mean(values)
        total = sum(values)
        fold_means = [(total - value) / (seed_count - 1) for value in values]
        fold_p = [fold[model_id] for fold in fold_holm]
        flips = sum(1 for value in fold_p if (value <= ALPHA) != full_reject[model_id])
        sample_stddev = stdev(values)
        observed_mdd = _mdd(sample_stddev, seed_count)
        models.append(
            {
                "model_id": model_id,
                "model": published[model_id]["model"],
                "full_panel_mean_lift": round(full_mean, 6),
                "full_panel_lift_stddev": round(sample_stddev, 6),
                "full_panel_holm_adjusted_p_value": round(full_holm[model_id], 6),
                "full_panel_holm_reject_at_0_05": full_reject[model_id],
                "published_holm_reject_at_0_05": bool(published[model_id]["holm_reject_at_0_05"]),
                "published_holm_adjusted_p_value": published[model_id]["holm_adjusted_p_value"],
                "leave_one_seed_out": {
                    "folds": seed_count,
                    "mean_lift_min": round(min(fold_means), 6),
                    "mean_lift_max": round(max(fold_means), 6),
                    "mean_lift_range": round(max(fold_means) - min(fold_means), 6),
                    "holm_adjusted_p_min": round(min(fold_p), 6),
                    "holm_adjusted_p_max": round(max(fold_p), 6),
                    "holm_rejection_flips": flips,
                    "holm_rejection_stable": flips == 0,
                },
                "minimum_detectable_difference": {
                    "observed": round(observed_mdd, 3),
                    "assumed": ASSUMED_MDD,
                    "within_assumed": observed_mdd <= ASSUMED_MDD,
                },
            }
        )
    models.sort(key=lambda row: row["model_id"])

    efficiency = _efficiency_rows()
    mdds = [row["minimum_detectable_difference"]["observed"] for row in models]
    return {
        "schema_version": 1,
        "benchmark_version": "sota-v5",
        "generated_by": "scripts/sota_v5_robustness.py",
        "primary_contrast": analysis["primary_contrast"],
        "holm_family_size": family_size,
        "seed_count": seed_count,
        "redaction": {
            "private_seed_panel": True,
            "seed_identifiers_included": False,
            "per_seed_rows_included": False,
            "public_view": "aggregate-only",
            "note": (
                "Leave-one-out is summarised by extremes and flip counts only. A full per-fold vector would "
                "invert back to the per-seed lifts that redaction removes."
            ),
        },
        "power": {
            "alpha": ALPHA,
            "power": POWER,
            "test": "two-sided paired sign-flip, normal approximation for the sample-size formula",
            "formula": "(z_{1-alpha/2} + z_power) * sd / sqrt(n)",
            "assumed_mdd": ASSUMED_MDD,
            "assumed_basis": analysis["within_seed_noise"]["basis"],
            "observed_mdd_min": min(mdds),
            "observed_mdd_max": max(mdds),
            "observed_mdd_median": round(sorted(mdds)[len(mdds) // 2], 3),
            "models_exceeding_assumed_mdd": [
                row["model_id"] for row in models if not row["minimum_detectable_difference"]["within_assumed"]
            ],
        },
        "leave_one_seed_out_summary": {
            "folds": seed_count,
            "models_with_any_rejection_flip": [
                row["model_id"] for row in models if not row["leave_one_seed_out"]["holm_rejection_stable"]
            ],
            "max_mean_lift_range": max(row["leave_one_seed_out"]["mean_lift_range"] for row in models),
        },
        "leave_one_out_by_season_or_mechanic": {
            "status": "not-possible",
            "reason": (
                "publication.mechanic_breakdown carries accepted/rejected counts only, and no per-seed score "
                "decomposition by season or mechanic is persisted, so a mechanic-held-out lift cannot be formed."
            ),
        },
        "models": models,
        "efficiency": {
            "rows": efficiency,
            "extremes": {
                field: _extremes(efficiency, field)
                for field in (
                    "cost_usd",
                    "cost_usd_per_decision",
                    "cost_usd_per_score_point",
                    "seconds_per_decision",
                    "mean_tokens_per_decision",
                    "mean_output_tokens_per_decision",
                    "mean_score",
                )
            },
        },
    }


def build_weight_sensitivity(draws: int, perturbation: float) -> dict[str, Any]:
    per_model: list[dict[str, Any]] = []
    canonical_weights: dict[str, float] = {}
    for model_id in _model_ids():
        raw_path = RAW_DIR / f"{model_id}{RAW_SUFFIX}"
        result = weight_sensitivity_analyse(
            seeds=[], seasons=0, draws=draws, perturbation=perturbation, result=raw_path
        )
        panel = result["panel"]
        candidate = next(name for name in panel["rows"] if ":" in name)
        canonical = result["canonical_ranking"]
        per_model.append(
            {
                "model_id": model_id,
                "model": candidate,
                "candidate_canonical_rank": canonical.index(candidate) + 1,
                "canonical_ranking": canonical,
                "canonical_mean_scores": {name: round(value, 6) for name, value in result["canonical_scores"].items()},
                "max_recombination_error": round(result["max_recombination_error"], 9),
                "adjacent_rank_flip_probability": result["adjacent_rank_flip_probability"],
                "kendall_tau": {key: round(value, 6) for key, value in result["kendall_tau"].items()},
                "candidate_adjacent_flip_probability_max": max(
                    (
                        probability
                        for pair, probability in result["adjacent_rank_flip_probability"].items()
                        if candidate in pair
                    ),
                    default=0.0,
                ),
            }
        )
        canonical_weights = result["canonical_weights"]
    return {
        "schema_version": 1,
        "benchmark_version": "sota-v5",
        "generated_by": "scripts/sota_v5_robustness.py",
        "method": {
            "source": "score_components persisted on raw episode rows (never published)",
            "perturbation": f"independent uniform multipliers in [{1.0 - perturbation:.2f}, {1.0 + perturbation:.2f}]",
            "draws": draws,
            "panel": "candidate plus the eight scripted baselines, one artifact per model",
        },
        "redaction": {
            "private_seed_panel": True,
            "seed_identifiers_included": False,
            "per_seed_rows_included": False,
            "public_view": "aggregate-only",
        },
        "canonical_weights": canonical_weights,
        "models": per_model,
    }


def render_markdown(robustness: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# sota-v5 robustness, power, and efficiency")
    lines.append("")
    lines.append(
        f"Primary contrast: {robustness['primary_contrast']}. "
        f"{robustness['seed_count']} paired seeds, Holm family size {robustness['holm_family_size']}. "
        "Recomputed from the operator's local raw artifacts; every number below is aggregate."
    )
    lines.append("")
    power = robustness["power"]
    lines.append("## Minimum detectable difference")
    lines.append("")
    lines.append(
        f"At alpha {power['alpha']} and power {power['power']} over {robustness['seed_count']} paired seeds, the "
        f"observed per-model detectable difference runs {power['observed_mdd_min']} to {power['observed_mdd_max']} "
        f"points (median {power['observed_mdd_median']}), against the {power['assumed_mdd']}-point figure the "
        "analysis assumes."
    )
    exceeding = power["models_exceeding_assumed_mdd"]
    lines.append("")
    lines.append(
        "Rows above the assumed figure: " + ", ".join(exceeding) + "."
        if exceeding
        else "No row needs a larger true difference than the assumed 30 points."
    )
    lines.append("")
    lines.append("## Leave-one-seed-out")
    lines.append("")
    flipped = robustness["leave_one_seed_out_summary"]["models_with_any_rejection_flip"]
    lines.append(
        f"Each of the {robustness['seed_count']} folds drops one panel position from every model at once and "
        "recomputes the exact sign-flip test on the remaining 28 seeds, with the Holm family held at "
        f"{robustness['holm_family_size']}. "
        + (
            "Rejection status flips for: " + ", ".join(flipped) + "."
            if flipped
            else "No model changes its Holm rejection status in any fold."
        )
    )
    lines.append("")
    for row in robustness["models"]:
        loo = row["leave_one_seed_out"]
        if loo["holm_rejection_stable"]:
            continue
        lines.append(
            f"{row['model']} is the fragile row: its Holm-adjusted p is "
            f"{row['full_panel_holm_adjusted_p_value']} on the full panel, but across the {loo['folds']} folds it "
            f"ranges {loo['holm_adjusted_p_min']} to {loo['holm_adjusted_p_max']}, and "
            f"{loo['holm_rejection_flips']} fold(s) cross 0.05. A single seed sustains the non-rejection."
        )
    lines.append("")
    lines.append("| model | mean lift | lift sd | Holm reject | LOO mean lift min | max | range | flips | MDD |")
    lines.append("| --- | ---: | ---: | :---: | ---: | ---: | ---: | ---: | ---: |")
    for row in sorted(robustness["models"], key=lambda item: -item["full_panel_mean_lift"]):
        loo = row["leave_one_seed_out"]
        lines.append(
            f"| {row['model']} | {row['full_panel_mean_lift']:.2f} | {row['full_panel_lift_stddev']:.2f} | "
            f"{'yes' if row['full_panel_holm_reject_at_0_05'] else 'no'} | {loo['mean_lift_min']:.2f} | "
            f"{loo['mean_lift_max']:.2f} | {loo['mean_lift_range']:.2f} | {loo['holm_rejection_flips']} | "
            f"{row['minimum_detectable_difference']['observed']:.1f} |"
        )
    lines.append("")
    lines.append("## Efficiency")
    lines.append("")
    lines.append(
        "| model | mean score | cost USD | USD/decision | s/decision | tokens/decision | out tokens/decision |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in sorted(robustness["efficiency"]["rows"], key=lambda item: -item["mean_score"]):
        lines.append(
            f"| {row['model']} | {row['mean_score']:.1f} | {row['cost_usd']:.2f} | "
            f"{row['cost_usd_per_decision']:.5f} | {row['seconds_per_decision']:.2f} | "
            f"{row['mean_tokens_per_decision']:.0f} | {row['mean_output_tokens_per_decision']:.0f} |"
        )
    lines.append("")
    lines.append(
        "Season- and mechanic-held-out robustness is not possible for v5: "
        + robustness["leave_one_out_by_season_or_mechanic"]["reason"]
    )
    lines.append("")
    return "\n".join(lines)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _guard(payload: dict[str, Any], label: str) -> None:
    if _contains_private_keys(payload):
        raise SystemExit(f"{label} contains a private seed key; refusing to write")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=1, help="candidate repeats per seed in the raw artifacts")
    parser.add_argument("--draws", type=int, default=200, help="weight-perturbation draws")
    parser.add_argument("--perturbation", type=float, default=0.30)
    parser.add_argument("--check", action="store_true", help="recompute and diff against the committed files")
    args = parser.parse_args(argv)

    robustness = build_robustness(args.repeats)
    _guard(robustness, "robustness")
    weights = build_weight_sensitivity(args.draws, args.perturbation)
    _guard(weights, "weight sensitivity")
    markdown = render_markdown(robustness)

    outputs = [
        (OUT_ROBUSTNESS_JSON, _dump(robustness)),
        (OUT_WEIGHTS_JSON, _dump(weights)),
        (OUT_ROBUSTNESS_MD, markdown),
    ]
    if args.check:
        stale = [path for path, text in outputs if not path.exists() or path.read_text() != text]
        for path in stale:
            print(f"stale: {path.relative_to(ROOT)}")
        if stale:
            return 1
        print("up to date: " + ", ".join(str(path.relative_to(ROOT)) for path, _ in outputs))
        return 0
    for path, text in outputs:
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
