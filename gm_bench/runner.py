"""Episode orchestration."""

from __future__ import annotations

import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Any, Callable

from gm_bench.agents import AGENTS, Agent
from gm_bench.baseline_cache import cache_key, default_cache_path, load_cache, put_cached_episode, save_cache
from gm_bench.scoring import score_breakdown
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
    decisions: int
    failed_decisions: int
    memo_writes: int
    mean_decision_seconds: float
    max_decision_seconds: float
    season_summaries: list[dict[str, Any]]
    transactions: list[dict[str, Any]]


def _decision_failed(actions: Any) -> bool:
    """Whether the agent's actions for a decision point came from a failure path.

    Adapters mark substituted output: `ExternalProcessAgent` returns a noop with
    an `error` key on timeouts/crashes/bad JSON, and the example adapters attach
    `model_error` to fallback actions when the model's own output was unusable.
    Without this accounting, a model that never produces valid output still
    scores like a scripted fallback agent and the failure is invisible.
    """
    if not isinstance(actions, list):
        return True
    return any(isinstance(action, dict) and ("error" in action or "model_error" in action) for action in actions)


def run_episode(
    agent: Agent,
    seed: int,
    seasons: int = 5,
    user_team_id: int = 0,
    progress: ProgressCallback | None = None,
) -> BenchmarkResult:
    league = League.new(seed=seed, user_team_id=user_team_id)
    decision = 0
    total_decisions = seasons * 3
    failed_decisions = 0
    decision_seconds: list[float] = []
    for season_index in range(1, seasons + 1):
        for phase in ["preseason", "trade_deadline", "draft"]:
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
            if phase == "draft":
                league.run_opponent_draft(before_user=True)
            observation = league.observation(phase)
            started = time.perf_counter()
            actions = agent.act(observation)
            decision_seconds.append(time.perf_counter() - started)
            if _decision_failed(actions):
                failed_decisions += 1
            league.apply_actions(actions, phase)
            if phase == "draft":
                league.run_opponent_draft(before_user=False)
            league.run_autopilot_opponents(phase)
        league.simulate_season()
    breakdown = score_breakdown(league, user_team_id)
    memo_writes = sum(
        1
        for transaction in league.transactions
        if transaction.team_id == user_team_id and transaction.accepted and transaction.action.get("type") == "memo"
    )
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
        decisions=total_decisions,
        failed_decisions=failed_decisions,
        memo_writes=memo_writes,
        mean_decision_seconds=round(mean(decision_seconds), 4) if decision_seconds else 0.0,
        max_decision_seconds=round(max(decision_seconds), 4) if decision_seconds else 0.0,
        season_summaries=[summary.__dict__ for summary in league.summaries],
        transactions=[transaction.__dict__ for transaction in league.transactions],
    )


def run_many(
    agent: Agent,
    seeds: list[int],
    seasons: int = 5,
    workers: int | None = None,
    repeats: int = 1,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run `repeats` episodes per seed (episodes carry a 1-based `repeat` index).

    The simulator is deterministic, so repeats only matter for stochastic
    agents — model-backed ones. Multiple repeats separate model sampling luck
    from seed (league-generation) luck: paired statistics use the per-seed
    mean across repeats, and summaries report the within-seed spread.
    """
    jobs = [(seed, repeat) for seed in seeds for repeat in range(1, max(1, repeats) + 1)]

    def one(job: tuple[int, int]) -> dict[str, Any]:
        seed, repeat = job
        result = run_episode(agent, seed=seed, seasons=seasons, progress=progress)
        return {**result.__dict__, "repeat": repeat}

    max_workers = workers if workers is not None else _default_workers(len(jobs))
    if max_workers <= 1 or len(jobs) <= 1:
        episodes = [one(job) for job in jobs]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            episodes = list(executor.map(one, jobs))
    payload = _episodes_payload(agent.name, seeds, seasons, episodes)
    payload["repeats"] = max(1, repeats)
    return payload


def summarize_episodes(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-episode stats into the summary block shared by every run payload.

    Live runs and baseline-cache hits both flow through here so the two paths can
    never drift into differently-shaped summaries.
    """
    seed_means = _per_seed_mean_scores(episodes)
    # Older cached baseline episodes may predate the reliability fields, so read
    # them defensively; wall-time latency stays per-episode to keep summaries
    # deterministic for a given agent behavior.
    decisions = sum(episode.get("decisions", 0) for episode in episodes)
    failed_decisions = sum(episode.get("failed_decisions", 0) for episode in episodes)
    return {
        "mean_score": round(mean(seed_means), 3) if seed_means else 0.0,
        "mean_strategy_score": round(mean(episode["strategy_score"] for episode in episodes), 3) if episodes else 0.0,
        "total_protocol_penalty": round(sum(episode["protocol_penalty"] for episode in episodes), 3),
        "score_stddev": round(pstdev(seed_means), 3) if len(seed_means) > 1 else 0.0,
        "mean_total_wins": round(mean(episode["wins"] for episode in episodes), 3) if episodes else 0.0,
        "championships": sum(episode["championships"] for episode in episodes),
        "illegal_actions": sum(episode["illegal_actions"] for episode in episodes),
        "within_seed_score_stddev": _within_seed_stddev(episodes),
        "decisions": decisions,
        "failed_decisions": failed_decisions,
        "decision_failure_rate": round(failed_decisions / decisions, 3) if decisions else 0.0,
        "memo_writes": sum(episode.get("memo_writes", 0) for episode in episodes),
    }


def _per_seed_mean_scores(episodes: list[dict[str, Any]]) -> list[float]:
    by_seed: dict[int, list[float]] = {}
    for episode in episodes:
        by_seed.setdefault(episode["seed"], []).append(episode["final_score"])
    return [mean(scores) for scores in by_seed.values()]


def _within_seed_stddev(episodes: list[dict[str, Any]]) -> float:
    """Mean per-seed score spread across repeats — the model-sampling noise.

    Zero when every seed ran once (or the agent is deterministic). Comparing
    this against the across-seed `score_stddev` shows whether score
    differences between models exceed their own run-to-run variance.
    """
    by_seed: dict[int, list[float]] = {}
    for episode in episodes:
        by_seed.setdefault(episode["seed"], []).append(episode["final_score"])
    spreads = [pstdev(scores) for scores in by_seed.values() if len(scores) > 1]
    return round(mean(spreads), 3) if spreads else 0.0


def _episodes_payload(
    agent_name: str,
    seeds: list[int],
    seasons: int,
    episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "agent": agent_name,
        "seasons": seasons,
        "seeds": seeds,
        "episodes": episodes,
        "summary": summarize_episodes(episodes),
    }


def run_many_cached_baselines(
    agent_name: str,
    seeds: list[int],
    seasons: int,
    *,
    cache_path: str | os.PathLike[str] | None = None,
    use_cache: bool = True,
) -> tuple[dict[str, Any], int]:
    """Return run_many-shaped payload for a scripted baseline, using cache hits where available."""
    if agent_name not in AGENTS:
        raise KeyError(f"unknown baseline agent {agent_name!r}")

    cache_path = cache_path if cache_path is not None else default_cache_path()
    cache = load_cache(cache_path) if use_cache else {}
    episodes: list[dict[str, Any]] = []
    cache_hits = 0
    agent = AGENTS[agent_name]()

    for seed in seeds:
        key = cache_key(agent_name, seed, seasons)
        cached = cache.get(key) if use_cache else None
        if cached is not None:
            episodes.append(cached)
            cache_hits += 1
            continue
        result = run_episode(agent, seed=seed, seasons=seasons)
        episode = result.__dict__
        episodes.append(episode)
        if use_cache:
            put_cached_episode(agent_name, seed, seasons, episode, cache=cache)

    if use_cache and cache_hits < len(seeds):
        save_cache(cache, cache_path)

    return _episodes_payload(agent_name, seeds, seasons, episodes), cache_hits


def evaluate_against_baselines(
    agent: Agent,
    seeds: list[int],
    seasons: int = 5,
    baseline_names: list[str] | None = None,
    *,
    repeats: int = 1,
    use_baseline_cache: bool = True,
    baseline_cache_path: str | os.PathLike[str] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    # Repeats apply to the candidate only: scripted baselines are deterministic,
    # so re-running them would produce identical episodes.
    baselines = baseline_names or ["random", "conservative", "win-now", "rebuild", "value"]
    candidate = run_many(agent, seeds=seeds, seasons=seasons, repeats=repeats, progress=progress)
    baseline_results: list[dict[str, Any]] = []
    cache_hits = 0
    resolved_cache_path = baseline_cache_path if baseline_cache_path is not None else default_cache_path()
    for name in baselines:
        if use_baseline_cache:
            payload, hits = run_many_cached_baselines(
                name,
                seeds,
                seasons,
                cache_path=resolved_cache_path,
                use_cache=True,
            )
            cache_hits += hits
            baseline_results.append(payload)
        else:
            baseline_results.append(run_many(AGENTS[name](), seeds=seeds, seasons=seasons))
    baseline_scores = [_precise_mean_score(result) for result in baseline_results]
    baseline_mean = mean(baseline_scores) if baseline_scores else 0.0
    candidate_mean = _precise_mean_score(candidate)
    return {
        "agent": agent.name,
        "seasons": seasons,
        "seeds": seeds,
        "candidate": candidate,
        "baselines": baseline_results,
        "baseline_cache": {
            "enabled": use_baseline_cache,
            "path": str(resolved_cache_path),
            "hits": cache_hits,
            "total": len(baselines) * len(seeds),
        },
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
            "candidate_decisions": candidate["summary"].get("decisions", 0),
            "candidate_failed_decisions": candidate["summary"].get("failed_decisions", 0),
            "candidate_decision_failure_rate": candidate["summary"].get("decision_failure_rate", 0.0),
            "candidate_memo_writes": candidate["summary"].get("memo_writes", 0),
        },
        "paired": _paired_analysis(seeds, candidate, baseline_results),
    }


def _scores_by_seed(result: dict[str, Any]) -> dict[int, float]:
    """Map each seed to its final score, averaged across repeats when present."""
    by_seed: dict[int, list[float]] = {}
    for episode in result["episodes"]:
        by_seed.setdefault(episode["seed"], []).append(episode["final_score"])
    return {seed: mean(scores) for seed, scores in by_seed.items()}


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
        # Exact at benchmark-sized seed panels, unlike the bootstrap interval,
        # which is coarse below ~10 samples. None with a single seed.
        "sign_flip_p_value": _sign_flip_p_value(lifts),
        # With one seed the bootstrap interval collapses to a point, which would
        # otherwise read as "significant" — significance is undefined there.
        "significant_at_95": len(lifts) >= 2 and (ci95_low > 0.0 or ci95_high < 0.0),
        "candidate_seed_win_rate": round(candidate_wins / len(seeds), 3) if seeds else 0.0,
        "best_baseline": best_block,
    }


def _sign_flip_p_value(lifts: list[float]) -> float | None:
    """Two-sided sign-flip permutation p-value for mean(paired lifts) != 0.

    Under the null (candidate and baseline panel are interchangeable), each
    per-seed lift is symmetric around zero, so flipping signs generates the
    exact null distribution of the mean. Enumerated exactly up to 14 seeds
    (2^14 flips); beyond that, a deterministically seeded sample of flips
    keeps the benchmark's reproducibility guarantee. The smallest achievable
    p is 2 / 2^n, so a 3-seed run can never look more certain than p=0.25 —
    an honest floor the bootstrap interval hides.
    """
    n = len(lifts)
    if n < 2:
        return None
    observed = abs(mean(lifts))
    tolerance = 1e-12
    if n <= 14:
        total = 1 << n
        hits = sum(
            1
            for mask in range(total)
            if abs(sum(lift if mask >> i & 1 else -lift for i, lift in enumerate(lifts)) / n) >= observed - tolerance
        )
        return round(hits / total, 4)
    rng = random.Random(f"gm-bench-signflip:{n}:{sum(lifts):.6f}")
    total = 20000
    hits = sum(
        1
        for _ in range(total)
        if abs(sum(lift if rng.random() < 0.5 else -lift for lift in lifts) / n) >= observed - tolerance
    )
    return round(hits / total, 4)


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
