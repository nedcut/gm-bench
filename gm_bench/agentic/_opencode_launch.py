"""Start OpenCode 2.x with its MCP servers connected before the first model request.

This file is copied verbatim into the agent's scratch directory beside the
proxy, and every OpenCode 2.x invocation runs through it. It imports nothing
from gm_bench, holds no secret, and runs on the harness's own python3.

Why: ``opencode run --standalone`` starts a private server and sends the
prompt at once. The server connects its MCP servers in the background, and
the tool list of each model request is whatever has connected by then
(2.0.27 and 2.0.28: ``MCP.tools`` does not wait for a server's startup, only
``MCP.callTool`` does). The GM-Bench proxy takes most of a second to connect,
so the first turn of every invocation went to the model without the GM-Bench
tools, and the agent spent it looking for them.

So the launcher starts ``opencode serve`` on a loopback port with a password
of its own (OpenCode keeps ``OPENCODE_SERVER_PASSWORD`` and
``OPENCODE_PASSWORD`` out of the environment of the processes it starts),
polls ``GET /api/mcp`` until no MCP server is still pending, refuses to go on
if one failed to connect, and then runs ``opencode run --server <url>`` with
the arguments it was given. The client's exit code is the launcher's. The
server is stopped when the client exits, when the launcher is signalled, and,
through a guard process holding a pipe from the launcher, when the launcher
is killed outright: the launcher leads a process group of its own, and the
guard stops whatever is left in it (the driver kills a same-user harness with SIGKILL on a
timeout or a stall).

Usage:
    python3 gm_bench_opencode_launch.py <opencode> run [<run arguments>...]
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time

#: How long the MCP servers get to connect before the launch is abandoned.
MCP_WAIT_SECONDS = 60.0
#: How long ``opencode serve`` gets to report its address.
SERVE_START_SECONDS = 30.0
POLL_SECONDS = 0.1
STOP_SECONDS = 10.0
SERVER_USER = "opencode"
PASSWORD_VARIABLES = ("OPENCODE_PASSWORD", "OPENCODE_SERVER_PASSWORD")
_LISTENING = re.compile(r"listening on http://127\.0\.0\.1:(\d+)")
LOOPBACK = "127.0.0.1"


SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


class LaunchError(RuntimeError):
    pass


class Signalled(BaseException):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _guard(read_fd: int, group: int) -> None:
    """In a forked child: when the launcher is gone, stop what is left of its process group.

    Every process the launcher starts is in its group from the moment it is
    forked, so a child the launcher had no time to record (a signal, or a
    SIGKILL, right after ``Popen``) is still covered.
    """
    # A group of its own, so the group it stops does not include it.
    os.setpgid(0, 0)
    # Hold none of the launcher's streams (the harness's event stream and stderr log) open.
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    with os.fdopen(read_fd, "rb") as pipe:
        pipe.read()
    # The pipe closes as the launcher exits; let it finish, so its exit status is its own.
    deadline = time.monotonic() + STOP_SECONDS
    while os.getppid() == group and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, sig)
        except OSError:
            return
        deadline = time.monotonic() + STOP_SECONDS
        while time.monotonic() < deadline and _group_alive(group):
            time.sleep(POLL_SECONDS)
        if not _group_alive(group):
            return


def _group_alive(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except OSError:
        return False
    return True


def _start_guard() -> int:
    """Lead a process group of our own and fork the guard; returns the pipe's write end, which only the launcher holds."""
    if os.getpgid(0) != os.getpid():
        os.setpgid(0, 0)
    group = os.getpid()
    read_fd, write_fd = os.pipe()
    if os.fork() == 0:
        os.close(write_fd)
        try:
            _guard(read_fd, group)
        finally:
            os._exit(0)
    os.close(read_fd)
    os.set_inheritable(write_fd, False)
    return write_fd


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=STOP_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _server_port(server: subprocess.Popen[bytes]) -> int:
    """Read the loopback port ``opencode serve`` prints, then keep draining its stdout."""
    found: list[int] = []
    ready = threading.Event()

    def read() -> None:
        assert server.stdout is not None
        for raw in server.stdout:
            if not found:
                match = _LISTENING.search(raw.decode("utf-8", errors="replace"))
                if match:
                    found.append(int(match.group(1)))
                    ready.set()
        ready.set()

    threading.Thread(target=read, daemon=True).start()
    if not ready.wait(SERVE_START_SECONDS) or not found:
        raise LaunchError(f"opencode serve did not report its address within {SERVE_START_SECONDS:.0f}s")
    return found[0]


def mcp_states(port: int, password: str) -> dict[str, str]:
    """``GET /api/mcp`` on the server: each MCP server's name and connection status."""
    token = base64.b64encode(f"{SERVER_USER}:{password}".encode()).decode("ascii")
    connection = http.client.HTTPConnection(LOOPBACK, port, timeout=10)
    try:
        connection.request("GET", "/api/mcp", headers={"Authorization": f"Basic {token}"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"GET /api/mcp: HTTP {response.status}")
        servers = json.loads(response.read()).get("data") or []
    finally:
        connection.close()
    return {str(entry.get("name")): str((entry.get("status") or {}).get("status")) for entry in servers}


def wait_for_mcp(port: int, password: str, server: subprocess.Popen[bytes]) -> dict[str, str]:
    """Poll until every configured MCP server has left ``pending``; raise unless all connected."""
    deadline = time.monotonic() + MCP_WAIT_SECONDS
    states: dict[str, str] = {}
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise LaunchError(f"opencode serve exited with {server.returncode} before its MCP servers connected")
        try:
            states = mcp_states(port, password)
        except (OSError, ValueError, AttributeError):
            states = {}
        # The list is empty until the first request loads the workspace, then each server is pending.
        if states and "pending" not in states.values():
            failed = {name: state for name, state in states.items() if state != "connected"}
            if failed:
                raise LaunchError(f"MCP servers did not connect: {json.dumps(failed, sort_keys=True)}")
            return states
        time.sleep(POLL_SECONDS)
    raise LaunchError(f"MCP servers not connected after {MCP_WAIT_SECONDS:.0f}s: {json.dumps(states, sort_keys=True)}")


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[2] != "run":
        sys.stderr.write("usage: gm_bench_opencode_launch.py <opencode> run [<run arguments>...]\n")
        return 2
    opencode, run_args = argv[1], argv[3:]
    guard = _start_guard()
    password = secrets.token_urlsafe(32)
    base = {key: value for key, value in os.environ.items() if key not in PASSWORD_VARIABLES}
    server: subprocess.Popen[bytes] | None = None
    client: subprocess.Popen[bytes] | None = None

    def on_signal(signum: int, _frame: object) -> None:
        # Unwind out of whatever wait is running; the ``finally`` below stops the children.
        raise Signalled(signum)

    for signum in SIGNALS:
        signal.signal(signum, on_signal)
    try:
        server = subprocess.Popen(
            [opencode, "serve", "--hostname", "127.0.0.1", "--port", "0"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            env={**base, "OPENCODE_SERVER_PASSWORD": password},
        )
        try:
            port = _server_port(server)
            wait_for_mcp(port, password, server)
        except LaunchError as error:
            sys.stderr.write(f"gm_bench_opencode_launch: {error}\n")
            return 1
        client = subprocess.Popen(
            [opencode, "run", "--server", f"http://{LOOPBACK}:{port}", *run_args],
            stdin=subprocess.DEVNULL,
            env={**base, "OPENCODE_PASSWORD": password},
        )
        return client.wait()
    except Signalled as signalled:
        return 128 + signalled.signum
    finally:
        for signum in SIGNALS:
            signal.signal(signum, signal.SIG_IGN)
        _stop(client)
        _stop(server)
        os.close(guard)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
