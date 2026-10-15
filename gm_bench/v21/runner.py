"""Play a scripted policy under the 2.1 rules and score it with score-v2.

Contract source for 2.1 (fingerprinted by ``gm_bench.v21.contract``). The
loop is ``gm_bench.runner.run_episode``'s, phase for phase, on ``League21``;
2.1's references (``pick-trader``, ``random``) and validity canaries are
played here, so they face exactly the league a 2.1 agentic episode does.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from gm_bench.agents import Agent
from gm_bench.protocol import PHASES, EpisodeConfig
from gm_bench.runner import run_decision_point
from gm_bench.v21.rules import League21
from gm_bench.v21.scoring import score_breakdown, score_components


def play_league(agent: Agent, seed: int, seasons: int = 5, user_team_id: int = 0) -> League21:
    """The finished league after ``agent`` manages ``seasons`` seasons on ``seed``."""
    config = EpisodeConfig()
    league = League21.new(seed=seed, user_team_id=user_team_id)
    for _season in range(seasons):
        for phase in PHASES:
            if phase == "midseason":
                league.prepare_midseason()
            if phase == "trade_deadline":
                league.prepare_trade_deadline()
            if phase == "draft":
                league.run_opponent_draft(before_user=True)
            run_decision_point(league, agent, phase, config)
            if phase == "draft":
                league.run_opponent_draft(before_user=False)
            league.run_autopilot_opponents(phase)
        league.simulate_season()
    return league


def run_episode(agent: Agent, seed: int, seasons: int = 5, user_team_id: int = 0) -> dict[str, Any]:
    league = play_league(agent, seed, seasons, user_team_id)
    breakdown = score_breakdown(league, user_team_id)
    return {
        "agent": agent.name,
        "seed": seed,
        "seasons": seasons,
        "final_score": round(breakdown["final_score"], 3),
        "strategy_score": round(breakdown["strategy_score"], 3),
        "protocol_penalty": round(breakdown["protocol_penalty"], 3),
        "score_components": score_components(league, user_team_id),
        "wins": sum(summary.wins for summary in league.summaries),
        "illegal_actions": league.illegal_actions,
        "rejected_offers": league.rejected_offers,
        "transactions": [transaction.__dict__ for transaction in league.transactions],
    }


def run_many(agent: Agent, seeds: list[int], seasons: int = 5, workers: int = 1) -> dict[str, Any]:
    """``gm_bench.runner.run_many``'s result shape, for the validity checks.

    Serial: scripted policies take a fraction of a second per episode.
    ``workers`` is accepted for signature parity and ignored.
    """
    episodes = [run_episode(agent, seed, seasons) for seed in seeds]
    return {
        "agent": agent.name,
        "episodes": episodes,
        "summary": {
            "mean_score": round(mean(e["final_score"] for e in episodes), 3),
            "mean_strategy_score": round(mean(e["strategy_score"] for e in episodes), 3),
            "total_protocol_penalty": round(sum(e["protocol_penalty"] for e in episodes), 3),
            "illegal_actions": sum(e["illegal_actions"] for e in episodes),
            "rejected_offers": sum(e["rejected_offers"] for e in episodes),
            "mean_total_wins": round(mean(e["wins"] for e in episodes), 3),
        },
    }
