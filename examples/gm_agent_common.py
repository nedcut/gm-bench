"""Shared helpers for model-backed GM-Bench example agents."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    from gm_bench.agent_utils import position_aware_lineup, public_asset_value
except ModuleNotFoundError:
    # Example agents run as standalone scripts (`python examples/claude_agent.py`),
    # where only examples/ is on sys.path and gm-bench is not necessarily installed.
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
        "draft_order": observation.get("draft_order", []),
        "trade_market": observation["trade_market"][:trade_limit],
        "incoming_offers": observation.get("incoming_offers", [])[:3],
        "scout_reports": observation.get("scout_reports", {}),
        "history": observation["history"],
        "memo": observation.get("memo", ""),
    }


def build_prompt(observation: dict[str, Any]) -> str:
    compact = compact_observation(observation)
    fallback_lineup = position_aware_lineup(observation["team"]["roster"])
    no_think = "/no_think\n" if os.environ.get("GM_AGENT_NO_THINK", "0") == "1" else ""
    return (
        no_think + "You are controlling a fictional hockey team in GM-Bench. "
        "Choose legal front-office actions that maximize long-term benchmark score: wins, playoffs, titles, young assets, cap health, and valid decisions.\n\n"
        'Return ONLY a JSON object shaped like {"actions":[...]}. Do not use markdown. Do not explain.\n\n'
        "Allowed action objects inside actions:\n"
        '{"type":"sign_free_agent","player_id":123,"years":1,"salary":2.5}\n'
        '{"type":"draft","prospect_id":1010001}\n'
        '{"type":"trade","partner_team_id":3,"give_player_ids":[1],"receive_player_ids":[88],"give_pick_seasons":[],"receive_pick_seasons":[4]}\n'
        '{"type":"accept_offer","offer_id":"offer-3-1-preseason-12-34"}\n'
        '{"type":"decline_offer","offer_id":"offer-3-1-preseason-12-34"}\n'
        '{"type":"release","player_id":1}\n'
        '{"type":"scout","player_id":1010001}\n'
        '{"type":"set_lineup","player_ids":[18 unique roster player ids]}\n'
        '{"type":"memo","text":"plan notes carried to your next decision"}\n'
        '{"type":"noop"}\n\n'
        "Public potential ratings are noisy; scout (limited points per season, see rules.scouting) buys a "
        "near-true potential reading, echoed forever in scout_reports — most valuable before drafting or big trades.\n"
        "Opponents may send you trade offers in incoming_offers; each is valid only for this decision point. "
        "Every offer looks fair to the SENDER's private valuation — some are bargains, some dump bad contracts on you. "
        "Judge with public stats before accepting; ignoring an offer is free.\n"
        "Future draft picks are tradeable assets: give_pick_seasons/receive_pick_seasons list future season numbers "
        "(up to rules.pick_trading.max_seasons_ahead ahead; rough values in rules.pick_trading.pick_value_estimate); "
        "owned picks per season are in team.draft_picks and future picks count toward your final score.\n"
        "Constraints: lineup must include exactly 18 unique current roster players with at least 10 F, 4 D, and 1 G. "
        "Only players in the lineup develop at full speed; the lineup also sets team strength. "
        "Trades: partners privately re-value players, accept at most trade_limit_per_partner trades per season, "
        "and rosters cannot drop below roster_min. Declined trade offers and free-agent lowballs cost no penalty, "
        "but after rejected_offer_limit_per_window declines a counterparty stops negotiating until your next "
        "decision window. Free agents accept offers down to a hidden reservation within fa_reservation_range of "
        "their ask; offering the full ask always works. Opponents draft in inverse-standings order, so top prospects "
        "may be gone before your pick. Opponent teams also sign free agents after every phase and trade among "
        "themselves at the deadline, so a free agent visible now may be gone at your next decision. "
        "Use the memo action to carry multi-season plans forward; your last memo "
        "is echoed in the observation. Do not invent IDs. Keep signings under cap room unless the player is clearly worth it. "
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
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError("model JSON was not an action list")
    actions = [_normalize_action_keys(action) for action in parsed if isinstance(action, dict)]
    actions = [action for action in actions if isinstance(action.get("type"), str)]
    if not actions:
        raise ValueError("model JSON did not contain typed actions")
    return actions


def _normalize_action_keys(action: dict[str, Any]) -> dict[str, Any]:
    """Mechanical key repair only: accept "action" as an alias for "type".

    Small local models often emit {"action": "draft", ...}. Renaming the key
    preserves the model's decision verbatim; semantic mistakes (an unknown
    action type, a bad id) still flow through to the simulator and are
    penalized as the model's own errors.
    """
    if "type" not in action and isinstance(action.get("action"), str):
        action = {**action, "type": action.pop("action")}
    return action


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


def make_usage(
    *,
    provider: str | None = None,
    model: str | None = None,
    api_calls: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    api_latency_ms: float | None = None,
    cost_usd: float | None = None,
) -> dict[str, Any] | None:
    """Build a usage block for the stdout envelope, dropping unknown fields.

    Report only what the backend actually returned — a missing token count is
    recorded as absent, never zero, so the harness can distinguish "free" from
    "unmeasured".
    """
    usage = {
        "provider": provider,
        "model": model,
        "api_calls": api_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "api_latency_ms": api_latency_ms,
        "cost_usd": cost_usd,
    }
    cleaned = {key: value for key, value in usage.items() if value is not None}
    return cleaned or None


def emit(actions: list[dict[str, Any]], usage: dict[str, Any] | None = None) -> None:
    """Print the adapter response: bare list without usage, envelope with it."""
    if usage:
        print(json.dumps({"actions": actions, "usage": usage}))
    else:
        print(json.dumps(actions))


def fallback_actions(observation: dict[str, Any], error: str | None = None) -> list[dict[str, Any]]:
    """Actions substituted when the model produced no usable output.

    The first action always carries a `model_error` marker so the runner can
    count the decision as failed instead of crediting the fallback policy to
    the model. With GM_AGENT_STRICT=1 the fallback is a pure noop, so the
    score reflects only what the model itself produced.
    """
    marker = (error or "model produced no usable actions")[:300]
    if os.environ.get("GM_AGENT_STRICT", "0") == "1":
        return [{"type": "noop", "model_error": marker}]
    actions: list[dict[str, Any]] = []
    if observation["phase"] == "draft" and observation["draft_class"]:
        prospect = max(observation["draft_class"], key=public_asset_value)
        actions.append({"type": "draft", "prospect_id": prospect["id"]})
    lineup = position_aware_lineup(observation["team"]["roster"])
    if lineup:
        actions.append({"type": "set_lineup", "player_ids": lineup})
    if not actions:
        actions.append({"type": "noop"})
    actions[0]["model_error"] = marker
    return actions
