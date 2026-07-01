from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from examples.claude_agent import build_command as build_claude_command
from examples.codex_agent import build_command as build_codex_command
from examples.gm_agent_common import parse_actions
from gm_bench.agents import ConservativeAgent, ValueAgent
from gm_bench.gui import _parse_seeds, agent_standings, dashboard_payload, run_from_request, score_history
from gm_bench.runner import run_episode, run_many
from gm_bench.simulator import League
from gm_bench.storage import log_payload


def test_episode_is_deterministic_for_same_seed() -> None:
    first = run_episode(ValueAgent(), seed=7, seasons=3)
    second = run_episode(ValueAgent(), seed=7, seasons=3)
    assert first.final_score == second.final_score
    assert first.wins == second.wins
    assert first.season_summaries == second.season_summaries


def test_observation_hides_true_potential() -> None:
    league = League.new(seed=11)
    encoded = json.dumps(league.observation("preseason"))
    assert "true_potential" not in encoded
    assert "draft_class" in encoded
    assert "trade_market" in encoded


def test_invalid_actions_are_penalized() -> None:
    league = League.new(seed=3)
    league.apply_actions([{"type": "sign_free_agent", "player_id": -999, "salary": 1, "years": 1}], "preseason")
    assert league.illegal_actions == 1
    assert league.transactions[-1].accepted is False


def test_value_agent_beats_randomish_floor_on_small_panel() -> None:
    value = run_many(ValueAgent(), seeds=[1, 2], seasons=3)
    conservative = run_many(ConservativeAgent(), seeds=[1, 2], seasons=3)
    assert value["summary"]["mean_score"] > 0
    assert conservative["summary"]["illegal_actions"] == 0


def test_cli_json_run() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "gm_bench", "run", "--agent", "value", "--seeds", "1", "--seasons", "1", "--json", "--no-log"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["agent"] == "value"
    assert payload["summary"]["mean_score"] > 0


def test_cli_evaluate_reports_normalized_score() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gm_bench",
            "evaluate",
            "--agent",
            "value",
            "--baselines",
            "random",
            "conservative",
            "--seeds",
            "1",
            "--seasons",
            "1",
            "--json",
            "--no-log",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["agent"] == "value"
    assert "score_lift" in payload["normalized"]
    assert len(payload["baselines"]) == 2


def test_storage_logs_episode_and_transactions(tmp_path: Path) -> None:
    payload = run_many(ValueAgent(), seeds=[1], seasons=1)
    run_id = log_payload("run", payload, tmp_path / "runs.sqlite")
    import sqlite3

    with sqlite3.connect(tmp_path / "runs.sqlite") as connection:
        run_count = connection.execute("SELECT COUNT(*) FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        episode_count = connection.execute("SELECT COUNT(*) FROM episodes WHERE run_id = ?", (run_id,)).fetchone()[0]
        transaction_count = connection.execute("SELECT COUNT(*) FROM transactions WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert run_count == 1
    assert episode_count == 1
    assert transaction_count > 0


def test_gui_backend_runs_and_logs_to_db(tmp_path: Path) -> None:
    db_path = tmp_path / "gui.sqlite"
    payload = run_from_request({"mode": "run", "agent": "value", "seeds": "1", "seasons": 1}, db_path)
    dashboard = dashboard_payload(db_path)
    assert payload["run_id"]
    assert dashboard["metrics"]["runs"] == 1
    assert dashboard["metrics"]["episodes"] == 1
    assert dashboard["metrics"]["best_agent"] == "value"
    assert dashboard["metrics"]["mean_score"] > 0
    assert dashboard["leaderboard"][0]["agent"] == "value"
    assert dashboard["agent_standings"][0]["agent"] == "value"
    assert dashboard["insights"]


def test_gui_agent_standings_and_score_history(tmp_path: Path) -> None:
    db_path = tmp_path / "gui.sqlite"
    run_from_request({"mode": "compare", "agents": ["random", "value"], "seeds": "1-2", "seasons": 1}, db_path)
    standings = agent_standings(db_path)
    history = score_history(db_path)
    assert {row["agent"] for row in standings} == {"random", "value"}
    assert all(row["episodes"] == 2 for row in standings)
    assert all("range" in row for row in standings)
    assert len(history) == 4
    assert {"agent", "seed", "final_score", "created_at"} <= set(history[0])


def test_gui_parse_seed_ranges() -> None:
    assert _parse_seeds("1-3, 5") == [1, 2, 3, 5]


def test_model_action_parser_accepts_actions_object() -> None:
    actions = parse_actions('{"actions":[{"type":"noop"}]}')
    assert actions == [{"type": "noop"}]


def test_model_action_parser_rejects_untyped_objects() -> None:
    try:
        parse_actions('{"F":12,"D":4,"G":2}')
    except ValueError:
        return
    raise AssertionError("parser should reject JSON objects without typed actions")


def test_coding_agent_schema_exists() -> None:
    schema_path = Path("schemas/gm_actions.schema.json")
    payload = json.loads(schema_path.read_text())
    assert payload["required"] == ["actions"]
    assert "draft" in payload["properties"]["actions"]["items"]["properties"]["type"]["enum"]


def test_protocol_schemas_exist_and_are_valid_json() -> None:
    for name in ("gm_observation.schema.json", "gm_action_list.schema.json", "gm_actions.schema.json"):
        payload = json.loads((Path("schemas") / name).read_text())
        assert "$schema" in payload


def test_sample_observation_matches_protocol_shape() -> None:
    league = League.new(seed=42)
    observation = league.observation("preseason")
    required = {
        "benchmark",
        "seed",
        "season",
        "phase",
        "rules",
        "team",
        "standings",
        "free_agents",
        "draft_class",
        "trade_market",
        "history",
        "recent_transactions",
    }
    assert required <= set(observation)
    assert "true_potential" not in json.dumps(observation)


def test_sample_observation_validates_against_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    league = League.new(seed=42)
    observation = league.observation("preseason")
    schema = json.loads(Path("schemas/gm_observation.schema.json").read_text())

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(observation, schema)


def test_coding_agent_commands_are_non_interactive() -> None:
    codex_command = build_codex_command()
    claude_command = build_claude_command('{"actions":[{"type":"noop"}]}')
    assert codex_command[:3] == ["codex", "--ask-for-approval", "never"]
    assert "--ephemeral" in codex_command
    assert "--output-schema" in codex_command
    assert claude_command[:2] == ["claude", "-p"]
    assert "--no-session-persistence" in claude_command
    assert "--json-schema" in claude_command


def test_coding_agent_effort_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_EFFORT", "high")
    monkeypatch.setenv("CLAUDE_EFFORT", "high")
    codex_command = build_codex_command()
    claude_command = build_claude_command('{"actions":[{"type":"noop"}]}')
    assert 'model_reasoning_effort="high"' in codex_command
    assert claude_command[claude_command.index("--effort") + 1] == "high"
