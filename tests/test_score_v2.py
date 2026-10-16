import importlib.util
import sys
from pathlib import Path

from gm_bench.agents import AGENTS
from gm_bench.runner import run_episode
from gm_bench.scoring import ACTIVE_SCORE_SCALE

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("score_v2", _SCRIPTS / "score_v2.py")
score_v2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(score_v2)

GAMES_PER_SEASON = 33


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_league():
    """The analysis hooks patch ``League`` for the whole process; undo them per test."""
    yield
    module = globals().get("score_v2") or globals()["deep_dive"].score_v2
    module.uninstall_hooks()
    if "deep_dive" in globals():
        globals()["deep_dive"].uninstall_records_reset()


def _played(seed: int = 11):
    score_v2.install_hooks()
    return score_v2.play(AGENTS["pick-trader"](), seed)


def test_hooks_leave_the_simulation_unchanged():
    league = _played()
    assert round(score_v2.variant_scores(league)["v1"], 3) == run_episode(AGENTS["pick-trader"](), 11).final_score


def test_per_season_wins_undo_the_running_total():
    league = _played()
    own = score_v2.per_season_wins(league)
    assert len(own) == 5
    assert sum(own) == league.summaries[-1].wins
    # Records never reset, so each summary is the running total.
    assert all(0 <= wins <= GAMES_PER_SEASON for wins in own)


def test_expected_wins_cover_every_user_game():
    league = _played()
    expected = league.expected_wins
    assert sorted(expected) == [1, 2, 3, 4, 5]
    assert all(0.0 < value < GAMES_PER_SEASON for value in expected.values())


def test_variants_differ_only_in_the_swapped_terms():
    league = _played()
    scores = score_v2.variant_scores(league)
    own = sum(score_v2.per_season_wins(league)[-3:])
    assert abs((scores["B"] - scores["A"]) - (own * ACTIVE_SCORE_SCALE.recent_win - scores["_cumulative_term"])) < 1e-9
    assert (
        abs((scores["C"] - scores["B"]) - own * (score_v2.PER_SEASON_RECENT_WIN - ACTIVE_SCORE_SCALE.recent_win)) < 1e-9
    )
