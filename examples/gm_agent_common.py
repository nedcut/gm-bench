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
    # Example agents run as standalone scripts (`python examples/claude_agent.py`),
    # where only examples/ is on sys.path and gm-bench is not necessarily installed.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from gm_bench.agent_utils import position_aware_lineup, public_asset_value

# decide() may return a bare action list or (actions, usage) for telemetry.
DecideResult = list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any] | None]
DecideFn = Callable[[dict[str, Any]], DecideResult]


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
    team = observation.get("team") or {}
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
        "seed": observation.get("seed"),
        "season": observation.get("season"),
        "phase": observation.get("phase"),
        "observation_tier": observation.get("observation_tier", "full"),
        "interaction_round": observation.get("interaction_round", 0),
        "rules": observation.get("rules"),
        "team": {
            "id": team.get("id"),
            "name": team.get("name"),
            "wins": team.get("wins"),
            "losses": team.get("losses"),
            "payroll": team.get("payroll"),
            "cap_room": team.get("cap_room"),
            "championships": team.get("championships"),
            "draft_picks": team.get("draft_picks"),
            "top_roster": roster_sorted[:roster_limit] if roster_sorted else team.get("roster_summary"),
        },
        "free_agents": free_agents_sorted[:free_agent_limit],
        "draft_class": draft_sorted[:draft_limit],
        "draft_order": observation.get("draft_order", []),
        "trade_market": trade_market[:trade_limit],
        "incoming_offers": observation.get("incoming_offers", [])[:3],
        "scout_reports": observation.get("scout_reports", {}),
        "waiver_wire_summary": observation.get("waiver_wire_summary"),
        "available_actions": observation.get("available_actions", []),
        "action_results": observation.get("action_results"),
        "history": observation.get("history"),
        "memo": observation.get("memo", ""),
        "hint": observation.get("hint"),
    }
    if observation.get("free_agents_summary"):
        payload["free_agents_summary"] = observation["free_agents_summary"]
    if observation.get("draft_class_summary"):
        payload["draft_class_summary"] = observation["draft_class_summary"]
    if observation.get("trade_market_summary"):
        payload["trade_market_summary"] = observation["trade_market_summary"]
    return payload


def build_prompt(observation: dict[str, Any]) -> str:
    compact = compact_observation(observation)
    roster = (observation.get("team") or {}).get("roster") or []
    fallback_lineup = position_aware_lineup(roster) if roster else []
    repair = observation.get("protocol_repair") or {}
    repair_prefix = (
        "PROTOCOL REPAIR: the previous response was invalid. Output only one valid JSON object; no prose or markdown.\n\n"
        if repair
        else ""
    )
    return repair_prefix + (
        "You are controlling a fictional hockey team in GM-Bench. "
        "Choose legal front-office actions that maximize long-term benchmark score: wins, playoffs, titles, young assets, cap health, and valid decisions.\n\n"
        'Return ONLY a JSON object shaped like {"actions":[...]}. Do not use markdown. Do not explain.\n\n'
        "Core actions:\n"
        '{"type":"sign_free_agent","player_id":123,"years":1,"salary":2.5}\n'
        '{"type":"draft","prospect_id":1010001}\n'
        '{"type":"trade","partner_team_id":3,"give_player_ids":[1],"receive_player_ids":[88],'
        '"give_pick_seasons":[],"receive_pick_seasons":[4]}\n'
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
        '{"type":"accept_trade_offer","offer_id":"offer-3-1-preseason-12-34"}\n'
        '{"type":"reject_trade_offer","offer_id":"offer-3-1-preseason-12-34"}\n'
        '{"type":"counter_trade_offer","offer_id":"offer-3-1-preseason-12-34","give_player_ids":[2],"receive_player_ids":[9]}\n'
        '{"type":"end_turn"} to finish an information-gathering round\n'
        '{"type":"noop"}\n\n'
        "Observations may be summary-tier: use inspect/list/scout before committing. "
        "Public potential ratings are noisy; scout (limited points per season, see rules.scouting) buys a "
        "near-true potential reading, echoed forever in scout_reports — most valuable before drafting or big trades.\n"
        "Opponents may send you trade offers in incoming_offers; accept, reject, or counter them. "
        "Every offer looks fair to the SENDER's private valuation — some are bargains, some dump bad contracts on you. "
        "Judge with public stats before accepting; ignoring an offer is free.\n"
        "Future draft picks are tradeable assets: give_pick_seasons/receive_pick_seasons list future season numbers "
        "(up to rules.pick_trading.max_seasons_ahead ahead; rough values in rules.pick_trading.pick_value_estimate); "
        "owned picks per season are in team.draft_picks and future picks count toward your final score.\n"
        "Midseason has waiver claims after partial-season games. "
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
        "is echoed in the observation. Review action_results before repeating failed moves. "
        "Do not invent IDs. Keep signings under cap room unless the player is clearly worth it. "
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
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError("model JSON was not an action list")
    # A well-formed but empty action list is a legitimate "do nothing this
    # window" decision, not a parse failure. Return an explicit noop so it is
    # attributed to the model, not the fallback policy. (Items that fail to
    # normalize below still raise, because that is a real formatting failure.)
    if not parsed:
        return [{"type": "noop"}]
    actions = [_normalize_action_keys(action) for action in parsed if isinstance(action, dict)]
    actions = [action for action in actions if isinstance(action.get("type"), str)]
    if not actions:
        raise ValueError("model JSON did not contain typed actions")
    return actions


# Canonical trade-field name -> natural-but-wrong names models emit for it.
# Aliasing is a pure key rename (see _normalize_action_keys): it never resolves
# names to ids or invents content, so an unrepairable payload stays illegal.
_TRADE_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "partner_team_id": ("team_id", "target_team_id", "opponent_team_id", "destination_team_id"),
    "give_player_ids": ("players_to_send", "offered_players", "players_offered"),
    "receive_player_ids": ("players_to_acquire", "requested_players", "players_requested"),
}


def _normalize_action_keys(action: dict[str, Any]) -> dict[str, Any]:
    """Mechanical key repair only: accept common aliases for canonical keys.

    Small local models often emit {"action": "draft", ...} or
    {"action_type": "draft", ...}, and phrase trade fields naturally
    ({"players_to_send": [...]}) instead of the schema's give_player_ids.
    Renaming the key preserves the model's decision verbatim; semantic mistakes
    (an unknown action type, a bad id) still flow through to the simulator and
    are penalized as the model's own errors. Aliases only apply when the
    canonical key is absent/null/empty, and the stale key is dropped.
    """
    for alias in ("action", "action_type"):
        if "type" not in action and isinstance(action.get(alias), str):
            renamed = dict(action)
            renamed["type"] = renamed.pop(alias)
            action = renamed
    for canonical, aliases in _TRADE_KEY_ALIASES.items():
        if _has_usable_value(action.get(canonical)):
            continue
        for alias in aliases:
            if _has_usable_value(action.get(alias)):
                renamed = dict(action)
                renamed[canonical] = renamed.pop(alias)
                action = renamed
                break
    return action


def _has_usable_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str | list | tuple | dict | set) and not value:
        return False
    return True


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


def resolve_call_timeout(env_var: str, default: float, margin: float = 15.0) -> float:
    """Resolve the per-call backend timeout for an adapter.

    An explicit adapter env var (e.g. ``OLLAMA_TIMEOUT``) always wins. Otherwise
    derive it from the harness decision budget (``GM_BENCH_AGENT_TIMEOUT``,
    exported by the runner) minus a margin, so a slow backend call fails inside
    the adapter — which can still emit a fallback envelope with usage — instead
    of the harness killing the process and recording nothing.
    """
    raw = os.environ.get(env_var)
    if raw is not None:
        try:
            return float(raw)
        except ValueError:
            pass
    budget = os.environ.get("GM_BENCH_AGENT_TIMEOUT")
    if budget is not None:
        try:
            return max(30.0, float(budget) - margin)
        except ValueError:
            pass
    return default


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
    """Print a consistent response envelope for one-shot and session adapters."""
    print(json.dumps({"actions": actions, "usage": usage}), flush=True)


def _unpack_decide_result(result: DecideResult) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, None


def run_agent_main(decide: DecideFn) -> None:
    """Run once per stdin observation, or as a persistent session when GM_BENCH_SESSION=1."""
    if os.environ.get("GM_BENCH_SESSION") == "1":
        run_session_loop(decide)
        return
    observation = json.load(sys.stdin)
    actions, usage = _unpack_decide_result(decide(observation))
    emit(actions, usage)


def run_session_loop(decide: DecideFn) -> None:
    """Line-delimited JSON session: start / observation / action_results / end."""
    for line in sys.stdin:
        if not line.strip():
            continue
        event = json.loads(line)
        event_type = event.get("event")
        if event_type == "end":
            break
        if event_type == "start":
            continue
        if event_type == "observation":
            actions, usage = _unpack_decide_result(decide(event["payload"]))
            emit(actions, usage)
        elif event_type == "action_results":
            payload = {
                "phase": "action_results",
                "action_results": event.get("results", []),
                "interaction_round": event.get("round", 0),
            }
            actions, usage = _unpack_decide_result(decide(payload))
            emit(actions, usage)


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
    draft_class = observation.get("draft_class") or []
    if observation.get("phase") == "draft" and draft_class:
        prospect = max(draft_class, key=public_asset_value)
        actions.append({"type": "draft", "prospect_id": prospect["id"]})
    roster = (observation.get("team") or {}).get("roster") or []
    lineup = position_aware_lineup(roster) if roster else []
    if lineup:
        actions.append({"type": "set_lineup", "player_ids": lineup})
    if not actions:
        actions.append({"type": "noop"})
    actions[0]["model_error"] = marker
    return actions
