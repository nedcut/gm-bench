#!/usr/bin/env python3
"""Estimate score differences detectable by GM-Bench's paired panel.

This is a diagnostic script, not part of the benchmark contract.  It uses the
scripted policies as an empirical distribution of seed-by-policy residuals,
then simulates two hypothetical model rows on that distribution.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from itertools import combinations
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

# Make direct source-tree invocation (`python scripts/...`) work as well as
# `uv run`, whose editable install already provides this import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# isort: split
from gm_bench.agents import AGENTS
from gm_bench.runner import run_many

BASELINES = ["random", "conservative", "win-now", "rebuild", "value", "shrewd", "strategic", "pick-trader"]


def _within_seed_stddev(path: Path) -> float:
    payload = json.loads(path.read_text())
    candidates = [payload.get("summary"), payload.get("candidate", {}).get("summary")]
    for summary in candidates:
        if isinstance(summary, dict) and "within_seed_score_stddev" in summary:
            return float(summary["within_seed_score_stddev"])
    raise ValueError(f"{path} does not contain a run summary with within_seed_score_stddev")


def _baseline_scores(seeds: list[int], seasons: int) -> dict[str, list[float]]:
    """Run the deterministic reference panel once, in-process and uncached."""
    scores: dict[str, list[float]] = {}
    for name in BASELINES:
        result = run_many(AGENTS[name](), seeds=seeds, seasons=seasons, workers=1)
        scores[name] = [float(episode["final_score"]) for episode in result["episodes"]]
    return scores


def _paired_residuals(scores: dict[str, list[float]]) -> list[float]:
    """Pool centred same-seed policy differences as observed paired noise."""
    residuals: list[float] = []
    for left, right in combinations(scores.values(), 2):
        differences = [a - b for a, b in zip(left, right, strict=True)]
        centre = mean(differences)
        residuals.extend(value - centre for value in differences)
    return residuals


def _simulate_detection_rate(
    residuals: list[float],
    *,
    seed_count: int,
    repeats: int,
    within_seed_stddev: float,
    gap: float,
    trials: int,
    rng: random.Random,
) -> float:
    detections = 0
    # The paired residual is sampled with replacement because 12+ seed designs
    # extrapolate the observed eight-seed panel rather than claim new data.
    repeat_noise = within_seed_stddev / math.sqrt(repeats)
    for _ in range(trials):
        lifts = [gap + rng.choice(residuals) + rng.gauss(0.0, math.sqrt(2.0) * repeat_noise) for _ in range(seed_count)]
        if _sign_flip_normal_p_value(lifts) < 0.05:
            detections += 1
    return detections / trials


def _sign_flip_normal_p_value(lifts: list[float]) -> float:
    """Fast normal approximation to the two-sided sign-flip null distribution.

    Enumerating 2^24 flips inside every synthetic trial is needlessly costly.
    Conditional on observed magnitudes, a random sign-flip mean has variance
    sum(lift**2) / n**2; its normal approximation is accurate at the larger
    extrapolated panels.  The exact eight-seed resolution remains reported
    separately below.
    """
    observed = abs(mean(lifts))
    standard_error = math.sqrt(sum(value * value for value in lifts)) / len(lifts)
    if standard_error == 0:
        return 1.0
    return math.erfc(observed / (math.sqrt(2.0) * standard_error))


def analyse(
    *,
    seeds: list[int],
    seasons: int,
    repeats: int,
    within_seed_stddev: float,
    trials: int,
    seed_counts: list[int],
    target_power: float,
    gap_step: float,
    max_gap: float,
) -> dict[str, Any]:
    scores = _baseline_scores(seeds, seasons)
    spreads = {name: pstdev(values) for name, values in scores.items()}
    residuals = _paired_residuals(scores)
    gaps = [round(index * gap_step, 6) for index in range(int(max_gap / gap_step) + 1)]
    mdds: dict[str, Any] = {}
    curves: dict[str, list[dict[str, float]]] = {}
    for seed_count in seed_counts:
        rng = random.Random(f"gm-bench-power-v1:{seed_count}:{repeats}:{within_seed_stddev}:{trials}")
        curve = []
        mdd = None
        for gap in gaps:
            rate = _simulate_detection_rate(
                residuals,
                seed_count=seed_count,
                repeats=repeats,
                within_seed_stddev=within_seed_stddev,
                gap=gap,
                trials=trials,
                rng=rng,
            )
            curve.append({"gap": gap, "detection_rate": rate})
            if mdd is None and rate >= target_power:
                mdd = gap
        mdds[str(seed_count)] = {"minimum_detectable_difference": mdd, "target_power": target_power}
        curves[str(seed_count)] = curve
    return {
        "method": {
            "description": "Empirical paired seed residual bootstrap plus independent Gaussian repeat noise; normal approximation to the two-sided sign-flip null at p < 0.05.",
            "seed_counts_above_panel": "resampled extrapolations from the observed panel, not newly simulated seed panels",
            "trials_per_gap": trials,
        },
        "panel": {"seeds": seeds, "seasons": seasons, "repeats": repeats, "baselines": BASELINES},
        "within_seed_score_stddev": within_seed_stddev,
        "across_seed_score_stddev": spreads,
        "paired_residual_stddev": pstdev(residuals),
        "exact_sign_flip": {
            "seed_count": len(seeds),
            "minimum_p_value": 2 / (2 ** len(seeds)),
            "resolution": 1 / (2 ** len(seeds)),
        },
        "mdd": mdds,
        "detection_curves": curves,
    }


def _print_human(result: dict[str, Any]) -> None:
    panel = result["panel"]
    print(
        f"GM-Bench power analysis: {len(panel['seeds'])} seeds x {panel['repeats']} repeats, {panel['seasons']} seasons"
    )
    print(
        f"Exact sign-flip minimum p-value: {result['exact_sign_flip']['minimum_p_value']:.6f} (resolution {result['exact_sign_flip']['resolution']:.6f})"
    )
    print(
        f"Observed paired-residual SD: {result['paired_residual_stddev']:.3f}; within-seed repeat SD: {result['within_seed_score_stddev']:.3f}"
    )
    print("Across-seed score SD by scripted policy:")
    for name, spread in result["across_seed_score_stddev"].items():
        print(f"  {name:12} {spread:7.3f}")
    print("Simulation MDD (smallest grid gap reaching target detection rate):")
    for count, row in result["mdd"].items():
        value = row["minimum_detectable_difference"]
        text = f"{value:.3f}" if value is not None else "not reached"
        print(f"  {count:>2} seeds: {text} at {row['target_power']:.0%} power")
    print("Larger seed-count entries are resampled extrapolations from the eight-seed panel.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(11, 19)))
    parser.add_argument("--seasons", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--result", type=Path, help="result JSON from which to read within_seed_score_stddev")
    parser.add_argument(
        "--within-seed-stddev", type=float, default=0.0, help="override repeat noise when no result JSON is supplied"
    )
    parser.add_argument("--trials", type=int, default=400)
    parser.add_argument("--seed-counts", nargs="+", type=int, default=[8, 12, 16, 24])
    parser.add_argument("--target-power", type=float, default=0.8)
    parser.add_argument("--gap-step", type=float, default=2.0)
    parser.add_argument("--max-gap", type=float, default=120.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.repeats < 1 or args.trials < 1 or args.gap_step <= 0 or args.max_gap < 0:
        parser.error("repeats/trials must be positive and gap settings must be non-negative")
    repeat_sd = _within_seed_stddev(args.result) if args.result else args.within_seed_stddev
    result = analyse(
        seeds=args.seeds,
        seasons=args.seasons,
        repeats=args.repeats,
        within_seed_stddev=repeat_sd,
        trials=args.trials,
        seed_counts=args.seed_counts,
        target_power=args.target_power,
        gap_step=args.gap_step,
        max_gap=args.max_gap,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()
