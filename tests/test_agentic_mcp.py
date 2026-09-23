"""The hand-written MCP server, driven over stdio by a minimal JSON-RPC client."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from gm_bench.agentic.mcp_server import EPISODE_ENV, SocketMcpServer
from gm_bench.agentic.opencode import (
    harness_environment,
    opencode_config,
    parse_opencode_events,
    sandbox_problems,
    usage_block,
)
from gm_bench.agentic.tools import TOOLS

REPO_ROOT = Path(__file__).resolve().parents[1]


class _Client:
    def __init__(self, episode_file: Path) -> None:
        env = {**os.environ, EPISODE_ENV: str(episode_file), "PYTHONPATH": str(REPO_ROOT)}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "gm_bench.agentic.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.next_id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        payload = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            payload["params"] = params
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        assert line, self.process.stderr.read() if self.process.stderr else ""
        reply = json.loads(line)
        assert reply["id"] == self.next_id
        return reply

    def notify(self, method: str) -> None:
        assert self.process.stdin
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.process.stdin.flush()

    def call(self, name: str, arguments: dict | None = None) -> dict:
        reply = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        assert "result" in reply, reply
        return reply["result"]

    def close(self) -> None:
        assert self.process.stdin
        self.process.stdin.close()
        self.process.wait(timeout=20)


class _SocketClient:
    """A JSON-RPC client over the driver's Unix socket, standing in for the proxy."""

    def __init__(self, path: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.reader = self.sock.makefile("r", encoding="utf-8")
        self.next_id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        payload = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        line = self.reader.readline()
        assert line, "socket server closed without answering"
        reply = json.loads(line)
        assert reply["id"] == self.next_id
        return reply

    def close(self) -> None:
        self.reader.close()
        self.sock.close()


def _episode_file(tmp_path: Path, seasons: int = 1) -> Path:
    path = tmp_path / "episode.json"
    path.write_text(
        json.dumps({"seed": 11, "seasons": seasons, "user_team_id": 0, "ledger_path": str(tmp_path / "ledger.jsonl")})
    )
    return path


def test_handshake_listing_and_tool_calls(tmp_path: Path) -> None:
    client = _Client(_episode_file(tmp_path))
    init = client.request(
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
    )["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["serverInfo"]["name"] == "gm-bench"
    assert "tools" in init["capabilities"]
    client.notify("notifications/initialized")
    assert client.request("ping")["result"] == {}
    listing = client.request("tools/list")["result"]["tools"]
    assert [tool["name"] for tool in listing] == [tool["name"] for tool in TOOLS]

    status = client.call("get_status")
    assert status["isError"] is False
    body = json.loads(status["content"][0]["text"])
    assert body["data"]["season"] == 1 and body["data"]["phase"] == "preseason"
    assert status["structuredContent"]["data"]["team"]["id"] == 0

    bad = client.call("scout", {"player_id": "nope"})
    assert bad["isError"] is True

    unknown = client.request("nope/method")
    assert unknown["error"]["code"] == -32601
    client.close()


def test_server_restart_resumes_from_ledger(tmp_path: Path) -> None:
    episode_file = _episode_file(tmp_path, seasons=1)
    first = _Client(episode_file)
    first.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {}})
    first.call("write_memo", {"text": "before restart"})
    first.call("end_phase")
    first.call("end_phase")
    first.close()

    second = _Client(episode_file)
    second.request("initialize", {"protocolVersion": "2099-01-01", "capabilities": {}, "clientInfo": {}})
    status = second.call("get_status")["structuredContent"]["data"]
    assert (status["season"], status["phase"]) == (1, "trade_deadline")
    assert status["memo"] == "before restart"
    second.call("end_phase")
    last = second.call("end_phase")["structuredContent"]
    assert last["episode_complete"] is True
    after = second.call("get_status")
    assert after["isError"] is True and after["structuredContent"]["episode_complete"] is True
    second.close()
    ledger = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert ledger[0]["event"] == "episode"
    # The closing tool call is logged after the phase/episode events it triggers,
    # and the refused post-completion call is logged too, unexecuted.
    assert [r["event"] for r in ledger[-4:]] == ["phase_end", "episode_end", "tool_call", "tool_call"]
    assert ledger[-2]["tool"] == "end_phase"
    assert ledger[-1]["tool"] == "get_status" and ledger[-1]["executed"] is False
    assert sum(1 for r in ledger if r["event"] == "episode") == 1
    assert not any(r["event"] == "tool_call" and r["tool"] == "get_status" and r["season"] > 1 for r in ledger)


def test_harness_environment_and_sandbox_check(tmp_path: Path) -> None:
    env = harness_environment(
        {
            "PATH": f"{REPO_ROOT / '.venv' / 'bin'}:/usr/bin:/bin",
            "PYTHONPATH": str(REPO_ROOT),
            "GM_BENCH_PRIVATE_SEEDS": "1,2,3",
            "GM_BENCH_DB": "x",
            "HOME": "/tmp",
        }
    )
    assert "PYTHONPATH" not in env
    assert not any(key.startswith("GM_BENCH_") for key in env)
    assert str(REPO_ROOT) not in env["PATH"]
    assert env["HOME"] == "/tmp"

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    # A python that can import gm_bench must be flagged.
    problems = sandbox_problems(scratch, {"PATH": str(Path(sys.executable).parent), "PYTHONPATH": str(REPO_ROOT)})
    assert any("can import gm_bench" in problem for problem in problems)
    # A scratch directory beneath a checkout must be flagged.
    inside = REPO_ROOT / "build" / "scratch-probe"
    inside.mkdir(parents=True, exist_ok=True)
    try:
        problems = sandbox_problems(inside, {"PATH": ""})
        assert any("inside the GM-Bench checkout" in problem for problem in problems)
    finally:
        inside.rmdir()
    # A clean scratch with no python on PATH passes.
    assert sandbox_problems(scratch, {"PATH": ""}) == []


def test_opencode_config_and_event_parsing(tmp_path: Path) -> None:
    config = opencode_config(tmp_path / "s", python="/harness/python3")
    server = config["mcp"]["servers"]["gm-bench"]
    assert server["command"] == ["/harness/python3", "gm_bench_proxy.py", str(tmp_path / "s")]
    assert server["codemode"] is False
    # Nothing the agent can read names the seed, our interpreter, or the checkout.
    rendered = json.dumps(config)
    assert "seed" not in rendered and str(REPO_ROOT) not in rendered and sys.executable not in rendered

    lines = [
        json.dumps({"type": "step_start", "sessionID": "ses_1", "part": {"type": "step-start"}}),
        json.dumps({"type": "tool", "sessionID": "ses_1", "part": {"type": "tool", "tool": "gm-bench_get_status"}}),
        json.dumps(
            {
                "type": "step_finish",
                "sessionID": "ses_1",
                "part": {
                    "type": "step-finish",
                    "tokens": {"input": 100, "output": 10, "reasoning": 5, "cache": {"read": 40, "write": 2}},
                    "cost": 0.001,
                },
            }
        ),
        "not json",
        json.dumps({"type": "step_finish", "part": {"type": "step-finish", "tokens": {"input": 50, "output": 5}}}),
    ]
    telemetry = parse_opencode_events(lines)
    assert telemetry["model_calls"] == 2
    assert telemetry["input_tokens"] == 150 and telemetry["output_tokens"] == 15
    assert telemetry["reasoning_tokens"] == 5 and telemetry["cached_input_tokens"] == 40
    assert telemetry["cost_usd"] == 0.001
    assert telemetry["harness_tool_events"] == {"gm-bench_get_status": 1}
    assert telemetry["session_id"] == "ses_1"
    assert telemetry["max_output_tokens_per_call"] == 10
    usage = usage_block(telemetry, model="opencode/test", decisions=20)
    assert usage["api_calls"] == 2 and usage["input_tokens"] == 150
    assert usage["cost_usd"] == 0.001
    assert usage["harness"]["telemetry_reported"] is True
    # One session total covers all twenty decisions: the run summary divides
    # by that, not by the one record; wall time is not API latency.
    assert usage["decisions_with_usage"] == 20 and usage["cost_decisions"] == 20
    assert usage["total_tokens"] == 165 and usage["max_output_tokens_per_call"] == 10
    assert usage["api_latency_ms"] == 0.0
    silent = usage_block(parse_opencode_events([]), model="opencode/test", decisions=20)
    assert silent["cost_usd"] is None and silent["harness"]["telemetry_reported"] is False
    assert silent["decisions_with_usage"] == 0 and silent["cost_decisions"] == 0


def test_agentic_contract_layers_on_the_unchanged_base_contract() -> None:
    from gm_bench.agentic.contract import agentic_contract, agentic_fingerprint
    from gm_bench.agentic.opencode import tool_call_agreement
    from gm_bench.contract import _CONTRACT_SOURCES, benchmark_contract

    contract = agentic_contract()
    base = benchmark_contract()
    assert contract["base_contract_fingerprint"] == base["contract_fingerprint"]
    assert contract["agentic_fingerprint"] == agentic_fingerprint()
    assert len(contract["agentic_fingerprint"]) == 16
    assert contract["agentic_fingerprint"] != base["contract_fingerprint"]
    # The 1.0 source list must never grow to include 2.0 files.
    assert not any("agentic" in path for path in _CONTRACT_SOURCES)

    telemetry = {"harness_tool_events": {"gm-bench_get_status": 3, "gm-bench_end_phase": 4, "bash": 2}}
    assert tool_call_agreement({"tool_calls": 7}, telemetry) == {"ledger": 7, "harness": 7, "agree": True}
    assert tool_call_agreement({"tool_calls": 8}, telemetry)["agree"] is False


def test_validate_run_replays_audits_and_checks_contract(tmp_path: Path) -> None:
    from gm_bench.agentic.contract import agentic_contract
    from gm_bench.agentic.episode import AgenticEpisode
    from gm_bench.agentic.validate import validate_run

    run_dir = tmp_path / "run"
    ledger = run_dir / "seed-11" / "ledger.jsonl"
    episode = AgenticEpisode(11, seasons=1, ledger_path=ledger)
    roster = episode.call_tool("get_team", {})["data"]["roster"]
    episode.call_tool("set_lineup", {"player_ids": [p["id"] for p in roster][:18]})
    while not episode.done:
        episode.call_tool("end_phase", {})
    result = episode.result("opencode:test")
    episode.close()
    calls = result["agentic"]["tool_calls"]
    events = ledger.with_name("opencode-events.jsonl")
    lines = []
    for tool, count in result["agentic"]["tool_calls_by_tool"].items():
        part = {"type": "tool", "tool": f"gm-bench_{tool}"}
        lines.extend(json.dumps({"type": "tool", "sessionID": "ses_x", "part": part}) for _ in range(count))
    events.write_text("\n".join(lines) + "\n")
    # Paths relative to the run directory, as the driver records them.
    result["harness_run"] = {
        "ledger_path": "seed-11/ledger.jsonl",
        "events_path": "seed-11/opencode-events.jsonl",
        "tool_call_agreement": {"ledger": calls, "harness": calls, "agree": True},
        "exit_code": 0,
        "timed_out": False,
    }
    result["usage"]["harness"] = {"telemetry_reported": True}
    run = {
        "agent": "opencode:test",
        "harness": {"name": "opencode"},
        "contract": agentic_contract(),
        "seeds": [11],
        "episodes": [result],
    }
    (run_dir / "run.json").write_text(json.dumps(run))

    def check() -> dict:
        (run_dir / "run.json").write_text(json.dumps(run))
        return validate_run(run_dir)

    report = check()
    assert report["ok"], report
    assert report["per_episode"][0]["replayed_score"] == result["final_score"]
    assert report["per_episode"][0]["replayed_tool_calls"] == report["per_episode"][0]["harness_tool_calls"] == calls
    assert report["warnings"] == []

    # The agreement is recomputed from the evidence, not read from the claim.
    run["episodes"][0]["harness_run"]["tool_call_agreement"] = {"ledger": 99999, "harness": 0, "agree": True}
    report = check()
    assert any("does not match the recomputed" in p for p in report["problems"]), report["problems"]
    run["episodes"][0]["harness_run"]["tool_call_agreement"] = {"ledger": calls, "harness": calls, "agree": True}
    events.write_text("\n".join(lines[:-1]) + "\n")  # a truncated harness stream
    report = check()
    assert any(f"harness stream has {calls - 1}" in p for p in report["problems"]), report["problems"]
    events.unlink()
    report = check()
    assert any("harness event stream missing" in p for p in report["problems"])
    events.write_text("\n".join(lines) + "\n")

    # The run's seed list must match the episodes; the ledger header must match the episode.
    run["seeds"] = [12]
    assert any("run.seeds does not match" in p for p in check()["problems"])
    run["seeds"] = [11]
    run["episodes"][0]["seed"] = 12
    assert any("ledger header seed" in p for p in check()["problems"])
    run["episodes"][0]["seed"] = 11
    assert check()["ok"]

    # A corrupt ledger is reported by both replay and audit, and validation still returns.
    good = ledger.read_text()
    ledger.write_text(good + "{not json\n")
    report = check()
    assert report["ok"] is False
    assert any("does not replay" in p for p in report["problems"])
    assert any("does not audit" in p for p in report["problems"])
    ledger.write_text(good)

    # Tamper with the score and the contract: both must be caught.
    run["episodes"][0]["final_score"] += 1.0
    run["contract"]["agentic_fingerprint"] = "0" * 16
    report = check()
    assert report["ok"] is False
    assert any("replayed score" in p for p in report["problems"])
    assert any("contract.agentic_fingerprint" in p for p in report["problems"])


def test_nudge_loop_resumes_until_done_and_stops_without_progress(tmp_path: Path, monkeypatch) -> None:
    """Drive run_episode with a fake harness: it plays a little per invocation, then stalls."""
    import gm_bench.agentic.opencode as driver

    calls: list[list[str]] = []

    def fake_harness(command, *, cwd, env, events_path, stderr_path, timeout, stalled=None):
        calls.append(command)
        config = json.loads((cwd / "opencode.json").read_text())
        socket_path = config["mcp"]["servers"]["gm-bench"]["command"][2]
        assert (cwd / "gm_bench_proxy.py").is_file()
        with events_path.open("a") as events:
            events.write(json.dumps({"type": "step_start", "sessionID": "ses_fake", "part": {}}) + "\n")
            invocation = len(calls)
            # First run: one phase. First nudge: one more. Second nudge: nothing (model gives up).
            if invocation <= 2:
                client = _SocketClient(socket_path)
                client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}})
                for name in ("get_status", "end_phase"):
                    reply = client.request("tools/call", {"name": name, "arguments": {}})
                    assert "result" in reply, reply
                    part = {"type": "tool", "tool": f"gm-bench_{name}"}
                    events.write(json.dumps({"type": "tool", "sessionID": "ses_fake", "part": part}) + "\n")
                client.close()
            finish = {"type": "step-finish", "tokens": {"input": 10, "output": 1}}
            events.write(json.dumps({"type": "step_finish", "sessionID": "ses_fake", "part": finish}) + "\n")
        return 0, False, 1.0, False

    monkeypatch.setattr(driver, "_run_harness", fake_harness)
    monkeypatch.setattr(driver, "sandbox_problems", lambda scratch, env: [])
    result = driver.run_episode(11, model="fake/model", run_dir=tmp_path / "run", seasons=1, max_nudges=5)
    harness_run = result["harness_run"]
    # Evidence paths are recorded relative to the run directory.
    assert harness_run["ledger_path"] == "seed-11/ledger.jsonl"
    assert harness_run["events_path"] == "seed-11/opencode-events.jsonl"
    assert harness_run["guard_kills"] == 0
    assert harness_run["server_drained"] is True
    # Initial run + nudge with progress + nudge without progress, then stop.
    assert len(calls) == 3
    assert "--session" in calls[1] and calls[1][calls[1].index("--session") + 1] == "ses_fake"
    assert "Reminder 1 of 5" in calls[1][-1] and "season 1" in calls[1][-1]
    assert harness_run["nudges_used"] == 2
    assert [n["new_tool_calls"] for n in harness_run["nudges"]] == [2, 0]
    assert harness_run["nudges_without_progress"] == 1
    assert result["failed_decisions"] == 2  # two phases closed by the agent, two abandoned
    assert result["agentic"]["phases_ended_by"] == {"agent": 2, "harness_exit": 2}
    assert harness_run["tool_call_agreement"]["agree"] is True
    assert harness_run["proxy_connections"] == 2
    # The seed never touched the run directory except inside the ledger header.
    assert not (tmp_path / "run" / "seed-11" / "episode.json").exists()

    # A second run into the same directory is refused before any harness launches.
    launches = len(calls)
    with pytest.raises(FileExistsError):
        driver.run_episode(11, model="fake/model", run_dir=tmp_path / "run", seasons=1, max_nudges=5)
    assert len(calls) == launches
    # The whole run still validates and redacts with the relative paths.
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from gm_bench.agentic.validate import validate_run

    run = {
        "agent": "opencode:fake/model",
        "harness": {"name": "opencode", "version": "0", "model": "fake/model"},
        "contract": driver.agentic_contract(),
        "seeds": [11],
        "seasons": 1,
        "episodes": [result],
        "summary": driver.summarize_episodes([result]),
    }
    (tmp_path / "run" / "run.json").write_text(json.dumps(run))
    report = validate_run(tmp_path / "run")
    assert report["ok"], report
    assert validate_agentic_artifact(compact_agentic_run(tmp_path / "run", isolation="same-user"))["ok"]


def test_run_harness_stops_a_stalled_harness_and_reports_it_apart_from_timeout(tmp_path: Path) -> None:
    import gm_bench.agentic.opencode as driver

    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    events, errors = tmp_path / "events.jsonl", tmp_path / "stderr.log"
    exit_code, timed_out, wall, stalled = driver._run_harness(
        sleeper,
        cwd=tmp_path,
        env=os.environ.copy(),
        events_path=events,
        stderr_path=errors,
        timeout=20.0,
        stalled=lambda: True,
        poll_seconds=0.1,
    )
    assert stalled is True and timed_out is False and exit_code != 0 and wall < 10
    exit_code, timed_out, wall, stalled = driver._run_harness(
        sleeper,
        cwd=tmp_path,
        env=os.environ.copy(),
        events_path=events,
        stderr_path=errors,
        timeout=0.3,
        stalled=lambda: False,
        poll_seconds=0.1,
    )
    assert timed_out is True and stalled is False and exit_code != 0
    exit_code, timed_out, wall, stalled = driver._run_harness(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        env=os.environ.copy(),
        events_path=events,
        stderr_path=errors,
        timeout=20.0,
        stalled=lambda: True,
        poll_seconds=0.1,
    )
    assert (exit_code, timed_out, stalled) == (0, False, False)


def test_run_harness_gives_the_harness_dev_null_as_stdin(tmp_path: Path) -> None:
    import gm_bench.agentic.opencode as driver

    # A driver that read private seeds from its stdin must not pass that
    # descriptor on to the harness.
    # pytest already points fd 0 at /dev/null, so put a seed file there first.
    probe = "import os; print(os.path.samestat(os.fstat(0), os.stat(os.devnull)))"
    events, errors = tmp_path / "events.jsonl", tmp_path / "stderr.log"
    seed_file = tmp_path / "seeds.txt"
    seed_file.write_text("11\n", encoding="utf-8")
    saved = os.dup(0)
    try:
        with seed_file.open("rb") as handle:
            os.dup2(handle.fileno(), 0)
        exit_code, timed_out, _, _ = driver._run_harness(
            [sys.executable, "-c", probe],
            cwd=tmp_path,
            env=os.environ.copy(),
            events_path=events,
            stderr_path=errors,
            timeout=20.0,
            poll_seconds=0.1,
        )
    finally:
        os.dup2(saved, 0)
        os.close(saved)
    assert (exit_code, timed_out) == (0, False)
    assert events.read_text(encoding="utf-8").strip() == "True"


def test_real_proxy_script_bridges_stdio_to_the_socket_server(tmp_path: Path) -> None:
    """Run the actual proxy file against a socket server, then reconnect as a restart would."""
    from gm_bench.agentic import _proxy
    from gm_bench.agentic.episode import AgenticEpisode

    proxy = tmp_path / "gm_bench_proxy.py"
    proxy.write_text(Path(_proxy.__file__).read_text())
    socket_dir = Path(tempfile.mkdtemp(prefix="gmb-"))
    socket_path = socket_dir / "s"
    episode = AgenticEpisode(11, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    server = SocketMcpServer(episode, socket_path)
    server.start()
    try:
        process = subprocess.Popen(
            [sys.executable, str(proxy), str(socket_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            cwd=tmp_path,
            env={"PATH": os.environ.get("PATH", "")},
        )
        assert process.stdin and process.stdout

        def ask(payload: dict) -> dict:
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            return json.loads(process.stdout.readline())

        init = ask({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        assert init["result"]["serverInfo"]["name"] == "gm-bench"
        call = {"name": "get_status", "arguments": {}}
        status = ask({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": call})
        assert status["result"]["isError"] is False
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        # A second proxy (a harness restart) reaches the same live engine.
        second = _SocketClient(str(socket_path))
        second.request("initialize", {"protocolVersion": "2025-06-18"})
        done = second.request("tools/call", {"name": "end_phase", "arguments": {}})
        assert done["result"]["structuredContent"]["now"]["phase"] == "midseason"
        assert episode.phase == "midseason"
        assert server.connections == 2
        # The second proxy is still attached when the driver stops the server:
        # stop() hangs up on it and does not return until its thread is gone.
        assert server.open_connections == 1
        assert server.stop() is True
        assert server.open_connections == 0
        assert second.sock.recv(1) == b""
        second.close()
    finally:
        server.stop()
        episode.close()
        shutil.rmtree(socket_dir, ignore_errors=True)


def test_guard_watch_fires_once_per_expired_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gm_bench.agentic.episode import AgenticEpisode
    from gm_bench.agentic.opencode import _GuardWatch

    # A controlled clock, so a slow worker cannot expire the guard on its own.
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    episode = AgenticEpisode(11, seasons=1, ledger_path=tmp_path / "ledger.jsonl", phase_guard_seconds=60.0)
    watch = _GuardWatch(episode, threading.Lock())
    episode.call_tool("get_status", {})  # opens season 1 preseason
    clock[0] += 59.0
    assert watch() is False
    clock[0] += 2.0
    assert watch() is True  # stop the harness once
    assert watch() is False  # ...but not the nudge that resumes it
    # The nudge's first call closes the expired phase as ``guard`` and opens the next one.
    reply = episode.call_tool("get_status", {})
    assert reply["ok"] is False and "phase guard" in reply["message"]
    assert episode.phase_log[-1]["ended_by"] == "guard"
    assert watch() is False
    clock[0] += 61.0
    assert watch() is True  # a new phase can expire on its own
    # A resumed harness that makes no call for a whole further guard period is stopped again.
    clock[0] += 60.0
    assert watch() is False
    clock[0] += 1.0
    assert watch() is True


def test_guard_watch_arm_remembers_a_phase_that_expired_without_a_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.episode import AgenticEpisode
    from gm_bench.agentic.opencode import _GuardWatch

    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    episode = AgenticEpisode(11, seasons=1, ledger_path=tmp_path / "ledger.jsonl", phase_guard_seconds=60.0)
    watch = _GuardWatch(episode, threading.Lock())
    watch.arm()  # nothing open yet: a no-op
    episode.call_tool("get_status", {})
    # The harness exits on its own after the guard elapses but before the next poll,
    # so the watch never fired for this phase. The nudge must still get to make its call.
    clock[0] += 61.0
    watch.arm()
    assert watch() is False
    clock[0] += 59.0
    assert watch() is False
    reply = episode.call_tool("get_status", {})
    assert reply["ok"] is False and "phase guard" in reply["message"]
    assert episode.phase_log[-1]["ended_by"] == "guard"


def test_socket_server_refuses_a_connection_accepted_after_stop_began(tmp_path: Path) -> None:
    """A connection accepted while stop() is starting is closed, never served (CodeRabbit on #139)."""
    from gm_bench.agentic.episode import AgenticEpisode

    episode = AgenticEpisode(11, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    server = SocketMcpServer(episode, tmp_path / "unused")
    ours, theirs = socket.socketpair()

    class _Listener:
        def accept(self):
            server._stop.set()  # stop() begins between accept() returning and admission
            return theirs, None

    server._listener = _Listener()
    server._accept_loop()
    assert server.connections == 0 and server.open_connections == 0
    ours.settimeout(5)
    assert ours.recv(1) == b""  # hung up on, not served
    ours.close()

    # stop() sets the flag under the admission lock, so admission and the
    # stop snapshot cannot interleave: while the lock is held, stop() waits.
    other = SocketMcpServer(episode, tmp_path / "unused-2")
    other._live_lock.acquire()
    stopper = threading.Thread(target=other.stop)
    stopper.start()
    time.sleep(0.2)
    assert not other._stop.is_set()
    other._live_lock.release()
    stopper.join(timeout=5)
    assert other._stop.is_set()
    episode.close()


def test_tcp_transport_needs_the_run_secret_and_bridges_through_the_real_proxy(tmp_path: Path) -> None:
    """The container transport: loopback TCP, the proxy presents the secret from the file beside it."""
    from gm_bench.agentic import _proxy
    from gm_bench.agentic.episode import AgenticEpisode

    episode = AgenticEpisode(11, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    with pytest.raises(ValueError):
        SocketMcpServer(episode, ("127.0.0.1", 0))
    server = SocketMcpServer(episode, ("127.0.0.1", 0), secret="s3cret-run-token")
    server.start()
    try:
        host, port = server.address
        assert host == "127.0.0.1" and port > 0

        # No secret, then a wrong one: both closed unserved and counted.
        for opener in (b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n', b"wrong\n"):
            with socket.create_connection((host, port), timeout=5) as raw:
                raw.sendall(opener + b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
                assert raw.recv(4096) == b""
        deadline = time.monotonic() + 5
        while server.rejected < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.rejected == 2

        proxy = tmp_path / "gm_bench_proxy.py"
        proxy.write_text(Path(_proxy.__file__).read_text())
        (tmp_path / _proxy.SECRET_FILENAME).write_text("s3cret-run-token\n")
        process = subprocess.Popen(
            [sys.executable, str(proxy), f"{host}:{port}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            cwd=tmp_path,
            env={"PATH": os.environ.get("PATH", "")},
        )
        assert process.stdin and process.stdout
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n")
        process.stdin.flush()
        assert json.loads(process.stdout.readline())["result"]["serverInfo"]["name"] == "gm-bench"
        call = {"name": "get_status", "arguments": {}}
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": call}) + "\n")
        process.stdin.flush()
        assert json.loads(process.stdout.readline())["result"]["isError"] is False
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert episode.tool_counts == {"get_status": 1}
        assert server.rejected == 2
    finally:
        assert server.stop() is True
        episode.close()
