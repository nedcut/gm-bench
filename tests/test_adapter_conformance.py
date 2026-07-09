"""End-to-end conformance: a protocol-perfect adapter must score clean.

Drives ``examples/conformance_agent.py`` through the real external-process
path — one-shot and persistent-session transports — and asserts the harness
records zero failures, zero illegal actions, zero protocol penalty, and usage
on every decision point. A regression here means harness/adapter plumbing can
corrupt a model's numbers, so adapter bugs would masquerade as model failure.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

from gm_bench.agents import ExternalProcessAgent
from gm_bench.protocol import EpisodeConfig
from gm_bench.runner import run_episode
from gm_bench.session import PersistentProcessAgent

CONFORMANCE_SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "conformance_agent.py"
COMMAND = f"{shlex.quote(sys.executable)} {shlex.quote(str(CONFORMANCE_SCRIPT))}"


def _assert_clean(result) -> None:
    assert result.failed_decisions == 0
    assert result.illegal_actions == 0
    assert result.protocol_penalty == 0
    assert result.usage["decisions_with_usage"] == result.decisions
    # One memo per decision window proves the memo action round-tripped.
    assert result.memo_writes == result.decisions


@pytest.mark.parametrize("seasons", [1, 2])
def test_one_shot_transport_records_clean_conformance_episode(seasons: int) -> None:
    agent = ExternalProcessAgent(COMMAND, timeout_seconds=30.0)
    result = run_episode(agent, seed=1, seasons=seasons, config=EpisodeConfig())
    assert result.decisions == seasons * 4  # preseason, midseason, trade_deadline, draft
    _assert_clean(result)


def test_session_transport_records_clean_conformance_episode() -> None:
    agent = PersistentProcessAgent(COMMAND, timeout_seconds=30.0)
    result = run_episode(agent, seed=1, seasons=2, config=EpisodeConfig(persistent_session=True))
    assert result.decisions == 8
    _assert_clean(result)


def test_transports_agree_on_the_played_episode() -> None:
    one_shot = run_episode(
        ExternalProcessAgent(COMMAND, timeout_seconds=30.0),
        seed=2,
        seasons=1,
        config=EpisodeConfig(),
    )
    session = run_episode(
        PersistentProcessAgent(COMMAND, timeout_seconds=30.0),
        seed=2,
        seasons=1,
        config=EpisodeConfig(persistent_session=True),
    )
    # The transport must never change the game: same deterministic agent, same
    # seed, same score.
    assert one_shot.final_score == session.final_score
    assert one_shot.strategy_score == session.strategy_score
    assert one_shot.wins == session.wins
