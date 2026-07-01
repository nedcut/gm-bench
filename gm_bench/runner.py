"""Episode orchestration."""

from __future__ import annotations

import random
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


def run_many(agent: Agent, seeds: list[int], seasons: int = 5) -> dict[str, Any]:
    results = [run_episode(agent, seed=seed, seasons=seasons) for seed in seeds]
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
            "baseline_panel_mean_score": round(baseline_mean, 3),
            "score_lift": round(candidate_mean - baseline_mean, 3),
            "score_lift_pct": round(((candidate_mean / baseline_mean) - 1.0) * 100.0, 2) if baseline_mean else 0.0,
            "candidate_illegal_actions": candidate["summary"]["illegal_actions"],
            "baseline_illegal_actions": sum(result["summary"]["illegal_actions"] for result in baseline_results),
        },
        "paired": _paired_analysis(seeds, candidate, baseline_results),
    }


def _scores_by_seed(result: dict[str, Any]) -> dict[int, float]:
    """Map each seed to the candidate/baseline final score for that episode."""
    return {episode["seed"]: episode["final_score"] for episode in result["episodes"]}


def _precise_mean_score(result: dict[str, Any]) -> float:
    """Mean of per-episode scores without the display rounding `summary` applies."""
    scores = [episode["final_score"] for episode in result["episodes"]]
    return mean(scores) if scores else 0.0


def _paired_analysis(
    seeds: list[int],
    candidate: dict[str, Any],
    baseline_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare candidate and baselines on the *same* seeds, differencing per seed.

    Because every agent plays identical seeds, per-seed differences cancel most of
    the league-generation luck the benchmark warns about. This yields a far
    lower-variance estimate of skill than comparing unpaired means, which is what
    matters when the benchmark is run on only a handful of seeds.
    """
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
    # Round the CI once, then derive significance from those exposed bounds so the
    # displayed interval and the significance flag can never contradict each other
    # (e.g. an interval that rounds to [0.0, ...] while the flag reads "significant").
    ci95_low = round(ci_low, 3)
    ci95_high = round(ci_high, 3)

    # The panel average includes weak baselines like `random`; the strongest single
    # baseline is a more honest bar to clear, so report it separately. Select it by
    # the precise per-episode mean, not the display-rounded summary, so near-ties
    # aren't decided by rounding.
    best_baseline = max(baseline_results, key=_precise_mean_score, default=None)
    best_block: dict[str, Any] | None = None
    if best_baseline is not None:
        best_scores = _scores_by_seed(best_baseline)
        best_lifts = [candidate_scores[seed] - best_scores[seed] for seed in seeds]
        best_block = {
            "agent": best_baseline["agent"],
            "mean_score": round(_precise_mean_score(best_baseline), 3),
            "paired_lift_mean": round(mean(best_lifts), 3) if best_lifts else 0.0,
            "seed_win_rate": round(sum(1 for lift in best_lifts if lift > 0) / len(best_lifts), 3) if best_lifts else 0.0,
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
    """Deterministic percentile bootstrap confidence interval for the mean.

    Uses a fixed RNG seed so a given set of per-seed lifts always yields the same
    interval, preserving the benchmark's reproducibility guarantee. With fewer
    than two samples the interval is undefined, so the point estimate is returned
    for both bounds.
    """
    if len(values) < 2:
        point = values[0] if values else 0.0
        return point, point
    rng = random.Random(f"gm-bench-bootstrap:{len(values)}:{sum(values):.6f}")
    count = len(values)
    means = sorted(mean(values[rng.randrange(count)] for _ in range(count)) for _ in range(iterations))
    tail = (1.0 - confidence) / 2.0
    # Percentile indexes into the 0-based sorted sample: floor(p * (n - 1)) keeps the
    # endpoints inside the array and centered on the requested quantile.
    last = iterations - 1
    low = means[int(tail * last)]
    high = means[int((1.0 - tail) * last)]
    return low, high
