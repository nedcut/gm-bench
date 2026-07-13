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


def test_rescouting_fails_and_unknown_target_is_a_failed_query():
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


def test_scout_accepts_prospect_id_alias():
    """The scaffold advertises {"type":"scout","prospect_id":...}; it must work."""
    league = League.new(seed=3)
    prospect_id = next(iter(league.prospects))
    league.apply_actions([{"type": "scout", "prospect_id": prospect_id}], "preseason")
    assert league.transactions[-1].accepted
    assert prospect_id in league.scout_reports
    report = league.scout_reports[prospect_id]
    true_potential = league.prospects[prospect_id].true_potential
    assert abs(report - true_potential) <= SCOUT_REPORT_NOISE + 0.05


def test_scout_prospect_id_and_player_id_are_equivalent():
    """player_id and prospect_id share one id namespace: both resolve the same target."""
    prospect_id = next(iter(League.new(seed=3).prospects))
    via_prospect = League.new(seed=3)
    via_prospect.apply_actions([{"type": "scout", "prospect_id": prospect_id}], "preseason")
    via_player = League.new(seed=3)
    via_player.apply_actions([{"type": "scout", "player_id": prospect_id}], "preseason")
    assert via_prospect.transactions[-1].accepted
    assert via_player.transactions[-1].accepted
    assert via_prospect.scout_reports[prospect_id] == via_player.scout_reports[prospect_id]


def test_unknown_scout_target_is_a_failed_query_not_illegal():
    league = League.new(seed=3)
    illegal_before = league.illegal_actions
    failed_before = league.failed_queries
    league.apply_actions([{"type": "scout", "player_id": 999999999}], "preseason")
    transaction = league.transactions[-1]
    assert not transaction.accepted
    # The improved message echoes the id and does not mislead about accepted keys.
    assert "999999999" in transaction.message
    # A misfired lookup is telemetry, not a protocol violation.
    assert league.illegal_actions == illegal_before
    assert league.failed_queries == failed_before + 1


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
    # Midseason is now in the default episode; golden moved with P3+P5+P6.
    assert baseline.final_score == 338.254
