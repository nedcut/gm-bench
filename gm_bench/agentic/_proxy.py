"""Stdio-to-socket proxy for the GM-Bench 2.0 MCP server.

This file is copied verbatim into the agent's scratch directory and launched
by the harness as the "MCP server". It imports nothing from gm_bench on
purpose: the agent can read it, and all it learns is where the server is.
The real server, the episode engine, and the seed live in the driver process
on the other end of that socket.

Usage:
    python3 gm_bench_proxy.py <socket-path>    # harness runs as the driver's user
    python3 gm_bench_proxy.py <host>:<port>    # harness runs in a container

The TCP form is for a containerized harness, which cannot reach a host Unix
socket through a bind mount. The driver's TCP listener accepts only
connections that open with the run secret, which the proxy reads from
``gm_bench_proxy.secret`` beside this file.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

SECRET_FILENAME = "gm_bench_proxy.secret"


def _pump_stdin(sock: socket.socket) -> None:
    try:
        for line in sys.stdin.buffer:
            sock.sendall(line)
    except (OSError, ValueError):
        pass
    finally:
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _connect(target: str) -> socket.socket:
    host, sep, port = target.rpartition(":")
    if "/" in target or not sep or not port.isdigit():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(target)
        return sock
    secret = Path(__file__).with_name(SECRET_FILENAME).read_text(encoding="utf-8").strip()
    sock = socket.create_connection((host, int(port)), timeout=30)
    sock.settimeout(None)
    sock.sendall(secret.encode("utf-8") + b"\n")
    return sock


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: gm_bench_proxy.py <socket-path> | <host>:<port>\n")
        return 2
    sock = _connect(argv[1])
    writer = threading.Thread(target=_pump_stdin, args=(sock,), daemon=True)
    writer.start()
    out = sys.stdout.buffer
    try:
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            out.write(chunk)
            out.flush()
    except OSError:
        pass
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
