from __future__ import annotations

import pytest

from gm_bench.simulator import (
    DEAD_CAP_FRACTION,
    DEAD_CAP_MAX_SEASONS,
    EXPIRY_SCRAMBLE_CANDIDATES,
    MARKET_INFLATION,
    League,
)


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


def test_unextended_top_expiring_player_can_be_lost_to_a_rival() -> None:
    """Letting a good player's contract lapse without extending him must hurt.

    A star who is not extended in his walk-year preseason plays out his final
    year, then expires to free agency at season end. Right there, before the
    user gets another decision window, rivals get one signing look at the
    best expiring players leaguewide (`_expiry_market_scramble`). He can end
    up on another team entirely, not just sitting in the pool for the user to
    re-sign later at the same price.
    """
    league = League.new(seed=24)
    league.cap = 1000.0
    player = _expiring_player(league)
    player.overall = 91.0
    player.potential = 91.0
    player.true_potential = 91.0

    league.simulate_season()

    assert player.team_id is not None
    assert player.team_id != league.user_team_id
    assert player.id not in league.free_agents
    assert player.id not in league.user_team.roster


def test_extending_before_expiry_removes_the_walk_year_risk() -> None:
    """The same star, extended in the window, never enters the open market."""
    league = League.new(seed=24)
    league.cap = 1000.0
    player = _expiring_player(league)
    player.overall = 91.0
    player.potential = 91.0
    player.true_potential = 91.0
    quote = league._contract_quote(player, 4, incumbent=True)
    result = league.apply_actions(
        [{"type": "extend_contract", "player_id": player.id, "years": 4, "salary": quote}],
        "preseason",
    )[0]
    assert result.accepted

    league.simulate_season()

    assert player.id in league.user_team.roster
    assert player.team_id == league.user_team_id


def test_expiry_scramble_never_touches_a_player_outside_the_top_n() -> None:
    """The rival scramble is bounded to the best expiring players leaguewide.

    A full season's worth of ordinary short-deal expiries can number in the
    dozens; scrambling all of them would swamp the extend-or-lose decision
    with unrelated churn. Give the scramble more free agents than
    `EXPIRY_SCRAMBLE_CANDIDATES`, all attractive enough to be signed, and the
    lowest-ranked one (outside the top N) must be left alone entirely,
    independent of whether any opponent would have wanted him.
    """
    league = League.new(seed=24)
    league.cap = 1000.0
    fa_ids = league.free_agents[: EXPIRY_SCRAMBLE_CANDIDATES + 2]
    for rank, player_id in enumerate(fa_ids):
        league.players[player_id].overall = 80.0 - rank
    excluded_id = fa_ids[-1]

    league._expiry_market_scramble(fa_ids, league._rng("test_scramble"))

    assert excluded_id in league.free_agents


def test_observation_publishes_the_expiry_risk_rule() -> None:
    league = League.new(seed=24)

    rules = league.observation("preseason")["rules"]["contracts"]

    assert rules["expiry_scramble_candidates"] == EXPIRY_SCRAMBLE_CANDIDATES
    assert isinstance(rules["expiry_risk"], str)
    assert str(EXPIRY_SCRAMBLE_CANDIDATES) in rules["expiry_risk"]


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


def _contender_with_expiring_star(seed: int = 24) -> tuple[League, "object"]:
    """A winning team holding a veteran final-year player who cracks its lineup.

    This is the exact situation the release-and-re-sign arbitrage targeted:
    the willingness discount is at its deepest for a contender offering a
    lineup role to a veteran.
    """
    league = League.new(seed=seed)
    league.cap = 1000.0
    league.user_team.wins, league.user_team.losses = 60, 10
    player = _expiring_player(league)
    player.age = 30
    return league, player


def test_contender_cannot_release_and_resign_its_own_expiring_player() -> None:
    """Releasing a final-year player must not be a cheaper extension.

    A contender's free-agent quotes carry the willingness discount (down to
    0.88) and one less year of inflation than the extension quote, so a
    release-then-re-sign round trip used to buy the same player back for
    roughly 10% under his loyalty-discounted extension price against a single
    bounded dead-cap charge. The price gap is asserted here to show the
    incentive is still live; the rule is what closes it.
    """
    league, player = _contender_with_expiring_star()
    extension_quote = league._contract_quote(player, 3, incumbent=True)

    released = league.apply_actions([{"type": "release", "player_id": player.id}], "preseason")[0]
    assert released.accepted
    free_agent_quote = league._signing_quote(player, 3)
    # The arbitrage the rule exists to kill: buying him back is cheaper than
    # keeping him.
    assert free_agent_quote < extension_quote

    result = league.apply_actions(
        [{"type": "sign_free_agent", "player_id": player.id, "years": 3, "salary": free_agent_quote}],
        "preseason",
    )[0]

    assert not result.accepted
    assert "will not re-sign with you until next season" in result.message
    assert player.id not in league.user_team.roster
    assert player.id in league.free_agents
    # Nor does paying full freight, or waiting for a later window in the same
    # season, buy him back.
    league.begin_decision_window()
    retry = league.apply_actions(
        [{"type": "sign_free_agent", "player_id": player.id, "years": 3, "salary": extension_quote * 2}],
        "midseason",
    )[0]
    assert not retry.accepted
    assert player.id not in league.user_team.roster


def test_release_and_resign_block_lifts_at_the_next_season() -> None:
    """The block is a one-season penalty, not a permanent blacklist."""
    league, player = _contender_with_expiring_star()
    assert league.apply_actions([{"type": "release", "player_id": player.id}], "preseason")[0].accepted
    assert (league.user_team_id, player.id) in league.released_by

    league.simulate_season()

    assert league.released_by == set()
    # The property under test only means anything while he is still available,
    # so the precondition is asserted rather than branched on: if a rival ever
    # signs him during the rollover the test fails instead of passing vacuously.
    assert player.id in league.free_agents
    result = league.apply_actions(
        [
            {
                "type": "sign_free_agent",
                "player_id": player.id,
                "years": 1,
                "salary": league._signing_quote(player, 1),
            }
        ],
        "preseason",
    )[0]
    assert result.accepted


def test_releasing_a_bad_contract_and_signing_a_rivals_castoff_still_work() -> None:
    """The rule must not touch the two legitimate flows it sits next to."""
    league = League.new(seed=24)
    league.cap = 1000.0
    bad_contract = league.players[league.user_team.roster[0]]
    bad_contract.contract_years = 3
    bad_contract.salary = 20.0

    released = league.apply_actions([{"type": "release", "player_id": bad_contract.id}], "preseason")[0]
    assert released.accepted
    assert bad_contract.id not in league.user_team.roster

    # A player another team dropped is signable by the user at once.
    rival = league.teams[1]
    rival.roster.extend(league.free_agents[:6])
    for player_id in rival.roster:
        league.players[player_id].team_id = rival.id
        if player_id in league.free_agents:
            league.free_agents.remove(player_id)
    league._trim_expiring_contracts(rival, league._rng("test_trim"))
    castoff_id = next(pid for team_id, pid in league.released_by if team_id == rival.id)

    result = league.apply_actions(
        [
            {
                "type": "sign_free_agent",
                "player_id": castoff_id,
                "years": 1,
                "salary": league._signing_quote(league.players[castoff_id], 1),
            }
        ],
        "preseason",
    )[0]

    assert result.accepted
    assert castoff_id in league.user_team.roster


def test_opponents_cannot_re_sign_the_players_they_just_dropped() -> None:
    """The same rule binds the autopilot teams, so it is not a user-only tax."""
    league = League.new(seed=24)
    league.cap = 1000.0
    rival = league.teams[1]
    rival.roster.extend(league.free_agents[:6])
    for player_id in list(rival.roster):
        league.players[player_id].team_id = rival.id
        if player_id in league.free_agents:
            league.free_agents.remove(player_id)
    league._trim_expiring_contracts(rival, league._rng("test_trim"))
    dropped = [player_id for team_id, player_id in league.released_by if team_id == rival.id]
    assert dropped
    # Make the man they just dropped the most attractive free agent alive and
    # leave the rival short-handed, so only the rule can keep them apart.
    for player_id in dropped:
        league.players[player_id].overall = 95.0
    del rival.roster[18:]
    roster_before = len(rival.roster)

    league._opponent_signings(rival, league._rng("test_signings"))

    assert len(rival.roster) > roster_before
    assert not any(player_id in rival.roster for player_id in dropped)


def test_a_rival_dropping_the_same_player_does_not_lift_the_users_block() -> None:
    """Two teams can hold a block on one player at the same time.

    The release record used to be a player-to-team map, so a rival dropping a
    player the user had already released overwrote the user's block and handed
    back the release-then-re-sign discount for free.
    """
    league = League.new(seed=24)
    league.cap = 1000.0
    # A replacement-level body, so he is unambiguously the man the rival trims
    # when it needs a roster spot back.
    player = min((league.players[pid] for pid in league.user_team.roster), key=lambda item: item.asset_value)
    player.age, player.overall, player.potential = 38, 48.0, 48.0
    assert league.apply_actions([{"type": "release", "player_id": player.id}], "preseason")[0].accepted

    # A rival signs him and then trims him back to free agency in the same
    # season, writing its own release record over the top of the user's.
    rival = league.teams[1]
    league.free_agents.remove(player.id)
    player.team_id = rival.id
    player.contract_years = 1
    # A full rival roster of clearly better players plus him: the one spot the
    # preseason trim gives back is his.
    keep = sorted(rival.roster, key=lambda pid: league.players[pid].asset_value, reverse=True)[:23]
    for player_id in rival.roster:
        if player_id not in keep:
            league.players[player_id].team_id = None
        else:
            keeper = league.players[player_id]
            keeper.age = min(keeper.age, 27)
            keeper.overall = max(keeper.overall, 70.0)
            keeper.potential = max(keeper.potential, 70.0)
    rival.roster = [*keep, player.id]
    assert len(rival.roster) == 24
    assert min(league.players[pid].asset_value for pid in keep) > player.asset_value
    league._trim_expiring_contracts(rival, league._rng("test_trim"))

    assert (rival.id, player.id) in league.released_by
    assert (league.user_team_id, player.id) in league.released_by
    assert player.id in league.free_agents

    league.begin_decision_window()
    result = league.apply_actions(
        [
            {
                "type": "sign_free_agent",
                "player_id": player.id,
                "years": 3,
                "salary": league._signing_quote(player, 3) * 2,
            }
        ],
        "preseason",
    )[0]

    assert not result.accepted
    assert "will not re-sign with you until next season" in result.message
    assert player.id not in league.user_team.roster


def test_a_released_player_cannot_come_back_through_the_waiver_wire() -> None:
    """A waiver claim is a signing, so the release block covers it too."""
    league, player = _contender_with_expiring_star()
    assert league.apply_actions([{"type": "release", "player_id": player.id}], "preseason")[0].accepted

    # He reaches the wire the way any waived player does: a rival picks him up
    # and later drops him onto waivers.
    league.free_agents.remove(player.id)
    league.waiver_wire.append(player.id)

    league.begin_decision_window()
    result = league.apply_actions([{"type": "claim_waiver", "player_id": player.id}], "midseason")[0]

    assert not result.accepted
    assert "will not re-sign with you until next season" in result.message
    assert player.id not in league.user_team.roster
    assert player.id in league.waiver_wire


def test_trading_a_player_away_carries_his_contract_so_it_cannot_reprice() -> None:
    """The adjacent arbitrage — trade him out, buy him back — does not exist.

    A traded player keeps his salary and remaining term and never reaches free
    agency, so there is no cheaper price to re-acquire him at; getting him back
    costs trade value, not a discounted contract.
    """
    league, player = _contender_with_expiring_star()
    salary, years = player.salary, player.contract_years
    partner = league.teams[1]
    incoming = min((league.players[pid] for pid in partner.roster), key=lambda item: item.asset_value)

    result = league.apply_actions(
        [
            {
                "type": "trade",
                "partner_team_id": partner.id,
                "give_player_ids": [player.id],
                "receive_player_ids": [incoming.id],
            }
        ],
        "preseason",
    )[0]

    assert result.accepted
    assert player.id in partner.roster
    assert player.id not in league.free_agents
    assert player.salary == salary
    assert player.contract_years == years


def test_observation_publishes_the_release_resign_block() -> None:
    league, player = _contender_with_expiring_star()

    rules = league.observation("preseason")["rules"]["contracts"]
    assert "release" in rules["release_resign_block"].lower()

    assert league.apply_actions([{"type": "release", "player_id": player.id}], "preseason")[0].accepted
    card = next(item for item in league.observation("preseason")["free_agents"] if item["id"] == player.id)

    assert card["resign_blocked"] is True
    other = next(item for item in league.observation("preseason")["free_agents"] if item["id"] != player.id)
    assert "resign_blocked" not in other
