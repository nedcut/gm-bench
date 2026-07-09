#!/usr/bin/env python3
"""Measure scripted-policy rank stability under score-weight perturbations."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from statistics import mean
from typing import Any

# Make direct source-tree invocation (`python scripts/...`) work as well as
# `uv run`, whose editable install already provides this import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# isort: split
from gm_bench import runner
from gm_bench.agents import AGENTS
from gm_bench.scoring import ACTIVE_SCORE_SCALE, score_components

BASELINES = ["random", "conservative", "win-now", "rebuild", "value", "shrewd", "strategic", "pick-trader"]
WEIGHTS = [
    "recent_win",
    "playoff_round",
    "championship",
    "total_asset",
    "young_asset",
    "future_pick_asset",
    "cap_room",
    "current_strength",
    "roster_depth",
    "illegal_action_penalty",
]
COMPONENT_TO_WEIGHT = {
    "recent_wins": "recent_win",
    "playoff_rounds": "playoff_round",
    "championships": "championship",
    "total_assets": "total_asset",
    "young_assets": "young_asset",
    "future_pick_assets": "future_pick_asset",
    "current_strength": "current_strength",
    "roster_depth": "roster_depth",
}


def _capture_panel(seeds: list[int], seasons: int) -> dict[str, list[dict[str, Any]]]:
    """Capture raw end-state components through a temporary runner wrapper.

    `run_episode` retains only final totals.  This diagnostic-only monkeypatch
    observes its final score call, records score_components, and is restored in
    a finally block; no benchmark module or artifact is modified.
    """
    captured: list[dict[str, Any]] = []
    original = runner.score_breakdown

    def wrapped(league: Any, team_id: int) -> dict[str, float]:
        captured.append(score_components(league, team_id))
        return original(league, team_id)

    runner.score_breakdown = wrapped
    try:
        panel: dict[str, list[dict[str, Any]]] = {}
        for name in BASELINES:
            before = len(captured)
            output = runner.run_many(AGENTS[name](), seeds=seeds, seasons=seasons, workers=1)
            entries = captured[before:]
            panel[name] = [
                {"components": components, "canonical_final_score": episode["final_score"]}
                for episode, components in zip(output["episodes"], entries, strict=True)
            ]
        return panel
    finally:
        runner.score_breakdown = original


def _score(components: dict[str, float], weights: dict[str, float]) -> float:
    strategy = sum(components[name] * weights[weight] for name, weight in COMPONENT_TO_WEIGHT.items())
    cap = max(
        ACTIVE_SCORE_SCALE.cap_score_min,
        min(ACTIVE_SCORE_SCALE.cap_score_max, components["cap_room"] * weights["cap_room"]),
    )
    return (
        strategy
        + cap
        - components["protocol_penalty"] / ACTIVE_SCORE_SCALE.illegal_action_penalty * weights["illegal_action_penalty"]
    )


def _ranking(panel: dict[str, list[dict[str, Any]]], weights: dict[str, float]) -> tuple[list[str], dict[str, float]]:
    scores = {name: mean(_score(row["components"], weights) for row in rows) for name, rows in panel.items()}
    return sorted(scores, key=lambda name: (-scores[name], name)), scores


def _kendall_tau(reference: list[str], ranking: list[str]) -> float:
    positions = {name: index for index, name in enumerate(ranking)}
    concordant = 0
    discordant = 0
    for left_index, left in enumerate(reference):
        for right in reference[left_index + 1 :]:
            if positions[left] < positions[right]:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total else 1.0


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * probability)]


def analyse(*, seeds: list[int], seasons: int, draws: int, perturbation: float) -> dict[str, Any]:
    panel = _capture_panel(seeds, seasons)
    canonical_weights = {name: float(getattr(ACTIVE_SCORE_SCALE, name)) for name in WEIGHTS}
    canonical_ranking, canonical_scores = _ranking(panel, canonical_weights)
    # Guard that raw recombination faithfully reproduces the runner's rounded score.
    max_recombination_error = max(
        abs(_score(row["components"], canonical_weights) - row["canonical_final_score"])
        for rows in panel.values()
        for row in rows
    )
    rng = random.Random(f"gm-bench-weight-sensitivity-v1:{draws}:{perturbation}")
    adjacent_flips = {f"{higher} > {lower}": 0 for higher, lower in zip(canonical_ranking, canonical_ranking[1:])}
    taus: list[float] = []
    for _ in range(draws):
        weights = {
            name: value * rng.uniform(1.0 - perturbation, 1.0 + perturbation)
            for name, value in canonical_weights.items()
        }
        ranking, _ = _ranking(panel, weights)
        positions = {name: index for index, name in enumerate(ranking)}
        for higher, lower in zip(canonical_ranking, canonical_ranking[1:]):
            if positions[lower] < positions[higher]:
                adjacent_flips[f"{higher} > {lower}"] += 1
        taus.append(_kendall_tau(canonical_ranking, ranking))
    return {
        "method": {
            "component_capture": "diagnostic-only temporary monkeypatch of gm_bench.runner.score_breakdown; restored after panel run",
            "perturbation": f"independent uniform multipliers in [{1.0 - perturbation:.2f}, {1.0 + perturbation:.2f}]",
            "draws": draws,
        },
        "panel": {"seeds": seeds, "seasons": seasons, "baselines": BASELINES},
        "canonical_ranking": canonical_ranking,
        "canonical_scores": canonical_scores,
        "max_recombination_error": max_recombination_error,
        "adjacent_rank_flip_probability": {name: count / draws for name, count in adjacent_flips.items()},
        "kendall_tau": {
            "mean": mean(taus),
            "median": _quantile(taus, 0.5),
            "p05": _quantile(taus, 0.05),
            "p95": _quantile(taus, 0.95),
            "min": min(taus),
            "max": max(taus),
        },
        "canonical_weights": canonical_weights,
    }


def _print_human(result: dict[str, Any]) -> None:
    print(
        f"GM-Bench weight sensitivity: {len(result['panel']['seeds'])} seeds x {result['panel']['seasons']} seasons; {result['method']['draws']} draws"
    )
    print("Canonical ranking:", " > ".join(result["canonical_ranking"]))
    print(f"Raw-component recombination maximum error: {result['max_recombination_error']:.6f}")
    print("Adjacent-pair rank-flip probabilities:")
    for pair, probability in result["adjacent_rank_flip_probability"].items():
        print(f"  {pair:30} {probability:6.1%}")
    tau = result["kendall_tau"]
    print(
        f"Kendall tau vs canonical: mean {tau['mean']:.3f}, median {tau['median']:.3f}, p05-p95 {tau['p05']:.3f}-{tau['p95']:.3f}"
    )
    print("Components were captured only in-process; saved model result artifacts cannot be recombined post-hoc.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(11, 19)))
    parser.add_argument("--seasons", type=int, default=5)
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--perturbation", type=float, default=0.30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.draws < 1 or not 0 <= args.perturbation < 1:
        parser.error("draws must be positive and perturbation must be in [0, 1)")
    result = analyse(seeds=args.seeds, seasons=args.seasons, draws=args.draws, perturbation=args.perturbation)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()
