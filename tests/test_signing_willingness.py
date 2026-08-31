"""Free agents price the signing team, not just themselves (v6).

Winning, a plausible lineup role, and money form one published composite:
`signing_appeal.quote_multiplier`. A contender with a lineup spot gets a
discount, a rebuilder offering a bench seat pays a premium (sharpest for
veterans), and offering the published adjusted quote always succeeds.
"""

from __future__ import annotations

from gm_bench.simulator import (
    FA_ROLE_APPEAL_WEIGHT,
    FA_VETERAN_AGE,
    FA_WIN_APPEAL_WEIGHT,
    FA_YOUNG_WIN_SENSITIVITY,
    League,
    Player,
)


def _set_user_record(league: League, wins: int, losses: int) -> None:
    league.user_team.wins = wins
    league.user_team.losses = losses
    # Quotes freeze per decision window; a new record means a new window.
    league.begin_decision_window()


def _free_agent(league: League, *, veteran: bool) -> Player:
    for player_id in league.free_agents:
        player = league.players[player_id]
        if (player.age >= FA_VETERAN_AGE) == veteran:
            return player
    raise AssertionError("league seed has no matching free agent")


def test_contender_gets_a_discount_and_rebuilder_pays_a_premium_for_veterans() -> None:
    league = League.new(seed=5)
    veteran = _free_agent(league, veteran=True)
    market = league._contract_quote(veteran, 1)

    _set_user_record(league, 20, 2)
    contender_quote = league._signing_quote(veteran, 1)
    _set_user_record(league, 2, 20)
    rebuilder_quote = league._signing_quote(veteran, 1)

    # For a veteran the win component (|signal| ~0.82 * 0.08) outweighs the
    # role component (0.04) in either direction, so the ordering is strict.
    assert contender_quote < market < rebuilder_quote


def test_veterans_weigh_winning_more_than_young_players() -> None:
    league = League.new(seed=5)
    veteran = _free_agent(league, veteran=True)
    young = _free_agent(league, veteran=False)

    spreads = {}
    for player in (veteran, young):
        _set_user_record(league, 20, 2)
        winning = league._signing_appeal(player, league.user_team)["quote_multiplier"]
        _set_user_record(league, 2, 20)
        losing = league._signing_appeal(player, league.user_team)["quote_multiplier"]
        spreads[player.id] = losing - winning

    # Role appeal cancels in the spread, isolating win sensitivity: full
    # weight for veterans, FA_YOUNG_WIN_SENSITIVITY for younger players.
    assert spreads[veteran.id] > spreads[young.id]
    # Published multipliers round to 3 decimals, so the sensitivity ratio is
    # only approximately 1 / FA_YOUNG_WIN_SENSITIVITY.
    assert abs(spreads[veteran.id] / spreads[young.id] - 1.0 / FA_YOUNG_WIN_SENSITIVITY) < 0.1


def test_lineup_role_discounts_and_depth_role_costs_a_premium() -> None:
    league = League.new(seed=5)
    player = _free_agent(league, veteran=True)
    incumbents = [
        item.overall for item in league._effective_lineup(league.user_team) if item.position == player.position
    ]

    # Season one, 0-0 record: the win signal is neutral, so the multiplier is
    # exactly the role component in each direction.
    player.overall = max(incumbents) + 1.0
    starter = league._signing_appeal(player, league.user_team)
    assert starter["projected_role"] == "lineup"
    assert starter["quote_multiplier"] == round(1.0 - FA_ROLE_APPEAL_WEIGHT, 3)

    player.overall = min(incumbents) - 1.0
    league.begin_decision_window()
    buried = league._signing_appeal(player, league.user_team)
    assert buried["projected_role"] == "depth"
    assert buried["quote_multiplier"] == round(1.0 + FA_ROLE_APPEAL_WEIGHT, 3)


def test_published_premium_ask_is_still_always_accepted() -> None:
    league = League.new(seed=5)
    league.cap = 1000.0
    veteran = _free_agent(league, veteran=True)
    _set_user_record(league, 2, 20)
    public = league._free_agent_public(veteran.id)
    assert public["signing_appeal"]["quote_multiplier"] > 1.0

    result = league.apply_actions(
        [{"type": "sign_free_agent", "player_id": veteran.id, "years": 1, "salary": public["asking_salary"]}],
        "preseason",
    )[0]

    assert result.accepted
    assert veteran.salary == public["asking_salary"]


def test_signing_appeal_is_published_and_reconstructs_the_quote() -> None:
    league = League.new(seed=5)
    _set_user_record(league, 16, 6)
    observation = league.observation("preseason")

    rules = observation["rules"]["free_agency_willingness"]
    assert rules["win_appeal_weight"] == FA_WIN_APPEAL_WEIGHT
    assert rules["role_appeal_weight"] == FA_ROLE_APPEAL_WEIGHT
    assert rules["veteran_age"] == FA_VETERAN_AGE
    assert rules["young_win_sensitivity"] == FA_YOUNG_WIN_SENSITIVITY

    for public in observation["free_agents"]:
        appeal = public["signing_appeal"]
        assert appeal["projected_role"] in {"lineup", "depth"}
        assert public["asking_salary"] == round(public["market_asking_salary"] * appeal["quote_multiplier"], 2)
        for years, quote in public["contract_quotes"].items():
            source = league.players[public["id"]]
            assert quote == round(league._contract_quote(source, int(years)) * appeal["quote_multiplier"], 2)


def test_willingness_is_deterministic_across_replays() -> None:
    league_a = League.new(seed=11)
    league_b = League.new(seed=11)
    for league in (league_a, league_b):
        league.user_team.wins = 14
        league.user_team.losses = 8
    for player_id in league_a.free_agents:
        assert league_a._free_agent_public(player_id) == league_b._free_agent_public(player_id)


def test_incumbent_extension_pricing_ignores_willingness() -> None:
    """The extension-dominance inequality is balanced on pure market quotes;
    the willingness multiplier must never leak into incumbent pricing."""
    league = League.new(seed=5)
    incumbent = league.players[league.user_team.roster[0]]
    _set_user_record(league, 2, 20)
    losing = league._contract_reservation(incumbent.id, years=3, incumbent=True)
    _set_user_record(league, 20, 2)
    winning = league._contract_reservation(incumbent.id, years=3, incumbent=True)
    assert losing == winning


def test_quotes_freeze_for_the_length_of_a_decision_window() -> None:
    """A quote published in the observation is honored even after earlier
    actions in the same batch reshuffle the roster or standings."""
    league = League.new(seed=5)
    league.begin_decision_window()
    player = _free_agent(league, veteran=True)
    frozen = league._signing_appeal(player, league.user_team)

    league.user_team.wins = 20
    player.overall = 99.0
    assert league._signing_appeal(player, league.user_team) == frozen

    league.begin_decision_window()
    assert league._signing_appeal(player, league.user_team) != frozen


def test_opponent_teams_are_priced_by_the_same_rule() -> None:
    league = League.new(seed=5)
    veteran = _free_agent(league, veteran=True)
    contender, rebuilder = league.teams[1], league.teams[2]
    contender.wins, contender.losses = 20, 2
    rebuilder.wins, rebuilder.losses = 2, 20
    assert league._signing_quote(veteran, 1, contender) < league._signing_quote(veteran, 1, rebuilder)
