import importlib.util
import sys
from pathlib import Path

from gm_bench.simulator import League

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deep_dive = _load("score_deep_dive")
score_v2 = deep_dive.score_v2

GAMES_PER_SEASON = 33


def _played(name: str = "pick-trader", seed: int = 11, dice: int = 0) -> League:
    score_v2.install_hooks()
    return deep_dive.play(name, seed, dice)


def test_term_vector_rebuilds_the_candidate_scores():
    league = _played()
    raw = deep_dive.raw_terms(league)
    scores = score_v2.variant_scores(league)
    for candidate in ("v1", "C", "D"):
        assert abs(deep_dive.score(raw, candidate) - scores[candidate]) < 1e-9


def test_records_reset_gives_each_season_its_own_record():
    deep_dive.install_records_reset()
    try:
        league = _played()
    finally:
        deep_dive.uninstall_records_reset()
    assert not getattr(League, "_records_reset_hooked", False)
    wins = deep_dive.season_wins(league)
    assert wins == [summary.wins for summary in league.summaries]
    assert all(summary.wins + summary.losses == GAMES_PER_SEASON for summary in league.summaries)
    # Without the hook the summaries are running totals.
    assert _played().summaries[-1].wins > GAMES_PER_SEASON


def test_redrawn_dice_keep_the_initial_league():
    same, redrawn = League.new(seed=11), League.new(seed=11)
    assert [p.true_potential for p in same.players.values()] == [p.true_potential for p in redrawn.players.values()]
    assert _played(dice=1).summaries[-1].wins != _played().summaries[-1].wins


def test_continuation_shares_dice_on_the_same_seed():
    first, second = _played(), _played()
    assert deep_dive.continue_seasons(first, seasons=2) == deep_dive.continue_seasons(second, seasons=2)
    assert len(first.summaries) == 7


def test_least_squares_recovers_exact_weights():
    rows = [[1.0, x, x * x - 3 * x] for x in range(6)]
    target = [2.0 + 0.5 * r[1] - 1.5 * r[2] for r in rows]
    assert [round(c, 9) for c in deep_dive.least_squares(rows, target)] == [2.0, 0.5, -1.5]
