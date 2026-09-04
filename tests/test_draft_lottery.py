"""Tests for the v6 draft lottery and original-team pick identity."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from gm_bench.simulator import PLAYOFF_SPOTS, League


def ranked_league(seed: int = 7) -> League:
    """A league with a strict standings order: team 0 worst, team 11 best."""
    league = League.new(seed=seed)
    for team in league.teams.values():
        team.wins = team.id * 3
    return league


def test_lottery_draws_nonplayoff_teams_into_top_slots() -> None:
    league = ranked_league()
    league.run_draft_lottery()
    group_size = league.num_teams - PLAYOFF_SPOTS
    lottery_ids = {team_id for team_id in range(group_size)}
    # Non-playoff teams occupy the top slots in some drawn order; playoff
    # teams follow deterministically, worst record first.
    assert set(league.lottery_order[:group_size]) == lottery_ids
    assert league.lottery_order[group_size:] == list(range(group_size, league.num_teams))


def test_lottery_is_deterministic_per_seed_and_idempotent() -> None:
    first, second = ranked_league(seed=9), ranked_league(seed=9)
    first.run_draft_lottery()
    second.run_draft_lottery()
    assert first.lottery_order == second.lottery_order
    drawn = list(first.lottery_order)
    first.run_draft_lottery()  # second call in the same season must not redraw
    assert first.lottery_order == drawn


def test_worst_record_is_favored_but_never_guaranteed() -> None:
    winners = []
    for seed in range(1, 41):
        league = ranked_league(seed=seed)
        league.run_draft_lottery()
        winners.append(league.lottery_order[0])
    worst_team_wins = sum(1 for winner in winners if winner == 0)
    # Weight 4/10 for the worst record: clearly favored (binomial mean 16 of
    # 40), but other lottery teams must win the top slot sometimes.
    assert 8 <= worst_team_wins <= 28
    assert set(winners) - {0}, "no lottery team other than the worst ever won slot 1"


def test_traded_pick_is_exercised_at_original_teams_slot() -> None:
    league = ranked_league()
    season = league.season
    # The user finishes best in the league but holds the WORST team's pick
    # (acquired by trade), so it drafts at that team's lottery slot.
    league.teams[0].wins = 40
    league.teams[5].wins = 0
    league.teams[5].draft_picks[season] = []
    league.user_team.draft_picks[season] = [0, 5]
    class_size_before = len(league.prospects)
    league.run_opponent_draft(before_user=True)
    drafted_ahead = class_size_before - len(league.prospects)
    assert drafted_ahead == league.lottery_order.index(5)
    assert drafted_ahead < league.num_teams - PLAYOFF_SPOTS


def test_user_draft_spends_the_earliest_slot_pick_first() -> None:
    league = ranked_league()
    season = league.season
    league.teams[0].wins = 40  # the user's own pick projects last
    league.teams[5].wins = 0  # the acquired pick projects into the lottery
    league.teams[5].draft_picks[season] = []
    league.user_team.draft_picks[season] = [0, 5]
    league.run_draft_lottery()
    prospect_id = next(iter(league.prospects))
    league.apply_actions([{"type": "draft", "prospect_id": prospect_id}], "draft")
    assert league.transactions[-1].accepted
    # The acquired (earlier-slot) pick is consumed; the user's own remains.
    assert league.user_team.draft_picks[season] == [0]


def test_pick_transfer_moves_the_best_projected_origin_and_keeps_identity() -> None:
    league = ranked_league()
    season = league.season + 1
    giver, receiver = league.teams[3], league.user_team
    giver.draft_picks[season] = [1, 2]
    league.teams[1].wins = 50
    league.teams[2].wins = 0
    league._transfer_pick(giver, receiver, season)
    # The giver keeps the pick projected to be best (worst origin record) and
    # transfers the one whose original team has the most wins.
    assert giver.draft_picks[season] == [2]
    assert receiver.draft_picks[season] == [receiver.id, 1]


def test_observation_exposes_pick_identity_and_lottery_projection() -> None:
    league = ranked_league()
    future = league.season + 1
    league.teams[7].draft_picks[future] = []
    league.user_team.draft_picks[future] = [league.user_team_id, 7]
    observation = league.observation("preseason")
    lottery = observation["draft_lottery"]
    assert lottery["drawn"] is False
    assert len(lottery["slots"]) == league.num_teams
    assert lottery["lottery_slots"] == league.num_teams - PLAYOFF_SPOTS
    acquired = next(
        pick for pick in observation["team"]["picks"] if pick["season"] == future and pick["from_team_id"] == 7
    )
    assert acquired["from_team_name"] == league.teams[7].name
    assert acquired["projected_slot"] == 8  # team 7 is 8th worst in ranked_league
    assert all("pick_origins" in row for row in observation["standings"])


def test_draft_phase_observation_shows_drawn_lottery_and_validates() -> None:
    league = ranked_league()
    league.run_opponent_draft(before_user=True)
    observation = league.observation("draft")
    lottery = observation["draft_lottery"]
    assert lottery["drawn"] is True
    assert [slot["pick_from_team_id"] for slot in lottery["slots"]] == league.lottery_order
    schema = json.loads(Path("schemas/gm_observation.schema.json").read_text())
    jsonschema.validate(observation, schema)


def test_lottery_draw_flows_through_the_seeded_rng_stream() -> None:
    """The lottery must consume the league's seeded stream, not ambient RNG."""
    league = ranked_league(seed=11)
    offset_before = league.rng_state_offset
    league.run_draft_lottery()
    assert league.rng_state_offset == offset_before + 1
