"""Shared helpers for model-backed GM-Bench example agents."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

try:
    from gm_bench.agent_utils import position_aware_lineup, public_asset_value
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
    roster = team.get("roster") or []
    roster_sorted = sorted(roster, key=lambda player: player["overall"], reverse=True) if roster else []
    free_agents = observation.get("free_agents") or []
    if not free_agents and observation.get("free_agents_summary"):
        free_agents = [{"id": pid} for pid in observation["free_agents_summary"].get("top_ids", [])]
    free_agents_sorted = sorted(
        [player for player in free_agents if isinstance(player, dict) and "overall" in player],
        key=public_asset_value,
        reverse=True,
    )
    draft_class = observation.get("draft_class") or []
    if not draft_class and observation.get("draft_class_summary"):
        draft_class = [{"id": pid} for pid in observation["draft_class_summary"].get("top_ids", [])]
    draft_sorted = sorted(
        [player for player in draft_class if isinstance(player, dict) and "overall" in player],
        key=public_asset_value,
        reverse=True,
    )
    trade_market = observation.get("trade_market") or []
    payload: dict[str, Any] = {
        "seed": observation["seed"],
        "season": observation["season"],
        "phase": observation["phase"],
        "observation_tier": observation.get("observation_tier", "full"),
        "interaction_round": observation.get("interaction_round", 0),
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
            "top_roster": roster_sorted[:roster_limit] if roster_sorted else team.get("roster_summary"),
        },
        "free_agents": free_agents_sorted[:free_agent_limit],
        "draft_class": draft_sorted[:draft_limit],
        "draft_order": observation.get("draft_order", []),
        "trade_market": trade_market[:trade_limit],
        "incoming_trade_offers": observation.get("incoming_trade_offers", []),
        "waiver_wire_summary": observation.get("waiver_wire_summary"),
        "scouting_budget": observation.get("scouting_budget"),
        "available_actions": observation.get("available_actions", []),
        "action_results": observation.get("action_results"),
        "history": observation["history"],
        "memo": observation.get("memo", ""),
    }
    return payload


def build_prompt(observation: dict[str, Any]) -> str:
    compact = compact_observation(observation)
    roster = observation["team"].get("roster") or []
    fallback_lineup = position_aware_lineup(roster) if roster else []
    no_think = "/no_think\n" if os.environ.get("GM_AGENT_NO_THINK", "0") == "1" else ""
    return (
        no_think + "You are controlling a fictional hockey team in GM-Bench v2. "
        "Maximize long-term benchmark score: wins, playoffs, titles, young assets, cap health, morale, and valid decisions.\n\n"
        'Return ONLY a JSON object shaped like {"actions":[...]}. Do not use markdown. Do not explain.\n\n'
        "Core actions:\n"
        '{"type":"sign_free_agent","player_id":123,"years":1,"salary":2.5}\n'
        '{"type":"draft","prospect_id":1010001}\n'
        '{"type":"trade","partner_team_id":3,"give_player_ids":[1],"receive_player_ids":[88],'
        '"give_pick_seasons":[6],"receive_pick_seasons":[]}\n'
        '{"type":"release","player_id":1}\n'
        '{"type":"set_lineup","player_ids":[18 unique roster player ids]}\n'
        '{"type":"claim_waiver","player_id":55}\n'
        '{"type":"memo","text":"plan notes carried to your next decision"}\n'
        "Information actions (same-turn results appear in action_results on the next round):\n"
        '{"type":"inspect_team","team_id":3}\n'
        '{"type":"inspect_player","player_id":88}\n'
        '{"type":"list_free_agents","position":"F","min_overall":55,"limit":12}\n'
        '{"type":"scout","player_id":88} or {"type":"scout","prospect_id":1010001}\n'
        "Incoming trade negotiation:\n"
        '{"type":"accept_trade_offer","offer_id":"1-1"}\n'
        '{"type":"reject_trade_offer","offer_id":"1-1"}\n'
        '{"type":"counter_trade_offer","offer_id":"1-1","give_player_ids":[2],"receive_player_ids":[9]}\n'
        '{"type":"end_turn"} to finish an information-gathering round\n'
        '{"type":"noop"}\n\n'
        "Observations may be summary-tier: use inspect/list/scout before committing. "
        "Morale and injuries affect performance. Midseason has waiver claims after partial-season games. "
        "Incoming_trade_offers are opponent proposals you can accept, reject, or counter. "
        "Draft picks can be traded via give_pick_seasons/receive_pick_seasons. "
        "Lineup must be exactly 18 unique roster players with at least 10 F, 4 D, and 1 G. "
        "Use memo for multi-season plans. Review action_results before repeating failed moves.\n"
        + (
            f"If unsure, at least set this valid lineup: {json.dumps(fallback_lineup)}.\n\n"
            if fallback_lineup
            else "\n"
        )
        + f"Observation JSON:\n{json.dumps(compact, sort_keys=True)}"
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


def is_strict_mode() -> bool:
    return os.environ.get("GM_BENCH_STRICT", "0") == "1"


def fallback_actions(observation: dict[str, Any], error: str | None = None) -> list[dict[str, Any]]:
    if is_strict_mode():
        action: dict[str, Any] = {"type": "noop"}
        if error:
            action["error"] = error[:300]
        return [action]
    actions: list[dict[str, Any]] = []
    draft_class = observation.get("draft_class") or []
    if observation["phase"] == "draft" and draft_class:
        prospect = max(draft_class, key=public_asset_value)
        actions.append({"type": "draft", "prospect_id": prospect["id"]})
    roster = observation["team"].get("roster") or []
    lineup = position_aware_lineup(roster) if roster else []
    if lineup:
        actions.append({"type": "set_lineup", "player_ids": lineup})
    if not actions:
        actions.append({"type": "noop"})
    if error:
        actions[0]["model_error"] = error[:300]
    return actions


def run_agent_main(decide: Callable[[dict[str, Any]], list[dict[str, Any]]]) -> None:
    """Run once per stdin observation, or as a persistent session when GM_BENCH_SESSION=1."""
    if os.environ.get("GM_BENCH_SESSION") == "1":
        run_session_loop(decide)
        return
    observation = json.load(sys.stdin)
    print(json.dumps(decide(observation)))


def run_session_loop(decide: Callable[[dict[str, Any]], list[dict[str, Any]]]) -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        event = json.loads(line)
        event_type = event.get("event")
        if event_type == "end":
            break
        if event_type == "observation":
            print(json.dumps({"actions": decide(event["payload"])}), flush=True)
        elif event_type == "action_results":
            payload = {
                "phase": "action_results",
                "action_results": event.get("results", []),
                "interaction_round": event.get("round", 0),
            }
            print(json.dumps({"actions": decide(payload)}), flush=True)
