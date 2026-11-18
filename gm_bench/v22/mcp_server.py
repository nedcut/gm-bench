"""The 2.2 MCP server: the frozen server bound to the 2.2 tools and brief.

Contract source for 2.2 (fingerprinted by ``gm_bench.v22.contract``).
``gm_bench/agentic/mcp_server.py`` is a 2.0 contract source and stays byte
for byte. It reads the 2.0 tool listing and server instructions as module
globals, so the methods that do are restated here; the transport, the
socket admission and the run secret are inherited.

There is no 2.2 stdio entry point: every harness driver serves the engine in
process through ``SocketMcpServer22``.
"""

from __future__ import annotations

import io
import socket
import threading
from typing import Any

from gm_bench.agentic.mcp_server import (
    SUPPORTED_PROTOCOL_VERSIONS,
    McpServer,
    SocketMcpServer,
    _close_quietly,
)
from gm_bench.v22.brief import server_instructions
from gm_bench.v22.tools import SERVER_NAME, TOOL_SURFACE_VERSION, mcp_tool_listing


class McpServer22(McpServer):
    def _dispatch(self, method: str, params: Any) -> dict[str, Any]:
        if method == "tools/list":
            return {"tools": mcp_tool_listing()}
        return super()._dispatch(method, params)

    def _initialize(self, params: Any) -> dict[str, Any]:
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[-1]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": TOOL_SURFACE_VERSION},
            "instructions": server_instructions(),
        }


class _LockedMcpServer22(McpServer22):
    def __init__(self, episode: Any, lock: threading.Lock, **streams: Any) -> None:
        super().__init__(episode, **streams)
        self._lock = lock

    def _dispatch(self, method: str, params: Any) -> dict[str, Any]:
        with self._lock:
            return super()._dispatch(method, params)


class SocketMcpServer22(SocketMcpServer):
    def _serve_connection(self, conn: socket.socket) -> None:
        # ``SocketMcpServer._serve_connection`` with the 2.2 server class.
        reader = conn.makefile("r", encoding="utf-8", newline="\n")
        writer = io.TextIOWrapper(conn.makefile("wb"), encoding="utf-8", write_through=True)
        server = _LockedMcpServer22(self.episode, self._lock, stdin=reader, stdout=writer, stderr=self.stderr)
        try:
            if self.secret is None or self._authenticated(conn, reader):
                with self._live_lock:
                    self.connections += 1
                server.serve()
        except (OSError, ValueError):
            pass
        finally:
            for stream in (reader, writer):
                try:
                    stream.close()
                except OSError:
                    pass
            _close_quietly(conn)
            with self._live_lock:
                self._live.pop(threading.current_thread(), None)
