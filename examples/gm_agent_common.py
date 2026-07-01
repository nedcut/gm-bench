"""Shared helpers for model-backed GM-Bench example agents."""

from __future__ import annotations

import json
import os
import re
from typing import Any


from gm_bench.agent_utils import position_aware_lineup, public_asset_value


def compact_observation(observation: dict[str, Any]) -> dict[str, Any]:
    profile = os.environ.get("GM_AGENT_PROFILE", "compact")
    if profile == "tiny":
        roster_limit = 18
        free_agent_limit = 6
        draft_limit = 6
        trade_limit = 0
    else:
        roster_limit = 24
        free_agent_limit = 16
        draft_limit = 16
        trade_limit = 12
    team = observation["team"]
    roster = sorted(team["roster"], key=lambda player: player["overall"], reverse=True)
    free_agents = sorted(observation["free_agents"], key=public_asset_value, reverse=True)
    draft_class = sorted(observation["draft_class"], key=public_asset_value, reverse=True)
    return {
        "seed": observation["seed"],
        "season": observation["season"],
        "phase": observation["phase"],
        "rules": observation["rules"],
        "team": {
            "id": team["id"],
            "name": team["name"],
            "wins": team["wins"],
            "losses": team["losses"],
            "payroll": team["payroll"],
            "cap_room": team["cap_room"],
            "championships": team["championships"],
            "draft_picks": team["draft_picks"],
            "top_roster": roster[:roster_limit],
        },
        "free_agents": free_agents[:free_agent_limit],
        "draft_class": draft_class[:draft_limit],
        "trade_market": observation["trade_market"][:trade_limit],
        "history": observation["history"],
    }


def build_prompt(observation: dict[str, Any]) -> str:
    compact = compact_observation(observation)
    fallback_lineup = position_aware_lineup(observation["team"]["roster"])
    no_think = "/no_think\n" if os.environ.get("GM_AGENT_NO_THINK", "0") == "1" else ""
    return (
        no_think
        +
        "You are controlling a fictional hockey team in GM-Bench. "
        "Choose legal front-office actions that maximize long-term benchmark score: wins, playoffs, titles, young assets, cap health, and valid decisions.\n\n"
        "Return ONLY a JSON object shaped like {\"actions\":[...]}. Do not use markdown. Do not explain.\n\n"
        "Allowed action objects inside actions:\n"
        '{"type":"sign_free_agent","player_id":123,"years":1,"salary":2.5}\n'
        '{"type":"draft","prospect_id":1010001}\n'
        '{"type":"trade","partner_team_id":3,"give_player_ids":[1],"receive_player_ids":[88]}\n'
        '{"type":"release","player_id":1}\n'
        '{"type":"set_lineup","player_ids":[18 unique roster player ids]}\n'
        '{"type":"noop"}\n\n'
        "Constraints: lineup must include exactly 18 unique current roster players with at least 10 F, 4 D, and 1 G. "
        "Do not invent IDs. Keep signings under cap room unless the player is clearly worth it. "
        f"If unsure, at least set this valid lineup: {json.dumps(fallback_lineup)}.\n\n"
        f"Observation JSON:\n{json.dumps(compact, sort_keys=True)}"
    )


def parse_actions(text: str) -> list[dict[str, Any]]:
    stripped = strip_terminal_codes(text).strip()
    try:
        parsed = json.loads(stripped)
        return _actions_from_json(parsed)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return _actions_from_json(parsed)
        except json.JSONDecodeError:
            pass

    for parsed in _scan_json_values(stripped, "{"):
        try:
            return _actions_from_json(parsed)
        except ValueError:
            continue

    for parsed in _scan_json_values(stripped, "["):
        try:
            return _actions_from_json(parsed)
        except ValueError:
            continue
    raise ValueError("model did not return a JSON action array")


def _actions_from_json(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, dict) and isinstance(parsed.get("actions"), list):
        parsed = parsed["actions"]
    if isinstance(parsed, dict) and isinstance(parsed.get("type"), str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError("model JSON was not an action list")
    actions = [action for action in parsed if isinstance(action, dict) and isinstance(action.get("type"), str)]
    if not actions:
        raise ValueError("model JSON did not contain typed actions")
    return actions


def _scan_json_values(text: str, opener: str) -> list[Any]:
    decoder = json.JSONDecoder()
    values: list[Any] = []
    for match in re.finditer(re.escape(opener), text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        values.append(value)
    return values


def strip_terminal_codes(text: str) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def fallback_actions(observation: dict[str, Any], error: str | None = None) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if observation["phase"] == "draft" and observation["draft_class"]:
        prospect = max(observation["draft_class"], key=public_asset_value)
        actions.append({"type": "draft", "prospect_id": prospect["id"]})
    lineup = position_aware_lineup(observation["team"]["roster"])
    if lineup:
        actions.append({"type": "set_lineup", "player_ids": lineup})
    if not actions:
        actions.append({"type": "noop"})
    if error:
        actions[0]["model_error"] = error[:300]
    return actions
