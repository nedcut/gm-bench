#!/usr/bin/env python3
"""Robustness, power, and efficiency for a decision-model lane row.

A decision-lane row (``run_info.transport == "decision-api"``, see
docs/typesafe_jev_lane.md) runs the sota-v5 contract on the sota-v5 private
panel but sits outside the pre-registered chat-lane family, so
scripts/sota_v5_robustness.py must not see it: that script's Holm family and
the site's eligible-headline count are about the registered sixteen alone.
This script gives such a row the same follow-ups on its own, from the
operator's local raw artifact, and writes aggregates only: no seed
identifiers, no per-seed or per-fold vectors, no episode content. The
pick-trader contrast is reported with an unadjusted exact sign-flip p-value
and labelled as outside any Holm family.

Outputs (regenerable; ``--check`` recomputes and diffs):
  results/analysis/decision-lane-<id>.json
  results/analysis/decision-lane-<id>.md
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
from analyze_publication_panel import per_seed_pick_trader_lifts, sign_flip_p_value  # noqa: E402
from weight_sensitivity import analyse as weight_sensitivity_analyse  # noqa: E402

from gm_bench.official import REDACTED_SEEDS_SENTINEL  # noqa: E402

ANALYSIS_DIR = ROOT / "results" / "analysis"
DEFAULT_ARTIFACT = ROOT / "results" / "leaderboard" / "decision-lane" / "typesafe-jev-1.13-openrouter.json"
DEFAULT_RAW = ROOT / "data" / "publication" / "jev-panel" / "typesafe-jev-1.13-openrouter-private-panel.raw.json"
ALPHA = 0.05
POWER = 0.8
Z_ALPHA_HALF = 1.959963984540054
Z_POWER = 0.8416212335729143
ASSUMED_MDD = 30.0
PRIVATE_KEYS = frozenset({"seed", "seeds", "per_seed", "seed_identifiers", "episodes"})


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _contains_private_keys(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key) in PRIVATE_KEYS or _contains_private_keys(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_private_keys(item) for item in value)
    return False


def _mdd(sample_stddev: float, seed_count: int) -> float:
    return (Z_ALPHA_HALF + Z_POWER) * sample_stddev / math.sqrt(seed_count)


def _scores_by_seed(block: dict[str, Any]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for episode in block.get("episodes") or []:
        scores[int(episode["seed"])] = float(episode["final_score"])
    return scores


def _baseline_contrasts(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Seed win counts and mean paired lift against every scripted baseline."""
    candidate = _scores_by_seed(raw["candidate"])
    rows: list[dict[str, Any]] = []
    for block in raw.get("baselines") or []:
        baseline = _scores_by_seed(block)
        if set(baseline) != set(candidate):
            raise SystemExit(f"baseline {block.get('agent')} does not share the candidate seed panel")
        lifts = [candidate[seed] - baseline[seed] for seed in sorted(candidate)]
        rows.append(
            {
                "baseline": str(block.get("agent")),
                "baseline_mean_score": round(mean(baseline.values()), 3),
                "mean_paired_lift": round(mean(lifts), 3),
                "paired_lift_stddev": round(stdev(lifts), 3),
                "seeds_won": sum(1 for lift in lifts if lift > 0),
                "seeds_total": len(lifts),
                "sign_flip_p_value": round(float(sign_flip_p_value(lifts) or 0.0), 6),
            }
        )
    rows.sort(key=lambda row: -row["baseline_mean_score"])
    return rows


def _efficiency(artifact: dict[str, Any]) -> dict[str, Any]:
    normalized = artifact["normalized"]
    usage = normalized["candidate_usage"]
    summary = artifact["candidate"]["summary"]
    decisions = int(normalized["candidate_decisions"])
    cost = float(usage["cost_usd"])
    score = float(summary["mean_score"])
    return {
        "model": usage["model"],
        "mean_score": round(score, 3),
        "cost_usd": round(cost, 5),
        "cost_usd_per_decision": round(cost / decisions, 6),
        "cost_usd_per_score_point": round(cost / score, 6),
        "decisions": decisions,
        "api_calls": int(usage["api_calls"]),
        "wall_clock_seconds": round(float(usage["harness_latency_ms"]) / 1000.0, 1),
        "seconds_per_decision": round(float(usage["harness_latency_ms"]) / 1000.0 / decisions, 3),
        "api_seconds_per_call": round(float(usage["api_latency_ms"]) / 1000.0 / int(usage["api_calls"]), 3),
        "mean_input_tokens_per_decision": float(usage["mean_input_tokens_per_decision"]),
        # The gateway reports answer tokens for a model that generates no text;
        # they are billed at zero (cost_usd reproduces from input tokens alone)
        # and are recorded here as reported rather than zeroed.
        "mean_output_tokens_per_decision": float(usage["mean_output_tokens_per_decision"]),
        "output_tokens_billed": False,
        "decision_failure_rate": float(summary["decision_failure_rate"]),
        "illegal_actions": int(summary["illegal_actions"]),
        "rejected_offers": int(summary.get("rejected_offers", 0)),
    }


def build_analysis(*, artifact_path: Path, raw_path: Path, draws: int, perturbation: float) -> dict[str, Any]:
    artifact = _load(artifact_path)
    raw = _load(raw_path)
    run_info = artifact["run_info"]
    if run_info.get("transport") != "decision-api":
        raise SystemExit("artifact is not a decision-api row")
    if artifact.get("seeds") != REDACTED_SEEDS_SENTINEL:
        raise SystemExit("artifact must be the redacted publication row")
    publication = artifact.get("publication") or {}

    lifts = [float(row["lift"]) for row in per_seed_pick_trader_lifts(raw, expected_repeats=1)]
    seed_count = len(lifts)
    if seed_count != int(run_info["seed_panel"]["count"]):
        raise SystemExit("raw artifact does not cover the published seed panel")
    full_mean = mean(lifts)
    sample_stddev = stdev(lifts)
    total = sum(lifts)
    fold_means = [(total - value) / (seed_count - 1) for value in lifts]
    fold_p = []
    for index in range(seed_count):
        fold_p.append(float(sign_flip_p_value(lifts[:index] + lifts[index + 1 :]) or 0.0))
    full_p = float(sign_flip_p_value(lifts) or 0.0)
    full_reject = full_p <= ALPHA
    flips = sum(1 for value in fold_p if (value <= ALPHA) != full_reject)
    observed_mdd = _mdd(sample_stddev, seed_count)

    weights = weight_sensitivity_analyse(seeds=[], seasons=0, draws=draws, perturbation=perturbation, result=raw_path)
    candidate = next(name for name in weights["panel"]["rows"] if ":" in name)
    canonical = weights["canonical_ranking"]

    paired = artifact["paired"]
    summary = artifact["candidate"]["summary"]
    return {
        "schema_version": 1,
        "benchmark_version": "sota-v5",
        "lane": "decision-api",
        "generated_by": "scripts/decision_lane_analysis.py",
        "row": {
            "id": artifact["agent"],
            "model": summary["usage"]["model"],
            "provider": run_info["provider"],
            "transport": run_info["transport"],
            "route": run_info.get("provider_options", {}).get("JEV_ROUTE"),
            "provider_options": {
                key: value
                for key, value in sorted((run_info.get("provider_options") or {}).items())
                if key.startswith("JEV_")
            },
            "scaffold_fingerprint": run_info.get("scaffold_fingerprint"),
            "contract_fingerprint": run_info["benchmark_contract"]["contract_fingerprint"],
            "seed_panel": {
                "name": run_info["seed_panel"]["name"],
                "count": run_info["seed_panel"]["count"],
                "sha256": run_info["seed_panel"]["sha256"],
            },
            "artifact": str(artifact_path.relative_to(ROOT)),
            "raw_artifact_sha256": publication.get("raw_artifact_sha256"),
            "mean_score": summary["mean_score"],
            "score_stddev": summary["score_stddev"],
            "decisions": summary["decisions"],
            "failed_decisions": summary["failed_decisions"],
            "illegal_actions": summary["illegal_actions"],
            "mechanic_breakdown": publication.get("mechanic_breakdown"),
        },
        "redaction": {
            "private_seed_panel": True,
            "seed_identifiers_included": False,
            "per_seed_rows_included": False,
            "public_view": "aggregate-only",
            "note": (
                "Leave-one-out is summarised by a fold-mean range and flip counts only; a per-fold vector "
                "would invert back to the per-seed lifts that redaction removes."
            ),
        },
        "family": {
            "holm_family": None,
            "note": (
                "This row was not pre-registered and is not a member of the sota-v5 Holm family of sixteen. "
                "The pick-trader p-value below is the unadjusted exact sign-flip test for this one row and "
                "must not be read beside the headline rows' Holm-adjusted values."
            ),
        },
        "panel_mean_contrast": {
            "baseline_panel_mean_score": artifact["normalized"]["baseline_panel_mean_score"],
            "paired_lift_mean": paired["paired_lift_mean"],
            "paired_lift_ci95": paired["paired_lift_ci95"],
            "candidate_seed_win_rate": paired["candidate_seed_win_rate"],
        },
        "pick_trader_contrast": {
            "pick_trader_mean_score": paired["best_baseline"]["mean_score"],
            "full_panel_mean_lift": round(full_mean, 6),
            "full_panel_lift_stddev": round(sample_stddev, 6),
            "seeds_won": sum(1 for value in lifts if value > 0),
            "seeds_total": seed_count,
            "sign_flip_p_value_unadjusted": round(full_p, 6),
            "reject_at_0_05_unadjusted": full_reject,
            "leave_one_seed_out": {
                "folds": seed_count,
                "mean_lift_range": round(max(fold_means) - min(fold_means), 6),
                "p_min": round(min(fold_p), 6),
                "p_max": round(max(fold_p), 6),
                "rejection_flips": flips,
                "rejection_stable": flips == 0,
            },
            "minimum_detectable_difference": {
                "alpha": ALPHA,
                "power": POWER,
                "formula": "(z_{1-alpha/2} + z_power) * sd / sqrt(n)",
                "observed": round(observed_mdd, 3),
                "assumed": ASSUMED_MDD,
                "within_assumed": observed_mdd <= ASSUMED_MDD,
            },
        },
        "baseline_contrasts": _baseline_contrasts(raw),
        "weight_sensitivity": {
            "method": {
                "source": "score_components persisted on raw episode rows (never published)",
                "perturbation": f"independent uniform multipliers in [{1.0 - perturbation:.2f}, {1.0 + perturbation:.2f}]",
                "draws": draws,
                "panel": "candidate plus the eight scripted baselines",
            },
            "candidate": candidate,
            "candidate_canonical_rank": canonical.index(candidate) + 1,
            "canonical_ranking": canonical,
            "canonical_mean_scores": {name: round(value, 6) for name, value in weights["canonical_scores"].items()},
            "max_recombination_error": round(weights["max_recombination_error"], 9),
            "adjacent_rank_flip_probability": weights["adjacent_rank_flip_probability"],
            "kendall_tau": {key: round(value, 6) for key, value in weights["kendall_tau"].items()},
            "candidate_adjacent_flip_probability_max": max(
                (p for pair, p in weights["adjacent_rank_flip_probability"].items() if candidate in pair),
                default=0.0,
            ),
            "canonical_weights": weights["canonical_weights"],
        },
        "efficiency": _efficiency(artifact),
    }


def render_markdown(analysis: dict[str, Any]) -> str:
    row = analysis["row"]
    panel = analysis["panel_mean_contrast"]
    pick = analysis["pick_trader_contrast"]
    loo = pick["leave_one_seed_out"]
    mdd = pick["minimum_detectable_difference"]
    weights = analysis["weight_sensitivity"]
    eff = analysis["efficiency"]
    lines = [
        f"# Decision-model lane: {row['model']}",
        "",
        f"Lane `{analysis['lane']}`, provider `{row['provider']}`, route `{row['route']}`, contract "
        f"`{row['contract_fingerprint']}`, scaffold `{row['scaffold_fingerprint']}`, "
        f"{row['seed_panel']['count']}-seed private panel `{row['seed_panel']['sha256'][:16]}`. "
        "Recomputed from the operator's local raw artifact; every number below is aggregate.",
        "",
        "This row is not in the sota-v5 Holm family. Its score measures the model plus the "
        "question scaffold in `examples/typesafe_jev_agent.py`; the comparison it supports is "
        "against the scripted baselines, not against the headline chat-lane rows.",
        "",
        "## Score and contrasts",
        "",
        f"Mean score {row['mean_score']:.3f} (sd {row['score_stddev']:.3f}) over {row['decisions']} decisions, "
        f"{row['failed_decisions']} failed, {row['illegal_actions']} illegal actions.",
        "",
        f"Against the baseline panel mean ({panel['baseline_panel_mean_score']:.3f}): paired lift "
        f"{panel['paired_lift_mean']:.2f} (95% CI {panel['paired_lift_ci95'][0]:.2f} to "
        f"{panel['paired_lift_ci95'][1]:.2f}), seed win rate {panel['candidate_seed_win_rate']:.3f}.",
        "",
        f"Against pick-trader ({pick['pick_trader_mean_score']:.3f}): mean paired lift "
        f"{pick['full_panel_mean_lift']:.2f} (sd {pick['full_panel_lift_stddev']:.2f}), "
        f"{pick['seeds_won']} of {pick['seeds_total']} seeds won, unadjusted exact sign-flip p "
        f"{pick['sign_flip_p_value_unadjusted']:.4f}"
        f" ({'rejects' if pick['reject_at_0_05_unadjusted'] else 'does not reject'} at 0.05, unadjusted).",
        "",
        "| baseline | baseline mean | mean paired lift | lift sd | seeds won | sign-flip p |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in analysis["baseline_contrasts"]:
        lines.append(
            f"| {item['baseline']} | {item['baseline_mean_score']:.1f} | {item['mean_paired_lift']:.2f} | "
            f"{item['paired_lift_stddev']:.2f} | {item['seeds_won']}/{item['seeds_total']} | "
            f"{item['sign_flip_p_value']:.4f} |"
        )
    lines += [
        "",
        "## Robustness and power (pick-trader contrast)",
        "",
        f"Leave-one-seed-out over {loo['folds']} folds: fold-mean lift range {loo['mean_lift_range']:.2f}, "
        f"p from {loo['p_min']:.4f} to {loo['p_max']:.4f}, {loo['rejection_flips']} rejection flip(s)"
        f" ({'stable' if loo['rejection_stable'] else 'fragile'}).",
        "",
        f"Minimum detectable difference at alpha {mdd['alpha']} and power {mdd['power']}: "
        f"{mdd['observed']:.1f} points observed against the {mdd['assumed']:.0f}-point figure the "
        f"sota-v5 analysis assumes ({'within' if mdd['within_assumed'] else 'above'} the assumed figure).",
        "",
        "## Weight sensitivity",
        "",
        f"With {weights['method']['draws']} draws of {weights['method']['perturbation']} on the score weights, "
        f"the candidate's canonical rank among the nine rows is {weights['candidate_canonical_rank']} "
        f"({' > '.join(weights['canonical_ranking'])}); the highest adjacent flip probability involving the "
        f"candidate is {weights['candidate_adjacent_flip_probability_max']:.3f}; Kendall tau mean "
        f"{weights['kendall_tau']['mean']:.3f} (p05 {weights['kendall_tau']['p05']:.3f}).",
        "",
        "## Efficiency",
        "",
        "| model | mean score | cost USD | USD/decision | s/decision | API s/call | input tokens/decision | reported output tokens/decision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {eff['model']} | {eff['mean_score']:.1f} | {eff['cost_usd']:.2f} | {eff['cost_usd_per_decision']:.5f} | "
        f"{eff['seconds_per_decision']:.2f} | {eff['api_seconds_per_call']:.2f} | "
        f"{eff['mean_input_tokens_per_decision']:.0f} | {eff['mean_output_tokens_per_decision']:.0f} |",
        "",
        "Output tokens are reported by the gateway for a model that generates no text and are billed at "
        "zero; the recorded cost reproduces from input tokens alone.",
        "",
    ]
    return "\n".join(lines)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--perturbation", type=float, default=0.30)
    parser.add_argument("--check", action="store_true", help="recompute and diff against the committed files")
    args = parser.parse_args(argv)

    analysis = build_analysis(
        artifact_path=args.artifact, raw_path=args.raw, draws=args.draws, perturbation=args.perturbation
    )
    if _contains_private_keys(analysis):
        raise SystemExit("refusing to write: analysis contains a private seed or episode key")
    stem = args.artifact.stem
    outputs = [
        (ANALYSIS_DIR / f"decision-lane-{stem}.json", _dump(analysis)),
        (ANALYSIS_DIR / f"decision-lane-{stem}.md", render_markdown(analysis)),
    ]
    if args.check:
        stale = [path for path, text in outputs if not path.exists() or path.read_text() != text]
        for path in stale:
            print(f"stale: {path.relative_to(ROOT)}")
        return 1 if stale else 0
    for path, text in outputs:
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
