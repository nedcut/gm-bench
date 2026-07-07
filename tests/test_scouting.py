"""Tests for the scout action."""

from __future__ import annotations

from gm_bench.agents import ValueAgent
from gm_bench.runner import run_episode
from gm_bench.simulator import SCOUT_POINTS_PER_SEASON, SCOUT_REPORT_NOISE, League


def test_scout_report_is_near_true_potential():
    league = League.new(seed=3)
    prospect_id = next(iter(league.prospects))
    league.apply_actions([{"type": "scout", "player_id": prospect_id}], "preseason")
    assert league.transactions[-1].accepted
    report = league.scout_reports[prospect_id]
    true_potential = league.prospects[prospect_id].true_potential
    assert abs(report - true_potential) <= SCOUT_REPORT_NOISE + 0.05
    observation = league.observation("preseason")
    assert observation["scout_reports"][str(prospect_id)] == report
    assert observation["rules"]["scouting"]["points_remaining"] == SCOUT_POINTS_PER_SEASON - 1


def test_scout_points_are_limited_and_reset_each_season():
    league = League.new(seed=3)
    targets = list(league.prospects)[: SCOUT_POINTS_PER_SEASON + 1]
    for player_id in targets[:SCOUT_POINTS_PER_SEASON]:
        league.apply_actions([{"type": "scout", "player_id": player_id}], "preseason")
        assert league.transactions[-1].accepted
    league.apply_actions([{"type": "scout", "player_id": targets[-1]}], "preseason")
    assert not league.transactions[-1].accepted
    assert "no scouting points left" in league.transactions[-1].message
    league.simulate_season()
    roster_target = league.user_team.roster[0]
    league.apply_actions([{"type": "scout", "player_id": roster_target}], "preseason")
    assert league.transactions[-1].accepted


def test_rescouting_and_unknown_targets_are_illegal():
    league = League.new(seed=3)
    prospect_id = next(iter(league.prospects))
    league.apply_actions([{"type": "scout", "player_id": prospect_id}], "preseason")
    league.apply_actions([{"type": "scout", "player_id": prospect_id}], "preseason")
    assert not league.transactions[-1].accepted
    assert "already scouted" in league.transactions[-1].message
    league.apply_actions([{"type": "scout", "player_id": 999999999}], "preseason")
    assert not league.transactions[-1].accepted
    # Failed scouts consume no points.
    assert league.scout_points_used == 1


def test_reports_persist_across_seasons():
    league = League.new(seed=3)
    prospect_id = next(iter(league.prospects))
    league.apply_actions([{"type": "scout", "player_id": prospect_id}], "preseason")
    report = league.scout_reports[prospect_id]
    league.simulate_season()
    assert league.observation("preseason")["scout_reports"][str(prospect_id)] == report


def test_scouting_does_not_perturb_scripted_scores():
    """Scout RNG is stream-isolated: a non-scouting run must be unchanged."""
    baseline = run_episode(ValueAgent(), seed=1, seasons=5)
    assert baseline.final_score == 231.140
