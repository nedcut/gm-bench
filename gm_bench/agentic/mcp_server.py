"""GM-Bench 2.0 MCP server over the stdio transport.

Hand-written on purpose (docs/bench_v2_spec.md, "Implementation"): the wire
output here is a contract source, and the surface a tool server needs is
five JSON-RPC methods. Newline-delimited JSON-RPC 2.0 on stdin/stdout; all
diagnostics go to stderr so they can never corrupt the stream.

Run as ``python -m gm_bench.agentic.mcp_server``. Configuration comes from
one environment variable, ``GM_BENCH_AGENTIC_EPISODE``, naming a JSON file the
driver wrote outside the agent's workspace::

    {"seed": 11, "seasons": 5, "user_team_id": 0,
     "ledger_path": ".../ledger.jsonl", "phase_guard_seconds": 1200}

If the ledger already exists the episode is rebuilt from it, so a harness
that restarts its MCP servers mid-episode resumes instead of starting over.
On stdin EOF the server exits without scoring: finalization is the driver's
job, because only the driver knows whether the harness is coming back.

The OpenCode driver does not use this stdio entry point directly. It keeps
the engine in its own process and serves the same ``McpServer`` over a
private Unix socket (``SocketMcpServer``); the harness launches a tiny
standard-library proxy (``_proxy.py``) that forwards stdio to that socket.
That way no file the agent can read names the seed, the interpreter, or the
repository, and the engine survives harness restarts and nudges without any
replay. The stdio mode stays for tests and for harnesses driven by hand.
"""

from __future__ import annotations

import io
import json
import os
import signal
import socket
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from gm_bench.agentic.brief import server_instructions
from gm_bench.agentic.episode import AgenticEpisode, EpisodeComplete
from gm_bench.agentic.tools import SERVER_NAME, TOOL_SURFACE_VERSION, mcp_tool_listing

EPISODE_ENV = "GM_BENCH_AGENTIC_EPISODE"
# Protocol revisions this server has been exercised against. The server
# answers with the client's own version when it is one of these, otherwise
# with the newest it knows; a client that cannot accept that must disconnect.
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28")

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


def load_episode(config: dict[str, Any]) -> AgenticEpisode:
    ledger = Path(config["ledger_path"])
    if ledger.exists() and ledger.stat().st_size > 0:
        return AgenticEpisode.from_ledger(ledger)
    return AgenticEpisode(
        int(config["seed"]),
        int(config.get("seasons", 5)),
        int(config.get("user_team_id", 0)),
        ledger_path=ledger,
        phase_guard_seconds=float(config.get("phase_guard_seconds", 20 * 60)),
    )


class McpServer:
    def __init__(self, episode: AgenticEpisode, *, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
        self.episode = episode
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.initialized = False

    # -- transport ------------------------------------------------------------

    def serve(self) -> None:
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._send({"jsonrpc": "2.0", "id": None, "error": {"code": _PARSE_ERROR, "message": "parse error"}})
                continue
            if isinstance(message, list):
                for item in message:
                    self._handle(item)
            else:
                self._handle(message)

    def _send(self, payload: dict[str, Any]) -> None:
        self.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
        self.stdout.flush()

    def _handle(self, message: Any) -> None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            self._send(
                {"jsonrpc": "2.0", "id": None, "error": {"code": _INVALID_REQUEST, "message": "invalid request"}}
            )
            return
        method = message.get("method")
        request_id = message.get("id")
        if "id" not in message or method is None:
            # A notification (no id) or a response to something we never sent: ignore.
            if method == "notifications/initialized":
                self.initialized = True
            return
        try:
            result = self._dispatch(method, message.get("params") or {})
        except _RpcError as exc:
            self._send({"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.code, "message": exc.message}})
            return
        except Exception as exc:  # noqa: BLE001 - the stream must survive any tool bug
            self.stderr.write(f"gm-bench mcp: internal error in {method}: {exc!r}\n")
            self._send({"jsonrpc": "2.0", "id": request_id, "error": {"code": _INTERNAL_ERROR, "message": str(exc)}})
            return
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    # -- methods --------------------------------------------------------------

    def _dispatch(self, method: str, params: Any) -> dict[str, Any]:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": mcp_tool_listing()}
        if method == "tools/call":
            return self._call(params)
        raise _RpcError(_METHOD_NOT_FOUND, f"method not found: {method}")

    def _initialize(self, params: Any) -> dict[str, Any]:
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[-1]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": TOOL_SURFACE_VERSION},
            "instructions": server_instructions(),
        }

    def _call(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise _RpcError(_INVALID_PARAMS, "tools/call needs a string name")
        name = params["name"]
        arguments = params.get("arguments")
        try:
            outcome = self.episode.call_tool(name, arguments)
        except EpisodeComplete as exc:
            outcome = {"ok": False, "message": str(exc), "episode_complete": True}
        text = json.dumps(outcome, sort_keys=True, ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": outcome,
            "isError": not bool(outcome.get("ok", False)),
        }


class SocketMcpServer:
    """Serve one episode to any number of sequential (or overlapping) stdio proxies.

    Each accepted connection is one newline-delimited JSON-RPC stream, handled
    by an ``McpServer`` over that socket. Tool calls are serialized with a lock
    so two connections can never interleave inside the engine.
    """

    def __init__(self, episode: AgenticEpisode, path: str | Path, *, stderr: TextIO | None = None) -> None:
        self.episode = episode
        self.path = str(path)
        self.stderr = stderr or sys.stderr
        self._lock = threading.Lock()
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.connections = 0

    def start(self) -> None:
        if os.path.exists(self.path):
            os.unlink(self.path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(self.path)
        os.chmod(self.path, 0o600)
        listener.listen(8)
        listener.settimeout(0.5)
        self._listener = listener
        self._thread = threading.Thread(target=self._accept_loop, name="gm-bench-mcp-socket", daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.connections += 1
            threading.Thread(target=self._serve_connection, args=(conn,), daemon=True).start()

    def _serve_connection(self, conn: socket.socket) -> None:
        reader = conn.makefile("r", encoding="utf-8", newline="\n")
        writer = io.TextIOWrapper(conn.makefile("wb"), encoding="utf-8", write_through=True)
        server = _LockedMcpServer(self.episode, self._lock, stdin=reader, stdout=writer, stderr=self.stderr)
        try:
            server.serve()
        except (OSError, ValueError):
            pass
        finally:
            for stream in (reader, writer):
                try:
                    stream.close()
                except OSError:
                    pass
            try:
                conn.close()
            except OSError:
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if os.path.exists(self.path):
            try:
                os.unlink(self.path)
            except OSError:
                pass


class _LockedMcpServer(McpServer):
    def __init__(self, episode: AgenticEpisode, lock: threading.Lock, **streams: Any) -> None:
        super().__init__(episode, **streams)
        self._lock = lock

    def _dispatch(self, method: str, params: Any) -> dict[str, Any]:
        with self._lock:
            return super()._dispatch(method, params)


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def main(argv: list[str] | None = None) -> int:
    config_path = os.environ.get(EPISODE_ENV)
    if not config_path:
        sys.stderr.write(f"gm-bench mcp: {EPISODE_ENV} is not set\n")
        return 2
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    episode = load_episode(config)
    server = McpServer(episode, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)

    def _terminate(_signum: int, _frame: Any) -> None:
        episode.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _terminate)
    try:
        server.serve()
    finally:
        episode.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
