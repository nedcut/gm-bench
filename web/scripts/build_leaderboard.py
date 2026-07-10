"""Build the public leaderboard dataset for the GM-Bench site.

Reads official ``results/leaderboard/*.json`` artifacts and explicitly marked
``results/diagnostics/*.json`` artifacts. Official artifacts are either the saved output of

    python -m gm_bench model --provider <p> --model <m> --preset leaderboard --repeats 3 --json > results/leaderboard/<name>.json

or a redacted private-panel artifact from ``python -m gm_bench redact-result``.
Diagnostics are visible on the site for transparency, but are deliberately kept
outside the official-artifact directory so the public-leaderboard CI gate remains
meaningful.
It writes ``web/src/data/leaderboard.json`` with one row per model plus the
scripted-baseline reference panel. When no model results exist yet, the baseline
panel is read from the current-contract cache or recomputed deterministically so
the site never mixes historical model rows with stale reference scores.

Usage (from the repository root):

    python web/scripts/build_leaderboard.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gm_bench.agents import AGENTS  # noqa: E402
from gm_bench.baseline_cache import cache_key, load_cache  # noqa: E402
from gm_bench.benchmark_config import PRESETS, PRIVATE_LEADERBOARD_PANEL_NAME  # noqa: E402
from gm_bench.official import REDACTED_SEEDS_SENTINEL, SOTA_V1_POLICY, validate_leaderboard_payload  # noqa: E402
from gm_bench.protocol import PHASES  # noqa: E402
from gm_bench.runner import run_many  # noqa: E402

RESULTS_DIR = ROOT / "results" / "leaderboard"
DIAGNOSTICS_DIR = ROOT / "results" / "diagnostics"
OUTPUT_PATH = ROOT / "web" / "src" / "data" / "leaderboard.json"
LEADERBOARD = PRESETS["leaderboard"]


def model_row(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload["candidate"]["summary"]
    usage = summary.get("usage") or {}
    paired = payload.get("paired") or {}
    normalized = payload.get("normalized") or {}
    run_info = payload.get("run_info") or {}
    contract = run_info.get("benchmark_contract") or {}
    seed_panel = run_info.get("seed_panel") or {}
    sota_report = _sota_report(payload)
    decisions = summary.get("decisions", 0)
    agent = payload.get("agent", "unknown")
    provider, _, model_name = agent.partition(":")
    if not model_name:
        provider, model_name = usage.get("provider") or "unknown", agent
    episodes = len(payload["candidate"].get("episodes", [])) or _redacted_episode_count(payload)
    cost = usage.get("cost_usd")
    seeds = payload.get("seeds")
    if seeds == REDACTED_SEEDS_SENTINEL:
        seeds = None
    elif seed_panel.get("name") == PRIVATE_LEADERBOARD_PANEL_NAME:
        seeds = None
    return {
        "id": agent,
        "model": model_name,
        "provider": provider,
        "mean_score": summary["mean_score"],
        "score_stddev": summary["score_stddev"],
        "mean_strategy_score": summary.get("mean_strategy_score"),
        "protocol_penalty": summary.get("total_protocol_penalty"),
        "paired_lift": paired.get("paired_lift_mean"),
        "ci95": paired.get("paired_lift_ci95"),
        "significant": paired.get("significant_at_95"),
        "seed_win_rate": paired.get("candidate_seed_win_rate"),
        "lift_vs_best_baseline": (paired.get("best_baseline") or {}).get("paired_lift_mean"),
        "fallback_rate": summary.get("decision_failure_rate", 0.0),
        "illegal_actions": summary.get("illegal_actions", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "tokens_per_decision": round(usage.get("total_tokens", 0) / decisions, 1) if decisions else None,
        "cost_usd": cost,
        "cost_per_episode_usd": round(cost / episodes, 4) if cost is not None and episodes else None,
        "api_latency_s_per_decision": round(usage.get("api_latency_ms", 0.0) / 1000.0 / decisions, 2)
        if decisions
        else None,
        "harness_latency_s_per_decision": round(usage.get("harness_latency_ms", 0.0) / 1000.0 / decisions, 2)
        if decisions
        else None,
        "decisions_with_usage": usage.get("decisions_with_usage", 0),
        "decision_points": decisions,
        "session": bool(run_info.get("session", False)),
        "seeds": seeds,
        "seasons": payload.get("seasons"),
        "baseline_panel_mean_score": normalized.get("baseline_panel_mean_score"),
        "benchmark_version": contract.get("benchmark_version"),
        "contract_fingerprint": contract.get("contract_fingerprint"),
        "seed_panel": seed_panel.get("name"),
        "seed_panel_hash": seed_panel.get("sha256"),
        "sota_v1_eligible": bool(sota_report.get("ok")),
        "sota_v1_issues": [*sota_report.get("errors", []), *sota_report.get("warnings", [])],
    }


def _sota_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Always recompute eligibility; never trust embedded validation_reports."""

    return validate_leaderboard_payload(payload, policy=SOTA_V1_POLICY).to_dict()


def _redacted_episode_count(payload: dict[str, Any]) -> int:
    seed_panel = (payload.get("run_info") or {}).get("seed_panel") or {}
    candidate = payload.get("candidate") or {}
    count = seed_panel.get("count")
    repeats = candidate.get("repeats", 1)
    if isinstance(count, int):
        return count * int(repeats or 1)
    return 0


def baselines_from_cache() -> list[dict[str, Any]]:
    """Load baseline rows that have complete seed coverage in the cache.

    Partial cache hits are ignored so ``current_baselines()`` recomputes rather
    than publishing a mean over a subset of seeds.
    """
    cache = load_cache()
    rows = []
    seeds = list(LEADERBOARD["seeds"])
    for agent in LEADERBOARD["baselines"]:
        scores = []
        for seed in seeds:
            episode = cache.get(cache_key(agent, seed, LEADERBOARD["seasons"]))
            if episode is None:
                scores = []
                break
            scores.append(episode["final_score"])
        if len(scores) != len(seeds):
            continue
        mean = sum(scores) / len(scores)
        stddev = (sum((score - mean) ** 2 for score in scores) / len(scores)) ** 0.5
        rows.append({"agent": agent, "mean_score": round(mean, 3), "score_stddev": round(stddev, 3)})
    return sorted(rows, key=lambda row: row["mean_score"], reverse=True)


def current_baselines() -> list[dict[str, Any]]:
    rows = baselines_from_cache()
    cached_agents = {row["agent"] for row in rows}
    for agent_name in LEADERBOARD["baselines"]:
        if agent_name in cached_agents:
            continue
        result = run_many(
            AGENTS[agent_name](),
            seeds=list(LEADERBOARD["seeds"]),
            seasons=int(LEADERBOARD["seasons"]),
            workers=1,
        )
        rows.append(
            {
                "agent": agent_name,
                "mean_score": result["summary"]["mean_score"],
                "score_stddev": result["summary"]["score_stddev"],
            }
        )
    return sorted(rows, key=lambda row: row["mean_score"], reverse=True)


def main() -> None:
    payloads = []
    for directory in (RESULTS_DIR, DIAGNOSTICS_DIR):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                payloads.append(json.loads(path.read_text()))
            except json.JSONDecodeError:
                print(f"skipping unparseable {path}", file=sys.stderr)
    models = sorted((model_row(payload) for payload in payloads), key=lambda row: row["mean_score"], reverse=True)
    baselines = current_baselines()
    dataset = {
        "updated": date.today().isoformat(),
        "preset": {
            "name": "leaderboard",
            "seeds": LEADERBOARD["seeds"],
            "seasons": LEADERBOARD["seasons"],
            "decision_points_per_episode": LEADERBOARD["seasons"] * len(PHASES),
        },
        "baselines": baselines,
        "models": models,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT_PATH} ({len(models)} model(s), {len(baselines)} baseline(s))")


if __name__ == "__main__":
    main()
