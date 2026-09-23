"""The Codex CLI harness driver, proven against a fake ``codex`` that speaks the documented JSONL.

No test here runs the real Codex CLI or contacts a model. The fake binary
reads the staged ``config.toml`` from its ``CODEX_HOME``, launches the MCP
proxy that config declares, makes real GM-Bench tool calls through it, and
prints the ``codex exec --json`` event stream of Codex CLI 0.156.1.
"""

from __future__ import annotations

import copy
import io
import json
import os
import sys
import tarfile
import tomllib
from pathlib import Path

import pytest

from gm_bench.agentic import codex, opencode
from gm_bench.agentic.codex import (
    CodexDriver,
    codex_config,
    codex_config_toml,
    codex_version,
    ended_in_provider_stall,
    parse_codex_events,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DUMMY_KEY = "sk-dummy-not-a-real-key-0000"

# The fake ``codex``. Behaviour per invocation comes from the plan file named
# by FAKE_CODEX_PLAN: {"log": path, "state": path, "steps": [{"phases": n,
# "error": message | null, "exit": code, "cat_auth": bool, "shell_proxy":
# bool}, ...]}. Each phase is a get_status then an end_phase call through the
# proxy the staged config declares. Like Codex 0.156.1 under ``exec``
# (approval policy never), it refuses every MCP call before dispatch when the
# sandbox is workspace-write and the server's tools are not approved;
# ``shell_proxy`` then drives the proxy from a shell command instead, as a
# model could. ``cat_auth`` prints CODEX_HOME/auth.json from a shell command.
FAKE_CODEX = r"""
import json, os, subprocess, sys, tomllib, uuid
from pathlib import Path

argv = sys.argv[1:]
if argv == ["--version"]:
    print("codex-cli 0.156.1")
    sys.exit(0)
plan = json.loads(Path(os.environ["FAKE_CODEX_PLAN"]).read_text())
state_path = Path(plan["state"])
state = json.loads(state_path.read_text()) if state_path.exists() else {"invocations": 0, "usage": {}}
state["invocations"] += 1
step = plan["steps"][min(state["invocations"], len(plan["steps"])) - 1]
home = Path(os.environ["CODEX_HOME"])
with open(plan["log"], "a") as log:
    log.write(json.dumps({
        "argv": argv,
        "cwd": os.getcwd(),
        "HOME": os.environ.get("HOME"),
        "CODEX_HOME": str(home),
        "codex_env": sorted(k for k in os.environ if k.startswith("CODEX_")),
        "home_files": sorted(p.name for p in home.iterdir()),
    }) + "\n")

def emit(event):
    print(json.dumps(event), flush=True)

assert argv[0] == "exec", argv
resume = argv[1] == "resume"
assert "--json" in argv and "--skip-git-repo-check" in argv
overrides = dict(argv[i + 1].split("=", 1) for i, arg in enumerate(argv) if arg == "-c")
sandbox = json.loads(overrides.get("sandbox_mode", '"read-only"'))
sessions = home / "sessions"
if resume:
    thread = argv[-2]
    if not (sessions / f"{thread}.jsonl").exists():
        emit({"type": "error", "message": f"no thread with id: {thread}"})
        sys.exit(1)
else:
    thread = str(uuid.uuid4())
    sessions.mkdir(exist_ok=True)
    (sessions / f"{thread}.jsonl").write_text("")
emit({"type": "thread.started", "thread_id": thread})
emit({"type": "turn.started"})
item = 0
if step.get("cat_auth"):
    auth = home / "auth.json"
    text = auth.read_text() if auth.exists() else "CODEX_API_KEY=" + os.environ.get("CODEX_API_KEY", "")
    shell = {"id": f"item_{item}", "type": "command_execution", "command": "cat $CODEX_HOME/auth.json",
             "aggregated_output": text, "exit_code": 0}
    emit({"type": "item.completed", "item": {**shell, "status": "completed"}})
    sys.stderr.write("tool output: " + text + "\n")
    item += 1
if step.get("phases"):
    server = tomllib.loads((home / "config.toml").read_text())["mcp_servers"]["gm-bench"]
    approved = server.get("default_tools_approval_mode") == "approve" or sandbox == "danger-full-access"
    proxy = subprocess.Popen([server["command"], *server["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(payload):
        proxy.stdin.write(json.dumps(payload) + "\n")
        proxy.stdin.flush()
        return json.loads(proxy.stdout.readline())
    rpc({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    proxy.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    for _ in range(step["phases"]):
        for tool in ("get_status", "end_phase"):
            base = {"id": f"item_{item}", "type": "mcp_tool_call", "server": "gm-bench", "tool": tool, "arguments": {}}
            emit({"type": "item.started", "item": {**base, "result": None, "error": None, "status": "in_progress"}})
            if not approved:
                error = {"message": "MCP tool call requires approval, but approval policy is never"}
                emit({"type": "item.completed", "item": {**base, "result": None, "error": error, "status": "failed"}})
                item += 1
                if not step.get("shell_proxy"):
                    continue
                shell = {"id": f"item_{item}", "type": "command_execution", "exit_code": 0,
                         "command": f"python3 gm_bench_proxy.py <<< {tool}", "aggregated_output": ""}
                emit({"type": "item.started", "item": {**shell, "status": "in_progress"}})
            reply = rpc({"jsonrpc": "2.0", "id": item + 1, "method": "tools/call", "params": {"name": tool, "arguments": {}}})
            if not approved:
                emit({"type": "item.completed", "item": {**shell, "status": "completed"}})
                item += 1
                continue
            result = {"content": reply["result"]["content"], "structured_content": reply["result"].get("structuredContent")}
            emit({"type": "item.completed", "item": {**base, "result": result, "error": None, "status": "completed"}})
            item += 1
    proxy.stdin.close()
    proxy.wait(timeout=30)
    shell = {"id": f"item_{item}", "type": "command_execution", "command": "ls", "aggregated_output": "", "exit_code": 0}
    emit({"type": "item.completed", "item": {**shell, "status": "completed"}})
    item += 1
usage = state["usage"].get(thread) or {"input_tokens": 0, "cached_input_tokens": 0, "cache_write_input_tokens": 0,
                                        "output_tokens": 0, "reasoning_output_tokens": 0}
for key, value in (("input_tokens", 1000), ("cached_input_tokens", 400), ("output_tokens", 50), ("reasoning_output_tokens", 20)):
    usage[key] += value
state["usage"][thread] = usage
state_path.write_text(json.dumps(state))
if step.get("rate_limits") is not None:
    # What Codex persists to the session rollout: token_count events with the account's rate limits.
    day = sessions / "2026" / "09" / "23"
    day.mkdir(parents=True, exist_ok=True)
    stamp = f"2026-09-23T00:00:{state['invocations']:02d}.000Z"
    with (day / f"rollout-2026-09-23T00-00-00-{thread}.jsonl").open("a") as rollout:
        rollout.write(json.dumps({"timestamp": stamp, "type": "session_meta", "payload": {"id": thread}}) + "\n")
        for limits in step["rate_limits"]:
            record = {"type": "token_count", "info": {"total_token_usage": usage}, "rate_limits": limits}
            rollout.write(json.dumps({"timestamp": stamp, "type": "event_msg", "payload": record}) + "\n")
if step.get("error"):
    emit({"type": "error", "message": "Reconnecting... 1/5"})
    emit({"type": "turn.failed", "error": {"message": step["error"]}})
    sys.exit(step.get("exit", 1))
emit({"type": "item.completed", "item": {"id": f"item_{item}", "type": "agent_message", "text": "Done for now."}})
emit({"type": "turn.completed", "usage": usage})
sys.exit(step.get("exit", 0))
"""


def _fake_codex(tmp_path: Path, steps: list[dict], monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    binary = tmp_path / "fake-codex"
    binary.write_text(f"#!{sys.executable}\n{FAKE_CODEX}")
    binary.chmod(0o755)
    log = tmp_path / "codex-calls.jsonl"
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"log": str(log), "state": str(tmp_path / "state.json"), "steps": steps}))
    monkeypatch.setenv("FAKE_CODEX_PLAN", str(plan))
    # Host Codex state that must not reach the harness.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "host-codex-home"))
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    # CI may install gm_bench into the system python; the sandbox check has its own tests.
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    return binary, log


def _auth_file(tmp_path: Path) -> Path:
    path = tmp_path / "operator-auth.json"
    path.write_text(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": DUMMY_KEY}))
    return path


def _calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


# -- the full loop against the fake binary --------------------------------------


def test_codex_panel_plays_through_the_staged_proxy_nudges_by_resume_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from gm_bench.agentic.validate import validate_run

    # First run: one phase, then the model answers with text and codex exits 0. The nudge resumes and finishes.
    binary, log = _fake_codex(tmp_path, [{"phases": 1}, {"phases": 3}], monkeypatch)
    run_dir = tmp_path / "run"
    payload = codex.run_panel(
        [11], model="gpt-fake", run_dir=run_dir, seasons=1, binary=str(binary), auth_file=_auth_file(tmp_path)
    )
    assert payload["agent"] == "codex:gpt-fake"
    assert payload["harness"] == {"name": "codex", "version": "0.156.1", "model": "gpt-fake", "variant": None}
    [episode] = payload["episodes"]
    harness_run = episode["harness_run"]
    assert harness_run["harness"] == "codex"
    assert harness_run["events_path"] == "seed-11/codex-events.jsonl"
    # (a) every GM-Bench call the fake made through the proxy is in the ledger and in the event stream.
    assert harness_run["tool_call_agreement"] == {"ledger": 8, "harness": 8, "agree": True}
    assert episode["usage"]["harness"]["tool_events"] == {"gm-bench_end_phase": 4, "gm-bench_get_status": 4, "shell": 2}
    assert episode["agentic"]["phases_ended_by"] == {"agent": 4}
    assert episode["failed_decisions"] == 0
    # (b) the early stop was nudged by resuming the same Codex session.
    calls = _calls(log)
    # (The version probe answers before the fake logs anything.)
    assert [call["argv"][:2] for call in calls] == [["exec", "--json"], ["exec", "resume"]]
    first, nudge = calls
    thread = json.loads((run_dir / "seed-11" / "codex-events.jsonl").read_text().splitlines()[0])["thread_id"]
    assert nudge["argv"][-2] == thread and "Reminder 1 of 20" in nudge["argv"][-1]
    assert harness_run["nudges_used"] == 1 and harness_run["nudges"][0]["new_tool_calls"] == 6
    # Same options on both invocations; the resume carries its sandbox through -c.
    assert first["argv"][1:-1] == nudge["argv"][2:-2]
    assert 'sandbox_mode="workspace-write"' in first["argv"]
    assert "sandbox_workspace_write.network_access=true" in first["argv"]
    # No host Codex state: HOME is the scratch, CODEX_HOME a private directory outside it (the same one
    # for the resume, removed at episode end), no other CODEX_* vars.
    assert first["CODEX_HOME"] == nudge["CODEX_HOME"]
    for call in calls:
        cwd = Path(call["cwd"]).resolve()
        assert Path(call["HOME"]).resolve() == cwd
        codex_home = Path(call["CODEX_HOME"]).resolve()
        assert not codex_home.is_relative_to(cwd) and codex_home != Path(os.environ["CODEX_HOME"]).resolve()
        assert not codex_home.exists()
        assert call["codex_env"] == ["CODEX_HOME"]
        assert call["home_files"][:2] == ["auth.json", "config.toml"]
    # Usage is the thread's running total, not a sum of the two invocations' reports.
    usage = episode["usage"]
    assert (usage["input_tokens"], usage["cached_input_tokens"], usage["output_tokens"]) == (2000, 800, 100)
    assert usage["reasoning_tokens"] == 40 and usage["api_calls"] == 2
    assert usage["harness"]["telemetry_reported"] is True and usage["harness"]["compactions"] is None
    assert usage["cost_usd"] is None and usage["harness"]["tool_calls_skipped"] == {}
    assert payload["agentic_summary"]["compactions"] is None
    assert harness_run["auth"] == "auth-file" and harness_run["session_resume"] == "codex exec resume"
    assert tomllib.loads(harness_run["harness_config"])["mcp_servers"]["gm-bench"]["args"][0] == "gm_bench_proxy.py"
    assert DUMMY_KEY not in json.dumps(payload)

    report = validate_run(run_dir)
    assert report["ok"], report
    assert report["per_episode"][0]["harness_tool_calls"] == 8
    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["harness"]["name"] == "codex"
    assert validate_agentic_artifact(artifact)["ok"]


def test_codex_provider_stall_is_retried_by_resume_and_is_not_a_nudge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.validate import validate_run

    # (c) the first run ends on a retryable 429 after one phase; the retry resumes and finishes.
    steps = [
        {"phases": 1, "error": "exceeded retry limit, last status: 429 Too Many Requests", "exit": 1},
        {"phases": 3},
    ]
    binary, log = _fake_codex(tmp_path, steps, monkeypatch)
    sleeps: list[float] = []
    run_dir = tmp_path / "run"
    result = codex.run_episode(
        11,
        model="gpt-fake",
        run_dir=run_dir,
        seasons=1,
        binary=str(binary),
        auth_file=_auth_file(tmp_path),
        max_nudges=5,
        max_provider_stalls=8,
        max_provider_stall_wait_seconds=3600.0,
        stall_backoff=lambda n: 7.0,
        sleep=sleeps.append,
        keep_scratch=True,
    )
    harness_run = result["harness_run"]
    assert sleeps == [7.0]
    assert harness_run["provider_stalls"] == 1 and harness_run["provider_stall_wait_seconds"] == 7.0
    assert harness_run["nudges_used"] == 0
    [retry] = harness_run["nudges"]
    assert retry["stall_retry"] is True and retry["provider_stall"] is False and retry["new_tool_calls"] == 6
    assert [call["argv"][:2] for call in _calls(log)] == [["exec", "--json"], ["exec", "resume"]]
    assert result["failed_decisions"] == 0
    assert harness_run["tool_call_agreement"]["agree"] is True
    assert result["usage"]["harness"]["turns_failed"] == 1
    # The kept scratch never held the Codex home, so no credential outlives the episode.
    scratch = Path(harness_run["scratch_dir"])
    assert not (scratch / ".codex").exists()
    assert not any(DUMMY_KEY in path.read_text() for path in scratch.rglob("*") if path.is_file())
    assert harness_run["codex_home"].startswith("private directory outside the scratch")

    run = {
        "agent": "codex:gpt-fake",
        "harness": {"name": "codex", "version": "0.156.1", "model": "gpt-fake"},
        "contract": opencode.agentic_contract(),
        "seeds": [11],
        "seasons": 1,
        "episodes": [result],
        "summary": opencode.summarize_episodes([result]),
        "agentic_summary": opencode._agentic_summary([result]),
    }
    (run_dir / "run.json").write_text(json.dumps(run))
    # Codex reports no compactions: unmeasured, not a summed 0.
    assert run["agentic_summary"]["compactions"] is None
    assert validate_run(run_dir)["ok"]


def test_codex_same_user_needs_credentials_and_refuses_bad_auth_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    with pytest.raises(ValueError, match="needs credentials"):
        CodexDriver().preflight("same-user")
    monkeypatch.setenv("CODEX_API_KEY", DUMMY_KEY)
    CodexDriver().preflight("same-user")
    assert CodexDriver().auth_source("same-user") == "CODEX_API_KEY"
    # An env key is no use to a container: it gets no environment.
    with pytest.raises(ValueError, match="needs --codex-auth-file"):
        CodexDriver().preflight("container")
    bad = tmp_path / "bad.json"
    bad.write_text("not json " + DUMMY_KEY)
    with pytest.raises(ValueError, match="not JSON") as excinfo:
        CodexDriver(auth_file=bad).preflight("same-user")
    assert DUMMY_KEY not in str(excinfo.value)
    bad.write_text(json.dumps({"auth_mode": "apikey"}))
    with pytest.raises(ValueError, match="neither OPENAI_API_KEY nor tokens"):
        CodexDriver(auth_file=bad).preflight("container")
    with pytest.raises(ValueError, match="is not a file"):
        CodexDriver(auth_file=tmp_path / "missing.json").preflight("container")
    CodexDriver(auth_file=_auth_file(tmp_path)).preflight("container")


# -- staging, version, parser ---------------------------------------------------


def test_codex_staging_keeps_host_codex_home_out_and_the_config_to_one_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.episode import AgenticEpisode

    monkeypatch.setenv("CODEX_HOME", str(Path.home() / ".codex"))
    monkeypatch.setenv("CODEX_THREAD_ID", "host-session")
    monkeypatch.setenv("CODEX_API_KEY", DUMMY_KEY)
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    episode = AgenticEpisode(8675309, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    driver = CodexDriver(auth_file=_auth_file(tmp_path))
    launch = opencode.HarnessLaunch(episode, binary="codex", driver=driver)
    try:
        # With an auth file, the env key is dropped too, so the file is what Codex uses.
        assert not any(key.startswith("CODEX_") and key != "CODEX_HOME" for key in launch.env)
        home = Path(launch.env["CODEX_HOME"])
        assert not home.resolve().is_relative_to(launch.scratch.resolve())
        assert home != Path.home() / ".codex"
        assert launch.env["HOME"] == str(launch.scratch)
        launch.prepare()
        # The agent's working directory holds only the proxy: no config, no credential.
        assert sorted(p.name for p in launch.scratch.iterdir()) == ["gm_bench_proxy.py"]
        assert sorted(p.name for p in home.iterdir()) == ["auth.json", "config.toml"]
        assert home.stat().st_mode & 0o077 == 0
        assert (home / "auth.json").stat().st_mode & 0o077 == 0
        assert json.loads((home / "auth.json").read_text())["OPENAI_API_KEY"] == DUMMY_KEY
        config = tomllib.loads((home / "config.toml").read_text())
        assert config == codex_config(launch.server.address, python=opencode.harness_python(launch.env))
        assert config == {
            "mcp_servers": {
                "gm-bench": {
                    "command": config["mcp_servers"]["gm-bench"]["command"],
                    "args": ["gm_bench_proxy.py", str(launch.server.address)],
                    # exec's approval policy is never: without this, workspace-write refuses every call.
                    "default_tools_approval_mode": "approve",
                }
            }
        }
        rendered = (home / "config.toml").read_text()
        assert "8675309" not in rendered and str(REPO_ROOT) not in rendered and sys.executable not in rendered
        argv, on_kill = launch.command(
            driver.run_args(model="gpt-x", variant="low", workdir=launch.workdir, brief="BRIEF", isolation="same-user")
        )
        assert on_kill is None
        assert argv == [
            "codex",
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--model",
            "gpt-x",
            "-c",
            'sandbox_mode="workspace-write"',
            "-c",
            "sandbox_workspace_write.network_access=true",
            "-c",
            'model_reasoning_effort="low"',
            "BRIEF",
        ]
        resume = driver.resume_args(
            model="gpt-x", variant="low", workdir=launch.workdir, session_id="T", text="NUDGE", isolation="same-user"
        )
        assert resume == ["exec", "resume", *argv[2:-1], "T", "NUDGE"]
    finally:
        launch.close(keep_scratch=True)
    # The private home (config, credential, sessions) is gone even with --keep-scratch.
    assert not home.exists()
    assert sorted(p.name for p in launch.scratch.iterdir()) == ["gm_bench_proxy.py"]
    episode.close()


def test_codex_config_toml_round_trips_awkward_paths() -> None:
    config = codex_config('/tmp/a "b"\\c/s', python="/opt/py thon/python3")
    assert tomllib.loads(codex_config_toml(config)) == config
    assert codex_config("host.docker.internal:4242") == {
        "mcp_servers": {
            "gm-bench": {
                "command": "python3",
                "args": ["gm_bench_proxy.py", "host.docker.internal:4242"],
                "default_tools_approval_mode": "approve",
            }
        }
    }


def test_codex_version_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary, _log = _fake_codex(tmp_path, [{}], monkeypatch)
    assert codex_version(str(binary)) == "0.156.1"
    assert CodexDriver().version(str(binary)) == "0.156.1"
    assert codex_version(str(tmp_path / "no-such-codex")) is None


def _item(event: str, item_id: str, kind: str = "mcp_tool_call", **fields) -> str:
    return json.dumps({"type": event, "item": {"id": item_id, "type": kind, **fields}})


def test_parse_codex_events_counts_tools_per_invocation_and_keeps_the_last_running_total() -> None:
    first_usage = {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10, "reasoning_output_tokens": 3}
    second_usage = {
        "input_tokens": 250,
        "cached_input_tokens": 90,
        "cache_write_input_tokens": 7,
        "output_tokens": 30,
        "reasoning_output_tokens": 9,
    }
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t-1"}),
        json.dumps({"type": "turn.started"}),
        _item("item.started", "item_0", server="gm-bench", tool="get_status", status="in_progress"),
        _item("item.completed", "item_0", server="gm-bench", tool="get_status", status="completed"),
        _item("item.completed", "item_1", "command_execution", command="ls", status="completed"),
        _item("item.completed", "item_2", "agent_message", text="hi"),
        _item("item.completed", "item_3", "reasoning", text="thinking"),
        "not json",
        json.dumps({"type": "turn.completed", "usage": first_usage}),
        # A resumed invocation: item ids restart, and one call was cut off by a guard stop.
        json.dumps({"type": "thread.started", "thread_id": "t-1"}),
        json.dumps({"type": "turn.started"}),
        _item("item.started", "item_0", server="gm-bench", tool="end_phase", status="in_progress"),
        _item("item.completed", "item_0", server="gm-bench", tool="end_phase", status="failed"),
        _item("item.started", "item_1", server="gm-bench", tool="scout", status="in_progress"),
        _item("item.completed", "item_2", "file_change", changes=[], status="completed"),
        _item("item.completed", "item_3", "web_search", query="q", action={"type": "other"}),
        json.dumps({"type": "error", "message": "Reconnecting... 1/5"}),
        json.dumps({"type": "turn.completed", "usage": second_usage}),
    ]
    telemetry = parse_codex_events(lines)
    assert telemetry["session_id"] == "t-1"
    assert telemetry["harness_tool_events"] == {
        "apply_patch": 1,
        "gm-bench_end_phase": 1,
        "gm-bench_get_status": 1,
        "gm-bench_scout": 1,
        "shell": 1,
        "web_search": 1,
    }
    assert opencode.harness_tool_calls(telemetry) == 3
    # Running total: the second report already includes the first.
    assert (telemetry["input_tokens"], telemetry["cached_input_tokens"], telemetry["output_tokens"]) == (250, 90, 30)
    assert (telemetry["reasoning_tokens"], telemetry["cache_write_tokens"]) == (9, 7)
    assert telemetry["model_calls"] == 2 and telemetry["turns_started"] == 2
    assert telemetry["cost_usd"] is None and telemetry["compactions"] is None
    assert telemetry["errors"] == 1

    # A fresh thread (not a resume) adds to the total instead of replacing it.
    other = [
        json.dumps({"type": "thread.started", "thread_id": "t-2"}),
        json.dumps({"type": "turn.completed", "usage": first_usage}),
    ]
    assert parse_codex_events(lines + other)["input_tokens"] == 350

    usage = codex.usage_block(telemetry, model="gpt-x", decisions=20)
    assert usage["api_calls"] == 2 and usage["input_tokens"] == 250
    assert usage["harness"]["name"] == "codex" and usage["harness"]["telemetry_reported"] is True
    assert usage["harness"]["api_calls_are"] == "completed turns"
    assert usage["harness"]["cost_reported_by_harness"] is False
    silent = codex.usage_block(parse_codex_events([]), model="gpt-x", decisions=20)
    assert silent["harness"]["telemetry_reported"] is False and silent["decisions_with_usage"] == 0


def test_mcp_calls_codex_refused_before_dispatch_are_not_harness_tool_calls() -> None:
    refused = {"message": "MCP tool call requires approval, but approval policy is never"}
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t-1"}),
        _item("item.started", "item_0", server="gm-bench", tool="get_status", status="in_progress"),
        _item("item.completed", "item_0", server="gm-bench", tool="get_status", status="failed", error=refused),
        _item("item.started", "item_1", server="gm-bench", tool="end_phase", status="in_progress"),
        _item(
            "item.completed",
            "item_1",
            server="gm-bench",
            tool="end_phase",
            status="failed",
            error={"message": "MCP tool `gm-bench/end_phase` is not available to the model"},
        ),
        # Reached the server and failed there: still a call.
        _item("item.started", "item_2", server="gm-bench", tool="scout", status="in_progress"),
        _item(
            "item.completed",
            "item_2",
            server="gm-bench",
            tool="scout",
            status="failed",
            error={"message": "tool call error: tool call failed for `gm-bench/scout`"},
        ),
        _item("item.completed", "item_3", "command_execution", command="python3 gm_bench_proxy.py", status="completed"),
    ]
    telemetry = parse_codex_events(lines)
    assert telemetry["harness_tool_events"] == {"gm-bench_scout": 1, "shell": 1}
    assert telemetry["harness_tool_calls_skipped"] == {"gm-bench_end_phase": 1, "gm-bench_get_status": 1}
    assert opencode.harness_tool_calls(telemetry) == 1
    usage = codex.usage_block(telemetry, model="gpt-x", decisions=20)
    assert usage["harness"]["tool_calls_skipped"] == {"gm-bench_end_phase": 1, "gm-bench_get_status": 1}


def test_calls_codex_refused_and_the_agent_made_from_a_shell_fail_the_agreement_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the approval key, Codex refuses every MCP call; the shell-driven proxy calls must not pass as them."""
    from gm_bench.agentic.validate import validate_run

    real_config = codex.codex_config

    def unapproved(target, *, python="python3"):
        config = real_config(target, python=python)
        del config["mcp_servers"]["gm-bench"]["default_tools_approval_mode"]
        return config

    monkeypatch.setattr(codex, "codex_config", unapproved)
    binary, _log = _fake_codex(tmp_path, [{"phases": 4, "shell_proxy": True}], monkeypatch)
    run_dir = tmp_path / "run"
    payload = codex.run_panel(
        [11], model="gpt-fake", run_dir=run_dir, seasons=1, binary=str(binary), auth_file=_auth_file(tmp_path)
    )
    [episode] = payload["episodes"]
    assert episode["agentic"]["tool_calls"] == 8
    assert episode["harness_run"]["tool_call_agreement"] == {"ledger": 8, "harness": 0, "agree": False}
    assert episode["usage"]["harness"]["tool_calls_skipped"] == {"gm-bench_end_phase": 4, "gm-bench_get_status": 4}
    assert not validate_run(run_dir)["ok"]


@pytest.mark.parametrize("source", ["auth-file", "env"])
def test_a_codex_credential_the_agent_prints_is_redacted_from_the_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    from gm_bench.agentic.validate import validate_run

    binary, _log = _fake_codex(tmp_path, [{"phases": 4, "cat_auth": True}], monkeypatch)
    auth_file = None
    if source == "auth-file":
        auth_file = _auth_file(tmp_path)
    else:
        monkeypatch.setenv("CODEX_API_KEY", DUMMY_KEY)
    run_dir = tmp_path / "run"
    payload = codex.run_panel(
        [11],
        model="gpt-fake",
        run_dir=run_dir,
        seasons=1,
        binary=str(binary),
        auth_file=auth_file,
        keep_scratch=True,
    )
    events = (run_dir / "seed-11" / "codex-events.jsonl").read_text()
    assert "[REDACTED]" in events and "[REDACTED]" in (run_dir / "seed-11" / "codex-stderr.log").read_text()
    leaked = [path for path in run_dir.rglob("*") if path.is_file() and DUMMY_KEY in path.read_text()]
    assert leaked == []
    # The redacted stream still parses and still agrees with the ledger.
    assert payload["episodes"][0]["harness_run"]["tool_call_agreement"]["agree"] is True
    assert validate_run(run_dir)["ok"]


def test_codex_publishes_no_cost_even_for_a_priced_model_and_no_measured_zeroes() -> None:
    """Codex reports tokens but no cost: a list-price estimate must not stand in as the harness's cost."""
    from web.scripts.build_study import _agentic_telemetry

    usage = {"input_tokens": 2_000_000, "cached_input_tokens": 1_800_000, "output_tokens": 10_000}
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t"}),
        json.dumps({"type": "turn.completed", "usage": usage}),
    ]
    block = codex.usage_block(parse_codex_events(lines), model="gpt-5.5", decisions=20)
    # The shared usage block would price this at gpt-5.5 list rates; Codex keeps it unmeasured.
    shared = opencode.usage_block(
        parse_codex_events(lines) | {"max_output_tokens_per_call": 0}, model="gpt-5.5", decisions=20
    )
    assert shared["cost_usd"] is not None
    assert block["cost_usd"] is None and block["cost_decisions"] == 0
    assert "max_output_tokens_per_call" not in block
    assert block["input_tokens"] == 2_000_000 and block["harness"]["compactions"] is None

    episode = {"agentic": {"tool_calls": 8}, "harness_run": {"wall_seconds": 1.0}, "usage": block}
    telemetry = _agentic_telemetry([episode, copy.deepcopy(episode)])
    assert telemetry["cost_usd"] is None and telemetry["cost_per_episode_usd"] is None
    assert telemetry["compactions"] is None
    assert telemetry["input_tokens"] == 4_000_000
    # A harness that does report compactions still sums them.
    counted = copy.deepcopy(episode)
    counted["usage"]["harness"]["compactions"] = 2
    assert _agentic_telemetry([counted, counted])["compactions"] == 4
    assert opencode._compactions([counted, counted]) == 4
    assert opencode._compactions([{"usage": block}, {"usage": counted["usage"]}]) is None


def test_codex_usage_block_carries_an_api_equivalent_estimate_beside_an_unmeasured_cost() -> None:
    """The estimate prices cached input at the cached rate and is labelled as never billed."""
    from web.scripts.build_study import _agentic_telemetry

    first = {
        "input_tokens": 200_000,
        "cached_input_tokens": 0,
        "output_tokens": 4_000,
        "reasoning_output_tokens": 1_000,
    }
    # Running totals: this turn's input grew by 1,000,000 - 200,000 = 800,000 (> 272K).
    second = {
        "input_tokens": 1_000_000,
        "cached_input_tokens": 700_000,
        "cache_write_input_tokens": 100_000,
        "output_tokens": 20_000,
        "reasoning_output_tokens": 8_000,
    }
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t"}),
        json.dumps({"type": "turn.completed", "usage": first}),
        json.dumps({"type": "thread.started", "thread_id": "t"}),
        json.dumps({"type": "turn.completed", "usage": second}),
    ]
    telemetry = parse_codex_events(lines)
    assert telemetry["max_turn_input_tokens"] == 800_000
    block = codex.usage_block(telemetry, model="gpt-6-luna", decisions=20)
    assert block["cost_usd"] is None and block["cost_decisions"] == 0
    # The shared token shape: inclusive input, output with reasoning inside it.
    assert block["token_shape"] == "inclusive-v1"
    assert (block["input_tokens"], block["uncached_input_tokens"]) == (1_000_000, 200_000)
    assert (block["cached_input_tokens"], block["cache_write_input_tokens"]) == (700_000, 100_000)
    assert (block["output_tokens"], block["reasoning_tokens"]) == (20_000, 8_000)
    harness = block["harness"]
    # 200k uncached at 0.10 + 700k cached at 0.01 + 100k written at 0.125 + 20k out at 0.50.
    assert harness["api_equivalent_cost_usd"] == pytest.approx(0.02 + 0.007 + 0.0125 + 0.01)
    assert harness["cost_basis"] == "api-list-price-estimate"
    assert harness["billed_by_harness"] is False and harness["cost_reported_by_harness"] is False
    assert harness["pricing_source"] == {
        "key": "gpt-6-luna",
        "verified": "2026-09-23",
        "cached_input_rate": "cached",
        "cache_write_rate": "cache-write",
    }
    assert harness["long_context_requests_possible"] is True
    short = parse_codex_events(lines[:2])
    assert (
        codex.usage_block(short, model="gpt-6-luna", decisions=20)["harness"]["long_context_requests_possible"] is False
    )

    # No usage, or an unpriced model: no estimate, and still no cost.
    for silent in (
        codex.usage_block(parse_codex_events([]), model="gpt-6-luna", decisions=20),
        codex.usage_block(telemetry, model="mystery-model-9000", decisions=20),
    ):
        assert silent["cost_usd"] is None
        assert silent["harness"]["api_equivalent_cost_usd"] is None and silent["harness"]["pricing_source"] is None
        assert silent["harness"]["billed_by_harness"] is False

    # OpenCode's block is unchanged: no estimate fields.
    assert (
        "api_equivalent_cost_usd"
        not in opencode.usage_block(telemetry | {"max_output_tokens_per_call": 0}, model="gpt-6-luna", decisions=20)[
            "harness"
        ]
    )

    # The site shows the estimate and never folds it into cost_usd.
    episode = {"agentic": {"tool_calls": 8}, "harness_run": {"wall_seconds": 1.0}, "usage": block}
    site = _agentic_telemetry([episode, copy.deepcopy(episode)])
    assert site["cost_usd"] is None and site["cost_per_episode_usd"] is None
    assert site["api_equivalent_cost_usd"] == pytest.approx(2 * 0.0495)
    assert site["api_equivalent_cost_per_episode_usd"] == pytest.approx(0.0495)
    assert site["api_equivalent_cost_episodes"] == 2 and site["api_equivalent_long_context_possible"] is True
    # A billed cost stays the only cost_usd; an OpenCode row has no estimate.
    billed = opencode.usage_block(
        parse_codex_events(lines) | {"max_output_tokens_per_call": 0, "cost_usd": 0.5}, model="x", decisions=20
    )
    other = _agentic_telemetry([{"agentic": {}, "harness_run": {}, "usage": billed}])
    assert other["cost_usd"] == 0.5 and other["api_equivalent_cost_usd"] is None
    assert other["api_equivalent_cost_episodes"] == 0

    summary = opencode._agentic_summary(
        [
            {
                "agentic": {"tool_calls": 1, "tool_calls_by_tool": {}, "phases_ended_by": {}},
                "harness_run": {"wall_seconds": 1.0},
                "usage": block,
            }
        ]
        * 2
    )
    assert summary["api_equivalent_cost_usd"] == pytest.approx(0.099)
    assert summary["api_equivalent_cost_episodes"] == 2 and summary["api_equivalent_long_context_possible"] is True
    opencode_summary = opencode._agentic_summary(
        [
            {
                "agentic": {"tool_calls": 1, "tool_calls_by_tool": {}, "phases_ended_by": {}},
                "harness_run": {"wall_seconds": 1.0},
                "usage": billed,
            }
        ]
    )
    assert "api_equivalent_cost_usd" not in opencode_summary


# -- subscription quota windows --------------------------------------------------

RESET = 1_790_000_000  # 2026-09-21T14:13:20Z, epoch seconds as Codex reports resets_at


def _limits(primary: float, *, limit_id: str | None = "codex", **extra) -> dict:
    snapshot = {
        "limit_id": limit_id,
        "limit_name": None,
        "primary": {"used_percent": primary, "window_minutes": 300, "resets_at": RESET},
        "secondary": {"used_percent": 41.0, "window_minutes": 10080, "resets_at": RESET + 86_400},
        "credits": {"has_credits": True, "unlimited": False, "balance": "917.25"},
        "plan_type": "plus",
        "rate_limit_reached_type": None,
    }
    return snapshot | extra


def test_rollout_quota_keeps_the_main_allowance_merges_partial_updates_and_drops_credits() -> None:
    def line(stamp: str, limits: dict | None, kind: str = "token_count") -> str:
        payload = {"type": kind, "info": {"total_token_usage": {"input_tokens": 5}}, "rate_limits": limits}
        return json.dumps({"timestamp": stamp, "type": "event_msg", "payload": payload})

    lines = [
        line(
            "2026-09-23T00:00:02.000Z",
            {"limit_id": "codex", "primary": {"used_percent": 88.0, "window_minutes": 300, "resets_at": RESET}},
        ),
        line("2026-09-23T00:00:01.000Z", _limits(10.0)),
        # A model-specific allowance never replaces the main one.
        line("2026-09-23T00:00:03.000Z", _limits(100.0, limit_id="codex_spark")),
        line("2026-09-23T00:00:04.000Z", None),
        line("2026-09-23T00:00:05.000Z", _limits(99.0), kind="agent_message"),
        "not json",
    ]
    quota = codex.rollout_quota(lines)
    # Timestamp order: the 00:02 update replaces primary and keeps the earlier secondary and plan.
    assert quota == {
        "quota_windows": [
            {"window_minutes": 300, "used_percent": 88.0, "resets_at_utc": "2026-09-21T14:13:20+00:00"},
            {"window_minutes": 10080, "used_percent": 41.0, "resets_at_utc": "2026-09-22T14:13:20+00:00"},
        ],
        "plan_type": "plus",
    }
    assert "917.25" not in json.dumps(quota)
    # No token_count with rate limits (an API key): nothing recorded.
    assert codex.rollout_quota([line("2026-09-23T00:00:01.000Z", None)]) == {}
    # Durations default by position; a free plan's primary window is monthly.
    bare = {"primary": {"used_percent": 150}, "secondary": {"used_percent": -3}, "plan_type": "free"}
    windows = codex.quota_windows(bare)
    assert [(w["window_minutes"], w["used_percent"], w["resets_at_utc"]) for w in windows] == [
        (30 * 24 * 60, 100.0, None),
        (7 * 24 * 60, 0.0, None),
    ]


def test_codex_quota_windows_are_recorded_per_episode_and_pause_the_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from web.scripts.build_study import _agentic_telemetry

    steps = [
        # Episode 0 ends with its 5-hour window 97.5% used, plus a model-specific snapshot that must not count.
        {"phases": 4, "rate_limits": [_limits(97.5), _limits(100.0, limit_id="codex_spark")]},
        # Episode 1 is well under the threshold: no pause after it (and none after the last episode anyway).
        {"phases": 4, "rate_limits": [_limits(12.0)]},
    ]
    binary, _log = _fake_codex(tmp_path, steps, monkeypatch)
    sleeps: list[float] = []
    events: list[dict] = []
    run_dir = tmp_path / "run"
    payload = codex.run_panel(
        [11, 12],
        model="gpt-fake",
        run_dir=run_dir,
        seasons=1,
        binary=str(binary),
        auth_file=_auth_file(tmp_path),
        max_provider_stall_wait_seconds=3600.0,
        sleep=sleeps.append,
        clock=lambda: RESET - 100.0,
        progress=events.append,
    )
    first, second = (episode["harness_run"] for episode in payload["episodes"])
    assert first["quota_windows"][0] == {
        "window_minutes": 300,
        "used_percent": 97.5,
        "resets_at_utc": "2026-09-21T14:13:20+00:00",
    }
    assert first["plan_type"] == "plus" and second["quota_windows"][0]["used_percent"] == 12.0
    # Until the reset plus a minute, through the injected sleep.
    assert sleeps == [160.0]
    pause = {
        "after_episode": 0,
        "window_minutes": 300,
        "used_percent": 97.5,
        "resets_at_utc": "2026-09-21T14:13:20+00:00",
        "wait_seconds": 160.0,
        "capped": False,
    }
    assert payload["quota_pauses"] == [pause] and payload["quota_pause_percent"] == 95.0
    assert {"stage": "quota_pause", **pause} in events
    text = (run_dir / "run.json").read_text()
    assert "917.25" not in text and "has_credits" not in text and "seed" not in json.dumps(payload["quota_pauses"])

    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["quota_pauses"] == [pause]
    assert artifact["episodes"][0]["harness_run"]["quota_windows"] == first["quota_windows"]
    assert artifact["episodes"][0]["harness_run"]["plan_type"] == "plus"
    assert validate_agentic_artifact(artifact, raw_run=run_dir)["ok"]
    quota = _agentic_telemetry(artifact["episodes"], quota_pauses=artifact["quota_pauses"])["quota"]
    assert quota == {
        "episodes_reporting": 2,
        "plan_types": ["plus"],
        "window_minutes": [300, 10080],
        "max_used_percent": 97.5,
        "pauses": 1,
        "pause_seconds": 160.0,
        "episodes_ended_by_quota": 0,
    }


def test_quota_pause_is_bounded_and_skipped_when_the_window_already_reset() -> None:
    episode = {
        "harness_run": {
            "quota_windows": [
                {"window_minutes": 300, "used_percent": 96.0, "resets_at_utc": "2026-09-21T14:13:20+00:00"},
                {"window_minutes": 10080, "used_percent": 100.0, "resets_at_utc": "2026-09-22T14:13:20+00:00"},
            ]
        }
    }
    # Both windows are exhausted: wait for the later reset, capped by the stall-wait bound.
    capped = opencode._quota_pause(episode, 3, 95.0, 600.0, RESET)
    assert capped["resets_at_utc"] == "2026-09-22T14:13:20+00:00"
    assert capped["wait_seconds"] == 600.0 and capped["capped"] is True and capped["after_episode"] == 3
    assert opencode._quota_pause(episode, 3, 95.0, 600.0, RESET + 90_000) is None
    assert opencode._quota_pause(episode, 3, 100.5, 600.0, RESET) is None
    assert opencode._quota_pause({"harness_run": {}}, 0, 95.0, 600.0, RESET) is None


def test_container_quota_read_returns_only_matching_lines_and_never_raises(tmp_path: Path) -> None:
    from gm_bench.agentic.container import ContainerHarness

    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "open(sys.argv[0] + '.log', 'a').write(json.dumps(args) + '\\n')\n"
        "if args[:1] == ['run']:\n"
        '    print(\'{"type": "token_count"}\')\n'
    )
    docker.chmod(0o755)
    harness = ContainerHarness({"image_id": "sha256:x"}, tmp_path, driver_port=1, docker=str(docker), env={})
    lines = harness.home_lines(".codex/sessions", "rollout-*.jsonl", '"token_count"')
    assert lines == ['{"type": "token_count"}']
    run = [json.loads(line) for line in Path(str(docker) + ".log").read_text().splitlines()][-1]
    assert run[:2] == ["run", "--rm"] and "none" in run and "ALL" in run
    assert run[-3:] == ["/home/node/.codex/sessions", "rollout-*.jsonl", '"token_count"']
    broken = ContainerHarness({"image_id": "sha256:x"}, tmp_path, driver_port=1, docker=str(docker), env={})
    broken.docker = str(tmp_path / "missing-docker")
    assert broken.home_lines(".codex/sessions", "rollout-*.jsonl", '"token_count"') is None


@pytest.mark.parametrize(
    "message",
    [
        "exceeded retry limit, last status: 429 Too Many Requests, request id: abc",
        "unexpected status 503 Service Unavailable: upstream connect error",
        "rate limit exceeded: slow down",
        "stream disconnected before completion: error sending request",
        "Connection failed: error sending request for url",
        "We’re currently experiencing high demand, which may cause temporary errors.",
        "Selected model is at capacity. Please try a different model.",
        "request timed out",
    ],
)
def test_retryable_codex_failures_are_provider_stalls(message: str) -> None:
    started = json.dumps({"type": "thread.started", "thread_id": "t"})
    assert ended_in_provider_stall([started, json.dumps({"type": "turn.failed", "error": {"message": message}})])
    assert ended_in_provider_stall([started, json.dumps({"type": "error", "message": message}), ""])


# -- quota exhaustion: "You've hit your usage limit ... try again at" ------------------

# Exactly what the first real Codex launch printed (Codex CLI 0.156.1, Plus plan).
USAGE_LIMIT = (
    "You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
    "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Sep 24th, 2026 4:19 PM."
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (USAGE_LIMIT, "2026-09-24T16:19:00+00:00"),
        ("You’ve hit your usage limit. Try again at Sep 1st, 2026 12:05 AM.", "2026-09-01T00:05:00+00:00"),
        ("You’ve hit your usage limit. Try again at Oct 2nd, 2026 12:30 PM.", "2026-10-02T12:30:00+00:00"),
        ("You’ve hit your usage limit. Try again at Nov 23rd 2026 9:07 pm.", "2026-11-23T21:07:00+00:00"),
        ("You’ve hit your usage limit. Try again at December 11th, 2026 1:00 p.m.", "2026-12-11T13:00:00+00:00"),
        # Later the same local day, Codex prints only the time.
        ("You’ve hit your usage limit. Try again at 4:19 PM.", "2026-09-21T16:19:00+00:00"),
        ("You’ve hit your usage limit. Try again later.", None),
        ("You’ve hit your usage limit. Try again at Smarch 3rd, 2026 4:19 PM.", None),
        ("You’ve hit your usage limit. Try again at Sep 24th, 2026 13:19 PM.", None),
    ],
)
def test_usage_limit_reset_time_is_parsed_into_utc(message: str, expected: str | None) -> None:
    from datetime import timezone

    assert codex.parse_reset_time(message, tz=timezone.utc, now=RESET) == expected


def test_usage_limit_reset_is_read_in_the_zone_codex_printed_it_in() -> None:
    from datetime import timedelta, timezone

    eastern = timezone(timedelta(hours=-4))
    assert codex.parse_reset_time(USAGE_LIMIT, tz=eastern) == "2026-09-24T20:19:00+00:00"
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t"}),
        json.dumps({"type": "error", "message": USAGE_LIMIT}),
        json.dumps({"type": "turn.failed", "error": {"message": USAGE_LIMIT}}),
    ]
    # A usage limit is quota exhaustion, never a provider stall.
    assert not ended_in_provider_stall(lines)
    driver = CodexDriver()
    assert driver.quota_exhausted(lines, isolation="container", now=RESET) == {
        "message_class": "usage_limit",
        "reset_at_utc": "2026-09-24T16:19:00+00:00",
    }
    assert codex.quota_exhaustion(lines[:1]) is None
    assert codex.quota_exhaustion([lines[0], json.dumps({"type": "error", "message": "rate limit exceeded"})]) is None


def _utc_epoch(iso: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(iso).timestamp()


def test_usage_limit_within_the_wait_budget_pauses_then_resumes_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact

    # The fake prints the reset in the machine's local zone, as Codex does in same-user isolation.
    reset = _utc_epoch(codex.parse_reset_time(USAGE_LIMIT))
    steps = [{"phases": 1, "error": USAGE_LIMIT, "exit": 1}, {"phases": 3}]
    binary, log = _fake_codex(tmp_path, steps, monkeypatch)
    sleeps: list[float] = []
    events: list[dict] = []
    run_dir = tmp_path / "run"
    payload = codex.run_panel(
        [11],
        model="gpt-fake",
        run_dir=run_dir,
        seasons=1,
        binary=str(binary),
        auth_file=_auth_file(tmp_path),
        max_provider_stall_wait_seconds=3600.0,
        sleep=sleeps.append,
        clock=lambda: reset - 1000.0,
        progress=events.append,
    )
    [episode] = payload["episodes"]
    run = episode["harness_run"]
    # Until the reset plus a minute; no 60 s stall ladder.
    assert sleeps == [1060.0]
    assert run["provider_stalls"] == 0 and run["nudges_used"] == 0 and run["ended_by_quota"] is None
    [resume] = run["nudges"]
    assert resume["quota_resume"] is True and resume["stall_retry"] is False and resume["new_tool_calls"] == 6
    assert [call["argv"][:2] for call in _calls(log)] == [["exec", "--json"], ["exec", "resume"]]
    assert episode["failed_decisions"] == 0 and episode["agentic"]["phases_ended_by"] == {"agent": 4}
    [pause] = run["quota_pauses"]
    assert pause["resets_at_utc"] == codex.parse_reset_time(USAGE_LIMIT) and pause["wait_seconds"] == 1060.0
    assert pause["message_class"] == "usage_limit" and pause["during_episode"] is True
    assert payload["quota_pauses"] == [{"episode": 0, **pause}] and "stopped_for_quota" not in payload
    assert any(e["stage"] == "quota_exhausted" and e["action"] == "pause" for e in events)
    assert not any(e["stage"] == "provider_stall" for e in events)

    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["episodes"][0]["harness_run"]["quota_pauses"] == [pause]
    assert artifact["episodes"][0]["harness_run"]["nudges"][0]["quota_resume"] is True
    assert artifact["quota_pauses"] == payload["quota_pauses"]
    assert validate_agentic_artifact(artifact, raw_run=run_dir)["ok"]


def test_usage_limit_beyond_the_wait_budget_stops_the_episode_and_the_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from web.scripts.build_study import _agentic_telemetry

    reset_iso = codex.parse_reset_time(USAGE_LIMIT)
    steps = [{"phases": 1, "error": USAGE_LIMIT, "exit": 1}, {"phases": 3}]
    binary, log = _fake_codex(tmp_path, steps, monkeypatch)
    sleeps: list[float] = []
    events: list[dict] = []
    run_dir = tmp_path / "run"
    payload = codex.run_panel(
        [11, 12, 13],
        model="gpt-fake",
        run_dir=run_dir,
        seasons=1,
        binary=str(binary),
        auth_file=_auth_file(tmp_path),
        max_provider_stall_wait_seconds=3600.0,
        sleep=sleeps.append,
        # 20 hours before the reset: far beyond the 1 h budget.
        clock=lambda: _utc_epoch(reset_iso) - 72_000.0,
        progress=events.append,
    )
    # No sleep, no resume, no later seed.
    assert sleeps == [] and len(_calls(log)) == 1 and len(payload["episodes"]) == 1
    [episode] = payload["episodes"]
    run = episode["harness_run"]
    assert run["ended_by_quota"] == {"reset_at_utc": reset_iso, "message_class": "usage_limit"}
    assert run["nudges"] == [] and run["provider_stalls"] == 0 and run["nudges_used"] == 0
    # The phases the harness walked away from are closed as today's harness_exit path closes them.
    assert episode["agentic"]["phases_ended_by"] == {"agent": 1, "harness_exit": 3}
    assert payload["stopped_for_quota"] == {
        "after_episode": 0,
        "episodes_not_run": 2,
        "reset_at_utc": reset_iso,
        "message_class": "usage_limit",
    }
    assert any(e["stage"] == "quota_exhausted" and e["action"] == "stop" for e in events)
    assert any(e["stage"] == "panel_stopped_for_quota" for e in events)
    assert json.loads((run_dir / "run.json").read_text())["stopped_for_quota"] == payload["stopped_for_quota"]

    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["stopped_for_quota"] == payload["stopped_for_quota"]
    assert artifact["episodes"][0]["harness_run"]["ended_by_quota"] == run["ended_by_quota"]
    report = validate_agentic_artifact(artifact, raw_run=run_dir)
    # The run is incomplete: three seeds, one episode.
    assert not report["ok"] and "1 episodes for 3 seeds" in report["errors"]
    assert _agentic_telemetry(artifact["episodes"])["quota"]["episodes_ended_by_quota"] == 1


@pytest.mark.parametrize(
    "message",
    [
        "Quota exceeded. Check your plan and billing details.",
        "unexpected status 401 Unauthorized: Missing bearer or basic authentication in header, request id: 5000-503",
        "Codex ran out of room in the model's context window. Start a new thread or clear earlier history before retrying.",
        "To use Codex with your ChatGPT plan, upgrade to Plus: https://chatgpt.com/explore/plus.",
    ],
)
def test_non_retryable_codex_failures_are_the_harness_stopping(message: str) -> None:
    assert not ended_in_provider_stall([json.dumps({"type": "turn.failed", "error": {"message": message}})])


def test_only_a_terminal_codex_error_is_a_stall() -> None:
    error = json.dumps({"type": "error", "message": "stream disconnected before completion: reset"})
    done = json.dumps({"type": "turn.completed", "usage": {}})
    assert not ended_in_provider_stall([error, done])  # Codex retried and recovered
    assert not ended_in_provider_stall([done])
    assert not ended_in_provider_stall([])


# -- container mode -------------------------------------------------------------


def _fake_docker(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A stand-in docker CLI: logs argv, saves any stdin, answers probes like a clean Codex image."""
    from gm_bench.agentic.container import EGRESS_ENTRYPOINT

    log = tmp_path / "docker-calls.jsonl"
    stdin_dir = tmp_path / "docker-stdin"
    stdin_dir.mkdir()
    script = tmp_path / "fake-docker"
    report = {"uid": 1000, "cap_eff": "0000000000000000", "cap_bnd": "0000000000000000", "canary_reachable": False}
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        f"calls = Path({str(log)!r})\n"
        "index = len(calls.read_text().splitlines()) if calls.exists() else 0\n"
        "with calls.open('a') as handle:\n"
        "    handle.write(json.dumps(args) + '\\n')\n"
        "if '-i' in args:\n"
        f"    Path({str(stdin_dir)!r}, f'{{index}}.bin').write_bytes(sys.stdin.buffer.read())\n"
        "if args[:1] == ['version']:\n"
        "    print('29.3.1')\n"
        "elif args[:2] == ['image', 'inspect']:\n"
        "    print('sha256:' + 'c' * 64)\n"
        "elif 'import gm_bench' in args:\n"
        "    sys.stderr.write(\"ModuleNotFoundError: No module named 'gm_bench'\\n\")\n"
        "    sys.exit(1)\n"
        f"elif {EGRESS_ENTRYPOINT!r} in args and '-c' in args:\n"
        f"    print(json.dumps({report!r}))\n"
        "elif args[-2:] == ['codex', '--version']:\n"
        "    print('codex-cli 0.156.1')\n"
    )
    script.chmod(0o755)
    return script, log, stdin_dir


def test_codex_image_is_its_own_pinned_image_and_the_opencode_image_is_unchanged(tmp_path: Path) -> None:
    import hashlib

    from gm_bench.agentic.container import CODEX_IMAGE, dockerfile, ensure_image

    # The OpenCode image text (and so its tag and recorded digest) did not move.
    assert (
        hashlib.sha256(dockerfile().encode()).hexdigest()
        == "eaf1fdfb2359e16e4468530aeed10e6e249a67a751c8b9a488e58a8d9d416ba8"
    )
    codex_text = dockerfile(CODEX_IMAGE.version, package=CODEX_IMAGE.package)
    assert "npm install -g @openai/codex@0.156.1 " in codex_text and "opencode" not in codex_text
    docker, log, _stdin = _fake_docker(tmp_path)
    image = ensure_image(docker=str(docker), spec=CODEX_IMAGE)
    assert image["codex_version"] == "0.156.1" and "opencode_version" not in image
    assert image["image"].startswith("gm-bench-agentic-codex:0.156.1-")
    assert image["dockerfile_sha256"] == hashlib.sha256(codex_text.encode()).hexdigest()
    assert CodexDriver().ensure_image(docker=str(docker), env=dict(os.environ)) == image
    probes = [call for call in _calls(log) if call[-2:] == ["codex", "--version"]]
    assert len(probes) == 2 and all("--network" in call for call in probes)


def test_codex_container_launch_puts_the_auth_file_only_in_the_home_volume(tmp_path: Path) -> None:
    from gm_bench.agentic import _proxy
    from gm_bench.agentic.container import EGRESS_ENTRYPOINT, HOST_ALIAS, WORKDIR
    from gm_bench.agentic.episode import AgenticEpisode

    docker, log, stdin_dir = _fake_docker(tmp_path)
    image = {"image": "gm-bench-agentic-codex:test", "image_id": "sha256:" + "c" * 64}
    ledger = tmp_path / "run" / "seed-8675309" / "ledger.jsonl"
    episode = AgenticEpisode(8675309, seasons=1, ledger_path=ledger)
    auth = _auth_file(tmp_path)
    driver = CodexDriver(auth_file=auth)
    launch = opencode.HarnessLaunch(episode, isolation="container", image=image, docker=str(docker), driver=driver)
    try:
        # (d) the docker client carries no host Codex variables (and passes the container none anyway).
        assert not any(key.startswith("CODEX_") for key in launch.env)
        launch.prepare()
        port = launch.server.address[1]
        # The bind-mounted scratch holds only the proxy and its secret: no config, no credential.
        assert sorted(p.name for p in launch.scratch.iterdir()) == sorted(["gm_bench_proxy.py", _proxy.SECRET_FILENAME])
        calls = _calls(log)
        [seed_index] = [i for i, call in enumerate(calls) if "-i" in call]
        seeding = calls[seed_index]
        mounts = [seeding[i + 1] for i, arg in enumerate(seeding) if arg in ("--mount", "-v", "--volume")]
        assert (
            len(mounts) == 1
            and mounts[0].startswith("type=volume,source=gmb-home-")
            and mounts[0].endswith(",target=/home/node")
        )
        assert seeding[seeding.index("--network") + 1] == "none"
        assert seeding[seeding.index("--cap-drop") + 1] == "ALL" and "--cap-add" not in seeding
        assert "-e" not in seeding and "--env" not in seeding
        with tarfile.open(fileobj=io.BytesIO((stdin_dir / f"{seed_index}.bin").read_bytes())) as tar:
            members = {member.name: member for member in tar.getmembers()}
            assert sorted(members) == [".codex", ".codex/auth.json", ".codex/config.toml"]
            assert members[".codex/auth.json"].mode == 0o600 and members[".codex"].mode == 0o700
            assert tar.extractfile(".codex/auth.json").read() == auth.read_bytes()
            config = tomllib.loads(tar.extractfile(".codex/config.toml").read().decode())
        assert config == {
            "mcp_servers": {
                "gm-bench": {
                    "command": "python3",
                    "args": ["gm_bench_proxy.py", f"{HOST_ALIAS}:{port}"],
                    "default_tools_approval_mode": "approve",
                }
            }
        }

        argv, on_kill = launch.command(
            driver.run_args(model="gpt-x", variant=None, workdir=launch.workdir, brief="BRIEF", isolation="container")
        )
        assert on_kill is not None
        assert argv[argv.index(image["image_id"]) + 1 :] == [
            EGRESS_ENTRYPOINT,
            str(port),
            "codex",
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--model",
            "gpt-x",
            "-c",
            'sandbox_mode="danger-full-access"',
            "BRIEF",
        ]
        binds = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--mount" and argv[i + 1].startswith("type=bind")]
        assert binds == [f"type=bind,source={launch.scratch},target={WORKDIR}"]
        record = driver.run_record(launch)
        assert record["auth"] == "auth-file" and record["sandbox_mode"] == "danger-full-access"
        assert record["codex_home"].startswith("/home/node/.codex")
    finally:
        assert launch.close() is True
    calls = _calls(log)
    # The credential and the key never appear on any docker command line or in the run's record.
    assert not any(DUMMY_KEY in arg or str(auth) in arg for call in calls for arg in call)
    assert DUMMY_KEY not in json.dumps(record)
    volume = mounts[0].split(",")[1].removeprefix("source=")
    assert calls[-1] == ["volume", "rm", "--force", volume]
    episode.close()


# -- CLI ------------------------------------------------------------------------


def test_cli_dispatches_codex_and_keeps_opencode_the_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gm_bench import cli

    seen: dict = {}

    def fake_run_panel(name):
        def run(seeds, **kwargs):
            seen[name] = kwargs
            raise SystemExit(0)

        return run

    monkeypatch.setattr(codex, "run_panel", fake_run_panel("codex"))
    monkeypatch.setattr(opencode, "run_panel", fake_run_panel("opencode"))
    auth = _auth_file(tmp_path)
    base = ["agentic", "--seeds", "11", "--model", "gpt-x", "--output", str(tmp_path / "run")]
    with pytest.raises(SystemExit):
        cli.main([*base, "--harness", "codex", "--codex-auth-file", str(auth), "--variant", "low"])
    assert seen["codex"]["auth_file"] == str(auth)
    assert (seen["codex"]["binary"], seen["codex"]["variant"]) == ("codex", "low")
    with pytest.raises(SystemExit):
        cli.main(base)
    assert seen["opencode"]["binary"] == "opencode" and "auth_file" not in seen["opencode"]

    with pytest.raises(SystemExit, match="only for --harness codex"):
        cli.main([*base, "--codex-auth-file", str(auth)])
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    seen.clear()
    with pytest.raises(SystemExit, match="needs --codex-auth-file"):
        cli.main([*base, "--harness", "codex", "--isolation", "container"])
    with pytest.raises(SystemExit, match="needs credentials"):
        cli.main([*base, "--harness", "codex"])
    assert seen == {}


def test_keychain_launcher_passes_the_harness_through() -> None:
    import argparse

    from scripts.run_bench_v2_panel_from_keychain import agentic_argv

    args = argparse.Namespace(model="gpt-x", output=Path("/elsewhere/run"), seasons=5)
    argv = agentic_argv(
        args, ["--harness", "codex", "--codex-auth-file", "/secure/auth.json", "--isolation", "container"]
    )
    assert argv[-6:] == ["--harness", "codex", "--codex-auth-file", "/secure/auth.json", "--isolation", "container"]
    assert "--seeds" not in argv
