"""The GM-Bench 2.0 tool surface.

Everything in this module is a contract source: tool names, descriptions and
input schemas are what the agent sees, so a change here is a new benchmark
version. Keep descriptions factual and short; the task brief carries the
narrative.

Tools come in four kinds:

- ``read``    answer from public state and never touch the simulator's ledger
- ``query``   the 1.0 query actions (inspect, list, scout); ``scout`` is budgeted
- ``move``    roster moves, applied immediately, judged by the simulator
- ``control`` ``end_phase``
"""

from __future__ import annotations

from typing import Any

SERVER_NAME = "gm-bench"
TOOL_SURFACE_VERSION = "gm-bench-agentic-v1"

_ID = {"type": "integer"}
_ID_LIST = {"type": "array", "items": {"type": "integer"}}
_SEASON_LIST = {"type": "array", "items": {"type": "integer"}, "description": "draft seasons, e.g. [4, 5]"}


def _schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


TOOLS: list[dict[str, Any]] = [
    # -- read -----------------------------------------------------------------
    {
        "name": "get_status",
        "kind": "read",
        "description": (
            "Where you are: season, phase, your team's record, cap room, picks, lineup, "
            "standings, season history, scouting points left, your saved memo, and the "
            "tools legal in this phase. Call this first in every phase."
        ),
        "inputSchema": _schema(),
    },
    {
        "name": "get_rules",
        "kind": "read",
        "description": (
            "League rules with current numbers: salary cap, roster and lineup limits, "
            "contract and dead-cap terms, free-agent willingness, pick trading, scouting."
        ),
        "inputSchema": _schema(),
    },
    {
        "name": "get_team",
        "kind": "read",
        "description": (
            "Your full roster with public ratings, contracts, injuries, dead-cap cost of "
            "releasing each player, and extension quotes for players in their final year."
        ),
        "inputSchema": _schema(),
    },
    {
        "name": "list_draft_class",
        "kind": "read",
        "description": "Prospects still available at your pick. Draft phase only.",
        "inputSchema": _schema(),
    },
    {
        "name": "list_waiver_wire",
        "kind": "read",
        "description": "Players opponents waived, claimable with claim_waiver. Midseason only.",
        "inputSchema": _schema(),
    },
    {
        "name": "list_offers",
        "kind": "read",
        "description": (
            "Trade offers opponents have sent you, with offer ids for accept_trade_offer, "
            "reject_trade_offer and counter_trade_offer. Usually only at the trade deadline."
        ),
        "inputSchema": _schema(),
    },
    {
        "name": "list_trade_market",
        "kind": "read",
        "description": "Players opponents are shopping, with the team that holds each one.",
        "inputSchema": _schema(),
    },
    {
        "name": "list_transactions",
        "kind": "read",
        "description": "Roster-changing moves league-wide over the current and previous season.",
        "inputSchema": _schema(),
    },
    # -- query ----------------------------------------------------------------
    {
        "name": "inspect_team",
        "kind": "query",
        "description": "Another team's cap position, picks and full public roster.",
        "inputSchema": _schema({"team_id": _ID}, ["team_id"]),
    },
    {
        "name": "inspect_player",
        "kind": "query",
        "description": "One player's full public card (any team, free agent, or prospect).",
        "inputSchema": _schema({"player_id": _ID}, ["player_id"]),
    },
    {
        "name": "list_free_agents",
        "kind": "query",
        "description": "Free agents with asking quotes, optionally filtered by position and minimum overall.",
        "inputSchema": _schema(
            {
                "position": {"type": "string", "enum": ["F", "D", "G"]},
                "min_overall": {"type": "number"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 24},
            }
        ),
    },
    {
        "name": "scout",
        "kind": "query",
        "description": (
            "Spend one of your scouting points for a near-true reading of a player's or "
            "prospect's potential. Points are per season and do not carry over; reports persist."
        ),
        "inputSchema": _schema({"player_id": _ID}, ["player_id"]),
    },
    # -- move -----------------------------------------------------------------
    {
        "name": "sign_free_agent",
        "kind": "move",
        "description": (
            "Offer a free agent a contract. Offering the published quote for that length always "
            "succeeds; shading below it may be declined, which is not penalized."
        ),
        "inputSchema": _schema(
            {"player_id": _ID, "years": {"type": "integer", "minimum": 1}, "salary": {"type": "number"}},
            ["player_id", "years", "salary"],
        ),
    },
    {
        "name": "extend_contract",
        "kind": "move",
        "description": "Extend a roster player in his final contract year. Preseason only.",
        "inputSchema": _schema(
            {"player_id": _ID, "years": {"type": "integer", "minimum": 1}, "salary": {"type": "number"}},
            ["player_id", "years", "salary"],
        ),
    },
    {
        "name": "release_player",
        "kind": "move",
        "description": "Release a roster player. Remaining salary becomes dead cap per the rules.",
        "inputSchema": _schema({"player_id": _ID}, ["player_id"]),
    },
    {
        "name": "trade",
        "kind": "move",
        "description": (
            "Propose a trade. The partner accepts if it favors their hidden valuation. A decline "
            "is not penalized, but after a few declines a partner stops talking for the phase."
        ),
        "inputSchema": _schema(
            {
                "partner_team_id": _ID,
                "give_player_ids": _ID_LIST,
                "receive_player_ids": _ID_LIST,
                "give_pick_seasons": _SEASON_LIST,
                "receive_pick_seasons": _SEASON_LIST,
            },
            ["partner_team_id"],
        ),
    },
    {
        "name": "draft",
        "kind": "move",
        "description": "Use your current-season pick on a prospect. Draft phase only.",
        "inputSchema": _schema({"prospect_id": _ID}, ["prospect_id"]),
    },
    {
        "name": "set_lineup",
        "kind": "move",
        "description": (
            "Choose the 18 players who dress. Drives team strength directly; players outside the "
            "lineup develop at half speed. Must satisfy the position minimums in get_rules."
        ),
        "inputSchema": _schema({"player_ids": _ID_LIST}, ["player_ids"]),
    },
    {
        "name": "claim_waiver",
        "kind": "move",
        "description": "Claim a player from the waiver wire. Midseason only.",
        "inputSchema": _schema({"player_id": _ID}, ["player_id"]),
    },
    {
        "name": "accept_trade_offer",
        "kind": "move",
        "description": "Accept an incoming offer by id.",
        "inputSchema": _schema({"offer_id": {"type": "string"}}, ["offer_id"]),
    },
    {
        "name": "reject_trade_offer",
        "kind": "move",
        "description": "Reject an incoming offer by id.",
        "inputSchema": _schema({"offer_id": {"type": "string"}}, ["offer_id"]),
    },
    {
        "name": "counter_trade_offer",
        "kind": "move",
        "description": "Counter an incoming offer with different assets; omitted fields keep the offer's.",
        "inputSchema": _schema(
            {
                "offer_id": {"type": "string"},
                "give_player_ids": _ID_LIST,
                "receive_player_ids": _ID_LIST,
                "give_pick_seasons": _SEASON_LIST,
                "receive_pick_seasons": _SEASON_LIST,
            },
            ["offer_id"],
        ),
    },
    {
        "name": "write_memo",
        "kind": "move",
        "description": (
            "Save up to 2000 characters of notes to yourself, returned by every get_status. "
            "Optional: your own context and files also persist for the whole episode."
        ),
        "inputSchema": _schema({"text": {"type": "string", "maxLength": 2000}}, ["text"]),
    },
    # -- control --------------------------------------------------------------
    {
        "name": "end_phase",
        "kind": "control",
        "description": (
            "Finish this decision phase. Opponents then act, the calendar advances, and the "
            "response tells you the next phase or that the episode is complete. There are "
            "four phases per season; you cannot return to a phase once ended."
        ),
        "inputSchema": _schema(),
    },
]

TOOLS_BY_NAME: dict[str, dict[str, Any]] = {tool["name"]: tool for tool in TOOLS}

# Tool name -> simulator action type, for everything that goes through
# ``League.apply_actions``. Read tools and ``end_phase`` are handled by the
# engine directly.
ACTION_TYPE_FOR_TOOL: dict[str, str] = {
    "inspect_team": "inspect_team",
    "inspect_player": "inspect_player",
    "list_free_agents": "list_free_agents",
    "scout": "scout",
    "sign_free_agent": "sign_free_agent",
    "extend_contract": "extend_contract",
    "release_player": "release",
    "trade": "trade",
    "draft": "draft",
    "set_lineup": "set_lineup",
    "claim_waiver": "claim_waiver",
    "accept_trade_offer": "accept_trade_offer",
    "reject_trade_offer": "reject_trade_offer",
    "counter_trade_offer": "counter_trade_offer",
    "write_memo": "memo",
}


def mcp_tool_listing() -> list[dict[str, Any]]:
    """The ``tools/list`` payload: the MCP fields only, in contract order."""
    return [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]} for t in TOOLS]


def validate_arguments(tool: str, arguments: Any) -> str | None:
    """Cheap structural check against the tool's input schema.

    Returns an error string or None. This is deliberately a subset of JSON
    Schema (types, required, enum, additionalProperties, array item types):
    the package has no schema dependency, and anything this misses is still
    judged by the simulator, which rejects bad values as protocol violations.
    """
    spec = TOOLS_BY_NAME.get(tool)
    if spec is None:
        return f"unknown tool {tool!r}"
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return "arguments must be an object"
    schema = spec["inputSchema"]
    properties = schema["properties"]
    for key in schema.get("required", []):
        if key not in arguments:
            return f"missing required argument {key!r}"
    for key, value in arguments.items():
        if key not in properties:
            return f"unexpected argument {key!r}"
        error = _check_value(key, value, properties[key])
        if error:
            return error
    return None


def _check_value(key: str, value: Any, prop: dict[str, Any]) -> str | None:
    kind = prop.get("type")
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{key} must be an integer"
        if "minimum" in prop and value < prop["minimum"]:
            return f"{key} must be >= {prop['minimum']}"
        if "maximum" in prop and value > prop["maximum"]:
            return f"{key} must be <= {prop['maximum']}"
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{key} must be a number"
    elif kind == "string":
        if not isinstance(value, str):
            return f"{key} must be a string"
        if "enum" in prop and value not in prop["enum"]:
            return f"{key} must be one of {prop['enum']}"
        if "maxLength" in prop and len(value) > prop["maxLength"]:
            return f"{key} must be at most {prop['maxLength']} characters"
    elif kind == "array":
        if not isinstance(value, list):
            return f"{key} must be an array"
        item = prop.get("items", {})
        for element in value:
            error = _check_value(f"{key}[]", element, item)
            if error:
                return error
    return None
