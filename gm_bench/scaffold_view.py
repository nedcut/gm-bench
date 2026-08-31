"""The observation view model adapters receive.

The prompt scaffold in ``examples/gm_agent_common.py`` does not hand a model
the observation the simulator emits: it sorts, truncates, renames, and drops
fields before serializing. That compaction lives here, in the package, for two
reasons. It is imported by ``examples/gm_agent_common.py`` so adapters keep
using it verbatim, and it is imported by the ``scaffold-view`` baseline in
``gm_bench.agents`` so a registered agent can be measured on exactly the view
models see. A second copy would make the measured gap a statement about a
scaffold nobody runs the moment either copy changed.

Two shapes are built from one selection. ``compact_observation`` renders the
selection as pipe-delimited rows, because the v6 budget is ~6,500 prompt tokens
against an 8,000 ceiling and per-field JSON keys repeated across ~70 player
records cost more than the records themselves. ``scaffold_view_observation``
returns the same selection as Python objects so a scripted policy can read it.
Neither shape may carry information the other lacks: the truncation limits and
the field set both come from ``_select``.
"""

from __future__ import annotations

import os
from typing import Any

from gm_bench.agent_utils import position_aware_lineup, public_asset_value

# Truncation limits per profile: roster, free agents, draft class, trade market,
# waiver wire. "compact" is the v6 benchmark lane and matches the spec's budget
# (~10 free agents, 8 prospects, 6 trade offers). "tiny" is the degraded-view
# diagnostic. Every list is cut by a stated, published rule -- roster by overall,
# candidate lists by public asset value -- so every model is truncated
# identically and knows it was truncated.
_LIMITS: dict[str, dict[str, int]] = {
    "compact": {"roster": 26, "free_agents": 10, "draft_class": 8, "trade_market": 6, "waiver_wire": 4},
    "tiny": {"roster": 18, "free_agents": 6, "draft_class": 6, "trade_market": 0, "waiver_wire": 3},
}

# Rows of echoed query answers kept in ``action_results``. One batch may send 24
# information actions, each answering with whole player records, so this is the
# one part of the view an agent could otherwise inflate past the token ceiling
# on its own.
_ACTION_RESULT_ROW_BUDGET = 14
# Characters of a single action argument echoed back beside its result.
_ARGUMENT_ECHO_CHARS = 80

_ROSTER_COLUMNS = "id|name|pos|age|overall|potential|salary|contract_years|injury_risk%|release_dead_cap(per season x seasons=total)|extension_quotes(1y..5y)"
_FREE_AGENT_COLUMNS = (
    "id|name|pos|age|overall|potential|injury_risk%|contract_quotes(1y..5y; the 1y quote is his "
    "asking_salary, already multiplied by quote_multiplier)|"
    "signing_appeal(projected_role,quote_multiplier,win_sensitivity)|flags"
)
_WAIVER_COLUMNS = "id|name|pos|age|overall|potential|injury_risk%|claim_cost(1 year)|flags"
_DRAFT_COLUMNS = "id|name|pos|age|overall|potential|injury_risk%|scouted_potential"
_TRADE_COLUMNS = "team_id|team_name|estimated_price|player: " + _DRAFT_COLUMNS.replace(
    "|scouted_potential", "|salary|contract_years"
)
_STANDINGS_COLUMNS = "team_id|team_name|wins-losses|championships|public_strength|pick_holdings(+acquired/-traded away)"
_HISTORY_COLUMNS = "season|wins-losses|playoff_rounds|champion_team_id|payroll|cap_room|score_after_season"
_LEDGER_COLUMNS = "season|phase|team|move"


def model_adapter_observation(observation: dict[str, Any]) -> dict[str, Any]:
    """Return the raw adapter payload with private run identity removed.

    The runner retains the seed for deterministic simulation, paired analysis,
    replay, and artifacts. External adapters do not need it to choose legal
    actions, however, and exposing it would let adapter code reconstruct hidden
    simulator state from the public generator. Use a shallow copy so removing
    the transport-only field never mutates the runner's canonical observation.
    """
    return {key: value for key, value in observation.items() if key != "seed"}


def _resolve_profile(profile: str | None) -> str:
    if profile is None:
        profile = os.environ.get("GM_AGENT_PROFILE", "compact")
    return profile if profile in _LIMITS else "compact"


def _players(candidates: Any) -> list[dict[str, Any]]:
    if not isinstance(candidates, list):
        return []
    return [player for player in candidates if isinstance(player, dict) and "overall" in player]


def _select(observation: dict[str, Any], profile: str | None) -> dict[str, Any]:
    """Sort and truncate the observation's lists once, for both output shapes.

    ``profile`` selects the truncation limits. Adapters leave it None and
    inherit ``GM_AGENT_PROFILE`` from the subprocess environment the harness
    pins. In-process callers (the ``scaffold-view`` baseline) must pass it
    explicitly: they run in the parent process, where that variable reflects the
    operator's shell rather than the lane, so inheriting it would let an ambient
    value silently decide which view was measured.
    """
    limits = _LIMITS[_resolve_profile(profile)]
    team = observation.get("team") or {}
    roster = sorted(_players(team.get("roster")), key=lambda player: player["overall"], reverse=True)

    def candidates(key: str, summary_key: str) -> list[dict[str, Any]]:
        items = observation.get(key) or []
        if not items and observation.get(summary_key):
            # Summary-tier observations publish ids only; keep them so the model
            # still knows who to inspect.
            return [{"id": player_id} for player_id in observation[summary_key].get("top_ids", [])][: limits[key]]
        return sorted(_players(items), key=public_asset_value, reverse=True)[: limits[key]]

    trade_market = observation.get("trade_market") or []
    trade_offers = [
        offer for offer in trade_market if isinstance(offer, dict) and isinstance(offer.get("player"), dict)
    ]
    trade_offers.sort(key=lambda offer: public_asset_value(offer["player"]), reverse=True)
    return {
        "limits": limits,
        "team": team,
        "roster": roster[: limits["roster"]],
        "roster_total": len(roster),
        "free_agents": candidates("free_agents", "free_agents_summary"),
        "free_agents_total": len(_players(observation.get("free_agents")))
        or _summary_count(observation, "free_agents_summary"),
        "draft_class": candidates("draft_class", "draft_class_summary"),
        "draft_class_total": len(_players(observation.get("draft_class")))
        or _summary_count(observation, "draft_class_summary"),
        "trade_market": trade_offers[: limits["trade_market"]],
        "trade_market_total": len(trade_offers) or _summary_count(observation, "trade_market_summary"),
        "waiver_wire": sorted(_players(observation.get("waiver_wire")), key=public_asset_value, reverse=True)[
            : limits["waiver_wire"]
        ],
        "incoming_offers": [offer for offer in (observation.get("incoming_offers") or []) if isinstance(offer, dict)][
            :3
        ],
    }


def _summary_count(observation: dict[str, Any], key: str) -> int:
    summary = observation.get(key)
    return int(summary.get("count", 0)) if isinstance(summary, dict) else 0


def _num(value: Any) -> str:
    """Render a number without trailing zeros, and non-numbers as a dash."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "-"
    rounded = round(float(value), 2)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


def _pct(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "-"
    return str(round(float(value) * 100))


def _position(player: dict[str, Any]) -> str:
    position = str(player.get("position", "?"))
    sub_position = player.get("sub_position")
    return f"{position}/{sub_position}" if sub_position else position


def _quotes(quotes: Any) -> str:
    """Render a 1-5 year price table as a slash-joined series."""
    if not isinstance(quotes, dict) or not quotes:
        return "-"
    return "/".join(_num(quotes[key]) for key in sorted(quotes, key=lambda item: int(item)))


def _dead_cap(charge: Any) -> str:
    """Render a release charge as "per-season x seasons (total)".

    The simulator books one flat charge per retained season, so listing the
    seasons out one by one repeats the same number; the compressed form keeps
    both halves a cap plan needs -- what it costs each season and in total.
    """
    if not isinstance(charge, dict):
        return "-"
    by_season = charge.get("by_season") or {}
    if not by_season:
        return _num(charge.get("total"))
    seasons = sorted(by_season, key=lambda item: int(item))
    amounts = {_num(by_season[season]) for season in seasons}
    total = _num(charge.get("total"))
    if len(amounts) == 1:
        return f"{amounts.pop()}x{len(seasons)}s={total}"
    return f"{'+'.join(f'S{season}:{_num(by_season[season])}' for season in seasons)}={total}"


def _player_core(player: dict[str, Any]) -> list[str]:
    """The id/name/position/age/overall/potential/injury columns every table shares."""
    return [
        _num(player.get("id")),
        str(player.get("name", "?")),
        _position(player),
        _num(player.get("age")),
        _num(player.get("overall")),
        _num(player.get("potential")),
        _pct(player.get("injury_risk")),
    ]


def _roster_rows(roster: list[dict[str, Any]]) -> list[str]:
    rows = []
    for player in roster:
        core = _player_core(player)
        rows.append(
            "|".join(
                core[:6]
                + [
                    _num(player.get("salary")),
                    _num(player.get("contract_years")),
                    core[6],
                    _dead_cap(player.get("release_dead_cap")),
                    _quotes(player.get("extension_quotes")),
                ]
            )
        )
    return rows


def _free_agent_rows(free_agents: list[dict[str, Any]]) -> list[str]:
    rows = []
    for player in free_agents:
        appeal = player.get("signing_appeal") or {}
        flags = "resign_blocked" if player.get("resign_blocked") else ""
        rows.append(
            "|".join(
                [
                    "|".join(_player_core(player)),
                    _quotes(player.get("contract_quotes")),
                    f"{appeal.get('projected_role', '-')},x{_num(appeal.get('quote_multiplier'))},"
                    f"sens{_num(appeal.get('win_sensitivity'))}",
                    flags,
                ]
            )
        )
    return rows


def _waiver_rows(players: list[dict[str, Any]]) -> list[str]:
    """Waiver claims are one-year, take-it-or-leave-it: one price, no term table."""
    return [
        "|".join(
            _player_core(player)
            + [
                _num(player.get("asking_salary")),
                "resign_blocked" if player.get("resign_blocked") else "",
            ]
        )
        for player in players
    ]


def _draft_rows(prospects: list[dict[str, Any]], scout_reports: dict[str, Any]) -> list[str]:
    return [
        "|".join(_player_core(prospect) + [_num(scout_reports.get(str(prospect.get("id"))))]) for prospect in prospects
    ]


def _trade_rows(offers: list[dict[str, Any]]) -> list[str]:
    rows = []
    for offer in offers:
        player = offer["player"]
        rows.append(
            "|".join(
                [
                    f"T{_num(offer.get('team_id'))}",
                    str(offer.get("team_name", "?")),
                    _num(offer.get("estimated_price")),
                    "|".join(_player_core(player)),
                    _num(player.get("salary")),
                    _num(player.get("contract_years")),
                ]
            )
        )
    return rows


def _offer_side(players: Any, pick_seasons: Any) -> str:
    parts = [
        f"{_num(player.get('id'))} {player.get('name', '?')} {_position(player)} "
        f"ovr{_num(player.get('overall'))} pot{_num(player.get('potential'))} "
        f"{_num(player.get('salary'))}x{_num(player.get('contract_years'))}y"
        for player in players or []
        if isinstance(player, dict)
    ]
    parts += [f"S{_num(season)} pick" for season in pick_seasons or []]
    return "; ".join(parts) if parts else "nothing"


def _offer_rows(offers: list[dict[str, Any]]) -> list[str]:
    return [
        f"{offer.get('offer_id')} from T{_num(offer.get('team_id'))} {offer.get('team_name', '?')} "
        f"|| you receive: {_offer_side(offer.get('you_receive_players'), offer.get('you_receive_pick_seasons'))} "
        f"|| they receive: {_offer_side(offer.get('they_receive_players'), offer.get('they_receive_pick_seasons'))} "
        f"|| expires: {offer.get('expires', 'this decision point')}"
        for offer in offers
    ]


def _pick_holdings(team_id: Any, holdings: Any) -> str:
    """Summarize a team's picks as departures from "its own pick every season".

    Twelve teams times seven seasons of "team N owns team N's pick" is pure
    redundancy; what a trade partner needs is which picks were acquired and
    which were traded away.
    """
    if not isinstance(holdings, dict) or not holdings:
        return "own"
    notes = []
    for season in sorted(holdings, key=lambda item: int(item)):
        origins = list(holdings[season] or [])
        extras = [origin for origin in origins if origin != team_id]
        notes += [f"+S{season}(T{origin})" for origin in extras]
        if team_id not in origins:
            notes.append(f"-S{season}")
    return " ".join(notes) if notes else "own"


def _standings_rows(standings: Any) -> list[str]:
    rows = []
    for team in standings or []:
        if not isinstance(team, dict):
            continue
        rows.append(
            "|".join(
                [
                    f"T{_num(team.get('team_id'))}",
                    str(team.get("team_name", "?")),
                    f"{_num(team.get('wins'))}-{_num(team.get('losses'))}",
                    _num(team.get("championships")),
                    _num(team.get("public_strength")),
                    _pick_holdings(team.get("team_id"), team.get("pick_origins")),
                ]
            )
        )
    return rows


def _history_rows(history: Any) -> list[str]:
    rows = []
    for summary in history or []:
        if not isinstance(summary, dict):
            continue
        rows.append(
            "|".join(
                [
                    f"S{_num(summary.get('season'))}",
                    f"{_num(summary.get('wins'))}-{_num(summary.get('losses'))}",
                    f"playoff_rounds {_num(summary.get('playoff_rounds'))}",
                    f"champion T{_num(summary.get('champion_team_id'))}",
                    f"payroll {_num(summary.get('payroll'))}",
                    f"cap_room {_num(summary.get('cap_room'))}",
                    f"score {_num(summary.get('score_after_season'))}",
                ]
            )
        )
    return rows


def _ledger_rows(transactions: Any, user_team_id: Any) -> list[str]:
    rows = []
    for transaction in transactions or []:
        if not isinstance(transaction, dict):
            continue
        actor = "YOU" if transaction.get("team_id") == user_team_id else f"T{_num(transaction.get('team_id'))}"
        rows.append(
            f"S{_num(transaction.get('season'))}|{transaction.get('phase', '?')}|{actor}|{transaction.get('message', '')}"
        )
    return rows


def _action_result_rows(results: Any, scout_reports: dict[str, Any]) -> list[str]:
    """Render one interaction round's results, with a hard row budget.

    An information action answers with whole player records -- ``inspect_team``
    returns a full opponent roster, ``list_free_agents`` up to 24 free-agent
    cards -- and up to 24 actions may be sent in one batch. Echoed verbatim that
    is several times the entire observation budget, so the attached records are
    rendered as the same rows the rest of the view uses and cut off at
    ``_ACTION_RESULT_ROW_BUDGET``. The cut is announced, the outcome line of
    every result is always kept, and results are served in order, so a model
    that asks one question at a time always sees its full answer.
    """
    rows: list[str] = []
    budget = _ACTION_RESULT_ROW_BUDGET
    dropped = 0
    for result in results or []:
        if not isinstance(result, dict):
            continue
        action = result.get("action") if isinstance(result.get("action"), dict) else {}
        arguments = " ".join(f"{key}={_compact_argument(value)}" for key, value in action.items() if key != "type")
        outcome = "ok" if result.get("accepted") else "REJECTED"
        rows.append(f"{outcome}|{action.get('type', '?')} {arguments}|{result.get('message', '')}".rstrip())
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        for kind, renderer in (
            ("team", lambda team: [_inspected_team_line(team)]),
            ("free_agents", lambda players: _free_agent_rows(_players(players))),
            ("roster", lambda players: _roster_rows(_players(players))),
            ("player", lambda player: _roster_rows(_players([player]))),
        ):
            if kind not in data:
                continue
            attached = renderer(data[kind])
            room = max(0, budget - len(rows))
            rows += [f"  {row}" for row in attached[:room]]
            dropped += len(attached) - min(room, len(attached))
        if len(rows) >= budget:
            break
    if dropped:
        rows.append(f"({dropped} further result rows omitted; the observation caps echoed query results)")
    return rows


def _inspected_team_line(team: Any) -> str:
    if not isinstance(team, dict):
        return "-"
    return (
        f"  T{_num(team.get('id'))} {team.get('name', '?')} {_num(team.get('wins'))}-{_num(team.get('losses'))} "
        f"championships {_num(team.get('championships'))} payroll {_num(team.get('payroll'))} "
        f"cap_room {_num(team.get('cap_room'))} "
        f"picks {_pick_holdings(team.get('id'), team.get('pick_origins'))}"
    ).strip()


def _compact_argument(value: Any) -> str:
    """Echo an argument back at bounded length.

    The echo exists so a model can tell which of several identical-looking
    actions a result belongs to. A memo action carries the full 2,000-character
    notebook, which the observation already publishes once under ``memo``, so
    long values are cut rather than repeated.
    """
    if isinstance(value, list):
        rendered = ",".join(_num(item) if isinstance(item, (int, float)) else str(item) for item in value) or "-"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        rendered = _num(value)
    else:
        rendered = str(value)
    return rendered if len(rendered) <= _ARGUMENT_ECHO_CHARS else rendered[:_ARGUMENT_ECHO_CHARS] + "..."


def _pick_rows(picks: Any) -> list[str]:
    rows = []
    for pick in picks or []:
        if not isinstance(pick, dict):
            continue
        rows.append(
            f"S{_num(pick.get('season'))} from T{_num(pick.get('from_team_id'))} "
            f"{pick.get('from_team_name', '?')} (projected slot {_num(pick.get('projected_slot'))})"
        )
    return rows


def _lottery_text(lottery: Any) -> str:
    if not isinstance(lottery, dict) or not lottery:
        return "not published this phase"
    weights = "/".join(_num(weight) for weight in lottery.get("weights_worst_first") or [])
    slots = " ".join(
        f"{_num(slot.get('slot'))}:from T{_num(slot.get('pick_from_team_id'))}->owner T{_num(slot.get('owner_team_id'))}"
        for slot in lottery.get("slots") or []
        if isinstance(slot, dict)
    )
    return (
        f"drawn={lottery.get('drawn')} lottery_slots={_num(lottery.get('lottery_slots'))} "
        f"weights_worst_first={weights}. {lottery.get('description', '')} "
        f"slots (slot:pick origin->current owner): {slots}"
    )


def _rules_text(rules: Any) -> dict[str, str]:
    """Re-render the rules block as one short line (or paragraph) per mechanic.

    The prose descriptions the simulator publishes for the center bonus, free-
    agent willingness, and extension expiry are kept verbatim: they are how each
    v6 mechanic is made legible, and paraphrasing them here would fork the
    explanation from the constants it describes. Only the machine-readable
    numbers around them are flattened.
    """
    if not isinstance(rules, dict):
        return {}
    lineup = rules.get("lineup_min_positions") or {}
    center = rules.get("lineup_center_bonus") or {}
    willingness = rules.get("free_agency_willingness") or {}
    contracts = rules.get("contracts") or {}
    picks = rules.get("pick_trading") or {}
    scouting = rules.get("scouting") or {}
    reservation = rules.get("fa_reservation_range") or []
    return {
        "cap": (
            f"salary_cap={_num(rules.get('salary_cap'))} hard_cap_buffer={_num(rules.get('hard_cap_buffer'))} "
            f"roster_min={_num(rules.get('roster_min'))}"
        ),
        "lineup": (
            f"lineup_size={_num(rules.get('lineup_size'))} minimums="
            + ",".join(f"{position}>={_num(count)}" for position, count in sorted(lineup.items()))
            + f". Center bonus: target={_num(center.get('target'))} "
            f"bonus_per_center={_num(center.get('bonus_per_center'))}. {center.get('description', '')}"
        ),
        "free_agency": (
            f"fa_reservation_range={'-'.join(_num(bound) for bound in reservation)} "
            f"rejected_offer_limit_per_window={_num(rules.get('rejected_offer_limit_per_window'))} "
            f"win_appeal_weight={_num(willingness.get('win_appeal_weight'))} "
            f"role_appeal_weight={_num(willingness.get('role_appeal_weight'))} "
            f"veteran_age={_num(willingness.get('veteran_age'))}. {willingness.get('description', '')}"
        ),
        "contracts": (
            f"dead_cap_fraction={_num(contracts.get('dead_cap_fraction'))} "
            f"dead_cap_max_seasons={_num(contracts.get('dead_cap_max_seasons'))} "
            f"annual_market_inflation={_num(contracts.get('annual_market_inflation'))} "
            f"additional_year_premium={_num(contracts.get('additional_year_premium'))} "
            f"incumbent_extension_discount={_num(contracts.get('incumbent_extension_discount'))}. "
            f"{contracts.get('expiry_risk', '')} {contracts.get('release_resign_block', '')}"
        ),
        "trades": (
            f"trade_value_threshold={_num(rules.get('trade_value_threshold'))} "
            f"trade_limit_per_partner={_num(rules.get('trade_limit_per_partner'))} "
            f"pick_trading.max_seasons_ahead={_num(picks.get('max_seasons_ahead'))} "
            "pick_trading.pick_value_estimate="
            + ",".join(
                f"S{season}:{_num(value)}" for season, value in sorted((picks.get("pick_value_estimate") or {}).items())
            )
        ),
        "scouting": (
            f"points_per_season={_num(scouting.get('points_per_season'))} "
            f"points_remaining={_num(scouting.get('points_remaining'))} "
            f"report_noise={_num(scouting.get('report_noise'))}"
        ),
    }


def _team_block(observation: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    team = selection["team"]
    limits = selection["limits"]
    roster_total = selection["roster_total"]
    block: dict[str, Any] = {
        "id": team.get("id"),
        "name": team.get("name"),
        "record": f"{_num(team.get('wins'))}-{_num(team.get('losses'))}",
        "championships": team.get("championships"),
        "payroll": team.get("payroll"),
        "cap_room": team.get("cap_room"),
        "dead_cap": {str(season): _num(charge) for season, charge in sorted((team.get("dead_cap") or {}).items())},
        "draft_picks": team.get("draft_picks"),
        "picks": _pick_rows(team.get("picks")),
        "current_lineup": team.get("lineup") or [],
        "roster_columns": _ROSTER_COLUMNS,
        "roster": _roster_rows(selection["roster"]),
    }
    if roster_total > len(selection["roster"]):
        block["roster_note"] = (
            f"roster truncated to the top {limits['roster']} of {roster_total} players by overall; "
            "inspect_team shows the rest"
        )
    return block


def _carded(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The selected players who came with a full card.

    Summary-tier observations publish ids without ratings; rendering those as
    rows of dashes would cost tokens and say nothing, so they are listed as bare
    ids for the model to inspect instead.
    """
    return [player for player in players if "overall" in player]


def _id_only(players: list[dict[str, Any]]) -> list[int]:
    return [player["id"] for player in players if "overall" not in player and "id" in player]


def _truncation_note(kind: str, shown: int, total: int, rule: str) -> str:
    if total > shown:
        return f"showing the top {shown} of {total} {kind} by {rule}; information actions reach the rest"
    return f"showing all {total} {kind}"


def compact_observation(observation: dict[str, Any], profile: str | None = None) -> dict[str, Any]:
    """Compact an observation to the view a model adapter receives.

    Rows are pipe-delimited and their columns are named after the underlying
    observation fields, so prompt text that refers to ``contract_quotes``,
    ``extension_quotes``, ``release_dead_cap``, ``signing_appeal`` or
    ``resign_blocked`` still points at something the model can find.
    """
    selection = _select(observation, profile)
    scout_reports = observation.get("scout_reports") or {}
    team = selection["team"]
    payload: dict[str, Any] = {
        "season": observation.get("season"),
        "phase": observation.get("phase"),
        "observation_tier": observation.get("observation_tier", "full"),
        "interaction_round": observation.get("interaction_round", 0),
        "format": (
            "Tables are lists of pipe-delimited rows; the matching *_columns field names the columns, "
            "and each name is the observation field it came from. Salaries and cap figures are in the "
            "same units as the salary cap. injury_risk% is a percentage. Every candidate list is "
            "truncated by a fixed public rule, identical for every agent, and states its cutoff."
        ),
        "rules": _rules_text(observation.get("rules")),
        "team": _team_block(observation, selection),
        "standings_columns": _STANDINGS_COLUMNS,
        "standings": _standings_rows(observation.get("standings")),
        "free_agents_columns": _FREE_AGENT_COLUMNS,
        "free_agents": _free_agent_rows(_carded(selection["free_agents"])),
        "free_agents_ids_only": _id_only(selection["free_agents"]),
        "free_agents_note": _truncation_note(
            "free agents", len(selection["free_agents"]), selection["free_agents_total"], "public asset value"
        ),
        "draft_class_columns": _DRAFT_COLUMNS,
        "draft_class": _draft_rows(_carded(selection["draft_class"]), scout_reports),
        "draft_class_ids_only": _id_only(selection["draft_class"]),
        "draft_class_note": _truncation_note(
            "prospects", len(selection["draft_class"]), selection["draft_class_total"], "public asset value"
        ),
        "trade_market_columns": _TRADE_COLUMNS,
        "trade_market": _trade_rows(selection["trade_market"]),
        "trade_market_note": _truncation_note(
            "listed players", len(selection["trade_market"]), selection["trade_market_total"], "public asset value"
        ),
        "incoming_offers": _offer_rows(selection["incoming_offers"]),
        "draft_order_inverse_standings": observation.get("draft_order", []),
        "draft_lottery": _lottery_text(observation.get("draft_lottery")),
        "scout_reports": {str(key): _num(value) for key, value in sorted(scout_reports.items())},
        "history_columns": _HISTORY_COLUMNS,
        "history": _history_rows(observation.get("history")),
        "recent_transactions_columns": _LEDGER_COLUMNS,
        "recent_transactions": _ledger_rows(observation.get("recent_transactions"), team.get("id")),
        "available_actions": observation.get("available_actions", []),
        "action_results_columns": "outcome|action|message, followed by indented result rows",
        "action_results": _action_result_rows(observation.get("action_results"), scout_reports),
        "memo": observation.get("memo", ""),
    }
    for key in ("free_agents_ids_only", "draft_class_ids_only"):
        if not payload[key]:
            del payload[key]
    if selection["waiver_wire"]:
        payload["waiver_wire_columns"] = _WAIVER_COLUMNS
        payload["waiver_wire"] = _waiver_rows(selection["waiver_wire"])
    if observation.get("waiver_wire_summary"):
        payload["waiver_wire_summary"] = observation["waiver_wire_summary"]
    if observation.get("hint"):
        payload["hint"] = observation["hint"]
    return payload


def scaffold_fallback_lineup(observation: dict[str, Any]) -> list[int]:
    """The legal lineup the prompt hands a model for free.

    Computed from the untruncated roster, so it is available even when the
    compact payload no longer carries enough players to build one.
    """
    roster = (observation.get("team") or {}).get("roster") or []
    return position_aware_lineup(roster) if roster else []


def scaffold_view_observation(observation: dict[str, Any], profile: str | None = None) -> dict[str, Any]:
    """The same selection as ``compact_observation``, shaped for a scripted policy.

    Only the rendering is undone: the rows a model reads become the dicts they
    were built from, and the flattened rules text becomes the rules dict. Every
    truncation stays in place, and no field is present here that the rendered
    rows do not publish. The payload is deliberately *not* round tripped through
    JSON -- that would turn ``team.draft_picks`` season keys into strings and
    make scripted ``.get(season)`` lookups miss, which is a Python typing
    artifact rather than information a model is denied.
    """
    selection = _select(observation, profile)
    team = dict(selection["team"])
    team["roster"] = list(selection["roster"])
    payload: dict[str, Any] = {
        "season": observation.get("season"),
        "phase": observation.get("phase"),
        "observation_tier": observation.get("observation_tier", "full"),
        "interaction_round": observation.get("interaction_round", 0),
        "rules": observation.get("rules") or {},
        "team": team,
        "standings": observation.get("standings") or [],
        "free_agents": list(selection["free_agents"]),
        "draft_class": list(selection["draft_class"]),
        "trade_market": list(selection["trade_market"]),
        "waiver_wire": list(selection["waiver_wire"]),
        "incoming_offers": list(selection["incoming_offers"]),
        "draft_order": observation.get("draft_order", []),
        "draft_lottery": observation.get("draft_lottery"),
        "scout_reports": observation.get("scout_reports") or {},
        "history": observation.get("history") or [],
        "recent_transactions": observation.get("recent_transactions") or [],
        "available_actions": observation.get("available_actions", []),
        "action_results": observation.get("action_results"),
        "memo": observation.get("memo", ""),
        "hint": observation.get("hint"),
        "scaffold_fallback_lineup": scaffold_fallback_lineup(observation),
    }
    return payload
