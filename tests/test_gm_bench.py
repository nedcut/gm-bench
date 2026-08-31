from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from statistics import mean

import pytest

import gm_bench.cli as cli_module
import gm_bench.gui as gui_module
import gm_bench.runner as runner_module
from examples import gm_agent_common
from examples.claude_agent import build_command as build_claude_command
from examples.codex_agent import build_command as build_codex_command
from examples.gm_agent_common import build_prompt
from gm_bench.agent_utils import position_aware_lineup
from gm_bench.agents import ExternalProcessAgent, RandomAgent, ValueAgent
from gm_bench.gui import (
    _is_loopback_host,
    _parse_seeds,
    agent_standings,
    dashboard_payload,
    run_from_request,
    score_history,
    serve,
)
from gm_bench.repair import (
    RAW_TEXT_FIELD,
    RULE_STRIP_CODE_FENCE,
    RepairOutcome,
    repair_adapter_output,
)
from gm_bench.runner import evaluate_against_baselines, run_episode, run_many
from gm_bench.session import PersistentProcessAgent
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


def test_observation_drops_inert_morale_market_patience_fields() -> None:
    """morale, market, and patience were written and serialized but read by no
    mechanic (see docs/bench_v6_spec.md's survival test); they must be gone
    from both the model and the observation, not merely unused."""
    from dataclasses import fields

    from gm_bench.models import Player, Team

    assert "morale" not in {field.name for field in fields(Player)}
    assert "market" not in {field.name for field in fields(Team)}
    assert "patience" not in {field.name for field in fields(Team)}

    league = League.new(seed=11)
    observation = league.observation("preseason")
    encoded = json.dumps(observation)
    assert "morale" not in encoded
    assert '"market"' not in encoded
    assert "patience" not in encoded
    for player in observation["team"]["roster"]:
        assert "morale" not in player
    assert "market" not in observation["team"]
    assert "patience" not in observation["team"]

    # drafted_round was set on every drafted prospect but read by nothing and
    # never published; a dead write in the same spirit as the fields above.
    assert "drafted_round" not in {field.name for field in fields(Player)}


def test_observation_lineup_rules_match_validation() -> None:
    league = League.new(seed=11)
    rules = league.observation("preseason")["rules"]
    assert rules["lineup_size"] == 18
    assert rules["lineup_min_positions"] == {"F": 10, "D": 4, "G": 1}
    assert "positions" not in rules


def test_observation_publishes_the_center_lineup_bonus_and_forward_sub_position() -> None:
    """The center-count bonus must be legible: a target, a rate, and every forward's role."""
    league = League.new(seed=11)
    observation = league.observation("preseason")
    bonus_rules = observation["rules"]["lineup_center_bonus"]
    assert bonus_rules["target"] > 0
    assert bonus_rules["bonus_per_center"] > 0
    roster = observation["team"]["roster"]
    forwards = [player for player in roster if player["position"] == "F"]
    assert forwards
    assert all(player["sub_position"] in ("C", "W") for player in forwards)
    assert all(player["sub_position"] is None for player in roster if player["position"] != "F")


def test_center_aware_lineup_beats_pure_overall_sort_despite_lower_total_overall() -> None:
    """Sorting a lineup by overall alone should not be the strongest legal lineup.

    Swapping a slightly weaker winger for a natural center to reach the
    lineup's center target must win on team strength even though it loses on
    total overall -- the tradeoff the mechanic exists to create.
    """
    league = League.new(seed=41)
    team = league.user_team
    roster = [league.players[player_id].public_dict() for player_id in team.roster]

    naive_lineup = position_aware_lineup(roster)
    center_aware_lineup = position_aware_lineup(
        roster, lambda player: player["overall"] + (100.0 if player["sub_position"] == "C" else 0.0)
    )
    assert naive_lineup != center_aware_lineup

    def centers_dressed(lineup: list[int]) -> int:
        return sum(
            1
            for player_id in lineup
            if league.players[player_id].position == "F" and league.players[player_id].sub_position == "C"
        )

    naive_centers = centers_dressed(naive_lineup)
    center_aware_centers = centers_dressed(center_aware_lineup)
    assert center_aware_centers > naive_centers

    naive_overall_total = sum(league.players[player_id].overall for player_id in naive_lineup)
    center_aware_overall_total = sum(league.players[player_id].overall for player_id in center_aware_lineup)
    # The naive sort really is picking higher-rated players overall...
    assert naive_overall_total > center_aware_overall_total

    team.lineup = naive_lineup
    naive_strength = league._team_strength(team, apply_injury_noise=False)
    team.lineup = center_aware_lineup
    center_aware_strength = league._team_strength(team, apply_injury_noise=False)
    # ...but still fields the weaker team.
    assert center_aware_strength > naive_strength


def test_trade_market_uses_public_estimates_not_hidden_asset_value() -> None:
    league = League.new(seed=17)
    market = league.observation("trade_deadline")["trade_market"]
    encoded = json.dumps(market)
    assert "asset_value" not in encoded
    assert "true_potential" not in encoded
    for offer in market:
        player = league.players[offer["player"]["id"]]
        assert offer["estimated_price"] == League._public_trade_estimate(player)


class _BadQueryAgent(ValueAgent):
    """Plays a valid strategy but always tacks on two doomed lookups per turn.

    The queries reference ids that cannot exist, so every one is a non-penalized
    failed query — the invisible-failure class that motivated the counter.
    """

    name = "bad-query"

    def act(self, observation):  # type: ignore[override]
        actions = super().act(observation)
        return [
            {"type": "scout", "player_id": 999999999},
            {"type": "inspect_team", "team_id": 987654},
            *actions,
        ]


def test_failed_queries_surface_in_episode_and_summary_without_illegal_actions() -> None:
    payload = run_episode(_BadQueryAgent(), seed=4, seasons=2)
    # Two failed queries per decision point, none of them a protocol violation.
    total_decisions = payload.decisions
    assert payload.failed_queries == 2 * total_decisions
    assert payload.illegal_actions == 0

    run = run_many(_BadQueryAgent(), seeds=[4, 5], seasons=2)
    episode = run["episodes"][0]
    assert episode["failed_queries"] > 0
    assert "failed_queries" in run["summary"]
    assert run["summary"]["failed_queries"] == sum(ep["failed_queries"] for ep in run["episodes"])
    assert run["summary"]["failed_queries"] > 0
    assert run["summary"]["illegal_actions"] == 0


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


def test_external_agent_scrubs_private_seed_from_transport_and_environment(monkeypatch, tmp_path: Path) -> None:
    script = tmp_path / "seed_probe_agent.py"
    script.write_text(
        "import json, os, sys\n"
        "observation = json.load(sys.stdin)\n"
        "evidence = {\n"
        "    'observation': observation,\n"
        "    'private_seeds': os.environ.get('GM_BENCH_PRIVATE_SEEDS'),\n"
        "    'private_seed_salt': os.environ.get('GM_BENCH_PRIVATE_SEED_SALT'),\n"
        "    'seed_panel_salt': os.environ.get('GM_BENCH_SEED_PANEL_SALT'),\n"
        "    'profile': os.environ.get('GM_AGENT_PROFILE'),\n"
        "}\n"
        "print(json.dumps({'actions': [{'type': 'memo', 'text': json.dumps(evidence)}]}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GM_BENCH_PRIVATE_SEEDS", "inherited-secret")
    monkeypatch.setenv("GM_BENCH_SEED_PANEL_SALT", "inherited-salt")
    agent = ExternalProcessAgent(
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}",
        env={"GM_BENCH_PRIVATE_SEED_SALT": "override-secret", "GM_AGENT_PROFILE": "tiny"},
    )

    actions = agent.act({"seed": 9_876_543_210, "phase": "preseason"})

    evidence = json.loads(actions[0]["text"])
    assert evidence["observation"] == {"phase": "preseason"}
    assert evidence["private_seeds"] is None
    assert evidence["private_seed_salt"] is None
    assert evidence["seed_panel_salt"] is None
    assert evidence["profile"] == "tiny"


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


def test_external_agents_default_to_serial_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model adapters must not fan out across seeds — that burns provider quotas."""
    monkeypatch.delenv("GM_BENCH_WORKERS", raising=False)
    external = ExternalProcessAgent("true", name="fake-model")
    persistent = PersistentProcessAgent("true", name="fake-session")
    assert cli_module._model_worker_count(external, None) == 1
    assert cli_module._model_worker_count(persistent, None) == 1
    assert cli_module._model_worker_count(ValueAgent(), None) is None
    monkeypatch.setenv("GM_BENCH_WORKERS", "4")
    assert cli_module._model_worker_count(external, None) == 4
    assert cli_module._model_worker_count(external, 2) == 2


def test_invalid_worker_environment_has_cli_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GM_BENCH_WORKERS", "many")
    external = ExternalProcessAgent("true", name="fake-model")
    with pytest.raises(SystemExit, match="GM_BENCH_WORKERS must be an integer"):
        cli_module._model_worker_count(external, None)


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


@pytest.mark.parametrize("host", ["127.0.0.1", "127.12.3.4", "::1", "localhost"])
def test_gui_recognizes_loopback_hosts(host: str) -> None:
    assert _is_loopback_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "example.test"])
def test_gui_rejects_non_loopback_hosts_by_default(host: str) -> None:
    assert not _is_loopback_host(host)


def test_gui_fails_before_binding_non_loopback_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gui_module,
        "ThreadingHTTPServer",
        lambda *_args, **_kwargs: pytest.fail("server must not be constructed"),
    )
    with pytest.raises(ValueError, match="non-loopback"):
        serve("0.0.0.0", db_path=tmp_path / "gui.sqlite")


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_gui_remote_escape_hatch_is_disabled_before_binding(
    host: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gui_module,
        "ThreadingHTTPServer",
        lambda *_args, **_kwargs: pytest.fail("server must not be constructed"),
    )
    with pytest.raises(ValueError, match="no authentication"):
        serve(host, db_path=tmp_path / "gui.sqlite", allow_remote=True)


def test_gui_entrypoints_cannot_bypass_disabled_remote_mode() -> None:
    with pytest.raises(ValueError, match="no authentication"):
        gui_module.main(["--allow-remote"])
    with pytest.raises(ValueError, match="no authentication"):
        cli_module.main(["gui", "--allow-remote"])


def test_gui_direct_entrypoint_honors_database_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "environment.sqlite"
    seen: dict[str, object] = {}
    monkeypatch.setenv("GM_BENCH_DB", str(database))
    monkeypatch.setattr(gui_module, "serve", lambda host, port, db, **kwargs: seen.update(db=db))

    gui_module.main([])

    assert seen["db"] == str(database)


def _adapter_reply(text: object) -> RepairOutcome:
    """What the harness makes of a model reply the adapter forwarded verbatim.

    Adapters no longer parse or repair model output: they print it in the
    envelope's raw_text field beside their usage, and gm_bench.repair -- the
    published rule set -- is the only thing that decides what it means. These
    tests therefore go through emit() and repair together, so the rules that
    are published are the rules that are measured.
    """
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        gm_agent_common.emit(text, {"api_calls": 1})
    return repair_adapter_output(stream.getvalue(), source="external agent")


def test_adapter_forwards_the_model_reply_verbatim_for_the_harness_to_judge() -> None:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        gm_agent_common.emit('{"actions":[{"type":"noop"}]}', {"api_calls": 1})
    envelope = json.loads(stream.getvalue())

    assert envelope[RAW_TEXT_FIELD] == '{"actions":[{"type":"noop"}]}'
    assert envelope["usage"] == {"api_calls": 1}
    outcome = repair_adapter_output(stream.getvalue(), source="external agent")
    assert outcome.actions == [{"type": "noop"}]
    assert not outcome.malformed
    assert outcome.usage == {"api_calls": 1}


def test_prose_wrapped_output_is_repaired_by_the_published_rule_and_counted() -> None:
    """The case the adapters used to hide: a fenced answer is now measured.

    The adapters' own JSON scan resolved this silently, so a model that wrapped
    every answer in prose scored as if it had formatted perfectly.
    """
    outcome = _adapter_reply('Sure!\n```json\n{"actions":[{"type":"noop"}]}\n```')

    assert outcome.actions[0]["type"] == "noop"
    assert outcome.malformed and not outcome.unrecoverable
    assert outcome.rules_applied == (RULE_STRIP_CODE_FENCE,)


def test_two_candidate_answers_stay_ambiguous_instead_of_being_chosen_between() -> None:
    """The adapters' first-valid-JSON scan silently picked one; repair refuses."""
    outcome = _adapter_reply('Either [{"type": "noop"}] or [{"type": "end_turn"}].')

    assert outcome.unrecoverable
    assert outcome.actions[0]["type"] == "noop"


def test_untyped_object_is_an_unrecoverable_decision() -> None:
    outcome = _adapter_reply('{"F":12,"D":4,"G":2}')

    assert outcome.unrecoverable
    assert "must return an action list or envelope" in (outcome.reason or "")


def test_null_content_is_the_models_malformed_decision_with_its_cost_kept() -> None:
    outcome = _adapter_reply(None)

    assert outcome.unrecoverable
    # The call was billed even though the backend returned no text.
    assert outcome.usage == {"api_calls": 1}


def test_key_aliases_are_no_longer_repaired_because_no_published_rule_covers_them() -> None:
    """A behavior change, stated as one: the operative rules are the published ones.

    The adapters used to rename {"action_type": ...} and natural trade field
    names into the canonical schema keys. That repair was never in the
    published table, so a model was scored under rules no reader could see.
    Such a reply is now a malformed, unrecoverable decision.
    """
    aliased_type = _adapter_reply('{"actions":[{"action_type":"draft","prospect_id":5}]}')
    assert aliased_type.unrecoverable

    # A mis-keyed trade is well-formed JSON, so it is not a formatting failure:
    # it reaches the simulator exactly as written and is refused there, counted
    # against the model as its own illegal action instead of being rewritten
    # into the legal trade nobody can see it did not ask for.
    mis_keyed = {"type": "trade", "target_team_id": 3, "players_to_send": [1], "players_to_acquire": [88]}
    aliased_trade = _adapter_reply(json.dumps({"actions": [mis_keyed]}))
    assert aliased_trade.actions == [mis_keyed]
    league = League.new(seed=21)
    results = league.apply_actions(aliased_trade.actions, "trade_deadline")
    assert not results[0].accepted
    assert league.illegal_actions == 1

    # The canonical spelling the prompt actually asks for is untouched.
    canonical = _adapter_reply(
        json.dumps(
            {
                "actions": [
                    {
                        "type": "trade",
                        "partner_team_id": 3,
                        "give_player_ids": [1],
                        "receive_player_ids": [88],
                    }
                ]
            }
        )
    )
    assert not canonical.malformed


def test_an_empty_action_list_is_a_clean_do_nothing_decision() -> None:
    # A well-formed empty list is an explicit "do nothing" turn, not a
    # formatting failure, and must not be counted as malformed.
    for text in ('{"actions": []}', "[]"):
        outcome = _adapter_reply(text)
        assert outcome.actions == []
        assert not outcome.malformed


def test_a_list_with_no_typed_items_is_unrecoverable() -> None:
    assert _adapter_reply('{"actions":[{"foo":"bar"}]}').unrecoverable


def test_malformed_items_are_not_silently_dropped() -> None:
    outcome = _adapter_reply('{"actions":[{"type":"noop"},{"salary":2.5}]}')

    assert outcome.unrecoverable
    assert "string type" in (outcome.reason or "")


def test_standalone_common_prefers_checkout_package_over_older_install(tmp_path: Path) -> None:
    fake_root = tmp_path / "fake-site"
    fake_package = fake_root / "gm_bench"
    fake_package.mkdir(parents=True)
    (fake_package / "__init__.py").write_text("# deliberately incomplete installed package\n")
    common = Path("examples/gm_agent_common.py").resolve()
    command = (
        "import pathlib, runpy, sys; "
        "runpy.run_path(sys.argv[1]); "
        "import gm_bench; "
        "print(pathlib.Path(gm_bench.__file__).resolve())"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command, str(common)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(fake_root)},
        text=True,
        capture_output=True,
        check=True,
    )

    assert completed.stdout.strip() == str((Path("gm_bench") / "__init__.py").resolve())


def test_prompt_builder_ignores_legacy_no_think_soft_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GM_AGENT_NO_THINK", "1")
    prompt = build_prompt(League.new(seed=42).observation("preseason"))
    assert "/no_think" not in prompt


def test_coding_agent_schema_exists() -> None:
    schema_path = Path("schemas/gm_actions.schema.json")
    payload = json.loads(schema_path.read_text())
    assert payload["required"] == ["actions"]
    assert "draft" in payload["properties"]["actions"]["items"]["properties"]["type"]["enum"]


def test_coding_agent_schema_matches_canonical_action_surface() -> None:
    canonical = json.loads(Path("schemas/gm_action_list.schema.json").read_text())
    structured = json.loads(Path("schemas/gm_actions.schema.json").read_text())
    canonical_items = canonical["$defs"]["action"]
    structured_items = structured["properties"]["actions"]["items"]

    assert structured["properties"]["actions"]["maxItems"] == canonical["maxItems"]
    assert set(structured_items["properties"]["type"]["enum"]) == set(canonical_items["properties"]["type"]["enum"])
    assert set(structured_items["properties"]) == set(canonical_items["properties"])


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


def test_codex_command_uses_scratch_schema_and_explicit_default_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    codex_command = build_codex_command(tmp_path)

    schema_path = Path(codex_command[codex_command.index("--output-schema") + 1])
    assert schema_path == tmp_path / "gm_actions.schema.json"
    assert str(Path("schemas/gm_actions.schema.json").resolve()) not in codex_command
    assert codex_command[codex_command.index("--model") + 1] == "gpt-5-mini"


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
                "decisions": 4 * len(seeds),
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
