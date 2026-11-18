"""score-v3: the GM-Bench 2.2 objective.

Contract source for 2.2 (fingerprinted by ``gm_bench.v22.contract``).

score-v2 with one hole closed; every term and weight is score-v2's
(``gm_bench/v21/scoring.py``, a frozen 2.1 source).

score-v2's pick term starts one season after ``league.season``. That is
right while a season is open, because its draft has been held. The final
score is taken after the last rollover, when ``league.season`` already names
the next season, so the picks for the draft straight after the episode
counted for nothing, yet they could be traded for value in the last three
seasons. score-v3 counts them at final scoring, at the value of a pick for
the current season (``docs/bench_v2_2_spec.md``, phase 1).
"""

from __future__ import annotations

from typing import Any

from gm_bench.models import pick_value
from gm_bench.scoring import breakdown_from_components
from gm_bench.v21 import scoring as score_v2

SCORING_VERSION = "score-v3"
SCALE = score_v2.SCALE
SCORE_TERMS = score_v2.SCORE_TERMS
SCORE_COMPONENT_KEYS = score_v2.SCORE_COMPONENT_KEYS
scale_fingerprint = score_v2.scale_fingerprint
persisted_score_components = score_v2.persisted_score_components


def score_components(league: Any, team_id: int, *, open_season_wins: int | None = None) -> dict[str, float]:
    """Raw metrics and weighted contributions for the user team of a ``League22``.

    ``open_season_wins`` marks a season whose playoffs are done but whose
    summary is not yet written (``score_after_season`` is computed there);
    that season's draft has been held, so its picks are not counted.
    """
    parts = score_v2.score_components(league, team_id, open_season_wins=open_season_wins)
    if open_season_wins is None:
        team = league.teams[team_id]
        held = len(team.draft_picks[league.season]) if league.season in team.draft_picks else 1
        next_draft = held * pick_value(league.season, league.season)
        parts["future_pick_assets"] += next_draft
        parts["future_pick_assets_contribution"] += next_draft * SCALE.future_pick_asset
    return parts


def score_breakdown(league: Any, team_id: int, **kwargs: Any) -> dict[str, float]:
    return breakdown_from_components(score_components(league, team_id, **kwargs))


def score_team(league: Any, team_id: int, **kwargs: Any) -> float:
    return score_breakdown(league, team_id, **kwargs)["final_score"]
