import copy
import importlib.util
from pathlib import Path

from gm_bench.agents import AGENTS
from gm_bench.runner import run_episode
from gm_bench.simulator import League

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
