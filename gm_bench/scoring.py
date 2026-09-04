"""Objective benchmark scoring."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
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

# Raw end-of-episode state metrics, in score order. Each has a matching
# `<name>_contribution` holding the same metric after its weight is applied.
SCORE_COMPONENT_METRICS = (
    "recent_wins",
    "playoff_rounds",
    "championships",
    "total_assets",
    "young_assets",
    "future_pick_assets",
    "cap_room",
    "current_strength",
    "roster_depth",
)
# Persisted raw metric name -> ScoreScale attribute used to weight it.
SCORE_COMPONENT_WEIGHT_ATTRS = {
    "recent_wins": "recent_win",
    "playoff_rounds": "playoff_round",
    "championships": "championship",
    "total_assets": "total_asset",
    "young_assets": "young_asset",
    "future_pick_assets": "future_pick_asset",
    "cap_room": "cap_room",
    "current_strength": "current_strength",
    "roster_depth": "roster_depth",
}
# The persisted per-episode component schema: raw metrics, the protocol
# penalty, and the weighted contributions. Both halves are stored because the
# contributions alone cannot be reweighted -- `cap_room` is clamped, so its
# contribution is not a linear function of its weight.
SCORE_COMPONENT_KEYS = (
    *SCORE_COMPONENT_METRICS,
    "protocol_penalty",
    *(f"{name}_contribution" for name in SCORE_COMPONENT_METRICS),
)
# Enough precision that reweighting stays faithful, few enough digits that
# artifacts stay byte-identical across runs.
SCORE_COMPONENT_PRECISION = 6


def contribution_from_metric(name: str, raw: float, scale: ScoreScale | None = None) -> float:
    """Rebuild one weighted contribution from a persisted raw metric.

    ``cap_room`` is clamped to the scale's score band; every other term is a
    plain product. Used by publication validation so a row cannot keep a
    coherent contribution total while lying about the raws that reweighting
    reads.
    """
    active = scale or ACTIVE_SCORE_SCALE
    weight = float(getattr(active, SCORE_COMPONENT_WEIGHT_ATTRS[name]))
    if name == "cap_room":
        return max(active.cap_score_min, min(active.cap_score_max, raw * weight))
    return raw * weight


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
    # Retained salary is real payroll even after the player leaves the roster.
    payroll = league._payroll(team)
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
    # Picks are valued by count and distance only; the origin team's record is
    # deliberately not priced in here. The bet on the origin's future pays off
    # (or doesn't) through the draft slot the pick eventually becomes.
    pick_assets = sum(
        (len(team.draft_picks[season]) if season in team.draft_picks else 1) * pick_value(league.season, season)
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

    return breakdown_from_components(score_components(league, team_id))


def breakdown_from_components(components: Mapping[str, float]) -> dict[str, float]:
    """Collapse a component dict into the three published score scalars."""

    strategy_score = sum(value for name, value in components.items() if name.endswith("_contribution"))
    protocol_penalty = components["protocol_penalty"]
    return {
        "strategy_score": strategy_score,
        "protocol_penalty": protocol_penalty,
        "final_score": strategy_score - protocol_penalty,
    }


def persisted_score_components(components: Mapping[str, float]) -> dict[str, float]:
    """Round components for storage in an episode row, refusing bad numbers.

    Artifacts are the only surviving evidence for a run, so a component that is
    non-finite (or missing) must stop the episode here rather than reach a
    publication JSON that no validator can rebuild a score from.
    """

    missing = [name for name in SCORE_COMPONENT_KEYS if name not in components]
    if missing:
        raise ValueError(f"score components missing keys: {missing}")
    persisted = {}
    for name in SCORE_COMPONENT_KEYS:
        value = float(components[name])
        if not math.isfinite(value):
            raise ValueError(f"score component {name!r} is not finite: {value!r}")
        persisted[name] = round(value, SCORE_COMPONENT_PRECISION)
    return persisted


def score_team(league: "League", team_id: int) -> float:
    return score_breakdown(league, team_id)["final_score"]
