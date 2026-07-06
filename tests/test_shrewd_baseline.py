"""Tests pinning the shrewd baseline as the strongest honest scripted agent."""

from __future__ import annotations

from statistics import mean

from gm_bench.agents import AGENTS, ExploitAgent, ShrewdAgent, ValueAgent
from gm_bench.runner import run_episode


def test_shrewd_is_registered() -> None:
    assert AGENTS["shrewd"] is ShrewdAgent


def test_shrewd_beats_value_on_shared_seeds() -> None:
    """Shrewd must dominate value per-seed (ties allowed) and win on average.

    This pins the skill bar: if a rules or scoring change makes the extra cap
    hygiene and development-aware lineups stop paying off, this test flags
    that the 'strongest baseline' claim no longer holds.
    """
    shrewd_scores: list[float] = []
    value_scores: list[float] = []
    for seed in (1, 2, 3):
        shrewd = run_episode(ShrewdAgent(), seed=seed, seasons=3)
        value = run_episode(ValueAgent(), seed=seed, seasons=3)
        assert shrewd.final_score >= value.final_score, f"value beat shrewd on seed {seed}"
        shrewd_scores.append(shrewd.final_score)
        value_scores.append(value.final_score)
    assert mean(shrewd_scores) > mean(value_scores)


def test_shrewd_plays_clean() -> None:
    result = run_episode(ShrewdAgent(), seed=1, seasons=5)
    assert result.illegal_actions == 0


def test_exploit_canary_stays_below_shrewd() -> None:
    exploit = run_episode(ExploitAgent(), seed=1, seasons=5)
    shrewd = run_episode(ShrewdAgent(), seed=1, seasons=5)
    assert exploit.final_score < shrewd.final_score
    assert exploit.strategy_score < shrewd.strategy_score
