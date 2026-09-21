"""Stdio-to-socket proxy for the GM-Bench 2.0 MCP server.

This file is copied verbatim into the agent's scratch directory and launched
by the harness as the "MCP server". It imports nothing from gm_bench on
purpose: the agent can read it, and all it learns is a socket path. The real
server, the episode engine, and the seed live in the driver process on the
other end of that socket.

Usage: python3 gm_bench_proxy.py <socket-path>
"""

from __future__ import annotations

import socket
import sys
import threading


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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: gm_bench_proxy.py <socket-path>\n")
        return 2
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(argv[1])
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
