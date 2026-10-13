#!/usr/bin/env python3
"""Export season 1 of the public pick-trader demo for the site's "How it works" tab.

The source is the committed trajectory demo (public seed 1, already checked by
tests/test_trajectory_export.py). This script only selects and names what the
walkthrough shows: the state at each of the four decisions, the moves
pick-trader made, written as the 2.0 tool calls a model would send, and how the
score moved. The brief and tool list come from the frozen 2.0 contract modules.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gm_bench.agentic.brief import _PHASE_NOTES, task_brief  # noqa: E402
from gm_bench.agentic.tools import ACTION_TYPE_FOR_TOOL, TOOLS  # noqa: E402

SOURCE = ROOT / "web/public/replay/trajectory-demo.json"
DESTINATION = ROOT / "web/src/data/walkthrough.json"
AGENT = "pick-trader"
SEASON = 1
SEASONS = 5
SCHEMA = "gm-bench-walkthrough-v1"
TOOL_FOR_ACTION = {action: tool for tool, action in ACTION_TYPE_FOR_TOOL.items()}
# Tools whose description limits them to one phase, e.g. "Draft phase only."
ONLY = re.compile(r"\b(Preseason|Midseason|Draft)(?: phase)? only\b")
PHASE_KEY = {"Preseason": "preseason", "Midseason": "midseason", "Draft": "draft"}


def r2(value: float) -> float:
    return round(float(value), 2)


def card(player: dict[str, Any]) -> dict[str, Any]:
    """The public face of a player, as a model would read it from the tools."""
    return {
        "id": player["id"],
        "name": player["name"],
        "position": player["position"],
        "age": player["age"],
        "overall": r2(player["overall"]),
        "potential": r2(player["potential"]),
        "salary": r2(player["salary"]),
        "contract_years": player["contract_years"],
    }


def tools() -> list[dict[str, Any]]:
    out = []
    for tool in TOOLS:
        match = ONLY.search(tool["description"])
        out.append(
            {
                "name": tool["name"],
                "kind": tool["kind"],
                "summary": tool["description"].split(". ")[0].rstrip(".") + ".",
                "only": PHASE_KEY[match.group(1)] if match else None,
            }
        )
    return out


def people(observation: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Every player an action in this decision can name, by id."""
    found: dict[int, dict[str, Any]] = {}
    pools = [
        observation["team"]["roster"],
        observation["free_agents"],
        observation["waiver_wire"],
        observation["draft_class"],
        [item["player"] for item in observation["trade_market"]],
    ]
    for offer in observation["incoming_offers"]:
        pools += [offer["they_receive_players"], offer["you_receive_players"]]
    for pool in pools:
        for player in pool:
            found.setdefault(player["id"], player)
    return found


def team_names(observation: dict[str, Any]) -> dict[int, str]:
    return {row["team_id"]: row["team_name"] for row in observation["standings"]}


def offer_summary(offer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": offer["offer_id"],
        "team": offer["team_name"],
        "you_give": [card(p) for p in offer["they_receive_players"]],
        "you_give_picks": offer["they_receive_pick_seasons"],
        "you_get": [card(p) for p in offer["you_receive_players"]],
        "you_get_picks": offer["you_receive_pick_seasons"],
    }


def context(phase: str, observation: dict[str, Any]) -> dict[str, Any]:
    """What matters in this phase, from the state at its start."""
    team = observation["team"]
    by_overall = lambda players: sorted(players, key=lambda p: -p["overall"])  # noqa: E731
    out: dict[str, Any] = {}
    if phase == "preseason":
        out["expiring"] = [
            {**card(p), "extension_quotes": {k: r2(v) for k, v in p["extension_quotes"].items()}}
            for p in by_overall(team["roster"])
            if p.get("extension_quotes")
        ]
        out["free_agents"] = [
            {**card(p), "asking_salary": r2(p["asking_salary"])} for p in by_overall(observation["free_agents"])[:6]
        ]
        out["free_agent_count"] = len(observation["free_agents"])
    if phase == "midseason":
        out["waiver_wire"] = [card(p) for p in by_overall(observation["waiver_wire"])]
    if phase == "trade_deadline":
        out["offers"] = [offer_summary(o) for o in observation["incoming_offers"]]
        out["trade_market_count"] = len(observation["trade_market"])
    if phase == "draft":
        out["prospects"] = [card(p) for p in by_overall(observation["draft_class"])[:6]]
        out["prospect_count"] = len(observation["draft_class"])
    return out


def move(result: dict[str, Any], players: dict[int, dict[str, Any]], teams: dict[int, str]) -> dict[str, Any]:
    action = result["action"]
    arguments = {key: value for key, value in action.items() if key != "type"}
    out: dict[str, Any] = {
        "tool": TOOL_FOR_ACTION[action["type"]],
        "arguments": arguments,
        "accepted": result["accepted"],
        "message": result["message"],
    }
    player_id = action.get("player_id", action.get("prospect_id"))
    if player_id is not None:
        out["player"] = card(players[player_id])
    if action["type"] == "trade":
        out["partner"] = teams[action["partner_team_id"]]
        out["give"] = [card(players[i]) for i in action["give_player_ids"]]
        out["get"] = [card(players[i]) for i in action["receive_player_ids"]]
    if action["type"] == "set_lineup":
        out["dressed"] = len(action["player_ids"])
    return out


def situation(observation: dict[str, Any]) -> dict[str, Any]:
    team = observation["team"]
    ranked = sorted(observation["standings"], key=lambda row: (-row["wins"], row["losses"]))
    return {
        "wins": team["wins"],
        "losses": team["losses"],
        "rank": 1 + [row["team_id"] for row in ranked].index(team["id"]),
        "cap_room": r2(team["cap_room"]),
        "payroll": r2(team["payroll"]),
        "roster_size": len(team["roster"]),
        "picks": len(team["picks"]),
    }


def build(demo: dict[str, Any]) -> dict[str, Any]:
    episode = next(e for e in demo["episodes"] if e["fixture"]["agent"] == AGENT)
    fixture = episode["fixture"]
    decisions = fixture["decisions"]
    first = decisions[0]["interaction_rounds"][0]["observation"]
    team = first["team"]
    teams = team_names(first)
    steps = []
    for decision in decisions:
        if decision["season"] != SEASON:
            continue
        rounds = decision["interaction_rounds"]
        start = rounds[0]["observation"]
        last = rounds[-1]["observation"]
        players = people(start) | people(last)
        queries = [
            {"tool": TOOL_FOR_ACTION[a["type"]], "arguments": {k: v for k, v in a.items() if k != "type"}}
            for r in rounds[:-1]
            for a in r["actions"]
        ]
        reports = last["scout_reports"]
        steps.append(
            {
                "phase": decision["phase"],
                "note": _PHASE_NOTES[decision["phase"]],
                "situation": situation(start),
                "context": context(decision["phase"], start),
                "queries": queries,
                "scouted": [
                    {**card(players[int(pid)]), "scouted_potential": r2(report)}
                    for pid, report in reports.items()
                    if int(pid) in players
                ],
                "moves": [move(result, players, teams) for result in decision["results"]],
                "delta": {k: r2(v) for k, v in decision["delta"].items() if k.endswith("_contribution")},
            }
        )
    history = decisions[-1]["interaction_rounds"][-1]["observation"]["history"]
    seasons = [
        {
            "season": h["season"],
            "wins": h["wins"],
            "losses": h["losses"],
            "playoff_rounds": h["playoff_rounds"],
            "champion": teams[h["champion_team_id"]],
            "score_after_season": r2(h["score_after_season"]),
        }
        for h in history
    ]
    return {
        "schema": SCHEMA,
        "source": {
            "file": str(SOURCE.relative_to(ROOT)),
            "track": demo["track"],
            "seed_scope": demo["seed_scope"],
            "seed": fixture["seed"],
            "agent": AGENT,
            "source_commit": demo["source_commit"],
        },
        "team": {"id": team["id"], "name": team["name"], "teams": len(teams)},
        "season": SEASON,
        "brief": task_brief(SEASONS, team["name"], team["id"]),
        "tools": tools(),
        "steps": steps,
        "seasons": seasons,
        "final_score": r2(episode["score"]["final_score"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = parser.parse_args()
    built = json.dumps(build(json.loads(SOURCE.read_text())), indent=1, sort_keys=True) + "\n"
    if args.check:
        if DESTINATION.read_text() != built:
            raise SystemExit(f"{DESTINATION.relative_to(ROOT)} is stale; run scripts/build_walkthrough.py")
        return
    DESTINATION.write_text(built)


if __name__ == "__main__":
    main()
