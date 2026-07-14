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


def test_incumbent_loyalty_does_not_cancel_max_term_premium() -> None:
    """Extension length must stay strategically distinct after the loyalty discount."""
    league = League.new(seed=24)
    player = league.players[league.free_agents[0]]
    fa1 = league._contract_quote(player, 1)
    inc5 = league._contract_quote(player, 5, incumbent=True)

    assert inc5 > fa1 * 1.04
    assert league._contract_quote(player, 5, incumbent=True) < league._contract_quote(player, 5)


def test_expiring_player_gets_public_discounted_extension_quotes() -> None:
    league = League.new(seed=24)
    player = _expiring_player(league)

    public_player = next(item for item in league.observation("preseason")["team"]["roster"] if item["id"] == player.id)

    assert "extension_quotes" in public_player
    assert public_player["extension_quotes"]["3"] < league._contract_quote(player, 3)
    assert "extend_contract" in league.observation("preseason")["available_actions"]
    assert league.observation("preseason")["rules"]["contracts"]["extension_minimum_contract_age_seasons"] == 1


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
    assert "one year remaining" in result.message


def test_new_one_year_signing_cannot_bypass_multi_year_price_with_immediate_extension() -> None:
    league = League.new(seed=24)
    league.cap = 1000.0
    player = league.players[league.free_agents[0]]

    results = league.apply_actions(
        [
            {
                "type": "sign_free_agent",
                "player_id": player.id,
                "years": 1,
                "salary": league._contract_quote(player, 1),
            },
            {
                "type": "extend_contract",
                "player_id": player.id,
                "years": 5,
                "salary": league._contract_quote(player, 5, incumbent=True),
            },
        ],
        "preseason",
    )

    assert results[0].accepted
    assert not results[1].accepted
    assert "signed before this season" in results[1].message
    assert player.contract_years == 1


def test_multi_year_signing_becomes_extension_eligible_in_later_final_season() -> None:
    league = League.new(seed=24)
    league.cap = 1000.0
    player = league.players[league.free_agents[0]]
    quote = league._contract_quote(player, 2)
    assert league.apply_actions(
        [{"type": "sign_free_agent", "player_id": player.id, "years": 2, "salary": quote}],
        "preseason",
    )[0].accepted

    league.simulate_season()
    public = next(item for item in league.observation("preseason")["team"]["roster"] if item["id"] == player.id)

    assert player.contract_years == 1
    assert "extension_quotes" in public


def test_summary_tier_inspection_publishes_extension_quote() -> None:
    league = League.new(seed=24)
    player = _expiring_player(league)

    result = league.apply_actions([{"type": "inspect_player", "player_id": player.id}], "preseason")[0]

    assert result.accepted
    assert result.data["player"]["extension_quotes"] == league._contract_quotes(player, incumbent=True)


def test_opponents_can_retain_eligible_expiring_players_without_consuming_rng() -> None:
    first = League.new(seed=24)
    second = League.new(seed=24)
    team = first.teams[1]
    candidate = max(
        (
            first.players[player_id]
            for player_id in team.roster
            if first.players[player_id].contract_years == 1 and first.players[player_id].age <= 27
        ),
        key=lambda player: player.asset_value,
    )
    # Ensure the calibrated opponent policy accepts this candidate in both
    # otherwise identical leagues.
    for league in (first, second):
        player = league.players[candidate.id]
        player.overall = 85.0
        player.potential = 90.0
        player.salary = league._contract_quote(player, 3, incumbent=True)
    offset = first.rng_state_offset

    first._opponent_extensions(first.teams[1])
    second._opponent_extensions(second.teams[1])

    assert first.players[candidate.id].contract_years == 3
    assert first.players[candidate.id].salary == second.players[candidate.id].salary
    assert first.rng_state_offset == offset


def test_one_year_extension_is_invalid() -> None:
    league = League.new(seed=24)
    player = _expiring_player(league)

    result = league.apply_actions(
        [
            {
                "type": "extend_contract",
                "player_id": player.id,
                "years": 1,
                "salary": league._contract_quote(player, 1, incumbent=True),
            }
        ],
        "preseason",
    )[0]

    assert not result.accepted
    assert "2-5" in result.message


def test_contract_quotes_and_reservations_are_deterministic() -> None:
    first = League.new(seed=24)
    second = League.new(seed=24)
    player_id = first.free_agents[0]

    assert first._contract_quotes(first.players[player_id]) == second._contract_quotes(second.players[player_id])
    assert first._contract_reservation(player_id, years=5) == second._contract_reservation(player_id, years=5)
