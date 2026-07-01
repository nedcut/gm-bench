"""Episode orchestration."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Any

from gm_bench.agents import AGENTS, Agent
from gm_bench.scoring import score_team
from gm_bench.simulator import League


@dataclass
class BenchmarkResult:
    agent: str
    seed: int
    seasons: int
    final_score: float
    wins: int
    championships: int
    illegal_actions: int
    season_summaries: list[dict[str, Any]]
    transactions: list[dict[str, Any]]


def run_episode(agent: Agent, seed: int, seasons: int = 5, user_team_id: int = 0) -> BenchmarkResult:
    league = League.new(seed=seed, user_team_id=user_team_id)
    for _ in range(seasons):
        for phase in ["preseason", "trade_deadline", "draft"]:
            observation = league.observation(phase)
            actions = agent.act(observation)
            league.apply_actions(actions, phase)
            if phase == "preseason":
                league.run_autopilot_opponents()
        league.simulate_season()
    final_score = score_team(league, user_team_id)
    return BenchmarkResult(
        agent=agent.name,
        seed=seed,
        seasons=seasons,
        final_score=round(final_score, 3),
        wins=sum(summary.wins for summary in league.summaries),
        championships=league.user_team.championships,
        illegal_actions=league.illegal_actions,
        season_summaries=[summary.__dict__ for summary in league.summaries],
        transactions=[transaction.__dict__ for transaction in league.transactions],
    )


def run_many(agent: Agent, seeds: list[int], seasons: int = 5, workers: int | None = None) -> dict[str, Any]:
    max_workers = workers if workers is not None else _default_workers(len(seeds))
    if max_workers <= 1 or len(seeds) <= 1:
        results = [run_episode(agent, seed=seed, seasons=seasons) for seed in seeds]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(lambda seed: run_episode(agent, seed=seed, seasons=seasons), seeds))
    scores = [result.final_score for result in results]
    wins = [result.wins for result in results]
    return {
        "agent": agent.name,
        "seasons": seasons,
        "seeds": seeds,
        "episodes": [result.__dict__ for result in results],
        "summary": {
            "mean_score": round(mean(scores), 3) if scores else 0.0,
            "score_stddev": round(pstdev(scores), 3) if len(scores) > 1 else 0.0,
            "mean_total_wins": round(mean(wins), 3) if wins else 0.0,
            "championships": sum(result.championships for result in results),
            "illegal_actions": sum(result.illegal_actions for result in results),
        },
    }


def evaluate_against_baselines(
    agent: Agent,
    seeds: list[int],
    seasons: int = 5,
    baseline_names: list[str] | None = None,
) -> dict[str, Any]:
    baselines = baseline_names or ["random", "conservative", "win-now", "rebuild", "value"]
    candidate = run_many(agent, seeds=seeds, seasons=seasons)
    baseline_results = [run_many(AGENTS[name](), seeds=seeds, seasons=seasons) for name in baselines]
    baseline_scores = [result["summary"]["mean_score"] for result in baseline_results]
    baseline_mean = mean(baseline_scores) if baseline_scores else 0.0
    candidate_mean = candidate["summary"]["mean_score"]
    return {
        "agent": agent.name,
        "seasons": seasons,
        "seeds": seeds,
        "candidate": candidate,
        "baselines": baseline_results,
        "normalized": {
            "candidate_mean_score": round(candidate_mean, 3),
            "baseline_panel_mean_score": round(baseline_mean, 3),
            "score_lift": round(candidate_mean - baseline_mean, 3),
            "score_lift_pct": round(((candidate_mean / baseline_mean) - 1.0) * 100.0, 2) if baseline_mean else 0.0,
            "candidate_illegal_actions": candidate["summary"]["illegal_actions"],
            "baseline_illegal_actions": sum(result["summary"]["illegal_actions"] for result in baseline_results),
        },
    }


def _default_workers(seed_count: int) -> int:
    configured = os.environ.get("GM_BENCH_WORKERS")
    if configured:
        return max(1, int(configured))
    return max(1, min(seed_count, os.cpu_count() or 1))
