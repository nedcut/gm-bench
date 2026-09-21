"""The hand-written MCP server, driven over stdio by a minimal JSON-RPC client."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

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
    config = opencode_config(tmp_path / "s", python="/usr/bin/python3")
    server = config["mcp"]["servers"]["gm-bench"]
    assert server["command"] == ["/usr/bin/python3", "gm_bench_proxy.py", str(tmp_path / "s")]
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
    usage = usage_block(telemetry, model="opencode/test", wall_seconds=12.5)
    assert usage["api_calls"] == 2 and usage["input_tokens"] == 150
    assert usage["cost_usd"] == 0.001
    assert usage["harness"]["telemetry_reported"] is True
    silent = usage_block(parse_opencode_events([]), model="opencode/test", wall_seconds=1.0)
    assert silent["cost_usd"] is None and silent["harness"]["telemetry_reported"] is False


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
    result["harness_run"] = {
        "ledger_path": str(ledger),
        "tool_call_agreement": {
            "ledger": result["agentic"]["tool_calls"],
            "harness": result["agentic"]["tool_calls"],
            "agree": True,
        },
        "exit_code": 0,
        "timed_out": False,
    }
    result["usage"]["harness"] = {"telemetry_reported": True}
    run = {"agent": "opencode:test", "contract": agentic_contract(), "seeds": [11], "episodes": [result]}
    (run_dir / "run.json").write_text(json.dumps(run))

    report = validate_run(run_dir)
    assert report["ok"], report
    assert report["per_episode"][0]["replayed_score"] == result["final_score"]
    assert report["warnings"] == []

    # Tamper with the score and the contract: both must be caught.
    run["episodes"][0]["final_score"] += 1.0
    run["contract"]["agentic_fingerprint"] = "0" * 16
    (run_dir / "run.json").write_text(json.dumps(run))
    report = validate_run(run_dir)
    assert report["ok"] is False
    assert any("replayed score" in p for p in report["problems"])
    assert any("contract.agentic_fingerprint" in p for p in report["problems"])


def test_nudge_loop_resumes_until_done_and_stops_without_progress(tmp_path: Path, monkeypatch) -> None:
    """Drive run_episode with a fake harness: it plays a little per invocation, then stalls."""
    import gm_bench.agentic.opencode as driver

    calls: list[list[str]] = []

    def fake_harness(command, *, cwd, env, events_path, stderr_path, timeout):
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
        return 0, False, 1.0

    monkeypatch.setattr(driver, "_run_harness", fake_harness)
    monkeypatch.setattr(driver, "sandbox_problems", lambda scratch, env: [])
    result = driver.run_episode(11, model="fake/model", run_dir=tmp_path / "run", seasons=1, max_nudges=5)
    harness_run = result["harness_run"]
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
        second.close()
        assert episode.phase == "midseason"
        assert server.connections == 2
    finally:
        server.stop()
        episode.close()
        shutil.rmtree(socket_dir, ignore_errors=True)
