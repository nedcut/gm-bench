"""Objective benchmark scoring."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gm_bench.simulator import League


def score_team(league: "League", team_id: int) -> float:
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
    illegal_penalty = league.illegal_actions * 2.5 if team_id == league.user_team_id else 0.0
    current_strength = league._team_strength(team, apply_injury_noise=False)

    return (
        recent_wins * 0.42
        + recent_rounds * 9.0
        + championships * 35.0
        + total_assets * 0.16
        + young_assets * 0.18
        + cap_score
        + current_strength * 0.28
        + roster_depth * 8.0
        - illegal_penalty
    )
