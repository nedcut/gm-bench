"""Tests for negotiation validity: legal-but-declined offers are counted as
rejected offers (no protocol penalty), free agents have hidden reservation
prices, and counterparties walk away after repeated declines."""

from __future__ import annotations

from gm_bench.simulator import (
    FA_RESERVATION_RANGE,
    REJECTED_OFFER_LIMIT_PER_WINDOW,
    League,
)


def _lowball(league: League, player_id: int) -> dict[str, object]:
    ask = league.players[player_id].asking_salary
    return {
        "type": "sign_free_agent",
        "player_id": player_id,
        "years": 1,
        "salary": round(ask * FA_RESERVATION_RANGE[0] * 0.5, 2),
    }


def _too_light_trade(league: League, partner_id: int) -> dict[str, object]:
    """A trade the partner clearly rejects: user's worst asset for partner's best."""
    give_id = min(league.user_team.roster, key=lambda pid: league.players[pid].asset_value)
    receive_id = max(league.teams[partner_id].roster, key=lambda pid: league.players[pid].asset_value)
    return {
        "type": "trade",
        "partner_team_id": partner_id,
        "give_player_ids": [give_id],
        "receive_player_ids": [receive_id],
    }


def test_lowball_offer_is_rejected_without_protocol_penalty() -> None:
    league = League.new(seed=7)
    player_id = league.free_agents[0]
    league.apply_actions([_lowball(league, player_id)], "preseason")
    assert league.transactions[-1].accepted is False
    assert league.rejected_offers == 1
    assert league.illegal_actions == 0
    assert player_id in league.free_agents


def test_full_ask_offer_always_accepted() -> None:
    league = League.new(seed=7)
    player_id = league.free_agents[0]
    ask = league.players[player_id].asking_salary
    league.apply_actions([{"type": "sign_free_agent", "player_id": player_id, "years": 1, "salary": ask}], "preseason")
    assert league.transactions[-1].accepted is True
    assert league.rejected_offers == 0


def test_fa_reservation_is_hidden_deterministic_and_bounded() -> None:
    league_a = League.new(seed=13)
    league_b = League.new(seed=13)
    for player_id in league_a.free_agents[:20]:
        reservation_a = league_a._fa_reservation(player_id)
        reservation_b = league_b._fa_reservation(player_id)
        ask = league_a.players[player_id].asking_salary
        assert reservation_a == reservation_b
        assert ask * FA_RESERVATION_RANGE[0] <= reservation_a <= ask * FA_RESERVATION_RANGE[1]


def test_fa_reservation_rerolls_each_season() -> None:
    league = League.new(seed=13)
    player_id = league.free_agents[0]
    before = league._fa_reservation(player_id)
    league.season += 1
    assert league._fa_reservation(player_id) != before


def test_free_agent_walks_away_after_repeated_lowballs() -> None:
    league = League.new(seed=7)
    player_id = league.free_agents[0]
    ask = league.players[player_id].asking_salary
    offers = [_lowball(league, player_id) for _ in range(REJECTED_OFFER_LIMIT_PER_WINDOW)]
    # Even a full-ask offer is refused once the player has broken off talks.
    offers.append({"type": "sign_free_agent", "player_id": player_id, "years": 1, "salary": ask})
    league.apply_actions(offers, "preseason")
    assert league.transactions[-1].accepted is False
    assert "broken off" in league.transactions[-1].message
    assert league.rejected_offers == REJECTED_OFFER_LIMIT_PER_WINDOW + 1
    assert league.illegal_actions == 0
    # Talks reopen at the next decision window.
    league.apply_actions([{"type": "sign_free_agent", "player_id": player_id, "years": 1, "salary": ask}], "preseason")
    assert league.transactions[-1].accepted is True


def test_too_light_trade_is_rejected_offer_not_illegal() -> None:
    league = League.new(seed=21)
    league.apply_actions([_too_light_trade(league, 1)], "trade_deadline")
    assert league.transactions[-1].accepted is False
    assert league.rejected_offers == 1
    assert league.illegal_actions == 0


def test_partner_walks_away_after_repeated_light_offers() -> None:
    league = League.new(seed=21)
    offers = [_too_light_trade(league, 1) for _ in range(REJECTED_OFFER_LIMIT_PER_WINDOW + 1)]
    league.apply_actions(offers, "trade_deadline")
    assert "broken off" in league.transactions[-1].message
    assert league.rejected_offers == REJECTED_OFFER_LIMIT_PER_WINDOW + 1
    assert league.illegal_actions == 0


def test_malformed_actions_remain_protocol_violations() -> None:
    league = League.new(seed=7)
    league.apply_actions(
        [
            {"type": "sign_free_agent", "player_id": -999, "years": 1, "salary": 5.0},
            {"type": "trade", "partner_team_id": 99, "give_player_ids": [1], "receive_player_ids": [2]},
            {"type": "unknown_action"},
        ],
        "preseason",
    )
    assert league.illegal_actions == 3
    assert league.rejected_offers == 0


def test_observation_exposes_negotiation_rules() -> None:
    league = League.new(seed=7)
    rules = league.observation("preseason")["rules"]
    assert rules["fa_reservation_range"] == list(FA_RESERVATION_RANGE)
    assert rules["rejected_offer_limit_per_window"] == REJECTED_OFFER_LIMIT_PER_WINDOW


def test_episode_result_reports_rejected_offers() -> None:
    from gm_bench.agents import ValueAgent
    from gm_bench.runner import run_episode

    result = run_episode(ValueAgent(), seed=1, seasons=1)
    assert result.rejected_offers == 0
    assert result.protocol_penalty == result.illegal_actions * 2.5


def test_non_positive_salary_is_a_protocol_violation_not_a_rejected_offer() -> None:
    """An impossible bid is malformed, not negotiation — it must not let a model
    dodge protocol penalties by lowballing below zero."""
    league = League.new(seed=7)
    player_id = league.free_agents[0]
    for salary in (-5.0, 0.0):
        league.apply_actions(
            [{"type": "sign_free_agent", "player_id": player_id, "years": 1, "salary": salary}], "preseason"
        )
        assert league.transactions[-1].accepted is False
        assert "positive" in league.transactions[-1].message
    assert league.illegal_actions == 2
    assert league.rejected_offers == 0
    assert player_id in league.free_agents
