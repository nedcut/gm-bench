"""Objective benchmark scoring."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from gm_bench.models import PICK_TRADE_MAX_SEASONS_AHEAD, pick_value

if TYPE_CHECKING:
    from gm_bench.simulator import League

SCORING_VERSION = "score-v1"


@dataclass(frozen=True)
class ScoreScale:
    recent_win: float
    playoff_round: float
    championship: float
    total_asset: float
    young_asset: float
    future_pick_asset: float
    cap_room: float
    cap_score_min: float
    cap_score_max: float
    current_strength: float
    roster_depth: float
    illegal_action_penalty: float


SCORE_SCALES = {
    "score-v1": ScoreScale(
        recent_win=0.42,
        playoff_round=9.0,
        championship=35.0,
        total_asset=0.16,
        young_asset=0.18,
        future_pick_asset=0.16,
        cap_room=0.35,
        cap_score_min=-12.0,
        cap_score_max=10.0,
        current_strength=0.28,
        roster_depth=8.0,
        illegal_action_penalty=2.5,
    )
}
PUBLISHED_SCORE_SCALE_FINGERPRINTS = {
    "score-v1": "05a60ff4f691e734",
}
ACTIVE_SCORE_SCALE = SCORE_SCALES[SCORING_VERSION]
ILLEGAL_ACTION_PENALTY = ACTIVE_SCORE_SCALE.illegal_action_penalty


def scoring_scale_fingerprint(version: str = SCORING_VERSION) -> str:
    payload = json.dumps(asdict(SCORE_SCALES[version]), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def scoring_scale_metadata(version: str = SCORING_VERSION) -> dict[str, Any]:
    return {
        "version": version,
        "fingerprint": scoring_scale_fingerprint(version),
        "weights": asdict(SCORE_SCALES[version]),
    }


def validate_published_scoring_scale(version: str = SCORING_VERSION) -> None:
    expected = PUBLISHED_SCORE_SCALE_FINGERPRINTS.get(version)
    actual = scoring_scale_fingerprint(version)
    if expected != actual:
        raise RuntimeError(
            f"scoring scale {version!r} changed without a new published version: expected {expected!r}, got {actual!r}"
        )


validate_published_scoring_scale()


def score_components(league: "League", team_id: int) -> dict[str, float]:
    """Return raw state metrics and weighted score contributions."""

    scale = ACTIVE_SCORE_SCALE
    team = league.teams[team_id]
    roster = [league.players[player_id] for player_id in team.roster]
    payroll = sum(player.salary for player in roster)
    young_assets = sum(player.asset_value for player in roster if player.age <= 24)
    total_assets = sum(player.asset_value for player in roster)
    # Future picks are assets: valued at the same discounted scale trades use,
    # so trading players for picks (or picks for players) is priced consistently
    # by the market and the objective. Every team is scored over the same
    # league-wide horizon with absent seasons defaulting to one implicit pick —
    # otherwise swapping not-yet-materialized far-future picks would mint score.
    horizon = league.season + PICK_TRADE_MAX_SEASONS_AHEAD
    for any_team in league.teams.values():
        if any_team.draft_picks:
            horizon = max(horizon, max(any_team.draft_picks))
    pick_assets = sum(
        team.draft_picks.get(season, 1) * pick_value(league.season, season)
        for season in range(league.season + 1, horizon + 1)
    )
    cap_room = league.cap - payroll
    recent = league.summaries[-3:]
    recent_wins = sum(summary.wins for summary in recent)
    recent_rounds = sum(summary.playoff_rounds for summary in recent)
    championships = team.championships
    roster_depth = min(len(roster), 24) / 24.0
    cap_score = max(scale.cap_score_min, min(scale.cap_score_max, cap_room * scale.cap_room))
    protocol_penalty = league.illegal_actions * scale.illegal_action_penalty if team_id == league.user_team_id else 0.0
    current_strength = league._team_strength(team, apply_injury_noise=False)

    contributions = {
        "recent_wins": recent_wins * scale.recent_win,
        "playoff_rounds": recent_rounds * scale.playoff_round,
        "championships": championships * scale.championship,
        "total_assets": total_assets * scale.total_asset,
        "young_assets": young_assets * scale.young_asset,
        "future_pick_assets": pick_assets * scale.future_pick_asset,
        "cap_room": cap_score,
        "current_strength": current_strength * scale.current_strength,
        "roster_depth": roster_depth * scale.roster_depth,
    }
    return {
        "recent_wins": float(recent_wins),
        "playoff_rounds": float(recent_rounds),
        "championships": float(championships),
        "total_assets": total_assets,
        "young_assets": young_assets,
        "future_pick_assets": pick_assets,
        "cap_room": cap_room,
        "current_strength": current_strength,
        "roster_depth": roster_depth,
        "protocol_penalty": protocol_penalty,
        **{f"{name}_contribution": value for name, value in contributions.items()},
    }


def score_breakdown(league: "League", team_id: int) -> dict[str, float]:
    """Split objective strategy quality from invalid-action penalties."""

    components = score_components(league, team_id)
    strategy_score = sum(value for name, value in components.items() if name.endswith("_contribution"))
    protocol_penalty = components["protocol_penalty"]
    return {
        "strategy_score": strategy_score,
        "protocol_penalty": protocol_penalty,
        "final_score": strategy_score - protocol_penalty,
    }


def score_team(league: "League", team_id: int) -> float:
    return score_breakdown(league, team_id)["final_score"]
