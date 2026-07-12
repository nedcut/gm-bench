#!/usr/bin/env python3
"""Merge partial model-panel result JSON files into one official-shaped payload.

Used to resume a leaderboard run after quota death: keep good seed episodes from
an earlier artifact, drop failed seeds, add a continuation run, then recompute
summary / paired / normalized blocks with the same helpers as live evaluate.

Example (Claude Sonnet medium resume)::

    python scripts/merge_model_panel.py \\
      --base results/diagnostics/claude-sonnet-medium.serial-quota-fail.json \\
      --keep-seeds 11 \\
      --add results/diagnostics/claude-sonnet-medium.seeds-12-18.json \\
      --output results/leaderboard/claude-sonnet-medium.json \\
      --validate sota-v1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRESETS, seed_panel_metadata  # noqa: E402
from gm_bench.official import POLICIES, validate_leaderboard_payload  # noqa: E402
from gm_bench.runner import (  # noqa: E402
    _paired_analysis,
    _precise_mean_score,
    summarize_episodes,
)
from gm_bench.telemetry import summarize_usage  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _episodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload.get("candidate", {}).get("episodes") or [])


def _sort_episodes(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(episodes, key=lambda ep: (int(ep["seed"]), int(ep.get("repeat") or 1)))


def _rebuild_normalized(
    seeds: list[int],
    candidate: dict[str, Any],
    baseline_results: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_scores = [_precise_mean_score(result) for result in baseline_results]
    baseline_mean = mean(baseline_scores) if baseline_scores else 0.0
    candidate_mean = _precise_mean_score(candidate)
    return {
        "candidate_mean_score": round(candidate_mean, 3),
        "candidate_mean_strategy_score": candidate["summary"]["mean_strategy_score"],
        "candidate_protocol_penalty": candidate["summary"]["total_protocol_penalty"],
        "baseline_panel_mean_score": round(baseline_mean, 3),
        "baseline_panel_mean_strategy_score": round(
            mean(result["summary"]["mean_strategy_score"] for result in baseline_results), 3
        )
        if baseline_results
        else 0.0,
        "baseline_panel_total_protocol_penalty": round(
            sum(result["summary"]["total_protocol_penalty"] for result in baseline_results), 3
        ),
        "score_lift": round(candidate_mean - baseline_mean, 3),
        "score_lift_pct": round(((candidate_mean / baseline_mean) - 1.0) * 100.0, 2) if baseline_mean else 0.0,
        "candidate_illegal_actions": candidate["summary"]["illegal_actions"],
        "baseline_illegal_actions": sum(result["summary"]["illegal_actions"] for result in baseline_results),
        "candidate_decisions": candidate["summary"].get("decisions", 0),
        "candidate_failed_decisions": candidate["summary"].get("failed_decisions", 0),
        "candidate_decision_failure_rate": candidate["summary"].get("decision_failure_rate", 0.0),
        "candidate_memo_writes": candidate["summary"].get("memo_writes", 0),
        "candidate_rejected_offers": candidate["summary"].get("rejected_offers", 0),
        "candidate_usage": candidate["summary"].get("usage", summarize_usage([])),
    }


def merge_payloads(
    *,
    base: dict[str, Any],
    keep_seeds: list[int],
    additions: list[dict[str, Any]],
    expected_seeds: list[int] | None = None,
) -> dict[str, Any]:
    keep = set(keep_seeds)
    kept = [ep for ep in _episodes(base) if int(ep["seed"]) in keep]
    if not kept:
        raise SystemExit(f"no episodes for keep-seeds {keep_seeds} in base payload")

    added: list[dict[str, Any]] = []
    for payload in additions:
        eps = _episodes(payload)
        if not eps:
            raise SystemExit("addition payload has no candidate episodes")
        overlap = {int(ep["seed"]) for ep in eps} & keep
        if overlap:
            raise SystemExit(f"addition episodes overlap keep-seeds: {sorted(overlap)}")
        added.extend(eps)

    episodes = _sort_episodes(kept + added)
    seed_order = expected_seeds or list(PRESETS["leaderboard"]["seeds"])
    present = sorted({int(ep["seed"]) for ep in episodes})
    if present != sorted(seed_order):
        raise SystemExit(f"merged seed set {present} does not match expected {seed_order}")

    # Require full repeat coverage per seed.
    by_seed: dict[int, list[int]] = {}
    for ep in episodes:
        by_seed.setdefault(int(ep["seed"]), []).append(int(ep.get("repeat") or 1))
    expected_repeats = int(base.get("candidate", {}).get("repeats") or 1)
    for seed in seed_order:
        reps = sorted(by_seed.get(seed, []))
        want = list(range(1, expected_repeats + 1))
        if reps != want:
            raise SystemExit(f"seed {seed} has repeats {reps}, expected {want}")

    agent_name = base.get("candidate", {}).get("agent") or base.get("agent") or "merged"
    seasons = int(base.get("seasons") or base.get("candidate", {}).get("seasons") or 5)
    candidate = {
        "agent": agent_name,
        "seasons": seasons,
        "seeds": list(seed_order),
        "repeats": expected_repeats,
        "episodes": episodes,
        "summary": summarize_episodes(episodes),
    }

    baselines = list(base.get("baselines") or [])
    if not baselines and additions:
        baselines = list(additions[0].get("baselines") or [])
    if not baselines:
        raise SystemExit("no baselines found in base or addition payloads")

    # Prefer full-panel baselines from base when present.
    baseline_seed_sets = [{int(ep["seed"]) for ep in (b.get("episodes") or [])} for b in baselines]
    if any(set(seed_order) - s for s in baseline_seed_sets):
        # Fall back to first addition's baselines if base only covered a subset.
        for payload in additions:
            cand = list(payload.get("baselines") or [])
            if cand and all(set(seed_order) <= {int(ep["seed"]) for ep in (b.get("episodes") or [])} for b in cand):
                baselines = cand
                break

    run_info = dict(base.get("run_info") or {})
    run_info["seed_panel"] = seed_panel_metadata(list(seed_order), "leaderboard")
    run_info["preset"] = "leaderboard"
    # Stamp resume provenance without breaking validators that only check known keys.
    run_info["resume"] = {
        "merged_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kept_seeds": list(keep_seeds),
        "added_seed_sets": [
            sorted({int(ep["seed"]) for ep in _episodes(payload)}) for payload in additions
        ],
        "note": "episodes stitched offline after quota interruption; summary/paired recomputed",
    }

    payload = {
        "agent": agent_name,
        "seasons": seasons,
        "seeds": list(seed_order),
        "candidate": candidate,
        "baselines": baselines,
        "baseline_cache": base.get("baseline_cache")
        or (additions[0].get("baseline_cache") if additions else None),
        "normalized": _rebuild_normalized(list(seed_order), candidate, baselines),
        "paired": _paired_analysis(list(seed_order), candidate, baselines),
        "run_info": run_info,
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="earlier result JSON (checkpoint source)")
    parser.add_argument(
        "--keep-seeds",
        nargs="+",
        type=int,
        required=True,
        help="seed ids to keep from --base",
    )
    parser.add_argument(
        "--add",
        action="append",
        type=Path,
        default=[],
        help="continuation result JSON (repeatable)",
    )
    parser.add_argument("--output", required=True, type=Path, help="merged output path")
    parser.add_argument(
        "--expected-seeds",
        nargs="+",
        type=int,
        default=None,
        help="final panel order (default: public leaderboard 11-18)",
    )
    parser.add_argument(
        "--validate",
        choices=sorted(POLICIES),
        default=None,
        help="run official validator after merge",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()

    if not args.add:
        parser.error("at least one --add continuation payload is required")

    base = _load(args.base)
    additions = [_load(path) for path in args.add]
    expected = args.expected_seeds or list(PRESETS["leaderboard"]["seeds"])
    merged = merge_payloads(
        base=base,
        keep_seeds=args.keep_seeds,
        additions=additions,
        expected_seeds=expected,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, indent=args.indent, sort_keys=True) + "\n")
    summary = merged["candidate"]["summary"]
    print(
        f"wrote {args.output} seeds={merged['seeds']} episodes={len(merged['candidate']['episodes'])} "
        f"mean={summary['mean_score']} fail_rate={summary['decision_failure_rate']} "
        f"failed={summary['failed_decisions']}/{summary['decisions']}"
    )

    if args.validate:
        report = validate_leaderboard_payload(merged, policy=POLICIES[args.validate])
        print(f"validate {args.validate}: ok={report.ok}")
        for err in report.errors:
            print(f"  error: {err}")
        for warn in report.warnings:
            print(f"  warning: {warn}")
        if not report.ok:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
