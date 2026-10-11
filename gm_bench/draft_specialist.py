"""Offline experimental draft specialist trained only on counterfactual lab labels."""

from __future__ import annotations

import argparse
import copy
import itertools
import math
import statistics
from pathlib import Path
from typing import Any

from gm_bench import counterfactual as cf
from gm_bench.agent_utils import public_asset_value

MODEL_VERSION = "gm-draft-specialist-linear-v1"
REPORT_VERSION = "gm-draft-specialist-evaluation-v1"
FEATURES = [
    "overall",
    "potential",
    "age",
    "injury_risk",
    "salary",
    "forward",
    "defender",
    "goalie",
    "center",
    "position_upgrade",
]


def features(observation: dict[str, Any], action: dict[str, Any]) -> list[float]:
    """Public-only inputs shared by training and the optional agent tool adapter."""
    if observation.get("phase") != "draft":
        raise ValueError("draft observation required")
    if set(action) != {"type", "prospect_id"} or action["type"] != "draft" or type(action["prospect_id"]) is not int:
        raise ValueError("single draft action required")
    player = next((p for p in observation["draft_class"] if p["id"] == action["prospect_id"]), None)
    if player is None:
        raise ValueError("candidate is not in the public draft class")
    position = player["position"]
    peers = [p["overall"] for p in observation["team"]["roster"] if p["position"] == position]
    values = [
        player["overall"],
        player["potential"],
        player["age"],
        player["injury_risk"],
        player.get("salary", 0.0),
        float(position == "F"),
        float(position == "D"),
        float(position == "G"),
        float(player.get("sub_position") == "C"),
        player["overall"] - min(peers, default=0.0),
    ]
    if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
        raise ValueError("features must be finite numbers")
    return [float(v) for v in values]


def validate_comparison(payload: dict[str, Any]) -> None:
    """Validate integrity and label semantics before fitting; hashes are not signatures."""
    if not isinstance(payload, dict) or payload.get("schema_version") != cf.COMPARISON_VERSION:
        raise ValueError("unsupported comparison schema")
    unsigned = {k: v for k, v in payload.items() if k != "comparison_id"}
    if payload.get("comparison_id") != cf.digest(unsigned):
        raise ValueError("comparison content hash mismatch")
    if payload.get("track") != "experimental-public-dev" or payload.get("continuation_policy") != cf.POLICY:
        raise ValueError("unsupported track or policy")
    league = cf.replay_checkpoint(payload["checkpoint"])
    cf._validate_candidates(league, payload["candidates"])
    horizons, seeds = payload["horizons"], payload["rollout_seeds"]
    if (
        not isinstance(horizons, list)
        or not 1 <= len(horizons) <= cf.MAX_HORIZON
        or len(set(horizons)) != len(horizons)
    ):
        raise ValueError("invalid horizons")
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= cf.MAX_ROLLOUTS or len(set(seeds)) != len(seeds):
        raise ValueError("invalid rollout seed panel")
    for h in horizons:
        cf._integer(h, 1, cf.MAX_HORIZON, "horizon")
    for seed in seeds:
        cf._integer(seed, 1001, 1032, "rollout seed")
    expected = set(itertools.product(range(len(payload["candidates"])), seeds, horizons))
    actual = set()
    for row in payload["rows"]:
        key = (row["candidate_index"], row["rollout_seed"], row["horizon"])
        if key not in expected or key in actual or any(type(k) is not int for k in key):
            raise ValueError("duplicate or unexpected rollout row")
        actual.add(key)
        for metric in ("score", "downstream_wins"):
            if type(row[metric]) not in (int, float) or not math.isfinite(row[metric]):
                raise ValueError("nonfinite label")
    if actual != expected:
        raise ValueError("incomplete rollout rows")
    expected_summaries = []
    for index in range(len(payload["candidates"])):
        for horizon in sorted(horizons):
            rows = [r for r in payload["rows"] if r["candidate_index"] == index and r["horizon"] == horizon]
            reference = {
                r["rollout_seed"]: r["score"]
                for r in payload["rows"]
                if r["candidate_index"] == 0 and r["horizon"] == horizon
            }
            expected_summaries.append(
                {
                    "candidate_index": index,
                    "horizon": horizon,
                    "score": cf.uncertainty([r["score"] for r in rows]),
                    "paired_score_delta_vs_candidate_0": cf.uncertainty(
                        [r["score"] - reference[r["rollout_seed"]] for r in rows]
                    ),
                    "downstream_wins": cf.uncertainty([r["downstream_wins"] for r in rows]),
                }
            )
    if cf.canonical(payload["summaries"]) != cf.canonical(expected_summaries):
        raise ValueError("summary/rollout labels disagree")


def _labels(payload: dict[str, Any], horizon: int) -> list[float]:
    if horizon not in payload["horizons"]:
        raise ValueError("requested label horizon unavailable")
    return [
        statistics.mean(r["score"] for r in payload["rows"] if r["candidate_index"] == i and r["horizon"] == horizon)
        for i in range(len(payload["candidates"]))
    ]


def _solve(matrix: list[list[float]], target: list[float]) -> list[float]:
    """Small ridge normal equation with partial pivoting; no numerical dependency."""
    a = [row[:] + [y] for row, y in zip(matrix, target, strict=True)]
    for col in range(len(target)):
        pivot = max(range(col, len(target)), key=lambda i: abs(a[i][col]))
        a[col], a[pivot] = a[pivot], a[col]
        divisor = a[col][col]
        if abs(divisor) < 1e-12:
            raise ValueError("singular fit")
        a[col] = [v / divisor for v in a[col]]
        for row in range(len(target)):
            if row != col:
                factor = a[row][col]
                a[row] = [x - factor * y for x, y in zip(a[row], a[col], strict=True)]
    return [row[-1] for row in a]


def fit(comparisons: list[dict[str, Any]], horizon: int = 2) -> dict[str, Any]:
    """Fixed ridge=1; center labels/features per decision and scale using training data only."""
    if not 2 <= len(comparisons) <= 16:
        raise ValueError("fit requires 2..16 public seed episodes")
    cf._integer(horizon, 1, cf.MAX_HORIZON, "label horizon")
    seeds = []
    xs, ys = [], []
    for payload in comparisons:
        validate_comparison(payload)
        seed = payload["checkpoint"]["seed"]
        if seed in seeds:
            raise ValueError("one checkpoint per seed; duplicated episode seed")
        seeds.append(seed)
        labels = _labels(payload, horizon)
        vectors = [features(payload["checkpoint"]["observation"], action) for action in payload["candidates"]]
        center = [statistics.mean(column) for column in zip(*vectors, strict=True)]
        label_center = statistics.mean(labels)
        xs.extend([[v - m for v, m in zip(vector, center, strict=True)] for vector in vectors])
        ys.extend(y - label_center for y in labels)
    scales = [max(math.sqrt(statistics.mean(row[i] ** 2 for row in xs)), 1e-8) for i in range(len(FEATURES))]
    x = [[v / scale for v, scale in zip(row, scales, strict=True)] for row in xs]
    # Equal candidate count in the CLI; library documents per-candidate weighting.
    matrix = [
        [sum(row[i] * row[j] for row in x) + float(i == j) for j in range(len(FEATURES))] for i in range(len(FEATURES))
    ]
    target = [sum(row[i] * y for row, y in zip(x, ys, strict=True)) for i in range(len(FEATURES))]
    model = {
        "schema_version": MODEL_VERSION,
        "track": "experimental-public-dev",
        "feature_names": FEATURES,
        "weights": _solve(matrix, target),
        "scales": scales,
        "ridge": 1.0,
        "label_horizon": horizon,
        "continuation_policy": cf.POLICY,
        "training_seeds": sorted(seeds),
        "training_comparison_ids": [p["comparison_id"] for p in comparisons],
        "label_provenance": comparisons[0]["checkpoint"]["provenance"],
        "specialist_source_sha256": cf.digest(Path(__file__).read_text()),
        "prediction_kind": "relative preference only; uncalibrated absolute values",
    }
    model["model_id"] = cf.digest(model)
    return model


def validate_model(model: dict[str, Any]) -> None:
    if model.get("schema_version") != MODEL_VERSION or model.get("feature_names") != FEATURES:
        raise ValueError("unsupported specialist model")
    if model.get("model_id") != cf.digest({k: v for k, v in model.items() if k != "model_id"}):
        raise ValueError("model integrity mismatch")
    if model.get("continuation_policy") != cf.POLICY or model.get("label_provenance") != cf.provenance():
        raise ValueError("model label policy/provenance mismatch")
    if model.get("specialist_source_sha256") != cf.digest(Path(__file__).read_text()):
        raise ValueError("specialist implementation mismatch")
    for name in ("weights", "scales"):
        values = model.get(name)
        if (
            not isinstance(values, list)
            or len(values) != len(FEATURES)
            or not all(type(v) in (int, float) and math.isfinite(v) for v in values)
        ):
            raise ValueError("invalid model vectors")
    if any(v <= 0 for v in model["scales"]):
        raise ValueError("invalid feature scales")
    cf._integer(model["label_horizon"], 1, 3, "model horizon")
    if not isinstance(model.get("training_seeds"), list) or not 2 <= len(model["training_seeds"]) <= 16:
        raise ValueError("invalid training seed panel")
    for seed in model["training_seeds"]:
        cf._integer(seed, 1, 32, "training seed")
    if len(set(model["training_seeds"])) != len(model["training_seeds"]):
        raise ValueError("duplicate training seed")


def rank_candidates(
    observation: dict[str, Any], candidates: list[dict[str, Any]], model: dict[str, Any]
) -> list[dict[str, Any]]:
    """Optional agent tool: public JSON in, preference-ranked actions out; no simulation/calls."""
    validate_model(model)
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= cf.MAX_CANDIDATES:
        raise ValueError("2..12 candidates required")
    picks = observation.get("team", {}).get("draft_picks", {})
    season = observation.get("season")
    remaining = picks.get(str(season), picks.get(season, 0))
    if type(remaining) is not int or remaining < 1:
        raise ValueError("no current-season draft pick available")
    ranked = []
    seen = set()
    for index, action in enumerate(candidates):
        vector = features(observation, action)
        if action["prospect_id"] in seen:
            raise ValueError("duplicate candidate")
        seen.add(action["prospect_id"])
        preference = sum(v / scale * w for v, scale, w in zip(vector, model["scales"], model["weights"], strict=True))
        ranked.append({"candidate_index": index, "action": copy.deepcopy(action), "preference": preference})
    return sorted(ranked, key=lambda row: (-row["preference"], row["action"]["prospect_id"]))


def evaluate(model: dict[str, Any], comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    validate_model(model)
    if not 2 <= len(comparisons) <= 16:
        raise ValueError("evaluation requires 2..16 independent held-out episode seeds")
    episodes, seen = [], set()
    for payload in comparisons:
        validate_comparison(payload)
        seed = payload["checkpoint"]["seed"]
        if seed in model["training_seeds"] or seed in seen:
            raise ValueError("train/test episode seed overlap or duplicate test seed")
        seen.add(seed)
        observation = payload["checkpoint"]["observation"]
        actions = payload["candidates"]
        labels = _labels(payload, model["label_horizon"])
        chosen = rank_candidates(observation, actions, model)[0]["candidate_index"]
        prospects = {p["id"]: p for p in observation["draft_class"]}
        heuristic = min(
            range(len(actions)),
            key=lambda i: (-public_asset_value(prospects[actions[i]["prospect_id"]]), actions[i]["prospect_id"]),
        )
        episodes.append(
            {
                "seed": seed,
                "checkpoint_id": payload["checkpoint"]["checkpoint_id"],
                "comparison_id": payload["comparison_id"],
                "selected_index": chosen,
                "heuristic_index": heuristic,
                "selected_estimated_score": labels[chosen],
                "heuristic_estimated_score": labels[heuristic],
                "estimated_score_delta_vs_heuristic": labels[chosen] - labels[heuristic],
                "estimated_candidate_gap": max(labels) - labels[chosen],
                "heuristic_estimated_candidate_gap": max(labels) - labels[heuristic],
            }
        )
    report = {
        "schema_version": REPORT_VERSION,
        "track": "experimental-public-dev",
        "model_id": model["model_id"],
        "training_seeds": model["training_seeds"],
        "test_seeds": sorted(seen),
        "label_horizon": model["label_horizon"],
        "episodes": episodes,
        "uncertainty_unit": "independent held-out public episode seed",
        "score_delta_vs_heuristic": cf.uncertainty([e["estimated_score_delta_vs_heuristic"] for e in episodes]),
        "mean_estimated_candidate_gap": statistics.mean(e["estimated_candidate_gap"] for e in episodes),
        "mean_heuristic_estimated_candidate_gap": statistics.mean(
            e["heuristic_estimated_candidate_gap"] for e in episodes
        ),
        "limitations": [
            *cf.LIMITATIONS,
            "This is a small proof of concept; no superiority claim is justified by the smoke panel.",
            "Candidate gaps use noisy label estimates; the maximum has selection optimism and is not an oracle.",
            "Evaluation concerns a single draft intervention followed by ValueAgent, not a deployed multi-step specialist policy.",
            "Ridge hyperparameter and horizon are fixed before evaluation; test seeds must not be used to tune them.",
            "Hash and semantic checks detect corruption, not intentionally forged simulation labels.",
        ],
    }
    report["report_id"] = cf.digest(report)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="generate labels, fit, evaluate and save all artifacts offline")
    demo.add_argument("--out-dir", required=True)
    demo.add_argument("--train-seeds", type=int, nargs="+", default=[1, 2, 3, 4])
    demo.add_argument("--test-seeds", type=int, nargs="+", default=[17, 18, 19, 20])
    demo.add_argument("--horizon", type=int, default=2)
    demo.add_argument("--rollouts", type=int, default=4)
    demo.add_argument("--candidates", type=int, default=4)
    train = sub.add_parser("fit", help="fit existing comparison JSON labels")
    train.add_argument("comparisons", nargs="+")
    train.add_argument("--horizon", type=int, default=2)
    train.add_argument("--out", required=True)
    assess = sub.add_parser("evaluate", help="evaluate a model on seed-disjoint comparison files")
    assess.add_argument("model")
    assess.add_argument("comparisons", nargs="+")
    assess.add_argument("--out", required=True)
    rank = sub.add_parser("rank", help="public-observation tool adapter; no simulator rollout")
    rank.add_argument("model")
    rank.add_argument("observation")
    rank.add_argument("candidates")
    rank.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            cf._integer(args.rollouts, 1, 16, "rollouts per split")
            cf._integer(args.candidates, 2, 12, "candidates")
            cf._integer(args.horizon, 1, 3, "horizon")
            all_seeds = [*args.train_seeds, *args.test_seeds]
            if (
                not 2 <= len(args.train_seeds) <= 16
                or not 2 <= len(args.test_seeds) <= 16
                or len(set(all_seeds)) != len(all_seeds)
            ):
                raise ValueError("provide disjoint train/test panels of 2..16 unique episode seeds each")
            for seed in all_seeds:
                cf._integer(seed, 1, 32, "public episode seed")
            destination = Path(args.out_dir)
            destination.mkdir(parents=True, exist_ok=False)
            panels = []
            for split, seeds, offset in (("train", args.train_seeds, 1001), ("test", args.test_seeds, 1017)):
                panel = []
                for seed in seeds:
                    checkpoint = cf.make_checkpoint(seed)
                    payload = cf.compare(
                        checkpoint,
                        cf.enumerate_candidates(checkpoint, args.candidates),
                        horizons=(args.horizon,),
                        rollout_seeds=tuple(range(offset, offset + args.rollouts)),
                    )
                    cf.save_json(destination / f"{split}-{seed}.json", payload)
                    panel.append(payload)
                panels.append(panel)
            model = fit(panels[0], args.horizon)
            cf.save_json(destination / "model.json", model)
            report = evaluate(model, panels[1])
            cf.save_json(destination / "evaluation.json", report)
            print(f"Saved labels, model and evaluation to {destination}")
        elif args.command == "fit":
            cf.save_json(args.out, fit([cf.read_json(p) for p in args.comparisons], args.horizon))
        elif args.command == "evaluate":
            cf.save_json(args.out, evaluate(cf.read_json(args.model), [cf.read_json(p) for p in args.comparisons]))
        else:
            cf.save_json(
                args.out,
                rank_candidates(
                    cf.read_json(args.observation), cf.read_json(args.candidates), cf.read_json(args.model)
                ),
            )
    except (ValueError, TypeError, KeyError, OSError, StopIteration) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
