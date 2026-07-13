from __future__ import annotations

from gm_bench.simulator import League


def _expiring_player(league: League):
    return next(
        league.players[player_id]
        for player_id in league.user_team.roster
        if league.players[player_id].contract_years == 1
    )


def test_contract_quotes_trade_current_cost_for_long_term_certainty() -> None:
    league = League.new(seed=24)
    player = league.players[league.free_agents[0]]

    quotes = league._contract_quotes(player)

    assert list(quotes) == ["1", "2", "3", "4", "5"]
    assert quotes["1"] < quotes["3"] < quotes["5"]
    first_year_quote = quotes["1"]
    league.season += 1
    assert league._contract_quote(player, 1) > first_year_quote


def test_expiring_player_gets_public_discounted_extension_quotes() -> None:
    league = League.new(seed=24)
    player = _expiring_player(league)

    public_player = next(item for item in league.observation("preseason")["team"]["roster"] if item["id"] == player.id)

    assert "extension_quotes" in public_player
    assert public_player["extension_quotes"]["3"] < league._contract_quote(player, 3)
    assert "extend_contract" in league.observation("preseason")["available_actions"]


def test_extension_replaces_expiring_term_and_prevents_free_agency() -> None:
    league = League.new(seed=24)
    league.cap = 1000.0
    player = _expiring_player(league)
    quote = league._contract_quote(player, 4, incumbent=True)

    result = league.apply_actions(
        [{"type": "extend_contract", "player_id": player.id, "years": 4, "salary": quote}],
        "preseason",
    )[0]

    assert result.accepted
    assert player.contract_years == 4
    assert player.salary == quote
    league.simulate_season()
    assert player.contract_years == 3
    assert player.id in league.user_team.roster
    assert player.id not in league.free_agents


def test_extension_is_limited_to_expiring_incumbents() -> None:
    league = League.new(seed=24)
    player = next(
        league.players[player_id]
        for player_id in league.user_team.roster
        if league.players[player_id].contract_years > 1
    )
    quote = league._contract_quote(player, 3, incumbent=True)

    result = league.apply_actions(
        [{"type": "extend_contract", "player_id": player.id, "years": 3, "salary": quote}],
        "preseason",
    )[0]

    assert not result.accepted
    assert "one contract year" in result.message


def test_contract_quotes_and_reservations_are_deterministic() -> None:
    first = League.new(seed=24)
    second = League.new(seed=24)
    player_id = first.free_agents[0]

    assert first._contract_quotes(first.players[player_id]) == second._contract_quotes(second.players[player_id])
    assert first._contract_reservation(player_id, years=5) == second._contract_reservation(player_id, years=5)
