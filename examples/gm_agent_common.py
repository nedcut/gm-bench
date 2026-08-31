"""Shared helpers for model-backed GM-Bench example agents."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

# Example agents run as standalone scripts (`python examples/claude_agent.py`),
# where only examples/ is initially on sys.path. Prefer this checkout's package
# before importing any gm_bench submodule; retrying after a partial import can
# leave an older installed `gm_bench` package cached with the wrong __path__.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[1]
if (_CHECKOUT_ROOT / "gm_bench").is_dir() and str(_CHECKOUT_ROOT) not in sys.path:
    sys.path.insert(0, str(_CHECKOUT_ROOT))

from gm_bench.agent_utils import position_aware_lineup, public_asset_value  # noqa: E402
from gm_bench.repair import RAW_TEXT_FIELD  # noqa: E402
from gm_bench.scaffold_view import compact_observation, scaffold_fallback_lineup  # noqa: E402

# compact_observation/scaffold_fallback_lineup are re-exported rather than
# defined here: the scaffold-view baseline in gm_bench.agents is scored on the
# same payload, and two copies of the truncation rules would drift.

# decide() returns the model's raw reply text, or a bare action list when the
# adapter itself failed before the model answered, optionally paired with usage
# for telemetry. Adapters never parse or repair the model's text: the published
# rules in gm_bench/repair.py are the only ones that decide what a reply means,
# so the recorded malformed rate is the model's own formatting record.
DecideResult = (
    str | list[dict[str, Any]] | tuple[str, dict[str, Any] | None] | tuple[list[dict[str, Any]], dict[str, Any] | None]
)
DecideFn = Callable[[dict[str, Any]], DecideResult]


_ACTION_EXAMPLES: tuple[tuple[str, str, str], ...] = (
    ("Core actions", "sign_free_agent", '{"type":"sign_free_agent","player_id":123,"years":1,"salary":2.5}'),
    ("Core actions", "extend_contract", '{"type":"extend_contract","player_id":11,"years":4,"salary":5.8}'),
    ("Core actions", "draft", '{"type":"draft","prospect_id":1010001}'),
    (
        "Core actions",
        "trade",
        '{"type":"trade","partner_team_id":3,"give_player_ids":[1],"receive_player_ids":[88],'
        '"give_pick_seasons":[],"receive_pick_seasons":[4]}',
    ),
    ("Core actions", "release", '{"type":"release","player_id":1}'),
    ("Core actions", "set_lineup", '{"type":"set_lineup","player_ids":[18 unique roster player ids]}'),
    ("Core actions", "claim_waiver", '{"type":"claim_waiver","player_id":55}'),
    ("Core actions", "memo", '{"type":"memo","text":"plan notes carried to your next decision"}'),
    (
        "Scouting (the one query whose answer survives to your next decision)",
        "scout",
        '{"type":"scout","player_id":88} or {"type":"scout","prospect_id":1010001}',
    ),
    (
        "Incoming trade negotiation",
        "accept_trade_offer",
        '{"type":"accept_trade_offer","offer_id":"offer-3-1-trade_deadline-12-34"}',
    ),
    (
        "Incoming trade negotiation",
        "reject_trade_offer",
        '{"type":"reject_trade_offer","offer_id":"offer-3-1-trade_deadline-12-34"}',
    ),
    (
        "Incoming trade negotiation",
        "counter_trade_offer",
        '{"type":"counter_trade_offer","offer_id":"offer-3-1-trade_deadline-12-34",'
        '"give_player_ids":[2],"receive_player_ids":[9]}',
    ),
    ("Control actions", "noop", '{"type":"noop"}'),
)
# inspect_team, inspect_player, list_free_agents and end_turn stay legal in the
# simulator (the scripted multi-round lane uses them) but are deliberately not
# advertised here. A model gets one call per decision phase, so a query's answer
# is never returned to it, and end_turn only cuts its own batch short.


def _current_pick_count(compact: dict[str, Any]) -> int:
    season = compact.get("season")
    picks = (compact.get("team") or {}).get("draft_picks") or {}
    value = picks.get(season, picks.get(str(season), 0))
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _render_action_guide(compact: dict[str, Any]) -> str:
    available = [str(value) for value in compact.get("available_actions") or []]
    available_set = set(available)
    phase = compact.get("phase")
    season = compact.get("season")
    lines = [
        f"CURRENT DECISION: season {season}, phase {phase}.",
        "Emit only action types listed in available_actions for this decision; any other action type is illegal.",
        f"available_actions: {json.dumps(available)}",
        "Examples below show JSON shape only; use IDs from the current observation and never copy placeholder IDs.",
    ]
    if "draft" in available_set:
        pick_count = _current_pick_count(compact)
        noun = "action" if pick_count == 1 else "actions"
        lines.append(
            f"You own {pick_count} current-season draft pick(s); emit at most {pick_count} draft {noun} in this "
            "decision. Any draft action beyond that is refused and counts against you."
        )
    lines.append("")

    current_section: str | None = None
    for section, action_type, example in _ACTION_EXAMPLES:
        if action_type not in available_set:
            continue
        if section != current_section:
            lines.append(f"{section} available now:")
            current_section = section
        lines.append(example)
    return "\n".join(lines) + "\n\n"


def build_prompt(observation: dict[str, Any]) -> str:
    compact = compact_observation(observation)
    fallback_lineup = scaffold_fallback_lineup(observation)
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
        + _render_action_guide(compact)
        + "This is your only call this phase. Your actions are applied as one batch and the phase then advances, "
        "so you never see their results: the observation below is everything you get. Asking a question instead of "
        "acting (inspect_team, inspect_player, list_free_agents) spends the decision and answers nothing.\n"
        "The one query worth making is scout: public potential ratings are noisy, and a scout report (limited "
        "points per season, see rules.scouting) is stored in scout_reports and readable at every later decision, "
        "so it pays before a draft or a big trade.\n"
        "Opponents may send you trade offers in incoming_offers; accept, reject, or counter them. "
        "Every offer looks fair to the SENDER's private valuation — some are bargains, some dump bad contracts on you. "
        "Judge with public stats before accepting; ignoring an offer is free.\n"
        "Future draft picks are tradeable assets: give_pick_seasons/receive_pick_seasons list future season numbers "
        "(up to rules.pick_trading.max_seasons_ahead ahead; rough values in rules.pick_trading.pick_value_estimate); "
        "your own counts from this season onward are in team.draft_picks, every team's acquisitions and departures "
        "are in the standings pick_holdings column, and future picks count toward your final score.\n"
        "Midseason has waiver claims after partial-season games. "
        "Constraints: lineup must include exactly 18 unique current roster players with at least 10 F, 4 D, and 1 G. "
        "Only players in the lineup develop at full speed; the lineup also sets team strength. "
        "Trades: partners privately re-value players, accept at most trade_limit_per_partner trades per season, "
        "and rosters cannot drop below roster_min. Declined trade offers and free-agent lowballs cost no penalty, "
        "but after rejected_offer_limit_per_window declines a counterparty stops negotiating until your next "
        "decision window. Free agents accept offers down to a hidden reservation within fa_reservation_range of "
        "their ask; offering the full ask always works. "
        "A free agent's contract_quotes column prices each 1-5 year term in order; salaries and the cap inflate "
        "annually, while longer terms cost a premium. In preseason, a final-year incumbent you may extend shows "
        "extension_quotes: four prices for 2-, 3-, 4- and 5-year terms. A roster row's release_dead_cap reads "
        "'per-season x seasons=total' — the exact charge for releasing that contract now; charges already retained "
        "from past releases are in team.dead_cap. "
        "Draft order is set by the lottery in draft_lottery once it is drawn, and projected by "
        "draft_order_inverse_standings before that; teams picking ahead of you take top prospects first. "
        "Opponent teams also sign free agents after every phase and trade among "
        "themselves at the deadline, so a free agent visible now may be gone at your next decision. "
        "Use the memo action to carry multi-season plans forward; your last memo "
        "is echoed in the observation. recent_transactions rows marked REJECTED: are your own refused moves with "
        "the reason they failed — do not repeat them. "
        "Do not invent IDs. Keep signings under cap room unless the player is clearly worth it. "
        + (
            f"If unsure, at least set this valid lineup: {json.dumps(fallback_lineup)}.\n\n"
            if fallback_lineup
            else "\n"
        )
        + f"Observation JSON:\n{json.dumps(compact, sort_keys=True)}"
    )


def strip_terminal_codes(text: str) -> str:
    """Remove terminal escape sequences and C0 control bytes from a reply.

    Transport hygiene, not repair: CLI harnesses colour and reposition their
    stdout, and a raw control byte is not legal inside a JSON string, so leaving
    them in would record a terminal artifact as the model's formatting error.
    Tabs, newlines and carriage returns are preserved.
    """

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


def emit(response: Any, usage: dict[str, Any] | None = None) -> None:
    """Print a consistent response envelope for one-shot and session adapters.

    A list is an adapter-produced action list, used only when the adapter
    failed before the model answered (no key, transport error) and therefore
    has no model text to forward. Anything else is the model's reply, forwarded
    verbatim in ``raw_text`` for the harness's published repair rules to judge
    — including a backend that returned no text at all, which is a malformed
    decision the model owns and not something the adapter may paper over.
    """
    if isinstance(response, list):
        payload: dict[str, Any] = {"actions": response, "usage": usage}
    else:
        text = response if isinstance(response, str) else json.dumps(response)
        payload = {RAW_TEXT_FIELD: strip_terminal_codes(text), "usage": usage}
    print(json.dumps(payload), flush=True)


def _unpack_decide_result(result: DecideResult) -> tuple[str | list[dict[str, Any]], dict[str, Any] | None]:
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
    the model. Strict handling is the default: the fallback is a pure noop, so
    the score reflects only what the model itself produced. Set
    GM_AGENT_STRICT=0 to opt into the legacy soft fallback, which substitutes
    host-chosen draft and lineup moves and is not publishable.
    """
    marker = (error or "model produced no usable actions")[:300]
    if os.environ.get("GM_AGENT_STRICT", "1") == "1":
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
