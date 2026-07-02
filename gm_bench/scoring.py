"""Objective benchmark scoring."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gm_bench.simulator import League

ILLEGAL_ACTION_PENALTY = 2.5


def score_breakdown(league: "League", team_id: int) -> dict[str, float]:
    """Score components for a team, split into strategy quality and protocol compliance.

    ``strategy_score`` measures roster management outcomes; ``protocol_penalty``
    measures invalid/rejected actions (user team only). ``final_score`` is their
    difference and remains the headline objective.
    """
    team = league.teams[team_id]
    roster = [league.players[player_id] for player_id in team.roster]
    payroll = sum(player.salary for player in roster)
    young_assets = sum(player.asset_value for player in roster if player.age <= 24)
    total_assets = sum(player.asset_value for player in roster)
    cap_room = league.cap - payroll
    recent = league.summaries[-3:]
    recent_wins = sum(summary.wins for summary in recent)
    recent_rounds = sum(summary.playoff_rounds for summary in recent)
    championships = team.championships
    roster_depth = min(len(roster), 24) / 24.0
    cap_score = max(-12.0, min(10.0, cap_room * 0.35))
    protocol_penalty = league.illegal_actions * ILLEGAL_ACTION_PENALTY if team_id == league.user_team_id else 0.0
    current_strength = league._team_strength(team, apply_injury_noise=False)

    strategy_score = (
        recent_wins * 0.42
        + recent_rounds * 9.0
        + championships * 35.0
        + total_assets * 0.16
        + young_assets * 0.18
        + cap_score
        + current_strength * 0.28
        + roster_depth * 8.0
    )
    return {
        "strategy_score": strategy_score,
        "protocol_penalty": protocol_penalty,
        "final_score": strategy_score - protocol_penalty,
    }


def score_team(league: "League", team_id: int) -> float:
    return score_breakdown(league, team_id)["final_score"]
