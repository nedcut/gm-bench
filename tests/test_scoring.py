"""Direct tests for the objective scoring function."""

from __future__ import annotations

from gm_bench.agents import ValueAgent
from gm_bench.runner import run_episode
from gm_bench.scoring import score_team
from gm_bench.simulator import League


def test_score_increases_with_championships() -> None:
    league = League.new(seed=5)
    base = score_team(league, league.user_team_id)
    league.user_team.championships = 2
    assert score_team(league, league.user_team_id) > base


def test_illegal_actions_reduce_user_score() -> None:
    league = League.new(seed=5)
    base = score_team(league, league.user_team_id)
    league.illegal_actions = 3
    assert score_team(league, league.user_team_id) < base


def test_opponent_scores_ignore_illegal_actions() -> None:
    league = League.new(seed=5)
    opponent_id = 1 if league.user_team_id != 1 else 2
    league.illegal_actions = 5
    user_score = score_team(league, league.user_team_id)
    opponent_score = score_team(league, opponent_id)
    league.illegal_actions = 0
    assert score_team(league, opponent_id) == opponent_score
    assert score_team(league, league.user_team_id) > user_score


def test_final_episode_score_matches_scoring_function() -> None:
    result = run_episode(ValueAgent(), seed=9, seasons=2)
    league = League.new(seed=9)
    for _ in range(2):
        for phase in ["preseason", "trade_deadline", "draft"]:
            if phase == "draft":
                league.run_opponent_draft(before_user=True)
            league.apply_actions(ValueAgent().act(league.observation(phase)), phase)
            if phase == "preseason":
                league.run_autopilot_opponents()
            elif phase == "draft":
                league.run_opponent_draft(before_user=False)
        league.simulate_season()
    assert result.final_score == round(score_team(league, league.user_team_id), 3)
