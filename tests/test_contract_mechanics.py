from __future__ import annotations

import pytest

from gm_bench.simulator import DEAD_CAP_FRACTION, DEAD_CAP_MAX_SEASONS, MARKET_INFLATION, League


def _expiring_player(league: League):
    return next(
        league.players[player_id]
        for player_id in league.user_team.roster
        if league.players[player_id].contract_years == 1
    )


def test_release_books_bounded_dead_cap() -> None:
    league = League.new(seed=24)
    league.user_team.roster.extend(league.free_agents[:2])
    player = league.players[league.user_team.roster[0]]
    player.contract_years = 3
    player.salary = 8.0
    expected_charge = player.salary * DEAD_CAP_FRACTION

    result = league.apply_actions([{"type": "release", "player_id": player.id}], "preseason")[0]

    assert result.accepted
    assert league.user_team.dead_cap == {1: expected_charge, 2: expected_charge}
    assert league._payroll(league.user_team) == pytest.approx(
        sum(league.players[player_id].salary for player_id in league.user_team.roster) + expected_charge
    )
    assert league.observation("preseason")["team"]["dead_cap"] == {
        "1": expected_charge,
        "2": expected_charge,
    }


def test_observation_publishes_exact_bounded_release_dead_cap() -> None:
    league = League.new(seed=24)
    player = league.players[league.user_team.roster[0]]
    player.contract_years = 4
    player.salary = 8.0
    expected_charge = round(player.salary * DEAD_CAP_FRACTION, 2)

    observed = next(row for row in league.observation("preseason")["team"]["roster"] if row["id"] == player.id)

    assert observed["release_dead_cap"] == {
        "by_season": {"1": expected_charge, "2": expected_charge},
        "total": round(expected_charge * DEAD_CAP_MAX_SEASONS, 2),
    }


def test_dead_cap_ages_off_at_the_season_rollover() -> None:
    league = League.new(seed=24)
    league.user_team.roster.extend(league.free_agents[:2])
    player = league.players[league.user_team.roster[0]]
    player.contract_years = 3
    player.salary = 8.0
    assert league.apply_actions([{"type": "release", "player_id": player.id}], "preseason")[0].accepted

    league.simulate_season()

    assert league.season == 2
    expected_charge = round(8.0 * DEAD_CAP_FRACTION, 2)
    assert league.user_team.dead_cap == {2: expected_charge}
    assert league._payroll(league.user_team) == pytest.approx(
        sum(league.players[player_id].salary for player_id in league.user_team.roster) + expected_charge
    )


def test_opponent_release_books_the_same_dead_cap() -> None:
    league = League.new(seed=24)
    team = league.teams[1]
    player = league.players[team.roster[0]]
    player.contract_years = 2
    player.salary = 6.0
    team.roster.append(league.free_agents[0])

    league._book_dead_cap(team, player)

    expected_charge = round(6.0 * DEAD_CAP_FRACTION, 2)
    assert team.dead_cap == {1: expected_charge, 2: expected_charge}
    assert league._payroll(team) == pytest.approx(
        sum(league.players[player_id].salary for player_id in team.roster) + expected_charge
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


def test_extension_never_dominates_free_agency() -> None:
    """A five-year extension must cost more per year than a one-year FA deal.

    This is the invariant PR #62 had to cut the loyalty discount 8% -> 3% to
    hold, and it is the whole reason contract length stays a decision. If a
    long extension is both cheaper per year *and* a longer guarantee, it
    strictly dominates every alternative: extend every incumbent for five years
    on sight, never shop your own expiring players, and the years dial is dead.

    The loyalty discount must therefore stay smaller than the term premium plus
    inflation it is competing against. Asserted on the quotes rather than the
    constants so the guard survives a change to how quotes are computed.
    """
    league = League.new(seed=24)
    # Quotes round to cents, so a player at the 0.70 salary floor would make
    # this a test of rounding rather than of pricing. Use the most expensive
    # free agent, where the ratios are resolvable.
    player = max((league.players[pid] for pid in league.free_agents), key=lambda p: p.asking_salary)
    fa1 = league._contract_quote(player, 1)
    inc1 = league._contract_quote(player, 1, incumbent=True)
    inc2 = league._contract_quote(player, 2, incumbent=True)
    inc5 = league._contract_quote(player, 5, incumbent=True)

    # The discount is real, compared like for like. An extension starts next
    # season, so its base carries one more year of inflation than a deal signed
    # today; the honest comparison is against the open market on that same base,
    # not against today's price.
    open_market_next_season = league._contract_quote(player, 5, incumbent=False) * (1.0 + MARKET_INFLATION)
    assert inc5 < open_market_next_season
    # But length is still paid for, and a five-year guarantee clears the
    # one-year market rate. This is the dominance guard.
    assert inc5 > fa1
    # Longer terms cost strictly more per year, incumbent or not.
    assert inc1 < inc2 < inc5


def test_salary_cap_and_market_prices_inflate_together() -> None:
    league = League.new(seed=24)
    player = league.players[league.free_agents[0]]
    # Pin overall/age below the asking-salary floor (44 overall) so this
    # season's normal free-agent "rust" decline cannot move the floored
    # asking_salary at all; the only thing that can move the quote is market
    # inflation, which is what this test verifies. Otherwise the outcome
    # rides on whichever free agent generation happens to draw into slot 0
    # (whether their post-decline overall stays below the floor too), which
    # is incidental to what the test verifies.
    player.overall = 40.0
    player.age = 25
    initial_cap = league.cap
    initial_ask = league._contract_quote(player, 1)

    league.simulate_season()

    assert league.cap == round(initial_cap * (1.0 + MARKET_INFLATION), 2)
    assert league._contract_quote(player, 1) >= round(initial_ask * (1.0 + MARKET_INFLATION), 2)


def test_expiring_player_gets_public_discounted_extension_quotes() -> None:
    league = League.new(seed=24)
    player = _expiring_player(league)

    public_player = next(item for item in league.observation("preseason")["team"]["roster"] if item["id"] == player.id)

    assert list(public_player["extension_quotes"]) == ["2", "3", "4", "5"]
    assert public_player["extension_quotes"]["3"] == league._contract_quote(player, 3, incumbent=True)
    assert "extend_contract" in league.observation("preseason")["available_actions"]
    assert "extend_contract" not in league.observation("midseason")["available_actions"]


def test_incumbent_contract_quotes_exclude_one_year_terms() -> None:
    league = League.new(seed=24)
    player = _expiring_player(league)

    quotes = league._contract_quotes(player, incumbent=True)

    assert list(quotes) == ["2", "3", "4", "5"]
    assert "1" not in quotes


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


def test_new_one_year_signing_cannot_immediately_harvest_loyalty_discount() -> None:
    league = League.new(seed=24)
    league.cap = 1000.0
    player = league.players[league.free_agents[0]]

    results = league.apply_actions(
        [
            {
                "type": "sign_free_agent",
                "player_id": player.id,
                "years": 1,
                # Offer the willingness-adjusted published ask, which always lands.
                "salary": league._signing_quote(player, 1),
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


def test_summary_tier_inspection_publishes_extension_quote() -> None:
    league = League.new(seed=24)
    player = _expiring_player(league)

    result = league.apply_actions([{"type": "inspect_player", "player_id": player.id}], "preseason")[0]

    assert result.accepted
    assert result.data is not None
    assert result.data["player"]["extension_quotes"] == league._contract_quotes(player, incumbent=True)
    assert result.data["player"]["release_dead_cap"] == league._release_dead_cap_public(player)


def test_opponents_deterministically_retain_good_expiring_players() -> None:
    first = League.new(seed=24)
    second = League.new(seed=24)
    candidate = max(
        (
            first.players[player_id]
            for player_id in first.teams[1].roster
            if first.players[player_id].contract_years == 1
        ),
        key=lambda player: player.asset_value,
    )
    for league in (first, second):
        player = league.players[candidate.id]
        player.age = 24
        player.overall = 85.0
        player.potential = 90.0
    offset = first.rng_state_offset

    first._opponent_extensions(first.teams[1])
    second._opponent_extensions(second.teams[1])

    assert first.players[candidate.id].contract_years == 4
    assert first.players[candidate.id].salary == second.players[candidate.id].salary
    assert first.rng_state_offset == offset
