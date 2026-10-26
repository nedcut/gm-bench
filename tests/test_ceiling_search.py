import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gm_bench.agents import AGENTS
from gm_bench.runner import run_decision_point, run_episode
from gm_bench.simulator import League
from gm_bench.v21.rules import League21
from gm_bench.v21.rules import bracket_odds as bracket_odds_v21
from gm_bench.v21.runner import run_episode as run_episode_v21
from gm_bench.v21.scoring import score_team as score_team_v2

_SPEC = importlib.util.spec_from_file_location(
    "ceiling_search", Path(__file__).resolve().parents[1] / "scripts" / "ceiling_search.py"
)
ceiling_search = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ceiling_search)


def test_stepper_reproduces_the_runner():
    league = League.new(seed=11)
    assert round(ceiling_search.rollout(league, 0), 3) == run_episode(AGENTS["pick-trader"](), 11).final_score


def _advance_to_midseason(seed: int) -> League:
    league = League.new(seed=seed)
    ceiling_search.play_step(league, AGENTS["pick-trader"](), 0)
    league.prepare_midseason()
    return league


def test_sampled_world_ignores_hidden_state():
    real = _advance_to_midseason(11)
    tampered = copy.deepcopy(real)
    tampered.seed = 987654321
    for pool in (tampered.players, tampered.prospects):
        for player in pool.values():
            player.true_potential = 95.0 - player.true_potential / 2.0
            player.injured_games = 7
    assert real != tampered
    assert ceiling_search.sample_world(real, "midseason", 3) == ceiling_search.sample_world(tampered, "midseason", 3)


def test_sampled_worlds_differ_by_world_seed():
    real = _advance_to_midseason(11)
    assert ceiling_search.sample_world(real, "midseason", 1) != ceiling_search.sample_world(real, "midseason", 2)


def test_tracked_league_does_not_change_the_simulation():
    tracked = ceiling_search.new_league(11)
    plain = League.new(seed=11)
    assert ceiling_search.rollout(tracked, 0) == ceiling_search.rollout(plain, 0)
    assert sorted(tracked.expected_playoffs) == [1, 2, 3, 4, 5]


def test_bracket_odds_are_a_distribution():
    league = League.new(seed=11)
    teams = list(league.teams.values())[:8]
    ratings = {team.id: 50.0 + 3.0 * index for index, team in enumerate(teams)}
    odds = ceiling_search.bracket_odds(teams, ratings)
    assert abs(sum(title for _rounds, title in odds.values()) - 1.0) < 1e-9
    # 4 + 2 + 1 games are won in an eight-team bracket.
    assert abs(sum(rounds for rounds, _title in odds.values()) - 7.0) < 1e-9
    equal = ceiling_search.bracket_odds(teams, {team.id: 60.0 for team in teams})
    assert all(abs(title - 0.125) < 1e-9 and abs(rounds - 0.875) < 1e-9 for rounds, title in equal.values())


def test_generated_moves_are_built_from_the_observation():
    league = ceiling_search.new_league(11)
    observation = league.observation("preseason", tier="full")
    moves = ceiling_search.generated_moves(observation)
    assert any(name.startswith("sign:") for name in moves)
    # A generated move is played first and the base finishes the window.
    name, move = next((name, move) for name, move in moves.items() if name.startswith("sign:"))
    agent = ceiling_search.OneMoveThenBase(move)
    ceiling_search.play_step(league, agent, 0)
    assert any(t.action == move and t.accepted for t in league.transactions)
    assert league.illegal_actions == 0


def test_generated_moves_handle_a_short_roster():
    league = ceiling_search.new_league(11)
    observation = league.observation("preseason", tier="full")
    observation["team"]["roster"] = observation["team"]["roster"][:10]
    assert any(name.startswith("buy:") for name in ceiling_search.generated_moves(observation))


# --------------------------------------------------------------------------
# --contract 2.1: League21 and score-v2
# --------------------------------------------------------------------------


def test_v21_stepper_reproduces_the_v21_runner():
    league = ceiling_search.new_league(11, "2.1")
    assert isinstance(league, League21)
    expected = run_episode_v21(AGENTS["pick-trader"](), 11)["final_score"]
    assert round(ceiling_search.rollout(league, 0), 3) == expected


def test_v21_objective_is_score_v2_either_way():
    league = ceiling_search.new_league(11, "2.1")
    ceiling_search.rollout(league, 0)
    score = score_team_v2(league, league.user_team_id)
    assert ceiling_search.objective(league, luck_neutral=False) == score
    assert ceiling_search.objective(league, luck_neutral=True) == score
    assert ceiling_search.contract_score(league) == score


def test_v21_realized_playoff_score_swaps_only_the_playoff_terms():
    league = ceiling_search.new_league(11, "2.1")
    ceiling_search.rollout(league, 0)
    expected = ceiling_search.user_expected_playoffs(league)
    assert sorted(expected) == [1, 2, 3, 4, 5]
    recent = league.summaries[-3:]
    rounds_gap = sum(s.playoff_rounds - expected[s.season][0] for s in recent)
    titles_gap = league.user_team.championships - sum(title for _rounds, title in expected.values())
    gap = ceiling_search.realized_playoff_score(league) - ceiling_search.contract_score(league)
    assert abs(gap - (9.0 * rounds_gap + 35.0 * titles_gap)) < 1e-9


def test_luck_neutral_odds_are_score_v2_odds():
    # The 1.0 luck-neutral score and score-v2 must price a bracket the same way.
    league = League.new(seed=11)
    teams = list(league.teams.values())[:8]
    ratings = {team.id: 48.0 + 2.5 * index + (index % 3) for index, team in enumerate(teams)}
    assert ceiling_search.bracket_odds(teams, ratings) == bracket_odds_v21(teams, ratings)


def _advance_v21_to_midseason(seed: int) -> League21:
    league = ceiling_search.new_league(seed, "2.1")
    ceiling_search.play_step(league, AGENTS["pick-trader"](), 0)
    league.prepare_midseason()
    return league


def test_v21_sampled_world_ignores_hidden_state():
    real = _advance_v21_to_midseason(11)
    tampered = copy.deepcopy(real)
    tampered.seed = 987654321
    for pool in (tampered.players, tampered.prospects):
        for player in pool.values():
            player.true_potential = 95.0 - player.true_potential / 2.0
            player.injured_games = 7
    assert real != tampered
    world = ceiling_search.sample_world(real, "midseason", 3)
    assert isinstance(world, League21)
    assert world == ceiling_search.sample_world(tampered, "midseason", 3)


def test_v21_rejects_luck_neutral_flag():
    with pytest.raises(SystemExit):
        ceiling_search.main(["hindsight", "--contract", "2.1", "--luck-neutral", "--seeds", "101"])


# --------------------------------------------------------------------------
# Win-now policies, extension and buy moves, plan commitment (2.1 planner)
# --------------------------------------------------------------------------

planner = ceiling_search.planner


def _v21_at(seed: int, index: int) -> League21:
    """A 2.1 league played by `pick-trader` up to window `index`, pre-step done."""
    league = ceiling_search.new_league(seed, "2.1")
    agent = AGENTS["pick-trader"]()
    for step in range(index):
        ceiling_search.play_step(league, agent, step)
    ceiling_search._pre_step(league, index)
    return league


def _play_window(league: League, agent, index: int) -> None:
    run_decision_point(league, agent, ceiling_search.STEPS[index][1], ceiling_search.CONFIG)
    ceiling_search._finish_step(league, index)


def test_strength_of_matches_the_engine():
    league = _v21_at(11, 4)
    team = league.user_team
    for player_id in team.roster:
        league.players[player_id].injured_games = 0
    roster = [league.players[player_id].public_dict() for player_id in team.roster]
    for two_goalies in (True, False):
        lineup = planner.best_lineup(roster, two_goalies=two_goalies)
        assert planner.lineup_is_legal(lineup)
        team.lineup = [player["id"] for player in lineup]
        engine = league._team_strength(team, apply_injury_noise=False)
        assert abs(planner.strength_of(lineup, league._payroll(team), league.cap) - engine) < 0.05


def test_second_goalie_is_dressed_only_with_the_option():
    league = _v21_at(11, 4)
    roster = [league.players[player_id].public_dict() for player_id in league.user_team.roster]
    goalies = sorted((p for p in roster if p["position"] == "G"), key=lambda p: -p["overall"])
    assert len(goalies) >= 2
    one = planner.best_lineup(roster, two_goalies=False)
    lowest_skater = min(p["overall"] for p in one if p["position"] != "G")
    # Without the option a second goalie dresses only if he ranks in by overall.
    assert sum(p["position"] == "G" for p in one) == 1 + (goalies[1]["overall"] > lowest_skater)
    two = planner.best_lineup(roster, two_goalies=True)
    assert planner.strength_of(two, 0.0, 1.0) >= planner.strength_of(one, 0.0, 1.0)


def test_public_rosters_are_the_inspect_team_payload():
    league = _v21_at(11, 1)
    rosters = planner.public_rosters(league)
    probe = copy.deepcopy(league)
    assert league.user_team_id not in rosters
    for team_id, roster in rosters.items():
        result = probe._inspect_team({"type": "inspect_team", "team_id": team_id}, "midseason")
        assert result.data["roster"] == roster


def test_extension_moves_use_published_quotes_and_go_through():
    league = _v21_at(12, 4)  # season 2 preseason
    observation = copy.deepcopy(league).observation("preseason", tier="full")
    moves = planner.extension_moves(observation)
    assert "extend-core" in moves
    quotes = {p["id"]: p.get("extension_quotes") for p in observation["team"]["roster"]}
    years = planner.contract_years_to_end(2, extension=True)
    assert years == 5
    for actions in moves.values():
        for action in actions:
            assert action["years"] == years
            assert action["salary"] == quotes[action["player_id"]][str(years)]
    _play_window(league, ceiling_search.OneMoveThenBase(moves["extend-core"]), 4)
    extended = [t for t in league.transactions if t.team_id == 0 and t.action.get("type") == "extend_contract"]
    assert len(extended) >= len(moves["extend-core"]) and all(t.accepted for t in extended)
    assert league.illegal_actions == 0
    # Never offered outside the preseason, where extending is illegal.
    assert planner.extension_moves({**observation, "phase": "midseason"}) == {}


def test_buy_moves_are_legal_trades_for_picks_and_bench_players():
    league = _v21_at(12, 5)  # season 2 midseason
    observation = copy.deepcopy(league).observation("midseason", tier="full")
    moves = planner.buy_moves(observation, planner.public_rosters(league))
    assert moves
    for name, (trade,) in moves.items():
        assert name == f"buy-now:{trade['receive_player_ids'][0]}"
        assert trade["give_pick_seasons"] or trade["give_player_ids"]
        trial = copy.deepcopy(league)
        trial.begin_decision_window()
        (result,) = trial.apply_actions([trade], "midseason")
        # Accepted, or declined on the hidden valuation: never a penalized move.
        assert result.accepted or trial.rejected_offers == 1
        assert trial.illegal_actions == 0


@pytest.mark.parametrize("label", ["contend", "contend-nobuy", "contend-extend", "contend-1g"])
def test_win_now_policies_play_legally(label):
    league = ceiling_search.new_league(11, "2.1")
    ceiling_search.rollout(league, 0, label)
    assert league.illegal_actions == 0
    own = [t for t in league.transactions if t.team_id == 0 and t.accepted]
    count = {kind: sum(t.action.get("type") == kind for t in own) for kind in ("extend_contract", "trade")}
    assert count["extend_contract"] >= 10
    assert (count["trade"] > 0) == (label in ("contend", "contend-1g"))
    signings = sum(t.action.get("type") == "sign_free_agent" for t in own)
    assert (signings == 0) == (label == "contend-extend")


def test_default_menu_is_unchanged():
    league = _v21_at(11, 4)
    menu = ceiling_search.fair_menu(league, 4, True)
    assert not any(name.startswith(("plan:", "extend", "buy-now:", "contend")) for name in menu)
    assert set(ceiling_search.candidate_moves(hindsight=False)) == {
        *ceiling_search.PUBLIC_POLICIES,
        *(f"pick-trader-no-{drop}" for drop in ceiling_search.DROPPABLE),
    }


def test_commit_candidates_hand_over_to_their_plan():
    league = _v21_at(12, 4)
    menu = ceiling_search.fair_menu(league, 4, True, menu="extended", plan="contend", commit=True)
    assert "plan:pick-trader" in menu and "plan:contend-nobuy" in menu and "plan:contend" not in menu
    assert "extend-core" in menu and any(name.startswith("buy-now:") for name in menu)
    assert ceiling_search.continuation_of("plan:contend-nobuy", "pick-trader") == "contend-nobuy"
    assert ceiling_search.continuation_of("extend-core", "contend") == "contend"
    # A generated move is finished by the plan, not by pick-trader.
    assert menu["extend-core"]().base.name == "contend"
    # Without win-now policies on the menu, only the scripted policies are plans.
    base = ceiling_search.fair_menu(league, 4, False, commit=True)
    assert {name for name in base if name.startswith("plan:")} == {
        f"plan:{name}" for name in ceiling_search.PUBLIC_POLICIES if name != "pick-trader"
    }


def test_v21_planner_paths_ignore_hidden_state():
    # Season 5 preseason: extension, buy and commit candidates are all on the menu.
    real = _v21_at(12, 16)
    tampered = copy.deepcopy(real)
    tampered.seed = 987654321
    for pool in (tampered.players, tampered.prospects):
        for player in pool.values():
            player.true_potential = 95.0 - player.true_potential / 2.0
            player.injured_games = 7
    assert real != tampered
    kwargs = {"generated": True, "menu": "extended", "plan": "contend", "commit": True}
    outcomes, menu = ceiling_search.menu_outcomes(real, 16, 2, 0, **kwargs)
    assert "extend-core" in menu and "plan:pick-trader" in menu
    assert any(name.startswith("buy-now:") for name in menu)
    assert ceiling_search.menu_outcomes(tampered, 16, 2, 0, **kwargs)[0] == outcomes


def test_policy_mode_records_play_counts(tmp_path):
    out = tmp_path / "policy.json"
    argv = ["policy", "--contract", "2.1", "--policy", "contend", "--seeds", "11", "--out", str(out)]
    # A subprocess: the worker pool pickles `_run_seed`, which needs the real module.
    subprocess.run([sys.executable, _SPEC.origin, *argv], check=True, capture_output=True)
    summary = json.loads(out.read_text())
    assert summary["options"]["policy"] == "contend" and "menu" not in summary["options"]
    assert summary["play_means"]["moves"]["extend_contract"] > 0
    assert summary["illegal_actions_total"] == 0
    (row,) = summary["rows"]
    assert {"end_state", "baseline_end_state", "continuation_winning", "baseline_continuation_winning"} <= set(row)
    gap = row["continuation_winning"] - row["baseline_continuation_winning"]
    assert summary["continuation"]["winning_gap"]["mean"] == round(gap, 3)


def test_continuation_leaves_the_final_leagues_alone():
    league = ceiling_search.new_league(11, "2.1")
    ceiling_search.rollout(league, 0)
    before = copy.deepcopy(league)
    out = planner.continuation(league, league, ceiling_search.play_step)
    assert league == before
    assert out["end_state"] == out["baseline_end_state"]
    assert out["continuation_winning"] == out["baseline_continuation_winning"] > 0
