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
# Re-calibrated for the v6 draft lottery. The deterministic inverse-standings
# draft handed the weaker `value` roster a guaranteed top pick every season;
# replacing that certainty with lottery odds compressed the measured
# shrewd-over-value gap on the 24-seed canary panel from 45.9 to 24.5 mean
# points. The paired significance check still asserts the ordering; this
# margin only guards against the gap collapsing outright.
CAP_HYGIENE_MIN_FINAL_MARGIN = 15.0
CANARY_MIN_PAIRED_T = 2.0
MECHANIC_MIN_SEED_RATES = {
    "memo": 0.75,
    "scouting": 0.75,
    "offer_response": 0.75,
    "accepted_offer": 0.25,
    "pick_trade": 0.25,
    "extension": 0.75,
    # This is a liveness check, not a target release frequency. The frozen
    # 24-seed scripted panel accepts seven releases across six seeds; a modest
    # 10% floor proves the user-facing branch remains reachable without tuning
    # the policy to manufacture churn.
    "release": 0.10,
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


# The canaries run their own seed panel, three times the width of the paid
# leaderboard lane, because they can afford to: every agent they run is a
# scripted policy costing nothing but CPU, while the leaderboard panel is sized
# by what a model row costs in API spend.
#
# Eight seeds is not enough to assert an ordering. On the final contract the
# matched contrast is effectively zero at n=8 (paired t=-0.004), reaches t=2.559
# at n=24, and reaches t=3.999 at n=48 with `pick-trader` ahead on 39 of 48
# seeds. The 48-seed paired variance puts the approximate two-sided 80%-power
# requirement at 24 seeds; adjacent reference contrasts need substantially more.
#
# This width is chosen from that power calculation with headroom, not by taste.
# Narrowing it back to the leaderboard panel would restore the failure mode
# where an ordering is asserted at a threshold noise can satisfy.
CANARY_SEEDS: tuple[int, ...] = tuple(range(11, 35))


def run_validity_canaries(
    *,
    seeds: list[int] | None = None,
    seasons: int | None = None,
) -> dict[str, Any]:
    leaderboard = PRESETS["leaderboard"]
    resolved_seeds = list(seeds or CANARY_SEEDS)
    resolved_seasons = int(seasons or leaderboard["seasons"])

    value = run_many(ValueAgent(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1)
    shrewd = run_many(ShrewdAgent(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1)
    strategic = run_many(StrategicAgent(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1)
    pick_trader = run_many(PickTraderAgent(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1)
    canaries = [
        run_many(agent_cls(), seeds=resolved_seeds, seasons=resolved_seasons, workers=1) for agent_cls in CANARY_AGENTS
    ]

    mechanic_coverage, mechanic_checks = _mechanic_coverage(pick_trader, len(resolved_seeds))
    # Adjacent reference means remain useful calibration rows, but they are not
    # invariants. Two pre-registered contrasts clear the significance bar and
    # are asserted; the rest are calibration rows only.
    #
    # `shrewd > value` is asserted again here. It was demoted when it measured
    # paired t=0.05 on the 8-seed leaderboard panel, which is what widening the
    # canary panel was for: at 24 seeds it is t=3.184. Restoring a claim the
    # evidence now supports is the point of the wider panel, and it was
    # pre-registered rather than picked because it came out significant.
    #
    # `pick-trader`, `strategic` and `shrewd` remain mutually unresolved
    # (t=-0.494 and t=-0.326 between adjacent pairs, both reversed in sign from
    # the historical ordering). Asserting any order among them would launder a
    # coin flip as a guarantee, which is the defect this gate exists to remove.
    checks = [
        _margin_check(pick_trader, value, "pick-trader", "value", "honest_bar"),
        _paired_significance_check(
            pick_trader,
            value,
            "pick-trader",
            "value",
            "final_score",
            "honest_bar",
        ),
        _margin_check(shrewd, value, "shrewd", "value", "cap_hygiene_bar"),
        _paired_significance_check(
            shrewd,
            value,
            "shrewd",
            "value",
            "final_score",
            "cap_hygiene_bar",
        ),
        *mechanic_checks,
    ]
    for canary in canaries:
        checks.append(_margin_check(value, canary, "value", canary["agent"], "canary_final_score"))
        checks.append(
            _paired_significance_check(
                value,
                canary,
                "value",
                canary["agent"],
                "final_score",
                "canary_final_score",
            )
        )
        checks.append(_strategy_margin_check(value, canary, "value", canary["agent"]))
        checks.append(
            _paired_significance_check(
                value,
                canary,
                "value",
                canary["agent"],
                "strategy_score",
                "canary_strategy_score",
            )
        )

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
                mechanics.append("extension")
            if action_type == "release":
                mechanics.append("release")
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
    if check_name == "honest_bar":
        minimum = 0.0
    elif check_name == "cap_hygiene_bar":
        minimum = CAP_HYGIENE_MIN_FINAL_MARGIN
    else:
        minimum = CANARY_MIN_FINAL_MARGIN
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


def _paired_significance_check(
    winner: dict[str, Any],
    loser: dict[str, Any],
    winner_name: str,
    loser_name: str,
    episode_metric: str,
    check_name: str,
) -> dict[str, Any]:
    winner_by_seed = _per_seed_metric(winner, episode_metric)
    loser_by_seed = _per_seed_metric(loser, episode_metric)
    shared_seeds = sorted(winner_by_seed.keys() & loser_by_seed.keys())
    complete_pairing = len(shared_seeds) == len(winner_by_seed) == len(loser_by_seed) and len(shared_seeds) >= 2
    differences = [winner_by_seed[seed] - loser_by_seed[seed] for seed in shared_seeds]
    paired_mean = sum(differences) / len(differences) if differences else 0.0
    if len(differences) >= 2:
        variance = sum((difference - paired_mean) ** 2 for difference in differences) / (len(differences) - 1)
        standard_error = math.sqrt(variance / len(differences))
    else:
        standard_error = 0.0
    paired_t = paired_mean / standard_error if standard_error > 0 else None
    # With identical paired differences the estimated standard error is zero:
    # the mathematical t limit is signed infinity. Keep the JSON field finite
    # (None) while preserving that limiting decision in the boolean gate.
    clears_bar = (paired_t is None and paired_mean > 0) or (paired_t is not None and paired_t >= CANARY_MIN_PAIRED_T)
    return {
        "name": f"{check_name}_paired_significance",
        "winner": winner_name,
        "loser": loser_name,
        "metric": "paired_t",
        "margin": round(paired_t, 3) if paired_t is not None else None,
        "minimum_margin": CANARY_MIN_PAIRED_T,
        "paired_mean_difference": round(paired_mean, 3),
        "paired_standard_error": round(standard_error, 3),
        "seed_count": len(shared_seeds),
        "complete_pairing": complete_pairing,
        "ok": complete_pairing and clears_bar,
    }


def _per_seed_metric(result: dict[str, Any], metric: str) -> dict[int, float]:
    scores: dict[int, list[float]] = {}
    for episode in result["episodes"]:
        scores.setdefault(int(episode["seed"]), []).append(float(episode[metric]))
    return {seed: sum(values) / len(values) for seed, values in scores.items()}


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
