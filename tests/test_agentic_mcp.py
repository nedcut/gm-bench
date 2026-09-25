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
    # Normalized to the shared shape: input includes cache reads and writes, output includes reasoning.
    assert telemetry["input_tokens"] == 150 + 40 + 2 and telemetry["uncached_input_tokens"] == 150
    assert telemetry["output_tokens"] == 15 + 5
    assert telemetry["reasoning_tokens"] == 5 and telemetry["cached_input_tokens"] == 40
    assert telemetry["cost_usd"] == 0.001
    assert telemetry["harness_tool_events"] == {"gm-bench_get_status": 1}
    assert telemetry["session_id"] == "ses_1"
    assert telemetry["max_output_tokens_per_call"] == 15
    usage = usage_block(telemetry, model="opencode/test", decisions=20)
    assert usage["api_calls"] == 2 and usage["input_tokens"] == 192
    assert (usage["uncached_input_tokens"], usage["cached_input_tokens"], usage["cache_write_input_tokens"]) == (
        150,
        40,
        2,
    )
    assert usage["output_tokens"] == 20 and usage["reasoning_tokens"] == 5
    assert usage["token_shape"] == "inclusive-v1"
    assert usage["cost_usd"] == 0.001
    assert usage["harness"]["telemetry_reported"] is True
    # One session total covers all twenty decisions: the run summary divides
    # by that, not by the one record; wall time is not API latency.
    assert usage["decisions_with_usage"] == 20 and usage["cost_decisions"] == 20
    assert usage["total_tokens"] == 212 and usage["max_output_tokens_per_call"] == 15
    assert usage["api_latency_ms"] == 0.0
    silent = usage_block(parse_opencode_events([]), model="opencode/test", decisions=20)
    assert silent["cost_usd"] is None and silent["harness"]["telemetry_reported"] is False
    assert silent["decisions_with_usage"] == 0 and silent["cost_decisions"] == 0


def test_the_frozen_2_0_contract_has_not_moved() -> None:
    from gm_bench.agentic.contract import AGENTIC_BENCHMARK_VERSION, agentic_fingerprint

    # gm-bench-2.0 is frozen: any change to tools.py, brief.py, episode.py or
    # mcp_server.py (or the 1.0 contract underneath) is a new benchmark version.
    # Bump AGENTIC_BENCHMARK_VERSION and this pin together, on purpose.
    assert (AGENTIC_BENCHMARK_VERSION, agentic_fingerprint()) == ("gm-bench-2.0", "07de948a4f4afbae")


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

    def fake_harness(command, *, cwd, env, events_path, stderr_path, timeout, stalled=None, on_kill=None):
        assert on_kill is None  # only the container launcher needs a kill hook
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
    assert (harness_run["isolation"], harness_run["transport"]) == ("same-user", "unix")
    assert harness_run["proxy_connections_refused"] == 0
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

        # No secret, a wrong one, and bytes that are not UTF-8: all closed unserved and counted.
        for opener in (b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n', b"wrong\n", b"\xff\xfe\n"):
            with socket.create_connection((host, port), timeout=5) as raw:
                raw.sendall(opener + b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
                assert raw.recv(4096) == b""
        deadline = time.monotonic() + 5
        while server.rejected < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.rejected == 3
        # Refused dials are not proxy connections.
        assert server.connections == 0

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
        assert (server.connections, server.rejected) == (1, 3)

        # A dial still silent when the driver stops is hung up on, not counted as refused.
        idle = socket.create_connection((host, port), timeout=5)
        deadline = time.monotonic() + 5
        while server.open_connections < 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.stop() is True
        assert idle.recv(1) == b""
        idle.close()
        assert (server.connections, server.rejected) == (1, 3)
    finally:
        server.stop()
        episode.close()


def _fake_docker(
    tmp_path: Path, *, canary_reachable: bool = False, rm_sleep: float = 0.0, cap_eff: str = "0000000000000000"
) -> tuple[Path, Path]:
    """A stand-in docker CLI that logs its argv and answers the sandbox and egress probes like a clean image."""
    from gm_bench.agentic.container import EGRESS_ENTRYPOINT

    log = tmp_path / "docker-calls.jsonl"
    script = tmp_path / "fake-docker"
    report = {"uid": 1000, "cap_eff": cap_eff, "cap_bnd": "0000000000000000", "canary_reachable": canary_reachable}
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if 'import gm_bench' in sys.argv:\n"
        "    sys.stderr.write(\"ModuleNotFoundError: No module named 'gm_bench'\\n\")\n"
        "    sys.exit(1)\n"
        f"if {EGRESS_ENTRYPOINT!r} in sys.argv and '-c' in sys.argv:\n"
        f"    print(json.dumps({report!r}))\n"
        f"if sys.argv[1:2] == ['rm']:\n"
        f"    time.sleep({rm_sleep!r})\n"
    )
    script.chmod(0o755)
    return script, log


def test_container_launch_mounts_only_the_scratch_and_keeps_the_secret_off_the_command_line(tmp_path: Path) -> None:
    from gm_bench.agentic import _proxy
    from gm_bench.agentic.container import EGRESS_ENTRYPOINT, HOST_ALIAS, WORKDIR
    from gm_bench.agentic.episode import AgenticEpisode
    from gm_bench.agentic.opencode import HarnessLaunch

    docker, log = _fake_docker(tmp_path)
    image = {"image": "gm-bench-agentic-opencode:test", "image_id": "sha256:" + "a" * 64}
    ledger = tmp_path / "run" / "seed-8675309" / "ledger.jsonl"
    episode = AgenticEpisode(8675309, seasons=1, ledger_path=ledger)
    launch = HarnessLaunch(episode, isolation="container", image=image, docker=str(docker))
    try:
        assert (launch.isolation, launch.transport, launch.workdir) == ("container", "tcp", WORKDIR)
        launch.prepare()
        config = json.loads((launch.scratch / "opencode.json").read_text())
        port = launch.server.address[1]
        assert config["mcp"]["servers"]["gm-bench"]["command"] == [
            "python3",
            "gm_bench_proxy.py",
            f"{HOST_ALIAS}:{port}",
        ]
        secret_file = launch.scratch / _proxy.SECRET_FILENAME
        assert secret_file.read_text().strip() == launch.server.secret
        assert secret_file.stat().st_mode & 0o077 == 0
        assert sorted(p.name for p in launch.scratch.iterdir()) == sorted(
            ["opencode.json", "gm_bench_proxy.py", _proxy.SECRET_FILENAME]
        )

        argv, on_kill = launch.command(["run", "--dir", WORKDIR, "--model", "m", "brief"])
        assert on_kill is not None
        text = " ".join(argv)
        assert launch.server.secret not in text
        for leak in ("8675309", str(ledger.parent), str(REPO_ROOT), "GM_BENCH"):
            assert leak not in text
        mounts = [argv[i + 1] for i, arg in enumerate(argv) if arg in ("--mount", "-v", "--volume")]
        binds = [m for m in mounts if m.startswith("type=bind")]
        assert binds == [f"type=bind,source={launch.scratch},target={WORKDIR}"]
        assert all(m.startswith("type=volume,source=gmb-home-") for m in mounts if m not in binds)
        assert "-e" not in argv and "--env" not in argv and "--env-file" not in argv
        # Root only for the egress entrypoint, with exactly the capabilities it needs to
        # install the firewall and drop to ``node``; never privileged, never host networking.
        added = sorted(argv[i + 1] for i, arg in enumerate(argv) if arg == "--cap-add")
        assert added == ["NET_ADMIN", "SETGID", "SETPCAP", "SETUID"]
        assert argv[argv.index("--cap-drop") + 1] == "ALL"
        assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
        assert "--privileged" not in argv and "--network" not in argv
        assert argv[argv.index(image["image_id"]) + 1 :] == [
            EGRESS_ENTRYPOINT,
            str(port),
            "opencode",
            "run",
            "--dir",
            WORKDIR,
            "--model",
            "m",
            "brief",
        ]
        on_kill()
    finally:
        scratch = launch.scratch
        assert launch.close() is True
    assert not scratch.exists()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    # The egress probe ran before launch, with the same entrypoint and the driver's port.
    probes = [call for call in calls if EGRESS_ENTRYPOINT in call and "-c" in call]
    assert len(probes) == 1 and probes[0][probes[0].index(EGRESS_ENTRYPOINT) + 1] == str(port)
    name = argv[argv.index("--name") + 1]
    assert ["rm", "--force", name] in calls
    assert calls[-1][:3] == ["volume", "rm", "--force"]
    assert launch.cleanup_problems == []
    episode.close()


@pytest.mark.parametrize(
    ("fake", "problem"),
    [
        ({"canary_reachable": True}, "host loopback listener"),
        ({"cap_eff": "00000000a80425fb"}, "capabilities"),
    ],
)
def test_container_launch_refuses_to_start_when_the_egress_probe_fails(
    tmp_path: Path, fake: dict, problem: str
) -> None:
    from gm_bench.agentic.episode import AgenticEpisode
    from gm_bench.agentic.opencode import HarnessLaunch, SandboxError

    docker, _log = _fake_docker(tmp_path, **fake)
    image = {"image": "gm-bench-agentic-opencode:test", "image_id": "sha256:" + "a" * 64}
    episode = AgenticEpisode(11, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    launch = HarnessLaunch(episode, isolation="container", image=image, docker=str(docker))
    try:
        with pytest.raises(SandboxError, match=problem):
            launch.prepare()
    finally:
        launch.close()
        episode.close()


def test_egress_script_is_valid_sh_and_baked_into_the_image() -> None:
    from gm_bench.agentic.container import EGRESS_ENTRYPOINT, EGRESS_SCRIPT, dockerfile

    checked = subprocess.run(["sh", "-n"], input=EGRESS_SCRIPT, capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stderr
    text = dockerfile()
    assert EGRESS_SCRIPT in text and EGRESS_ENTRYPOINT in text
    assert text.index(EGRESS_ENTRYPOINT) < text.index("USER node")


def test_docker_timeouts_become_container_errors_and_cleanup_still_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gm_bench.agentic.container as container
    from gm_bench.agentic.episode import AgenticEpisode
    from gm_bench.agentic.opencode import HarnessLaunch

    with pytest.raises(container.ContainerError, match="did not finish"):
        container._docker("/bin/sleep", "3", timeout=0.3)

    # A daemon that hangs on ``docker rm`` past the cleanup timeout.
    docker, log = _fake_docker(tmp_path, rm_sleep=3.0)
    monkeypatch.setattr(container, "CLEANUP_TIMEOUT_SECONDS", 0.5)
    image = {"image": "gm-bench-agentic-opencode:test", "image_id": "sha256:" + "a" * 64}
    episode = AgenticEpisode(11, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    launch = HarnessLaunch(episode, isolation="container", image=image, docker=str(docker))
    launch.prepare()
    _argv, on_kill = launch.command(["run", "brief"])
    launch.command(["run", "--session", "s", "nudge"])
    assert on_kill is not None
    on_kill()  # the guard's kill hook must not raise either
    assert launch.close() is True  # does not raise
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    # Every container was attempted, then the volume, and the scratch (with the secret) is gone.
    assert [call[0] for call in calls if call[0] == "rm"] == ["rm", "rm", "rm"]
    assert calls[-1][:3] == ["volume", "rm", "--force"]
    assert not launch.scratch.exists()
    # The kill hook's timeout and both close-time timeouts are kept, not raised.
    assert len(launch.cleanup_problems) == 3 and all("did not finish" in p for p in launch.cleanup_problems)
    episode.close()


def test_run_harness_runs_the_kill_hook_after_killing_the_client(tmp_path: Path) -> None:
    import gm_bench.agentic.opencode as driver

    killed: list[str] = []
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    _code, timed_out, _wall, stalled = driver._run_harness(
        sleeper,
        cwd=tmp_path,
        env=os.environ.copy(),
        events_path=tmp_path / "events.jsonl",
        stderr_path=tmp_path / "stderr.log",
        timeout=20.0,
        stalled=lambda: True,
        poll_seconds=0.1,
        on_kill=lambda: killed.append("stalled"),
    )
    assert stalled and not timed_out and killed == ["stalled"]
    driver._run_harness(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        env=os.environ.copy(),
        events_path=tmp_path / "events.jsonl",
        stderr_path=tmp_path / "stderr.log",
        timeout=20.0,
        on_kill=lambda: killed.append("clean exit"),
    )
    assert killed == ["stalled"]


# -- provider stalls ------------------------------------------------------------

_RATE_LIMIT_ERROR = {
    "type": "error",
    "sessionID": "ses_fake",
    "error": {
        "name": "APIError",
        "data": {
            "message": "Error from provider (Console): Rate limit exceeded. Please try again later.",
            "statusCode": 429,
            "isRetryable": True,
        },
    },
}
_AUTH_ERROR = {
    "type": "error",
    "sessionID": "ses_fake",
    "error": {"name": "APIError", "data": {"message": "Unauthorized", "statusCode": 401, "isRetryable": False}},
}
# The first line of nine of sixteen gate6/gate7 opencode/space-bunny-free
# episodes (session id and ref faked): OpenCode's server failing about a
# second after launch, before any model step.
_STARTUP_SERVER_ERROR = {
    "type": "error",
    "timestamp": 1790279428885,
    "sessionID": "ses_fake",
    "error": {
        "name": "UnknownError",
        "data": {"message": "Unexpected server error. Check server logs for details.", "ref": "err_fake"},
    },
}


def _scripted_harness(script: list[dict], calls: list[list[str]], *, before_call=None):
    """A fake ``_run_harness`` that plays ``script[i]`` on invocation ``i``.

    Each step may make ``calls`` GM-Bench tool calls (``get_status`` then
    ``end_phase`` pairs, so each pair closes a phase), then end with an
    optional ``error`` event and ``exit`` code. A ``silent`` step prints
    nothing and makes no call: only ``before_call`` runs (to move the clock
    and poll), like OpenCode retrying a 429 internally. A ``bare`` step
    prints only its ``error`` event and makes no call, like OpenCode's
    server failing at startup.
    """

    def fake_harness(command, *, cwd, env, events_path, stderr_path, timeout, stalled=None, on_kill=None):
        calls.append(command)
        step = script[min(len(calls), len(script)) - 1]
        config = json.loads((cwd / "opencode.json").read_text())
        socket_path = config["mcp"]["servers"]["gm-bench"]["command"][2]
        was_stalled = False
        if step.get("bare"):
            with events_path.open("a") as events:
                events.write(json.dumps(step["error"]) + "\n")
            return step.get("exit", 0), False, 1.0, False
        if step.get("silent"):
            if before_call is not None:
                was_stalled = before_call(len(calls), stalled)
            return (-9 if was_stalled else step.get("exit", 0)), False, 1.0, was_stalled
        with events_path.open("a") as events:
            events.write(json.dumps({"type": "step_start", "sessionID": "ses_fake", "part": {}}) + "\n")
            events.flush()  # a real harness writes straight to the file
            if before_call is not None:
                was_stalled = before_call(len(calls), stalled)
            if step.get("phases", 0):
                client = _SocketClient(socket_path)
                client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}})
                for _ in range(step["phases"]):
                    for name in ("get_status", "end_phase"):
                        reply = client.request("tools/call", {"name": name, "arguments": {}})
                        assert "result" in reply, reply
                        part = {"type": "tool", "tool": f"gm-bench_{name}"}
                        events.write(json.dumps({"type": "tool", "sessionID": "ses_fake", "part": part}) + "\n")
                client.close()
            finish = {"type": "step-finish", "tokens": {"input": 10, "output": 1}}
            events.write(json.dumps({"type": "step_finish", "sessionID": "ses_fake", "part": finish}) + "\n")
            if step.get("error") is not None:
                events.write(json.dumps(step["error"]) + "\n")
        return step.get("exit", 0), False, 1.0, was_stalled

    return fake_harness


def _stall_episode(tmp_path, monkeypatch, script, *, before_call=None, **kwargs):
    import gm_bench.agentic.opencode as driver

    calls: list[list[str]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(driver, "_run_harness", _scripted_harness(script, calls, before_call=before_call))
    monkeypatch.setattr(driver, "sandbox_problems", lambda scratch, env: [])
    kwargs.setdefault("sleep", sleeps.append)
    # Limits are injected, so these tests do not move when the defaults do.
    kwargs.setdefault("max_provider_stalls", 8)
    kwargs.setdefault("max_provider_stall_wait_seconds", 45 * 60.0)
    result = driver.run_episode(11, model="fake/model", run_dir=tmp_path / "run", seasons=1, max_nudges=5, **kwargs)
    return result, calls, sleeps


def test_ended_in_provider_stall_reads_only_a_terminal_retryable_error() -> None:
    from gm_bench.agentic.opencode import ended_in_provider_stall

    step = json.dumps({"type": "step_finish", "part": {}})
    assert ended_in_provider_stall([step, json.dumps(_RATE_LIMIT_ERROR)])
    assert not ended_in_provider_stall([json.dumps(_RATE_LIMIT_ERROR), step])  # recovered: not terminal
    assert not ended_in_provider_stall([step, json.dumps(_AUTH_ERROR)])
    assert not ended_in_provider_stall([step])
    assert not ended_in_provider_stall([])
    for data in ({"statusCode": 503}, {"message": "Model is overloaded"}, {"isRetryable": True}):
        event = {"type": "error", "error": {"name": "APIError", "data": data}}
        assert ended_in_provider_stall([json.dumps(event), ""]), data


def test_provider_stall_is_retried_after_backoff_and_not_counted_as_a_nudge(tmp_path: Path, monkeypatch) -> None:
    """The gate6 seed-6 shape: the run ends on a 429, the resume succeeds."""
    script = [{"phases": 1, "error": _RATE_LIMIT_ERROR, "exit": 1}, {"phases": 3}]
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script, stall_backoff=lambda n: 0.0)
    harness_run = result["harness_run"]
    assert len(calls) == 2 and "--session" in calls[1]
    assert sleeps == [0.0]
    assert harness_run["provider_stalls"] == 1
    assert harness_run["provider_stall_wait_seconds"] == 0.0
    assert harness_run["nudges_used"] == 0  # the retry did not use up a nudge
    assert harness_run["nudges_without_progress"] == 0
    [retry] = harness_run["nudges"]
    assert retry["stall_retry"] is True and retry["provider_stall"] is False and retry["backoff_seconds"] == 0.0
    assert retry["new_tool_calls"] == 6
    assert result["agentic"]["phases_ended_by"] == {"agent": 4}
    assert result["failed_decisions"] == 0


def test_consecutive_provider_stalls_back_off_exponentially(tmp_path: Path, monkeypatch) -> None:
    from gm_bench.agentic.opencode import provider_stall_backoff

    assert [provider_stall_backoff(n) for n in range(1, 8)] == [60.0, 120.0, 240.0, 480.0, 600.0, 600.0, 600.0]
    # Like seed 6: the first resume also hits the 429 and makes no tool call.
    # That zero-call relaunch is not a no-progress nudge; the next one plays on.
    script = [
        {"phases": 1, "error": _RATE_LIMIT_ERROR, "exit": 1},
        {"phases": 0, "error": _RATE_LIMIT_ERROR, "exit": 1},
        {"phases": 3},
    ]
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script)
    harness_run = result["harness_run"]
    assert sleeps == [60.0, 120.0]
    assert len(calls) == 3
    assert harness_run["provider_stalls"] == 2
    assert harness_run["provider_stall_wait_seconds"] == 180.0
    assert [(n["stall_retry"], n["backoff_seconds"], n["provider_stall"]) for n in harness_run["nudges"]] == [
        (True, 60.0, True),
        (True, 120.0, False),
    ]
    assert harness_run["nudges_used"] == 0 and harness_run["nudges_without_progress"] == 0
    assert result["failed_decisions"] == 0


def test_exhausted_stall_budget_falls_through_to_the_stop(tmp_path: Path, monkeypatch) -> None:
    script = [
        {"phases": 1, "error": _RATE_LIMIT_ERROR, "exit": 1},
        {"phases": 0, "error": _RATE_LIMIT_ERROR, "exit": 1},
    ]
    # Retry count exhausted: two retries, then the zero-call stall stops the loop like any zero-call nudge.
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script, max_provider_stalls=2)
    harness_run = result["harness_run"]
    assert sleeps == [60.0, 120.0]
    assert len(calls) == 3
    assert harness_run["provider_stalls"] == 3
    assert harness_run["nudges_used"] == 0
    assert result["agentic"]["phases_ended_by"] == {"agent": 1, "harness_exit": 3}


def test_exhausted_stall_wait_falls_through_to_the_stop(tmp_path: Path, monkeypatch) -> None:
    script = [
        {"phases": 1, "error": _RATE_LIMIT_ERROR, "exit": 1},
        {"phases": 0, "error": _RATE_LIMIT_ERROR, "exit": 1},
    ]
    # 60 + 120 would pass a 100 s wait budget, so only the first stall is retried.
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script, max_provider_stall_wait_seconds=100.0)
    assert sleeps == [60.0]
    assert len(calls) == 2
    assert result["harness_run"]["provider_stalls"] == 2
    assert result["harness_run"]["provider_stall_wait_seconds"] == 60.0
    assert result["agentic"]["phases_ended_by"] == {"agent": 1, "harness_exit": 3}


def test_initial_stall_with_no_budget_is_nudged_as_before(tmp_path: Path, monkeypatch) -> None:
    script = [{"phases": 1, "error": _RATE_LIMIT_ERROR, "exit": 1}, {"phases": 3}]
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script, max_provider_stalls=0)
    assert sleeps == [] and len(calls) == 2
    assert "Reminder 1 of 5" in calls[1][-1]
    assert result["harness_run"]["nudges_used"] == 1
    assert result["harness_run"]["nudges"][0]["stall_retry"] is False


@pytest.mark.parametrize("error", [None, _AUTH_ERROR], ids=["exit-1-no-error", "401"])
def test_non_retryable_exit_keeps_the_nudge_behaviour(tmp_path: Path, monkeypatch, error) -> None:
    script = [{"phases": 1, "error": error, "exit": 1}, {"phases": 0, "error": error, "exit": 1}]
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script)
    harness_run = result["harness_run"]
    assert sleeps == []
    assert len(calls) == 2  # initial run, one nudge without progress, stop
    assert "Reminder 1 of 5" in calls[1][-1]
    assert harness_run["provider_stalls"] == 0 and harness_run["provider_stall_wait_seconds"] == 0.0
    assert harness_run["nudges_used"] == 1 and harness_run["nudges_without_progress"] == 1
    assert harness_run["nudges"][0]["stall_retry"] is False and harness_run["nudges"][0]["provider_stall"] is False
    assert result["agentic"]["phases_ended_by"] == {"agent": 1, "harness_exit": 3}


def test_startup_server_error_is_a_stall_only_before_the_invocation_acted() -> None:
    from gm_bench.agentic.opencode import OPENCODE_DRIVER, ended_in_provider_stall

    error = json.dumps(_STARTUP_SERVER_ERROR)
    start = json.dumps({"type": "step_start", "sessionID": "ses_fake", "part": {"type": "step-start"}})
    tool = json.dumps({"type": "tool_use", "sessionID": "ses_fake", "part": {"type": "tool", "tool": "gm-bench_x"}})
    finish = json.dumps({"type": "step_finish", "sessionID": "ses_fake", "part": {"type": "step-finish"}})
    text = json.dumps({"type": "text", "sessionID": "ses_fake", "part": {"type": "text", "text": "hi"}})
    # The recorded shape: the invocation's only event.
    assert ended_in_provider_stall([error, ""])
    assert OPENCODE_DRIVER.ended_in_provider_stall([error])
    # Failing inside the first model call, before it finished, is still startup.
    assert ended_in_provider_stall([start, error])
    # After a tool call, a finished model step or model text, it is not.
    for before in ([start, tool], [start, finish], [start, text], [start, tool, finish, start]):
        assert not ended_in_provider_stall([*before, error]), before
    # Not terminal: the invocation recovered.
    assert not ended_in_provider_stall([error, start])
    # Only OpenCode's generic server error, not any UnknownError.
    other = {**_STARTUP_SERVER_ERROR, "error": {"name": "UnknownError", "data": {"message": "bad config"}}}
    assert not ended_in_provider_stall([json.dumps(other)])
    renamed = {**_STARTUP_SERVER_ERROR, "error": {**_STARTUP_SERVER_ERROR["error"], "name": "APIError"}}
    assert not ended_in_provider_stall([json.dumps(renamed)])


def test_startup_server_error_is_retried_as_a_stall_not_a_nudge(tmp_path: Path, monkeypatch) -> None:
    """The gate6 seed-1 shape: the first launch dies on the server error, the resume plays the episode."""
    script = [{"bare": True, "error": _STARTUP_SERVER_ERROR, "exit": 1}, {"phases": 4}]
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script)
    harness_run = result["harness_run"]
    # The launch opened a session, so the retry resumes it with the reminder.
    assert len(calls) == 2 and calls[1][calls[1].index("--session") + 1] == "ses_fake"
    assert sleeps == [60.0]
    assert harness_run["provider_stalls"] == 1 and harness_run["provider_stall_wait_seconds"] == 60.0
    assert harness_run["nudges_used"] == 0 and harness_run["nudges_without_progress"] == 0
    [retry] = harness_run["nudges"]
    assert retry["stall_retry"] is True and retry["provider_stall"] is False and retry["new_tool_calls"] == 8
    # The first launch failed; the harness finished cleanly.
    assert harness_run["exit_code"] == 1 and harness_run["final_exit_code"] == 0
    assert result["agentic"]["phases_ended_by"] == {"agent": 4}
    assert result["failed_decisions"] == 0


def test_repeated_startup_server_error_does_not_lose_the_episode(tmp_path: Path, monkeypatch) -> None:
    """Before, a second startup error on the resume was a no-progress nudge and abandoned every phase."""
    bare = {"bare": True, "error": _STARTUP_SERVER_ERROR, "exit": 1}
    script = [bare, bare, {"phases": 4}]
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script)
    harness_run = result["harness_run"]
    assert len(calls) == 3 and sleeps == [60.0, 120.0]
    assert harness_run["provider_stalls"] == 2 and harness_run["nudges_used"] == 0
    assert result["agentic"]["phases_ended_by"] == {"agent": 4}
    assert result["failed_decisions"] == 0


def test_server_error_after_progress_keeps_the_nudge_behaviour(tmp_path: Path, monkeypatch) -> None:
    script = [{"phases": 1, "error": _STARTUP_SERVER_ERROR, "exit": 1}, {"phases": 3}]
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script)
    harness_run = result["harness_run"]
    assert sleeps == [] and len(calls) == 2 and "Reminder 1 of 5" in calls[1][-1]
    assert harness_run["provider_stalls"] == 0 and harness_run["nudges_used"] == 1
    assert result["failed_decisions"] == 0


def test_exit_code_warning_follows_how_the_harness_finished(tmp_path: Path, monkeypatch) -> None:
    import gm_bench.agentic.opencode as driver
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from gm_bench.agentic.validate import validate_run

    script = [{"bare": True, "error": _STARTUP_SERVER_ERROR, "exit": 1}, {"phases": 4}]
    result, _calls, _sleeps = _stall_episode(tmp_path, monkeypatch, script)
    run = {
        "agent": "opencode:fake/model",
        "harness": {"name": "opencode", "version": "0", "model": "fake/model"},
        "contract": driver.agentic_contract(),
        "seeds": [11],
        "seasons": 1,
        "max_nudges": 5,
        "episodes": [result],
        "summary": driver.summarize_episodes([result]),
        "agentic_summary": driver._agentic_summary([result]),
    }
    run_json = tmp_path / "run" / "run.json"
    run_json.write_text(json.dumps(run))
    report = validate_run(run_json)
    assert report["ok"]
    assert not any("exit code" in warning for warning in report["warnings"])
    artifact = compact_agentic_run(tmp_path / "run", isolation="same-user")
    compact = artifact["episodes"][0]["harness_run"]
    assert (compact["exit_code"], compact["final_exit_code"]) == (1, 0)
    assert validate_agentic_artifact(artifact)["ok"]
    # A run recorded before final_exit_code is read from its first exit code, as before.
    del result["harness_run"]["final_exit_code"]
    run_json.write_text(json.dumps(run))
    assert "episode 0 (seed 11): harness exit code 1" in validate_run(run_json)["warnings"]
    # And a harness that finished badly still warns.
    result["harness_run"]["final_exit_code"] = 2
    run_json.write_text(json.dumps(run))
    assert "episode 0 (seed 11): harness exit code 2" in validate_run(run_json)["warnings"]


def test_guard_does_not_fire_for_a_backoff_but_still_catches_a_hung_retry(tmp_path: Path, monkeypatch) -> None:
    """A backoff longer than the phase guard must not be mistaken for a hung harness."""
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    polls: list[tuple[int, bool]] = []

    def before_call(invocation: int, stalled) -> bool:
        # Poll the guard the way _run_harness does, right after launch.
        fired = stalled()
        polls.append((invocation, fired))
        if invocation == 3:
            # The retried harness hangs: no call for a whole further guard period.
            clock[0] += 51.0
            fired = stalled()
            polls.append((invocation, fired))
        return fired

    script = [
        {"phases": 1, "error": _RATE_LIMIT_ERROR, "exit": 1},
        {"phases": 0, "error": _RATE_LIMIT_ERROR, "exit": 1},
        {"phases": 0},
    ]
    result, calls, sleeps = _stall_episode(
        tmp_path,
        monkeypatch,
        script,
        before_call=before_call,
        phase_guard_seconds=50.0,
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),  # a 60 s then 120 s backoff
    )
    harness_run = result["harness_run"]
    # Invocation 2 starts after a 60 s backoff that took the phase past its guard: no stop.
    # Invocation 3 starts after 120 s more: still no stop at launch, but a hung harness is stopped.
    assert polls == [(1, False), (2, False), (3, False), (3, True)]
    assert harness_run["provider_stall_wait_seconds"] == 180.0
    # Both waits were taken off the engine's phase clock, so the hung retry,
    # not the backoff, is what ran the phase out.
    ledger = (tmp_path / "run" / "seed-11" / "ledger.jsonl").read_text().splitlines()
    pauses = [json.loads(line) for line in ledger if '"clock_pause"' in line]
    assert [pause["seconds"] for pause in pauses] == [60.0, 120.0]
    assert harness_run["guard_kills"] == 1
    assert [n["stalled"] for n in harness_run["nudges"]] == [False, True]


def test_provider_stall_counts_reach_run_json_and_the_redacted_artifact(tmp_path: Path, monkeypatch) -> None:
    import gm_bench.agentic.opencode as driver
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from gm_bench.agentic.validate import validate_run

    script = [{"phases": 1, "error": _RATE_LIMIT_ERROR, "exit": 1}, {"phases": 3}]
    result, _calls, _sleeps = _stall_episode(tmp_path, monkeypatch, script)
    run = {
        "agent": "opencode:fake/model",
        "harness": {"name": "opencode", "version": "0", "model": "fake/model"},
        "contract": driver.agentic_contract(),
        "seeds": [11],
        "seasons": 1,
        "max_nudges": 5,
        "max_provider_stalls": 8,
        "max_provider_stall_wait_seconds": 2700.0,
        "episodes": [result],
        "summary": driver.summarize_episodes([result]),
        "agentic_summary": driver._agentic_summary([result]),
    }
    (tmp_path / "run" / "run.json").write_text(json.dumps(run))
    saved = json.loads((tmp_path / "run" / "run.json").read_text())
    assert saved["episodes"][0]["harness_run"]["provider_stalls"] == 1
    assert saved["episodes"][0]["harness_run"]["provider_stall_wait_seconds"] == 60.0
    assert saved["agentic_summary"]["provider_stalls"] == 1
    assert validate_run(tmp_path / "run")["ok"]
    artifact = compact_agentic_run(tmp_path / "run", isolation="same-user")
    assert (artifact["max_provider_stalls"], artifact["max_provider_stall_wait_seconds"]) == (8, 2700.0)
    compact = artifact["episodes"][0]["harness_run"]
    assert (compact["provider_stalls"], compact["provider_stall_wait_seconds"]) == (1, 60.0)
    assert compact["nudges"][0]["stall_retry"] is True and compact["nudges"][0]["backoff_seconds"] == 60.0
    assert validate_agentic_artifact(artifact)["ok"]


def test_stall_backoff_is_not_phase_guard_time(tmp_path: Path, monkeypatch) -> None:
    """A backoff longer than the guard does not cost the agent the open phase."""
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    script = [
        {"phases": 1, "error": _RATE_LIMIT_ERROR, "exit": 1},
        {"phases": 0, "error": _RATE_LIMIT_ERROR, "exit": 1},
        {"phases": 3},
    ]
    result, calls, _sleeps = _stall_episode(
        tmp_path,
        monkeypatch,
        script,
        phase_guard_seconds=50.0,
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    assert len(calls) == 3
    assert result["harness_run"]["provider_stall_wait_seconds"] == 180.0
    assert result["agentic"]["phases_ended_by"] == {"agent": 4}
    assert result["failed_decisions"] == 0


# -- silent harness -------------------------------------------------------------


def test_run_harness_stops_a_silent_harness_but_not_one_that_spoke(tmp_path: Path) -> None:
    """The real kill path, with a real file: silence is no event byte and no ledger call since launch."""
    import types

    import gm_bench.agentic.opencode as driver

    events_path = tmp_path / "events.jsonl"
    events_path.write_text("")
    engine = types.SimpleNamespace(tool_counts={})
    killed: list[str] = []

    def run(script: str, name: str) -> tuple[bool, bool, driver._SilenceWatch]:
        watch = driver._SilenceWatch(engine, threading.Lock(), events_path, 0.5)
        _code, timed_out, _wall, stalled = driver._run_harness(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            env=os.environ.copy(),
            events_path=events_path,
            stderr_path=tmp_path / "stderr.log",
            timeout=2.0,
            stalled=watch,
            poll_seconds=0.1,
            on_kill=lambda: killed.append(name),
        )
        return stalled, timed_out, watch

    stalled, timed_out, watch = run("import time; time.sleep(30)", "silent")
    assert stalled and not timed_out and watch.fired and watch.silent_for >= 0.5
    assert killed == ["silent"]
    # One event, then a hang: never silent, so only the timeout (here) or the guard stops it.
    speaks = 'import sys, time; print(\'{"type": "step_start"}\', flush=True); time.sleep(30)'
    stalled, timed_out, watch = run(speaks, "spoke")
    assert not stalled and timed_out and watch.heard and not watch.fired
    # A harness writing to stderr only is still silent: only the event stream counts.
    stalled, _timed_out, watch = run(
        "import sys, time; print('retrying', file=sys.stderr, flush=True); time.sleep(30)", "stderr"
    )
    assert stalled and watch.fired


def _silent_then(clock: list[float], seconds: float, silent_invocations: set[int]):
    """A ``before_call`` that lets ``seconds`` pass on the listed invocations and polls like ``_run_harness``."""
    polls: list[tuple[int, bool]] = []

    def before_call(invocation: int, stalled) -> bool:
        fired = stalled()
        polls.append((invocation, fired))
        if invocation in silent_invocations and not fired:
            clock[0] += seconds
            fired = stalled()
            polls.append((invocation, fired))
        return fired

    return before_call, polls


def test_silent_launch_is_stopped_and_retried_as_a_provider_stall(tmp_path: Path, monkeypatch) -> None:
    """The gate6 seed-5 shape: OpenCode prints nothing while it retries a 429."""
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    before_call, polls = _silent_then(clock, 241.0, {1})
    script = [{"silent": True}, {"phases": 4}]
    result, calls, _sleeps = _stall_episode(
        tmp_path,
        monkeypatch,
        script,
        before_call=before_call,
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    harness_run = result["harness_run"]
    assert polls == [(1, False), (1, True), (2, False)]
    # No session was opened, so the retry is a new session with the brief, not a reminder.
    assert len(calls) == 2 and "--session" not in calls[1] and calls[1][-1] == calls[0][-1]
    assert harness_run["silent_kills"] == 1 and harness_run["silent_harness_seconds"] == 240.0
    assert harness_run["provider_stalls"] == 1 and harness_run["provider_stall_wait_seconds"] == 60.0
    assert harness_run["guard_kills"] == 0
    assert harness_run["nudges_used"] == 0 and harness_run["nudges_without_progress"] == 0
    [retry] = harness_run["nudges"]
    assert retry["stall_retry"] is True and retry["new_session"] is True
    assert retry["silent"] is False and retry["stalled"] is False and retry["new_tool_calls"] == 8
    assert result["agentic"]["phases_ended_by"] == {"agent": 4}
    assert result["failed_decisions"] == 0
    # Both the silent window and the backoff came off the phase clock.
    ledger = (tmp_path / "run" / "seed-11" / "ledger.jsonl").read_text().splitlines()
    pauses = [json.loads(line) for line in ledger if '"clock_pause"' in line]
    assert [(pause["reason"], pause["seconds"]) for pause in pauses] == [
        ("silent_harness", 241.0),
        ("provider_stall", 60.0),
    ]


def test_silent_resume_climbs_the_stall_ladder(tmp_path: Path, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    before_call, _polls = _silent_then(clock, 241.0, {2})
    script = [{"phases": 1, "error": _RATE_LIMIT_ERROR, "exit": 1}, {"silent": True}, {"phases": 3}]
    result, calls, sleeps = _stall_episode(tmp_path, monkeypatch, script, before_call=before_call)
    harness_run = result["harness_run"]
    assert sleeps == [60.0, 120.0]  # the silent stop is the second consecutive stall
    assert len(calls) == 3 and "--session" in calls[1] and "--session" in calls[2]
    assert harness_run["provider_stalls"] == 2 and harness_run["silent_kills"] == 1
    assert harness_run["guard_kills"] == 0 and harness_run["nudges_used"] == 0
    assert [(n["silent"], n["provider_stall"], n["stalled"]) for n in harness_run["nudges"]] == [
        (True, True, False),
        (False, False, False),
    ]
    assert result["agentic"]["phases_ended_by"] == {"agent": 4}


def test_harness_that_spoke_then_hung_is_left_to_the_guard(tmp_path: Path, monkeypatch) -> None:
    """A slow first model call prints ``step_start``: not silent, however long it then takes."""
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    # Past both the silence threshold (30 s) and the guard (50 s).
    before_call, polls = _silent_then(clock, 51.0, {1})
    script = [{"phases": 0}, {"phases": 3}]
    result, calls, sleeps = _stall_episode(
        tmp_path, monkeypatch, script, before_call=before_call, phase_guard_seconds=50.0, silent_harness_seconds=30.0
    )
    harness_run = result["harness_run"]
    assert polls == [(1, False), (1, True), (2, False)]
    assert sleeps == []
    assert harness_run["silent_kills"] == 0 and harness_run["provider_stalls"] == 0
    assert harness_run["guard_kills"] == 1
    assert harness_run["nudges_used"] == 1 and harness_run["nudges"][0]["silent"] is False
    assert "Reminder 1 of 5" in calls[1][-1]
    assert result["agentic"]["phases_ended_by"]["guard"] == 1


def test_silence_detection_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    before_call, polls = _silent_then(clock, 10_000.0, {1})
    result, calls, _sleeps = _stall_episode(
        tmp_path, monkeypatch, [{"silent": True}], before_call=before_call, silent_harness_seconds=0.0
    )
    # Only the phase guard stops it; with no session there is nothing to resume.
    assert polls == [(1, False), (1, True)]
    assert len(calls) == 1
    assert result["harness_run"]["silent_kills"] == 0 and result["harness_run"]["guard_kills"] == 1
    assert result["agentic"]["phases_ended_by"] == {"harness_exit": 4}


def test_silent_kill_counts_reach_run_json_and_the_redacted_artifact(tmp_path: Path, monkeypatch) -> None:
    import gm_bench.agentic.opencode as driver
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from gm_bench.agentic.validate import validate_run

    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    before_call, _polls = _silent_then(clock, 241.0, {1})
    result, _calls, _sleeps = _stall_episode(
        tmp_path,
        monkeypatch,
        [{"silent": True}, {"phases": 4}],
        before_call=before_call,
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    run = {
        "agent": "opencode:fake/model",
        "harness": {"name": "opencode", "version": "0", "model": "fake/model"},
        "contract": driver.agentic_contract(),
        "seeds": [11],
        "seasons": 1,
        "max_nudges": 5,
        "max_provider_stalls": 8,
        "max_provider_stall_wait_seconds": 2700.0,
        "silent_harness_seconds": 240.0,
        "episodes": [result],
        "summary": driver.summarize_episodes([result]),
        "agentic_summary": driver._agentic_summary([result]),
    }
    (tmp_path / "run" / "run.json").write_text(json.dumps(run))
    saved = json.loads((tmp_path / "run" / "run.json").read_text())
    assert saved["episodes"][0]["harness_run"]["silent_kills"] == 1
    assert saved["agentic_summary"]["silent_harness_kills"] == 1
    assert saved["agentic_summary"]["provider_stalls"] == 1
    assert validate_run(tmp_path / "run")["ok"]
    artifact = compact_agentic_run(tmp_path / "run", isolation="same-user")
    assert artifact["silent_harness_seconds"] == 240.0
    assert artifact["agentic_summary"]["silent_harness_kills"] == 1
    compact = artifact["episodes"][0]["harness_run"]
    assert compact["silent_kills"] == 1 and compact["provider_stalls"] == 1
    assert compact["nudges"][0]["silent"] is False and compact["nudges"][0]["stall_retry"] is True
    assert validate_agentic_artifact(artifact)["ok"]
    from web.scripts.build_study import _agentic_telemetry

    telemetry = _agentic_telemetry(artifact["episodes"])
    assert (telemetry["silent_harness_kills"], telemetry["provider_stalls"], telemetry["guard_kills"]) == (1, 1, 0)
