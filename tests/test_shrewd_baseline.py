"""Tests pinning the shrewd baseline as a stronger-on-average honest reference."""

from __future__ import annotations

from statistics import mean

from gm_bench.agents import AGENTS, ExploitAgent, ShrewdAgent, ValueAgent
from gm_bench.runner import run_episode


def test_shrewd_is_registered() -> None:
    assert AGENTS["shrewd"] is ShrewdAgent


def test_shrewd_beats_value_on_average_across_seed_panel() -> None:
    """Shrewd must beat value on the panel mean, not on every seed.

    Its development-weighted lineups are a horizon bet that loses individual
    seeds (a wider 30-seed sweep shows ~7/30 losses but a +7 mean lift), so
    per-seed dominance would be an overfit claim. This pins the honest one:
    if a rules or scoring change makes the cap hygiene and youth dressing
    stop paying off *on average*, this test flags that shrewd is no longer a
    stronger reference than value.
    """
    # Contract decisions compound over the official five-season horizon, so
    # pin this ordering on the public panel rather than a shorter surrogate.
    lifts = [
        run_episode(ShrewdAgent(), seed=seed, seasons=5).final_score
        - run_episode(ValueAgent(), seed=seed, seasons=5).final_score
        for seed in range(11, 19)
    ]
    assert mean(lifts) > 0.0
    assert sum(1 for lift in lifts if lift >= 0) > len(lifts) / 2


def test_shrewd_plays_clean() -> None:
    result = run_episode(ShrewdAgent(), seed=1, seasons=5)
    assert result.illegal_actions == 0


def test_exploit_canary_stays_below_shrewd() -> None:
    exploit = run_episode(ExploitAgent(), seed=1, seasons=5)
    shrewd = run_episode(ShrewdAgent(), seed=1, seasons=5)
    assert exploit.final_score < shrewd.final_score
    assert exploit.strategy_score < shrewd.strategy_score
