"""The hand-written MCP server, driven over stdio by a minimal JSON-RPC client."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from gm_bench.agentic.mcp_server import EPISODE_ENV
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
    # The closing tool call is logged after the phase/episode events it triggers.
    assert [r["event"] for r in ledger[-3:]] == ["phase_end", "episode_end", "tool_call"]
    assert ledger[-1]["tool"] == "end_phase"
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
    config = opencode_config(tmp_path / "episode.json", python="/usr/bin/python3")
    server = config["mcp"]["servers"]["gm-bench"]
    assert server["command"][:2] == ["/usr/bin/python3", "-m"]
    assert server["codemode"] is False
    assert server["environment"][EPISODE_ENV].endswith("episode.json")

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
