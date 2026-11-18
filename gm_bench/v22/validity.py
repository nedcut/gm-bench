"""The 2.2 contract checks: 2.0's orderings plus two end-of-run canaries.

``gm_bench.validity.run_validity_canaries`` played under ``League22`` and
score-v3, then two checks 2.2 adds because its brief says when the
end-of-run credit is counted (``docs/bench_v2_2_spec.md``, phase 1):

- ``extend-everything``: ``pick-trader`` that also extends every eligible
  player in the final preseason, for the shortest term that outlasts the
  final rollover. The credit pays for those players; this bounds how much.
- ``run-down``: ``pick-trader`` that makes no extension in the final season,
  so its roster expires before the credit is counted. It must not gain.

Both are compared with ``pick-trader`` on the same seeds.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from gm_bench.agents import Agent, PickTraderAgent
from gm_bench.simulator import HARD_CAP_BUFFER
from gm_bench.v22.runner import run_many
from gm_bench.validity import CANARY_SEEDS, _summary_row
from gm_bench.validity import run_validity_canaries as _run_base

# What a 32-seed panel can detect (paired SD 26 to 29 under 2.1). A final-season
# move that the end-of-run credit over-pays by less than this cannot reorder rows.
END_OF_RUN_MAX_GAIN = 13.0


class ExtendEverythingAgent(Agent):
    name = "extend-everything"

    def __init__(self, final_season: int = 5) -> None:
        self.base = PickTraderAgent()
        self.final_season = final_season

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = self.base.act(observation)
        if (
            int(observation["season"]) != self.final_season
            or observation["phase"] != "preseason"
            or int(observation.get("interaction_round", 0)) != 0
        ):
            return actions
        team = observation["team"]
        hard_cap = float(observation["rules"]["salary_cap"]) + HARD_CAP_BUFFER
        taken = {a.get("player_id") for a in actions if a.get("type") == "extend_contract"}
        payroll = float(team["payroll"])
        extra = []
        for player in sorted(team.get("roster", []), key=lambda p: (-p["overall"], p["id"])):
            quotes = player.get("extension_quotes")
            if not quotes or player["id"] in taken:
                continue
            # Two years: this season and the next, so the player outlasts the final rollover.
            salary = float(quotes["2"])
            if payroll - player["salary"] + salary > hard_cap:
                continue
            extra.append({"type": "extend_contract", "player_id": player["id"], "years": 2, "salary": salary})
            payroll += salary - player["salary"]
        return [a for a in actions if a.get("type") != "noop"] + extra or [{"type": "noop"}]


class RunDownAgent(Agent):
    name = "run-down"

    def __init__(self, final_season: int = 5) -> None:
        self.base = PickTraderAgent()
        self.final_season = final_season

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = self.base.act(observation)
        if int(observation["season"]) != self.final_season:
            return actions
        return [a for a in actions if a.get("type") != "extend_contract"] or [{"type": "noop"}]


def _gain_check(canary: dict[str, Any], reference: dict[str, Any], maximum: float) -> dict[str, Any]:
    by_seed = {e["seed"]: e["final_score"] for e in reference["episodes"]}
    gain = mean(e["final_score"] - by_seed[e["seed"]] for e in canary["episodes"])
    return {
        "name": "end_of_run_gain",
        "winner": "pick-trader",
        "loser": canary["agent"],
        "metric": "paired_mean_score",
        "margin": round(-gain, 3),
        "minimum_margin": 0.0 - maximum,
        "ok": gain <= maximum,
    }


def run_validity_canaries(*, seeds: list[int] | None = None, seasons: int | None = None) -> dict[str, Any]:
    result = _run_base(seeds=seeds, seasons=seasons, run=run_many)
    panel, length = result["seeds"], result["seasons"]
    reference = run_many(PickTraderAgent(), seeds=panel, seasons=length)
    extend = run_many(ExtendEverythingAgent(length), seeds=panel, seasons=length)
    rundown = run_many(RunDownAgent(length), seeds=panel, seasons=length)
    checks = [_gain_check(extend, reference, END_OF_RUN_MAX_GAIN), _gain_check(rundown, reference, 0.0)]
    for canary in (extend, rundown):
        result["canaries"].append(_summary_row(canary))
    result["checks"].extend(checks)
    result["ok"] = result["ok"] and all(check["ok"] for check in checks)
    return result


__all__ = ["CANARY_SEEDS", "END_OF_RUN_MAX_GAIN", "ExtendEverythingAgent", "RunDownAgent", "run_validity_canaries"]
