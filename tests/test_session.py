from __future__ import annotations

import json
import random
import shlex
import sys

import pytest

from examples.gm_agent_common import emit
from gm_bench.protocol import EpisodeConfig
from gm_bench.runner import run_episode
from gm_bench.session import PersistentProcessAgent
from gm_bench.simulator import League


def _session_command(script_path: str) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(script_path)}"


def test_emit_always_uses_session_safe_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    emit([{"type": "noop"}])

    assert json.loads(capsys.readouterr().out) == {"actions": [{"type": "noop"}], "usage": None}


def test_persistent_agent_times_out_without_hanging(tmp_path) -> None:
    script = tmp_path / "hung_agent.py"
    script.write_text(
        "import sys, time\nfor line in sys.stdin:\n    if 'observation' in line:\n        time.sleep(60)\n",
        encoding="utf-8",
    )
    agent = PersistentProcessAgent(_session_command(str(script)), timeout_seconds=0.05)

    agent.start_episode(seed=1, seasons=1)
    try:
        actions = agent.act({"phase": "preseason"})
    finally:
        agent.end_episode()

    assert actions[0]["type"] == "noop"
    assert "timed out" in actions[0]["error"]


def test_persistent_agent_stderr_cannot_block_actions(tmp_path) -> None:
    script = tmp_path / "noisy_agent.py"
    script.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    event = json.loads(line)\n"
        "    if event['event'] == 'observation':\n"
        "        sys.stderr.write('x' * 200_000)\n"
        "        sys.stderr.flush()\n"
        "        print(json.dumps({'actions': [{'type': 'noop'}], 'usage': None}), flush=True)\n"
        "    elif event['event'] == 'end':\n"
        "        break\n",
        encoding="utf-8",
    )
    agent = PersistentProcessAgent(_session_command(str(script)), timeout_seconds=2)

    agent.start_episode(seed=1, seasons=1)
    try:
        actions = agent.act({"phase": "preseason"})
    finally:
        agent.end_episode()

    assert actions == [{"type": "noop"}]


def test_persistent_agent_preserves_usage_envelope(tmp_path) -> None:
    script = tmp_path / "usage_agent.py"
    script.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    event = json.loads(line)\n"
        "    if event['event'] == 'observation':\n"
        "        print(json.dumps({'actions': [{'type': 'noop'}], "
        "'usage': {'provider': 'test', 'total_tokens': 12}}), flush=True)\n"
        "    elif event['event'] == 'end':\n"
        "        break\n",
        encoding="utf-8",
    )
    agent = PersistentProcessAgent(_session_command(str(script)), timeout_seconds=2)

    agent.start_episode(seed=1, seasons=1)
    try:
        actions, usage = agent.act_with_usage({"phase": "preseason"})
    finally:
        agent.end_episode()

    assert actions == [{"type": "noop"}]
    assert usage == {"provider": "test", "total_tokens": 12}


def test_run_episode_cleans_up_when_persistent_start_fails() -> None:
    class FailingStartAgent(PersistentProcessAgent):
        def __init__(self) -> None:
            super().__init__("unused")
            self.cleaned_up = False

        def start_episode(self, seed: int, seasons: int) -> None:
            raise RuntimeError("startup failed")

        def end_episode(self) -> None:
            self.cleaned_up = True

    agent = FailingStartAgent()

    with pytest.raises(RuntimeError, match="startup failed"):
        run_episode(agent, seed=1, seasons=1, config=EpisodeConfig())

    assert agent.cleaned_up


def test_injured_player_is_unavailable_until_games_expire() -> None:
    league = League.new(seed=4)
    home = league.user_team
    away = league.teams[1]
    for player in league.players.values():
        player.injury_risk = 0.0
        player.injured_games = 0
    star = max(league._effective_lineup(home), key=lambda player: player.overall)
    healthy_strength = league._team_strength(home, apply_injury_noise=False)
    star.injured_games = 1
    injured_strength = league._team_strength(home, apply_injury_noise=False)
    ratings = {team.id: league._team_strength(team, apply_injury_noise=False) for team in league.teams.values()}

    league._play_game(home, away, ratings, random.Random(0))

    assert injured_strength < healthy_strength
    assert star.injured_games == 0
    assert ratings[home.id] == pytest.approx(healthy_strength)
