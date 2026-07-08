"""Reproducible scoring-scale and reference-policy calibration."""

from __future__ import annotations

from typing import Any

from gm_bench.agents import PickTraderAgent, ShrewdAgent, StrategicAgent, ValueAgent
from gm_bench.benchmark_config import PRESETS
from gm_bench.runner import run_many
from gm_bench.scoring import ACTIVE_SCORE_SCALE, scoring_scale_metadata


class _StrategicNoScoutAgent(StrategicAgent):
    name = "strategic-no-scout"

    def _next_scout_action(self, observation: dict[str, Any]) -> None:
        return None


class _StrategicNoOffersAgent(StrategicAgent):
    name = "strategic-no-offers"

    def _offer_actions(
        self,
        observation: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], set[int], set[int]]:
        return [], set(), set()


class _StrategicNoMemoAgent(StrategicAgent):
    name = "strategic-no-memo"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        return [action for action in super().act(observation) if action.get("type") != "memo"]


def marginal_value_table() -> list[dict[str, Any]]:
    """Return local score deltas implied by the active published scale."""

    scale = ACTIVE_SCORE_SCALE
    return [
        _marginal("one championship", "championships", 1.0, scale.championship),
        _marginal("ten recent wins", "recent_wins", 10.0, 10.0 * scale.recent_win),
        _marginal("one playoff round", "playoff_rounds", 1.0, scale.playoff_round),
        _marginal("twenty veteran asset value", "total_assets", 20.0, 20.0 * scale.total_asset),
        _marginal(
            "twenty young asset value",
            "total_assets + young_assets",
            20.0,
            20.0 * (scale.total_asset + scale.young_asset),
        ),
        _marginal(
            "ten future-pick asset value",
            "future_pick_assets",
            10.0,
            10.0 * scale.future_pick_asset,
        ),
        _marginal(
            "ten cap room before clamp",
            "cap_room",
            10.0,
            10.0 * scale.cap_room,
            note=f"applies only while cap contribution is between {scale.cap_score_min} and {scale.cap_score_max}",
        ),
        _marginal("ten current strength", "current_strength", 10.0, 10.0 * scale.current_strength),
        _marginal("one illegal action", "illegal_actions", 1.0, -scale.illegal_action_penalty),
    ]


def build_scoring_calibration(
    *,
    seeds: list[int] | None = None,
    seasons: int | None = None,
) -> dict[str, Any]:
    """Run deterministic reference policies and their key ablations."""

    leaderboard = PRESETS["leaderboard"]
    resolved_seeds = list(seeds or leaderboard["seeds"])
    resolved_seasons = int(seasons or leaderboard["seasons"])
    policy_types = (
        PickTraderAgent,
        StrategicAgent,
        _StrategicNoScoutAgent,
        _StrategicNoOffersAgent,
        _StrategicNoMemoAgent,
        ShrewdAgent,
        ValueAgent,
    )
    results = [
        run_many(agent_type(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1) for agent_type in policy_types
    ]
    strategic_mean = next(
        result["summary"]["mean_score"] for result in results if result["agent"] == StrategicAgent.name
    )
    policies = []
    for result in results:
        summary = result["summary"]
        policies.append(
            {
                "agent": result["agent"],
                "mean_score": summary["mean_score"],
                "delta_vs_strategic": round(summary["mean_score"] - strategic_mean, 3),
                "score_stddev": summary["score_stddev"],
                "illegal_actions": summary["illegal_actions"],
                "mean_total_wins": summary["mean_total_wins"],
                "championships": summary["championships"],
            }
        )
    return {
        "scoring_scale": scoring_scale_metadata(),
        "panel": {
            "seeds": resolved_seeds,
            "seasons": resolved_seasons,
        },
        "marginal_values": marginal_value_table(),
        "policies": policies,
    }


def _marginal(
    scenario: str,
    metric: str,
    metric_delta: float,
    score_delta: float,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "scenario": scenario,
        "metric": metric,
        "metric_delta": metric_delta,
        "score_delta": round(score_delta, 3),
    }
    if note is not None:
        row["note"] = note
    return row
