"""score-v2: the GM-Bench 2.1 objective.

Contract source for 2.1 (fingerprinted by ``gm_bench.v21.contract``).

score-v1 with three terms changed and every end-state term kept, weight for
weight (``docs/score_v2_proposal.md``, candidate E; the evidence for each
change is in ``docs/score_deep_dive.md``):

- ``season_wins``: every season's own wins at 1.02 a win. score-v1 summed
  running win totals after seasons 3-5 (records never reset), weighting the
  seasons 3, 3, 3, 2, 1. 1.02 keeps ``pick-trader``'s mean contribution from
  wins equal to v1's on the canary seeds 11-34.
- ``expected_playoff_rounds``: playoff rounds over the last three seasons,
  scored as their exact expectation given the bracket and the playoff
  ratings rather than the single-game results (9 a round, as in v1).
- ``expected_championships``: titles over every season, likewise expected
  (35 a title, as in v1).

The playoff dice are drawn after the ratings that set the odds, so the
expectation is unbiased for every policy; it removes most of the score's
variance (playoffs were ~64% of it) without changing a single game.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from gm_bench.scoring import breakdown_from_components
from gm_bench.scoring import score_components as score_components_v1

SCORING_VERSION = "score-v2"
# Playoff rounds count over the last this-many seasons, as in score-v1.
RECENT_PLAYOFF_SEASONS = 3


@dataclass(frozen=True)
class ScoreScaleV2:
    season_win: float = 1.02
    playoff_round: float = 9.0
    championship: float = 35.0
    total_asset: float = 0.16
    young_asset: float = 0.18
    future_pick_asset: float = 0.16
    cap_room: float = 0.35
    cap_score_min: float = -12.0
    cap_score_max: float = 10.0
    current_strength: float = 0.28
    roster_depth: float = 8.0
    illegal_action_penalty: float = 2.5


SCALE = ScoreScaleV2()
PUBLISHED_SCALE_FINGERPRINT = "dfdb5369a60bebc3"

# Raw metric -> weight, for every term but the clamped cap room.
_LINEAR_WEIGHTS = {
    "season_wins": SCALE.season_win,
    "expected_playoff_rounds": SCALE.playoff_round,
    "expected_championships": SCALE.championship,
    "total_assets": SCALE.total_asset,
    "young_assets": SCALE.young_asset,
    "future_pick_assets": SCALE.future_pick_asset,
    "current_strength": SCALE.current_strength,
    "roster_depth": SCALE.roster_depth,
}
SCORE_TERMS = (*_LINEAR_WEIGHTS, "cap_room")
SCORE_COMPONENT_KEYS = (
    *SCORE_TERMS,
    "protocol_penalty",
    *(f"{name}_contribution" for name in SCORE_TERMS),
)
_PRECISION = 6


def scale_fingerprint() -> str:
    payload = json.dumps(asdict(SCALE), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _validate_scale() -> None:
    actual = scale_fingerprint()
    if actual != PUBLISHED_SCALE_FINGERPRINT:
        raise RuntimeError(
            f"score-v2 weights changed without a new scoring version: expected {PUBLISHED_SCALE_FINGERPRINT!r}, "
            f"got {actual!r}"
        )


_validate_scale()


def score_components(league: Any, team_id: int, *, open_season_wins: int | None = None) -> dict[str, float]:
    """Raw metrics and weighted contributions for the user team of a ``League21``.

    ``open_season_wins`` counts a season whose playoffs are done but whose
    summary is not yet written (``score_after_season`` is computed there).
    """
    if team_id != league.user_team_id:
        raise ValueError("score-v2 needs the season history, which is kept for the user team only")
    v1 = score_components_v1(league, team_id)
    seasons = [(summary.season, summary.wins) for summary in league.summaries]
    if open_season_wins is not None:
        seasons.append((league.season, open_season_wins))
    odds = league.expected_playoffs
    recent = [season for season, _wins in seasons[-RECENT_PLAYOFF_SEASONS:]]
    raw = {
        "season_wins": float(sum(wins for _season, wins in seasons)),
        "expected_playoff_rounds": sum(odds.get(season, {}).get(team_id, (0.0, 0.0))[0] for season in recent),
        "expected_championships": sum(odds.get(season, {}).get(team_id, (0.0, 0.0))[1] for season, _w in seasons),
        **{name: float(v1[name]) for name in ("total_assets", "young_assets", "future_pick_assets")},
        "current_strength": float(v1["current_strength"]),
        "roster_depth": float(v1["roster_depth"]),
        "cap_room": float(v1["cap_room"]),
        "protocol_penalty": float(league.illegal_actions * SCALE.illegal_action_penalty),
    }
    contributions = {f"{name}_contribution": raw[name] * weight for name, weight in _LINEAR_WEIGHTS.items()}
    contributions["cap_room_contribution"] = max(
        SCALE.cap_score_min, min(SCALE.cap_score_max, raw["cap_room"] * SCALE.cap_room)
    )
    return {**raw, **contributions}


def score_breakdown(league: Any, team_id: int, **kwargs: Any) -> dict[str, float]:
    return breakdown_from_components(score_components(league, team_id, **kwargs))


def score_team(league: Any, team_id: int, **kwargs: Any) -> float:
    return score_breakdown(league, team_id, **kwargs)["final_score"]


def persisted_score_components(components: Mapping[str, float]) -> dict[str, float]:
    """Round components for an episode row, refusing missing or non-finite values."""
    missing = [name for name in SCORE_COMPONENT_KEYS if name not in components]
    if missing:
        raise ValueError(f"score-v2 components missing keys: {missing}")
    persisted = {}
    for name in SCORE_COMPONENT_KEYS:
        value = float(components[name])
        if not math.isfinite(value):
            raise ValueError(f"score-v2 component {name} is not finite: {value!r}")
        persisted[name] = round(value, _PRECISION)
    return persisted
