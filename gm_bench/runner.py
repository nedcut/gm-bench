"""Episode orchestration."""

from __future__ import annotations

import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Any, Callable

from gm_bench.agents import AGENTS, Agent
from gm_bench.protocol import PHASES, EpisodeConfig
from gm_bench.scoring import score_breakdown
from gm_bench.session import PersistentProcessAgent, should_continue_interaction
from gm_bench.simulator import League

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class BenchmarkResult:
    agent: str
    seed: int
    seasons: int
    final_score: float
    strategy_score: float
    protocol_penalty: float
    wins: int
    championships: int
    illegal_actions: int
    season_summaries: list[dict[str, Any]]
    transactions: list[dict[str, Any]]


def run_episode(
    agent: Agent,
    seed: int,
    seasons: int = 5,
    user_team_id: int = 0,
    progress: ProgressCallback | None = None,
    config: EpisodeConfig | None = None,
) -> BenchmarkResult:
    episode_config = config or EpisodeConfig()
    league = League.new(seed=seed, user_team_id=user_team_id)
    phases = list(PHASES) if episode_config.include_midseason else [phase for phase in PHASES if phase != "midseason"]
    total_decisions = seasons * len(phases)
    decision = 0
    persistent = isinstance(agent, PersistentProcessAgent)
    if persistent:
        agent.start_episode(seed, seasons)
    try:
        for season_index in range(1, seasons + 1):
            for phase in phases:
                decision += 1
                if progress is not None:
                    progress(
                        {
                            "agent": agent.name,
                            "seed": seed,
                            "season": season_index,
                            "phase": phase,
                            "decision": decision,
                            "total_decisions": total_decisions,
                        }
                    )
                if phase == "midseason":
                    league.prepare_midseason()
                if phase == "trade_deadline":
                    league.prepare_trade_deadline()
                if phase == "draft":
                    league.run_opponent_draft(before_user=True)
                run_decision_point(league, agent, phase, episode_config)
                if phase == "draft":
                    league.run_opponent_draft(before_user=False)
                league.run_autopilot_opponents(phase)
            league.simulate_season()
    finally:
        if persistent:
            agent.end_episode()
    breakdown = score_breakdown(league, user_team_id)
    return BenchmarkResult(
        agent=agent.name,
        seed=seed,
        seasons=seasons,
        final_score=round(breakdown["final_score"], 3),
        strategy_score=round(breakdown["strategy_score"], 3),
        protocol_penalty=round(breakdown["protocol_penalty"], 3),
        wins=sum(summary.wins for summary in league.summaries),
        championships=league.user_team.championships,
        illegal_actions=league.illegal_actions,
        season_summaries=[summary.__dict__ for summary in league.summaries],
        transactions=[transaction.__dict__ for transaction in league.transactions],
    )


def run_decision_point(league: League, agent: Agent, phase: str, config: EpisodeConfig) -> list[dict[str, Any]]:
    """Run one decision window, optionally across multiple interaction rounds."""
    tier = _observation_tier_for_agent(agent, config)
    action_results: list[dict[str, Any]] | None = None
    last_results: list[dict[str, Any]] = []
    for round_index in range(config.max_interaction_rounds):
        observation = league.observation(
            phase,
            tier=tier,
            action_results=action_results,
            interaction_round=round_index,
        )
        if round_index == 0:
            actions = agent.act(observation)
        elif isinstance(agent, PersistentProcessAgent):
            actions = agent.act_on_results(action_results or [])
        else:
            observation["action_results"] = action_results
            actions = agent.act(observation)
        results = [item.to_dict() for item in league.apply_actions(actions, phase)]
        last_results = results
        if not should_continue_interaction(results, max_rounds=config.max_interaction_rounds, round_index=round_index):
            break
        action_results = results
    return last_results


def _observation_tier_for_agent(agent: Agent, config: EpisodeConfig) -> str:
    if config.builtin_full_observation and agent.name in AGENTS:
        return "full"
    return config.observation_tier


def run_many(
    agent: Agent,
    seeds: list[int],
    seasons: int = 5,
    workers: int | None = None,
    progress: ProgressCallback | None = None,
    config: EpisodeConfig | None = None,
) -> dict[str, Any]:
    max_workers = workers if workers is not None else _default_workers(len(seeds))
    if max_workers <= 1 or len(seeds) <= 1:
        results = [
            run_episode(agent, seed=seed, seasons=seasons, progress=progress, config=config) for seed in seeds
        ]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(
                executor.map(
                    lambda seed: run_episode(agent, seed=seed, seasons=seasons, progress=progress, config=config),
                    seeds,
                )
            )
    scores = [result.final_score for result in results]
    wins = [result.wins for result in results]
    return {
        "agent": agent.name,
        "seasons": seasons,
        "seeds": seeds,
        "episodes": [result.__dict__ for result in results],
        "summary": {
            "mean_score": round(mean(scores), 3) if scores else 0.0,
            "mean_strategy_score": round(mean(result.strategy_score for result in results), 3) if results else 0.0,
            "total_protocol_penalty": round(sum(result.protocol_penalty for result in results), 3),
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
    *,
    progress: ProgressCallback | None = None,
    config: EpisodeConfig | None = None,
) -> dict[str, Any]:
    baselines = baseline_names or ["random", "conservative", "win-now", "rebuild", "value"]
    candidate = run_many(agent, seeds=seeds, seasons=seasons, progress=progress, config=config)
    baseline_results = [run_many(AGENTS[name](), seeds=seeds, seasons=seasons, config=config) for name in baselines]
    baseline_scores = [_precise_mean_score(result) for result in baseline_results]
    baseline_mean = mean(baseline_scores) if baseline_scores else 0.0
    candidate_mean = _precise_mean_score(candidate)
    return {
        "agent": agent.name,
        "seasons": seasons,
        "seeds": seeds,
        "candidate": candidate,
        "baselines": baseline_results,
        "normalized": {
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
        },
        "paired": _paired_analysis(seeds, candidate, baseline_results),
    }


def _scores_by_seed(result: dict[str, Any]) -> dict[int, float]:
    return {episode["seed"]: episode["final_score"] for episode in result["episodes"]}


def _precise_mean_score(result: dict[str, Any]) -> float:
    scores = [episode["final_score"] for episode in result["episodes"]]
    return mean(scores) if scores else 0.0


def _paired_analysis(
    seeds: list[int],
    candidate: dict[str, Any],
    baseline_results: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_scores = _scores_by_seed(candidate)
    baseline_scores = [_scores_by_seed(result) for result in baseline_results]

    per_seed: list[dict[str, Any]] = []
    lifts: list[float] = []
    candidate_wins = 0
    for seed in seeds:
        candidate_score = candidate_scores[seed]
        panel_score = mean(scores[seed] for scores in baseline_scores) if baseline_scores else 0.0
        lift = candidate_score - panel_score
        lifts.append(lift)
        if lift > 0:
            candidate_wins += 1
        per_seed.append(
            {
                "seed": seed,
                "candidate_score": round(candidate_score, 3),
                "baseline_panel_score": round(panel_score, 3),
                "lift": round(lift, 3),
            }
        )

    lift_mean = mean(lifts) if lifts else 0.0
    ci_low, ci_high = _bootstrap_mean_ci(lifts)
    ci95_low = round(ci_low, 3)
    ci95_high = round(ci_high, 3)

    best_baseline = max(baseline_results, key=_precise_mean_score, default=None)
    best_block: dict[str, Any] | None = None
    if best_baseline is not None:
        best_scores = _scores_by_seed(best_baseline)
        best_lifts = [candidate_scores[seed] - best_scores[seed] for seed in seeds]
        best_block = {
            "agent": best_baseline["agent"],
            "mean_score": round(_precise_mean_score(best_baseline), 3),
            "paired_lift_mean": round(mean(best_lifts), 3) if best_lifts else 0.0,
            "seed_win_rate": round(sum(1 for lift in best_lifts if lift > 0) / len(best_lifts), 3)
            if best_lifts
            else 0.0,
        }

    return {
        "num_seeds": len(seeds),
        "per_seed": per_seed,
        "paired_lift_mean": round(lift_mean, 3),
        "paired_lift_stddev": round(pstdev(lifts), 3) if len(lifts) > 1 else 0.0,
        "paired_lift_ci95": [ci95_low, ci95_high],
        "significant_at_95": ci95_low > 0.0 or ci95_high < 0.0,
        "candidate_seed_win_rate": round(candidate_wins / len(seeds), 3) if seeds else 0.0,
        "best_baseline": best_block,
    }


def _bootstrap_mean_ci(
    values: list[float],
    confidence: float = 0.95,
    iterations: int = 2000,
) -> tuple[float, float]:
    if len(values) < 2:
        point = values[0] if values else 0.0
        return point, point
    rng = random.Random(f"gm-bench-bootstrap:{len(values)}:{sum(values):.6f}")
    count = len(values)
    means = sorted(mean(values[rng.randrange(count)] for _ in range(count)) for _ in range(iterations))
    tail = (1.0 - confidence) / 2.0
    last = iterations - 1
    low = means[int(tail * last)]
    high = means[int((1.0 - tail) * last)]
    return low, high


def make_progress_printer(verbose: bool = False) -> ProgressCallback | None:
    if not verbose and os.environ.get("GM_BENCH_VERBOSE", "0") != "1":
        return None

    def _print(event: dict[str, Any]) -> None:
        print(
            f"[gm-bench] {event['agent']} seed={event['seed']} "
            f"decision {event['decision']}/{event['total_decisions']} "
            f"(season {event['season']} {event['phase']})",
            file=sys.stderr,
        )

    return _print


def _default_workers(seed_count: int) -> int:
    configured = os.environ.get("GM_BENCH_WORKERS")
    if configured:
        return max(1, int(configured))
    return max(1, min(seed_count, os.cpu_count() or 1))
