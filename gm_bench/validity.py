"""Benchmark validity canaries for score-gaming regressions."""

from __future__ import annotations

import math
from typing import Any

from gm_bench.agent_utils import position_aware_lineup, public_asset_value
from gm_bench.agents import Agent, ExploitAgent, PickTraderAgent, ShrewdAgent, StrategicAgent, ValueAgent
from gm_bench.benchmark_config import PRESETS
from gm_bench.models import ROSTER_MIN
from gm_bench.runner import run_many

CANARY_MIN_FINAL_MARGIN = 25.0
CANARY_MIN_STRATEGY_MARGIN = 25.0
MECHANIC_MIN_SEED_RATES = {
    "memo": 0.75,
    "scouting": 0.75,
    "offer_response": 0.75,
    "accepted_offer": 0.25,
    "pick_trade": 0.25,
    "contract_extension": 0.50,
}


class PickHoardAgent(Agent):
    """Degenerate canary that tries to score future assets over team quality."""

    name = "pick-hoard"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        season = int(observation["season"])
        moved_ids: set[int] = set()
        target_pick_season = season + 1
        if len(observation["team"]["roster"]) > ROSTER_MIN:
            partners_with_pick = [
                row
                for row in observation["standings"]
                if row["team_id"] != observation["team"]["id"]
                and row.get("draft_picks", {}).get(target_pick_season, 1) > 0
            ]
            if partners_with_pick:
                partner_id = partners_with_pick[0]["team_id"]
                roster = sorted(observation["team"]["roster"], key=public_asset_value, reverse=True)
                for player in roster:
                    if player["age"] < 25:
                        continue
                    actions.append(
                        {
                            "type": "trade",
                            "partner_team_id": partner_id,
                            "give_player_ids": [player["id"]],
                            "receive_player_ids": [],
                            "receive_pick_seasons": [target_pick_season],
                        }
                    )
                    moved_ids.add(player["id"])
                    break
        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(observation["draft_class"], key=public_asset_value)
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        remaining = [player for player in observation["team"]["roster"] if player["id"] not in moved_ids]
        lineup = position_aware_lineup(remaining, lambda player: player["overall"])
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions or [{"type": "noop"}]


class CapHoardAgent(Agent):
    """Degenerate canary that over-values cap room by dumping productive players."""

    name = "cap-hoard"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        moved_ids: set[int] = set()
        if len(observation["team"]["roster"]) > 20:
            veterans = [
                player for player in observation["team"]["roster"] if player["age"] >= 27 and player["salary"] > 0
            ]
            if veterans:
                player = max(veterans, key=lambda item: item["salary"])
                actions.append({"type": "release", "player_id": player["id"]})
                moved_ids.add(player["id"])
        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(observation["draft_class"], key=lambda player: player["potential"])
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        remaining = [player for player in observation["team"]["roster"] if player["id"] not in moved_ids]
        lineup = position_aware_lineup(remaining, lambda player: player["overall"])
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions or [{"type": "noop"}]


class AcceptEverythingAgent(Agent):
    """Degenerate canary that blindly accepts every opponent-initiated offer."""

    name = "accept-everything"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = [
            {"type": "accept_offer", "offer_id": offer["offer_id"]} for offer in observation.get("incoming_offers", [])
        ]
        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(observation["draft_class"], key=public_asset_value)
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        lineup = position_aware_lineup(observation["team"]["roster"], lambda player: player["overall"])
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions or [{"type": "noop"}]


CANARY_AGENTS: tuple[type[Agent], ...] = (
    ExploitAgent,
    PickHoardAgent,
    CapHoardAgent,
    AcceptEverythingAgent,
)


def run_validity_canaries(
    *,
    seeds: list[int] | None = None,
    seasons: int | None = None,
) -> dict[str, Any]:
    leaderboard = PRESETS["leaderboard"]
    resolved_seeds = list(seeds or leaderboard["seeds"])
    resolved_seasons = int(seasons or leaderboard["seasons"])

    value = run_many(ValueAgent(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1)
    shrewd = run_many(ShrewdAgent(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1)
    strategic = run_many(StrategicAgent(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1)
    pick_trader = run_many(PickTraderAgent(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1)
    canaries = [
        run_many(agent_cls(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1) for agent_cls in CANARY_AGENTS
    ]

    mechanic_coverage, mechanic_checks = _mechanic_coverage(pick_trader, len(resolved_seeds))
    checks = [
        # Extra protocol mechanics are coverage surfaces, not guaranteed score
        # improvements. The calibrated honest ordering that must hold is the
        # issue's shrewd-over-value roster-management bar.
        _margin_check(shrewd, value, "shrewd", "value", "honest_bar"),
        *mechanic_checks,
    ]
    for canary in canaries:
        checks.append(_margin_check(value, canary, "value", canary["agent"], "canary_final_score"))
        checks.append(_strategy_margin_check(value, canary, "value", canary["agent"]))

    return {
        "ok": all(check["ok"] for check in checks),
        "seeds": resolved_seeds,
        "seasons": resolved_seasons,
        "baselines": [
            _summary_row(pick_trader),
            _summary_row(strategic),
            _summary_row(shrewd),
            _summary_row(value),
        ],
        "mechanic_coverage": mechanic_coverage,
        "canaries": [_summary_row(result) for result in canaries],
        "checks": checks,
    }


def _mechanic_coverage(
    result: dict[str, Any],
    seed_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    covered_seeds: dict[str, set[int]] = {name: set() for name in MECHANIC_MIN_SEED_RATES}
    accepted_actions: dict[str, int] = {name: 0 for name in MECHANIC_MIN_SEED_RATES}
    for episode in result["episodes"]:
        seed = int(episode["seed"])
        for transaction in episode["transactions"]:
            if transaction.get("team_id") != 0 or not transaction.get("accepted"):
                continue
            action = transaction.get("action") or {}
            action_type = action.get("type")
            mechanics: list[str] = []
            if action_type == "memo":
                mechanics.append("memo")
            if action_type == "scout":
                mechanics.append("scouting")
            if action_type in {"accept_trade_offer", "reject_trade_offer", "counter_trade_offer"}:
                mechanics.append("offer_response")
            if action_type == "accept_trade_offer":
                mechanics.append("accepted_offer")
            if action_type == "trade" and (action.get("give_pick_seasons") or action.get("receive_pick_seasons")):
                mechanics.append("pick_trade")
            if action_type == "extend_contract":
                mechanics.append("contract_extension")
            for mechanic in mechanics:
                accepted_actions[mechanic] += 1
                covered_seeds[mechanic].add(seed)

    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for mechanic, minimum_rate in MECHANIC_MIN_SEED_RATES.items():
        minimum_seeds = max(1, math.ceil(seed_count * minimum_rate))
        observed = len(covered_seeds[mechanic])
        rows.append(
            {
                "mechanic": mechanic,
                "accepted_actions": accepted_actions[mechanic],
                "seed_count": observed,
                "seed_rate": round(observed / max(seed_count, 1), 3),
                "minimum_seed_count": minimum_seeds,
            }
        )
        checks.append(
            {
                "name": "mechanic_coverage",
                "winner": result["agent"],
                "loser": f"missing-{mechanic}",
                "metric": "seed_count",
                "margin": observed,
                "minimum_margin": minimum_seeds,
                "ok": observed >= minimum_seeds,
            }
        )
    return rows, checks


def _margin_check(
    winner: dict[str, Any],
    loser: dict[str, Any],
    winner_name: str,
    loser_name: str,
    check_name: str,
) -> dict[str, Any]:
    margin = winner["summary"]["mean_score"] - loser["summary"]["mean_score"]
    minimum = CANARY_MIN_FINAL_MARGIN if check_name != "honest_bar" else 0.0
    return {
        "name": check_name,
        "winner": winner_name,
        "loser": loser_name,
        "metric": "mean_score",
        "margin": round(margin, 3),
        "minimum_margin": minimum,
        "ok": margin >= minimum,
    }


def _strategy_margin_check(
    winner: dict[str, Any], loser: dict[str, Any], winner_name: str, loser_name: str
) -> dict[str, Any]:
    margin = winner["summary"]["mean_strategy_score"] - loser["summary"]["mean_strategy_score"]
    return {
        "name": "canary_strategy_score",
        "winner": winner_name,
        "loser": loser_name,
        "metric": "mean_strategy_score",
        "margin": round(margin, 3),
        "minimum_margin": CANARY_MIN_STRATEGY_MARGIN,
        "ok": margin >= CANARY_MIN_STRATEGY_MARGIN,
    }


def _summary_row(result: dict[str, Any]) -> dict[str, Any]:
    summary = result["summary"]
    return {
        "agent": result["agent"],
        "mean_score": summary["mean_score"],
        "mean_strategy_score": summary["mean_strategy_score"],
        "protocol_penalty": summary["total_protocol_penalty"],
        "illegal_actions": summary["illegal_actions"],
        "rejected_offers": summary["rejected_offers"],
        "mean_total_wins": summary["mean_total_wins"],
    }
