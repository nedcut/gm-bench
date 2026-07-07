from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from statistics import mean

import pytest

import gm_bench.runner as runner_module
from examples.claude_agent import build_command as build_claude_command
from examples.codex_agent import build_command as build_codex_command
from examples.gm_agent_common import parse_actions
from gm_bench.agents import ExternalProcessAgent, RandomAgent, ValueAgent
from gm_bench.gui import _parse_seeds, agent_standings, dashboard_payload, run_from_request, score_history
from gm_bench.runner import evaluate_against_baselines, run_episode, run_many
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


def test_observation_lineup_rules_match_validation() -> None:
    league = League.new(seed=11)
    rules = league.observation("preseason")["rules"]
    assert rules["lineup_size"] == 18
    assert rules["lineup_min_positions"] == {"F": 10, "D": 4, "G": 1}
    assert "positions" not in rules


def test_trade_market_uses_public_estimates_not_hidden_asset_value() -> None:
    league = League.new(seed=17)
    market = league.observation("trade_deadline")["trade_market"]
    encoded = json.dumps(market)
    assert "asset_value" not in encoded
    assert "true_potential" not in encoded
    for offer in market:
        player = league.players[offer["player"]["id"]]
        assert offer["estimated_price"] == League._public_trade_estimate(player)


def test_invalid_actions_are_penalized() -> None:
    league = League.new(seed=3)
    league.apply_actions([{"type": "sign_free_agent", "player_id": -999, "salary": 1, "years": 1}], "preseason")
    assert league.illegal_actions == 1
    assert league.transactions[-1].accepted is False


def test_trade_with_duplicate_ids_is_rejected_without_side_effects() -> None:
    league = League.new(seed=3)
    partner = league.teams[1]
    give_id = league.user_team.roster[0]
    receive_id = partner.roster[0]
    league.apply_actions(
        [
            {
                "type": "trade",
                "partner_team_id": 1,
                "give_player_ids": [give_id, give_id],
                "receive_player_ids": [receive_id],
            }
        ],
        "preseason",
    )
    assert league.transactions[-1].accepted is False
    assert give_id in league.user_team.roster
    assert give_id not in partner.roster
    assert league.players[give_id].team_id == league.user_team_id


def test_external_agent_timeout_returns_noop_instead_of_crashing() -> None:
    agent = ExternalProcessAgent(f"{sys.executable} -c 'import time; time.sleep(5)'", timeout_seconds=0.5)
    actions = agent.act({"phase": "preseason"})
    assert actions[0]["type"] == "noop"
    assert "timed out" in actions[0]["error"]


def test_external_agent_missing_command_returns_noop() -> None:
    agent = ExternalProcessAgent("this-command-does-not-exist-xyz")
    actions = agent.act({"phase": "preseason"})
    assert actions[0]["type"] == "noop"
    assert "could not be launched" in actions[0]["error"]


def test_external_agent_timeout_warns_when_too_low(capsys: pytest.CaptureFixture[str]) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gm_bench",
            "run",
            "--agent-cmd",
            f'{sys.executable} -c \'import json; print(json.dumps([{{"type":"noop"}}]))\'',
            "--agent-timeout",
            "5",
            "--seeds",
            "1",
            "--seasons",
            "1",
            "--no-log",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "warning:" in completed.stderr
    assert "--agent-timeout=5" in completed.stderr


def test_value_agent_beats_randomish_floor_on_small_panel() -> None:
    value = run_many(ValueAgent(), seeds=[1, 2], seasons=3)
    random = run_many(RandomAgent(), seeds=[1, 2], seasons=3)
    assert value["summary"]["mean_score"] > random["summary"]["mean_score"]
    assert value["summary"]["illegal_actions"] == 0


def test_parallel_run_many_matches_sequential_results() -> None:
    seeds = [1, 2, 3, 4]
    sequential = run_many(ValueAgent(), seeds=seeds, seasons=2, workers=1)
    parallel = run_many(ValueAgent(), seeds=seeds, seasons=2, workers=4)
    assert sequential["summary"] == parallel["summary"]
    assert {episode["seed"] for episode in sequential["episodes"]} == {
        episode["seed"] for episode in parallel["episodes"]
    }


def test_cli_json_run() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gm_bench",
            "run",
            "--agent",
            "value",
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
        transaction_count = connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
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


def test_paired_evaluation_reports_per_seed_lift_and_ci() -> None:
    seeds = [1, 2, 3]
    result = evaluate_against_baselines(ValueAgent(), seeds=seeds, seasons=2, baseline_names=["random", "conservative"])
    paired = result["paired"]
    assert paired["num_seeds"] == 3
    assert [row["seed"] for row in paired["per_seed"]] == seeds
    # The panel lift is exactly the average of the per-seed paired lifts.
    assert paired["paired_lift_mean"] == pytest.approx(mean(row["lift"] for row in paired["per_seed"]), abs=1e-3)
    # And it must agree with the unpaired panel lift on shared seeds. Both values
    # are independently rounded to 3 decimals, so they may differ by one ulp of
    # that rounding (0.001) even though the underlying quantity is identical.
    assert paired["paired_lift_mean"] == pytest.approx(result["normalized"]["score_lift"], abs=2e-3)
    low, high = paired["paired_lift_ci95"]
    assert low <= paired["paired_lift_mean"] <= high
    assert 0.0 <= paired["candidate_seed_win_rate"] <= 1.0
    assert paired["best_baseline"]["agent"] in {"random", "conservative"}
    # The strongest baseline is picked by the precise per-episode mean, so it must be
    # the baseline with the genuinely highest mean score, not a rounding artifact.
    baseline_means = {
        baseline["agent"]: mean(ep["final_score"] for ep in baseline["episodes"]) for baseline in result["baselines"]
    }
    assert paired["best_baseline"]["agent"] == max(baseline_means, key=baseline_means.get)


def test_evaluation_lift_uses_precise_episode_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_many(agent: object, seeds: list[int], seasons: int, **kwargs: object) -> dict[str, object]:
        del seasons, kwargs
        if getattr(agent, "name") == "value":
            scores = [1.0004 for _ in seeds]
            summary_score = 1.0
        else:
            scores = [0.9996 for _ in seeds]
            summary_score = 1.0
        return {
            "agent": getattr(agent, "name"),
            "summary": {
                "mean_score": summary_score,
                "mean_strategy_score": summary_score,
                "total_protocol_penalty": 0.0,
                "illegal_actions": 0,
                "decisions": 3 * len(seeds),
                "failed_decisions": 0,
                "decision_failure_rate": 0.0,
            },
            "episodes": [{"seed": seed, "final_score": score} for seed, score in zip(seeds, scores, strict=True)],
        }

    monkeypatch.setattr(runner_module, "run_many", fake_run_many)

    result = evaluate_against_baselines(
        ValueAgent(), seeds=[1, 2], seasons=1, baseline_names=["random"], use_baseline_cache=False
    )

    assert result["normalized"]["score_lift"] == pytest.approx(0.001)
    assert result["paired"]["paired_lift_mean"] == pytest.approx(result["normalized"]["score_lift"])


def test_cli_evaluate_prints_paired_section() -> None:
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
            "2",
            "--seasons",
            "1",
            "--no-log",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "paired_lift=" in completed.stdout
    assert "candidate_seed_win_rate=" in completed.stdout
    assert "vs strongest baseline" in completed.stdout


def test_paired_evaluation_is_deterministic() -> None:
    first = evaluate_against_baselines(ValueAgent(), seeds=[4, 5], seasons=2, baseline_names=["random", "conservative"])
    second = evaluate_against_baselines(
        ValueAgent(), seeds=[4, 5], seasons=2, baseline_names=["random", "conservative"]
    )
    assert first["paired"] == second["paired"]


def test_coding_agent_effort_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_EFFORT", "high")
    monkeypatch.setenv("CLAUDE_EFFORT", "high")
    codex_command = build_codex_command()
    claude_command = build_claude_command('{"actions":[{"type":"noop"}]}')
    assert 'model_reasoning_effort="high"' in codex_command
    assert claude_command[claude_command.index("--effort") + 1] == "high"
