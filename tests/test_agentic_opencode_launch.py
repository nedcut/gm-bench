"""The staged OpenCode launcher: ``opencode run`` starts only once the MCP servers have connected."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gm_bench.agentic import _opencode_launch
from gm_bench.agentic.opencode import LAUNCHER_FILENAME, OPENCODE_DRIVER, opencode_config

LAUNCHER = _opencode_launch.__file__

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the launcher forks a guard process")

# A stand-in ``opencode``. ``serve`` answers ``GET /api/mcp`` (Basic auth with the server password)
# with the statuses in $FAKE_STATES, one per poll, the last repeated; ``run`` records what it was given.
FAKE_OPENCODE = r"""
import base64, http.server, json, os, sys, time
log = os.environ["FAKE_LOG"]
def record(entry):
    with open(log, "a") as out:
        out.write(json.dumps(entry) + "\n")
if sys.argv[1] == "serve":
    password = os.environ["OPENCODE_SERVER_PASSWORD"]
    states = json.loads(os.environ["FAKE_STATES"])
    polls = []
    class Status(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            expected = "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()
            if self.path != "/api/mcp" or self.headers.get("authorization") != expected:
                self.send_response(401)
                self.end_headers()
                return
            polls.append(1)
            record({"poll": len(polls)})
            state = states[min(len(polls), len(states)) - 1]
            data = [] if state is None else [{"name": "gm-bench", "status": {"status": state}}]
            body = json.dumps({"location": {"directory": os.getcwd()}, "data": data}).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Status)
    record({"serve": os.getpid(), "argv": sys.argv[1:], "password": password,
            "client_password": os.environ.get("OPENCODE_PASSWORD")})
    print(f"server listening on http://127.0.0.1:{server.server_address[1]}", flush=True)
    server.serve_forever()
record({"run": os.getpid(), "argv": sys.argv[1:], "password": os.environ.get("OPENCODE_PASSWORD"),
        "server_password": os.environ.get("OPENCODE_SERVER_PASSWORD")})
print(json.dumps({"type": "text", "sessionID": "ses_launch"}), flush=True)
if os.environ.get("FAKE_RUN_SLEEP"):
    time.sleep(float(os.environ["FAKE_RUN_SLEEP"]))
sys.exit(7)
"""


def _fake(tmp_path: Path) -> Path:
    binary = tmp_path / "fake-opencode"
    binary.write_text(f"#!{sys.executable}\n{FAKE_OPENCODE}")
    binary.chmod(0o755)
    return binary


def _env(tmp_path: Path, states: list[str | None], **extra: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "FAKE_LOG": str(tmp_path / "log.jsonl"),
        "FAKE_STATES": json.dumps(states),
        **extra,
    }


def _log(tmp_path: Path) -> list[dict]:
    path = tmp_path / "log.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _gone(pid: int, seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        # A zombie child of the test process still answers signal 0; it is not running.
        try:
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                return True
        except ChildProcessError:
            pass
        time.sleep(0.05)
    return False


def test_run_starts_only_after_every_mcp_server_has_connected(tmp_path: Path) -> None:
    binary = _fake(tmp_path)
    # Empty until the workspace loads, then pending, then connected.
    env = _env(tmp_path, [None, "pending", "pending", "connected"])
    args = ["run", "--format", "json", "--auto", "--model", "opencode-go/m", "--session", "ses_x", "the brief"]

    completed = subprocess.run(
        [sys.executable, LAUNCHER, str(binary), *args], env=env, capture_output=True, text=True, timeout=60
    )

    assert completed.returncode == 7, completed.stderr
    assert json.loads(completed.stdout) == {"type": "text", "sessionID": "ses_launch"}
    log = _log(tmp_path)
    [serve] = [entry for entry in log if "serve" in entry]
    [run] = [entry for entry in log if "run" in entry]
    assert serve["argv"] == ["serve", "--hostname", "127.0.0.1", "--port", "0"]
    # The client starts after the fourth poll, the first to find every server connected.
    assert [entry.get("poll") for entry in log if "poll" in entry or "run" in entry][-1] is None
    assert max(entry["poll"] for entry in log if "poll" in entry) == 4
    port = run["argv"][2].rsplit(":", 1)[1]
    assert run["argv"] == ["run", "--server", f"http://127.0.0.1:{port}", *args[1:]]
    # One fresh password: the server's to require, the client's to present, neither the other's.
    assert serve["password"] and run["password"] == serve["password"]
    assert serve["client_password"] is None and run["server_password"] is None
    assert _gone(serve["serve"])


def test_launcher_ignores_an_inherited_password(tmp_path: Path) -> None:
    binary = _fake(tmp_path)
    env = _env(tmp_path, ["connected"], OPENCODE_PASSWORD="operator", OPENCODE_SERVER_PASSWORD="operator")

    completed = subprocess.run([sys.executable, LAUNCHER, str(binary), "run", "x"], env=env, timeout=60)

    assert completed.returncode == 7
    [serve] = [entry for entry in _log(tmp_path) if "serve" in entry]
    assert serve["password"] != "operator" and serve["client_password"] is None


def test_a_server_that_failed_to_connect_stops_the_launch(tmp_path: Path) -> None:
    binary = _fake(tmp_path)
    env = _env(tmp_path, ["pending", "failed"])

    completed = subprocess.run(
        [sys.executable, LAUNCHER, str(binary), "run", "x"], env=env, capture_output=True, text=True, timeout=60
    )

    assert completed.returncode == 1
    assert 'MCP servers did not connect: {"gm-bench": "failed"}' in completed.stderr
    log = _log(tmp_path)
    assert not [entry for entry in log if "run" in entry]
    [serve] = [entry for entry in log if "serve" in entry]
    assert _gone(serve["serve"])


def test_a_launcher_killed_outright_takes_the_server_and_client_with_it(tmp_path: Path) -> None:
    binary = _fake(tmp_path)
    env = _env(tmp_path, ["connected"], FAKE_RUN_SLEEP="120")
    launcher = subprocess.Popen(
        [sys.executable, LAUNCHER, str(binary), "run", "x"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while not [entry for entry in _log(tmp_path) if "run" in entry]:
            assert time.monotonic() < deadline, "the client never started"
            time.sleep(0.05)
        # What the driver does to a same-user harness on a timeout or a stall.
        launcher.send_signal(signal.SIGKILL)
        launcher.wait()
        log = _log(tmp_path)
        [serve] = [entry["serve"] for entry in log if "serve" in entry]
        [run] = [entry["run"] for entry in log if "run" in entry]
        assert _gone(serve) and _gone(run)
    finally:
        if launcher.poll() is None:
            launcher.kill()


def test_a_terminated_launcher_stops_both(tmp_path: Path) -> None:
    binary = _fake(tmp_path)
    env = _env(tmp_path, ["connected"], FAKE_RUN_SLEEP="120")
    launcher = subprocess.Popen([sys.executable, LAUNCHER, str(binary), "run", "x"], env=env, stdout=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while not [entry for entry in _log(tmp_path) if "run" in entry]:
            assert time.monotonic() < deadline, "the client never started"
            time.sleep(0.05)
        launcher.terminate()
        assert launcher.wait(timeout=30) == 128 + signal.SIGTERM
        log = _log(tmp_path)
        assert _gone(next(entry["serve"] for entry in log if "serve" in entry))
        assert _gone(next(entry["run"] for entry in log if "run" in entry))
    finally:
        if launcher.poll() is None:
            launcher.kill()


def test_only_run_goes_through_the_launcher() -> None:
    launch = type("L", (), {"proxy_python": "python3", "workdir": "/work"})()

    assert OPENCODE_DRIVER.invocation_argv(launch, "opencode", ["run", "--format", "json", "b"]) == [
        "python3",
        f"/work/{LAUNCHER_FILENAME}",
        "opencode",
        "run",
        "--format",
        "json",
        "b",
    ]
    export = ["session", "export", "ses_1", "--standalone"]
    assert OPENCODE_DRIVER.invocation_argv(launch, "opencode", export) == ["opencode", *export]


def test_code_mode_execute_is_denied() -> None:
    config = opencode_config("/tmp/s")

    # OpenCode 2.x offers ``execute`` for its own Code Mode tools; denying the permission removes the tool.
    assert config["permission"] == {"execute": "deny"}
    assert config["mcp"]["servers"]["gm-bench"]["codemode"] is False
