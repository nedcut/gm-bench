"""Tests for draft-pick trading."""

from __future__ import annotations

from gm_bench.models import PICK_TRADE_MAX_SEASONS_AHEAD, pick_value
from gm_bench.scoring import score_team
from gm_bench.simulator import League


def make_league(seed: int = 1) -> League:
    return League.new(seed=seed)


def find_accepted_pick_sale(league: League) -> dict | None:
    """Find a partner that accepts a decent player for a next-season pick."""
    roster = sorted(
        (league.players[player_id] for player_id in league.user_team.roster),
        key=lambda player: player.asset_value,
    )
    for player in roster:
        for partner_id in league.teams:
            if partner_id == league.user_team_id:
                continue
            action = {
                "type": "trade",
                "partner_team_id": partner_id,
                "give_player_ids": [player.id],
                "receive_player_ids": [],
                "give_pick_seasons": [],
                "receive_pick_seasons": [league.season + 1],
            }
            before = league.illegal_actions
            league.apply_actions([action], "preseason")
            if league.transactions[-1].accepted:
                return action
            league.illegal_actions = before  # probing, not judging
    return None


def test_player_for_pick_trade_transfers_ownership():
    league = make_league()
    action = find_accepted_pick_sale(league)
    assert action is not None, "no partner accepted any player-for-pick offer"
    partner = league.teams[action["partner_team_id"]]
    season = league.season + 1
    assert league.user_team.draft_picks[season] == 2
    assert partner.draft_picks[season] == 0
    assert action["give_player_ids"][0] in partner.roster


def test_pick_seasons_outside_window_rejected():
    league = make_league()
    partner_id = next(team_id for team_id in league.teams if team_id != league.user_team_id)
    give = [league.user_team.roster[0]]
    for bad_season in (league.season, league.season + PICK_TRADE_MAX_SEASONS_AHEAD + 1, 0):
        league.apply_actions(
            [
                {
                    "type": "trade",
                    "partner_team_id": partner_id,
                    "give_player_ids": give,
                    "receive_player_ids": [],
                    "receive_pick_seasons": [bad_season],
                }
            ],
            "preseason",
        )
        assert not league.transactions[-1].accepted
        assert "pick seasons must be between" in league.transactions[-1].message


def test_cannot_trade_more_picks_than_owned():
    league = make_league()
    partner_id = next(team_id for team_id in league.teams if team_id != league.user_team_id)
    season = league.season + 1
    league.apply_actions(
        [
            {
                "type": "trade",
                "partner_team_id": partner_id,
                "give_player_ids": [],
                "receive_player_ids": [],
                "give_pick_seasons": [season, season],
                "receive_pick_seasons": [season + 1],
            }
        ],
        "preseason",
    )
    assert not league.transactions[-1].accepted
    assert "does not own enough" in league.transactions[-1].message


def test_empty_side_rejected():
    league = make_league()
    partner_id = next(team_id for team_id in league.teams if team_id != league.user_team_id)
    league.apply_actions(
        [
            {
                "type": "trade",
                "partner_team_id": partner_id,
                "give_player_ids": [league.user_team.roster[0]],
                "receive_player_ids": [],
            }
        ],
        "preseason",
    )
    assert not league.transactions[-1].accepted
    assert "assets from both teams" in league.transactions[-1].message


def test_team_without_pick_skips_draft_and_double_pick_drafts_twice():
    league = make_league()
    season = league.season
    # Give team 1's current-season pick to team 2 directly (simulating a past trade).
    team_1, team_2 = league.teams[1], league.teams[2]
    team_1.draft_picks[season] = 0
    team_2.draft_picks[season] = 2
    sizes_before = {team.id: len(team.roster) for team in league.teams.values()}
    league.run_opponent_draft(before_user=True)
    league.run_opponent_draft(before_user=False)
    assert len(team_1.roster) == sizes_before[1]
    assert len(team_2.roster) == sizes_before[2] + 2


def test_far_future_pick_churn_is_score_neutral():
    """Materializing implicit far-future picks by swapping them must not mint score.

    The user gives its season+3 pick and receives the partner's season+3 pick:
    identical assets, so the score must not change at all.
    """
    league = make_league()
    partner_id = next(team_id for team_id in league.teams if team_id != league.user_team_id)
    far_season = league.season + PICK_TRADE_MAX_SEASONS_AHEAD
    before = score_team(league, league.user_team_id)
    league.apply_actions(
        [
            {
                "type": "trade",
                "partner_team_id": partner_id,
                "give_player_ids": [],
                "receive_player_ids": [],
                "give_pick_seasons": [far_season],
                "receive_pick_seasons": [far_season],
            }
        ],
        "preseason",
    )
    after = score_team(league, league.user_team_id)
    if league.transactions[-1].accepted:
        assert after == before
    else:
        # Rejection is also fine (bias made the swap unpalatable) — but it must
        # not have moved pick ownership.
        assert league.user_team.draft_picks.get(far_season, 1) == 1


def test_acquired_pick_raises_score():
    league = make_league()
    action = find_accepted_pick_sale(league)
    assert action is not None
    season = league.season + 1
    with_pick = score_team(league, league.user_team_id)
    league.user_team.draft_picks[season] -= 1  # counterfactually remove the acquired pick
    without_pick = score_team(league, league.user_team_id)
    league.user_team.draft_picks[season] += 1
    assert with_pick - without_pick > 0
    expected = pick_value(league.season, season) * 0.16
    assert abs((with_pick - without_pick) - expected) < 1e-6


def test_observation_exposes_pick_trading_rules():
    league = make_league()
    observation = league.observation("preseason")
    rules = observation["rules"]["pick_trading"]
    assert rules["max_seasons_ahead"] == PICK_TRADE_MAX_SEASONS_AHEAD
    assert len(rules["pick_value_estimate"]) == PICK_TRADE_MAX_SEASONS_AHEAD
    assert all("draft_picks" in row for row in observation["standings"])
