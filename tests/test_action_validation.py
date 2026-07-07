"""Fuzz-style tests for action validation."""

from __future__ import annotations

import random

from gm_bench.simulator import League


def test_simulator_survives_random_garbage_actions() -> None:
    league = League.new(seed=99)
    rng = random.Random(99)
    garbage_actions = [
        {},
        {"type": "noop"},
        {"type": "sign_free_agent"},
        {"type": "sign_free_agent", "player_id": rng.randint(-100, 9999), "years": rng.randint(-1, 10), "salary": -5},
        {"type": "trade", "partner_team_id": 0, "give_player_ids": [], "receive_player_ids": []},
        {"type": "set_lineup", "player_ids": [1, 2, 3]},
        {"type": "unknown_action"},
        "not-an-object",
    ]
    league.apply_actions(garbage_actions, "preseason")  # type: ignore[arg-type]
    assert league.illegal_actions >= 5


def test_trade_rejected_when_give_value_too_low() -> None:
    league = League.new(seed=21)
    partner_id = 1
    partner = league.teams[partner_id]
    user_roster = league.user_team.roster[:]
    partner_roster = partner.roster[:]
    if not user_roster or not partner_roster:
        return
    give_id = min(user_roster, key=lambda pid: league.players[pid].asset_value)
    receive_id = max(partner_roster, key=lambda pid: league.players[pid].asset_value)
    illegal_before = league.illegal_actions
    rejected_before = league.rejected_offers
    league.apply_actions(
        [
            {
                "type": "trade",
                "partner_team_id": partner_id,
                "give_player_ids": [give_id],
                "receive_player_ids": [receive_id],
            }
        ],
        "trade_deadline",
    )
    # A legal-but-declined offer is negotiation, not a protocol violation.
    assert league.illegal_actions == illegal_before
    assert league.rejected_offers > rejected_before
    assert league.transactions[-1].accepted is False
