"""Strict, dependency-free validation for external-agent action payloads."""

from __future__ import annotations

import math
from typing import Any

ACTION_TYPES = frozenset(
    {
        "sign_free_agent",
        "extend_contract",
        "release",
        "trade",
        "draft",
        "set_lineup",
        "memo",
        "noop",
        "inspect_team",
        "inspect_player",
        "list_free_agents",
        "scout",
        "accept_trade_offer",
        "reject_trade_offer",
        "counter_trade_offer",
        "claim_waiver",
        "end_turn",
    }
)

INTEGER_FIELDS = {"player_id", "prospect_id", "partner_team_id", "team_id", "limit", "years"}
INTEGER_LIST_FIELDS = {
    "player_ids",
    "give_player_ids",
    "receive_player_ids",
    "give_pick_seasons",
    "receive_pick_seasons",
}
NUMBER_FIELDS = {"min_overall", "salary"}
STRING_FIELDS = {"type", "offer_id", "position", "text", "error", "model_error"}


def validate_action_list(actions: Any) -> list[dict[str, Any]]:
    """Return a validated action list or raise ``ValueError``.

    Semantic legality (phase, IDs, cap room, and roster state) remains the
    simulator's responsibility. This boundary enforces JSON-schema scalar
    types, notably rejecting booleans where Python would otherwise accept them
    as integers.
    """
    if not isinstance(actions, list):
        raise ValueError("actions must be a list")
    if len(actions) > 24:
        raise ValueError("actions must contain at most 24 items")
    if any(not isinstance(action, dict) for action in actions):
        raise ValueError("every action must be an object")
    for action in actions:
        action_type = action.get("type")
        if not isinstance(action_type, str):
            raise ValueError("every action must have a string type")
        if action_type not in ACTION_TYPES:
            raise ValueError(f"unknown action type {action_type!r}")
        for key, value in action.items():
            if value is None:
                continue
            if key in INTEGER_FIELDS and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"action field {key!r} must be an integer")
            if key in INTEGER_LIST_FIELDS and (
                not isinstance(value, list)
                or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
            ):
                raise ValueError(f"action field {key!r} must be an array of integers")
            if key in NUMBER_FIELDS and (
                not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(float(value))
            ):
                raise ValueError(f"action field {key!r} must be a finite number")
            if key in STRING_FIELDS and not isinstance(value, str):
                raise ValueError(f"action field {key!r} must be a string")
    return actions
