"""Fuzz-style tests for action validation."""

from __future__ import annotations

import json
import random

import pytest

from gm_bench.repair import RAW_TEXT_FIELD, repair_adapter_output
from gm_bench.simulator import League


def _model_reply(text: str):
    """Judge a model reply exactly as the harness does.

    Adapters forward the model's raw text and never parse it, so these cases
    are checked through ``gm_bench.repair`` -- the published rule set that
    actually decides what reaches the simulator. An unusable reply is not an
    exception any more: it is an unrecoverable, malformed decision recorded as
    a structured no-op, with the reason kept for the artifact.
    """
    envelope = json.dumps({RAW_TEXT_FIELD: text, "usage": {"api_calls": 1}})
    return repair_adapter_output(envelope, source="external agent")


def _rejected(text: str, expected: str) -> None:
    outcome = _model_reply(text)
    assert outcome.malformed and outcome.unrecoverable
    assert expected in (outcome.reason or "")
    assert outcome.actions[0]["type"] == "noop"
    assert len(outcome.actions) == 1
    # The paid call is still reported, so cost telemetry is not lost with it.
    assert outcome.usage == {"api_calls": 1}


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


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_action_numbers_are_rejected_at_repair_and_simulator_boundaries(value: str) -> None:
    _rejected(f'{{"actions":[{{"type":"sign_free_agent","salary":{value}}}]}}', "non-finite")

    league = League.new(seed=7)
    player_id = league.free_agents[0]
    league.apply_actions(
        [{"type": "sign_free_agent", "player_id": player_id, "years": 1, "salary": json.loads(value)}], "preseason"
    )
    assert not league.transactions[-1].accepted
    assert player_id in league.free_agents
    assert league.user_team.roster.count(player_id) == 0


@pytest.mark.parametrize(
    "payload",
    [
        '{"actions":[{"type":"sign_free_agent","salary":1e999}]}',
        '{"actions":[{"type":"set_lineup","player_ids":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,1e999]}]}',
        '{"actions":[{"type":"memo","metadata":{"nested":[1e999]}}]}',
    ],
)
def test_numeric_overflow_is_rejected_recursively(payload: str) -> None:
    _rejected(payload, "non-finite")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("player_id", "true"),
        ("years", "false"),
        ("salary", "true"),
        ("player_ids", "[1,2,true]"),
    ],
)
def test_repair_rejects_booleans_in_numeric_fields(field: str, value: str) -> None:
    _rejected(f'{{"actions":[{{"type":"sign_free_agent","{field}":{value}}}]}}', "must be")


def test_repair_rejects_more_than_protocol_maximum() -> None:
    _rejected(json.dumps({"actions": [{"type": "noop"}] * 25}), "at most 24")


def test_simulator_defensively_rejects_overflowing_integer_coercion() -> None:
    league = League.new(seed=7)
    league.apply_actions([{"type": "release", "player_id": float("inf")}], "preseason")
    assert not league.transactions[-1].accepted
    assert "invalid or missing argument values" in league.transactions[-1].message


@pytest.mark.parametrize("action_type", [[], {}])
def test_simulator_rejects_unhashable_action_type_without_aborting(action_type: object) -> None:
    league = League.new(seed=7)

    results = league.apply_actions([{"type": action_type}], "preseason")

    assert len(results) == 1
    assert not results[0].accepted
    assert results[0].message == "action type must be a string"
    assert league.illegal_actions == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_query_threshold_is_rejected(value: float) -> None:
    league = League.new(seed=7)
    league.apply_actions([{"type": "list_free_agents", "min_overall": value}], "preseason")
    assert not league.transactions[-1].accepted
    assert "finite number" in league.transactions[-1].message


def _eligible_extension_player(league: League):
    return next(
        league.players[player_id]
        for player_id in league.user_team.roster
        if league._extension_eligible(league.players[player_id])
    )


def test_extend_contract_rejects_one_year_terms() -> None:
    league = League.new(seed=24)
    league.cap = 1000.0
    player = _eligible_extension_player(league)
    league.apply_actions(
        [{"type": "extend_contract", "player_id": player.id, "years": 1, "salary": player.salary}],
        "preseason",
    )
    assert not league.transactions[-1].accepted
    assert "2-5" in league.transactions[-1].message


def test_extend_contract_rejects_roster_player_with_years_remaining() -> None:
    """Extensions are for final-year incumbents only.

    Select on the term condition explicitly rather than on `not
    _extension_eligible`, which is satisfied by either half of the rule. The
    same-season half is covered by
    `test_new_one_year_signing_cannot_immediately_harvest_loyalty_discount`,
    since no player is signed in the season the league is created.
    """
    league = League.new(seed=24)
    league.cap = 1000.0
    player = next(
        league.players[player_id]
        for player_id in league.user_team.roster
        if league.players[player_id].contract_years > 1
    )
    assert not league._extension_eligible(player)
    league.apply_actions(
        [
            {
                "type": "extend_contract",
                "player_id": player.id,
                "years": 3,
                "salary": league._contract_quote(player, 3, incumbent=True),
            }
        ],
        "preseason",
    )
    assert not league.transactions[-1].accepted
    assert "signed before this season" in league.transactions[-1].message


def test_extend_contract_rejects_non_positive_salary() -> None:
    league = League.new(seed=24)
    player = _eligible_extension_player(league)
    league.apply_actions(
        [{"type": "extend_contract", "player_id": player.id, "years": 3, "salary": 0.0}],
        "preseason",
    )
    assert not league.transactions[-1].accepted
    assert "positive amount" in league.transactions[-1].message
