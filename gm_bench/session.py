"""Persistent external-agent sessions with multi-round interaction."""

from __future__ import annotations

import json
import os
import selectors
import shlex
import subprocess
import tempfile
import time
from typing import Any, BinaryIO

from gm_bench.agents import Agent
from gm_bench.protocol import QUERY_ACTION_TYPES
from gm_bench.telemetry import normalize_usage


class PersistentProcessAgent(Agent):
    """Keeps one subprocess alive for an entire episode with line-delimited JSON events."""

    name = "external-session"

    def __init__(
        self,
        command: str,
        timeout_seconds: float = 120.0,
        *,
        env: dict[str, str] | None = None,
        name: str | None = None,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.env = env
        if name is not None:
            self.name = name
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr_file: BinaryIO | None = None
        self._stdout_buf = b""

    def start_episode(self, seed: int, seasons: int) -> None:
        run_env = os.environ.copy()
        run_env["GM_BENCH_SESSION"] = "1"
        if self.env:
            run_env.update(self.env)
        self._stdout_buf = b""
        self._stderr_file = tempfile.TemporaryFile()
        try:
            self._process = subprocess.Popen(
                shlex.split(self.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_file,
                env=run_env,
            )
        except OSError:
            self._stderr_file.close()
            self._stderr_file = None
            raise
        self._send({"event": "start", "seed": seed, "seasons": seasons})

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, _ = self.act_with_usage(observation)
        return actions

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        self._send({"event": "observation", "payload": observation})
        return self._read_response()

    def act_on_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actions, _ = self.act_on_results_with_usage(results)
        return actions

    def act_on_results_with_usage(
        self,
        results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        self._send({"event": "action_results", "results": results})
        return self._read_response()

    def end_episode(self) -> None:
        if self._process is None:
            return
        process = self._process
        try:
            if process.poll() is None:
                try:
                    self._send({"event": "end"})
                except OSError:
                    pass
                if process.stdin is not None:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if self._stderr_file is not None:
                self._stderr_file.close()
                self._stderr_file = None
            self._process = None
            self._stdout_buf = b""

    def clone(self) -> PersistentProcessAgent:
        """Return an independent session handle for parallel seed runs."""
        return PersistentProcessAgent(
            self.command,
            timeout_seconds=self.timeout_seconds,
            env=dict(self.env) if self.env else None,
            name=self.name,
        )

    def _send(self, payload: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("persistent agent session is not started")
        line = json.dumps(payload, sort_keys=True) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        self._process.stdin.flush()

    def _read_response(self) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("persistent agent session is not started")
        line = self._read_stdout_line()
        if line is None:
            return ([{"type": "noop", "error": f"persistent agent timed out after {self.timeout_seconds}s"}], None)
        if line == "":
            stderr = self._stderr_tail()
            return ([{"type": "noop", "error": f"persistent agent exited early: {stderr[-500:]}"}], None)
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return ([{"type": "noop", "error": "persistent agent returned invalid JSON"}], None)
        actions = payload.get("actions", payload) if isinstance(payload, dict) else payload
        if isinstance(actions, dict) and isinstance(actions.get("actions"), list):
            actions = actions["actions"]
        if not isinstance(actions, list):
            return ([{"type": "noop", "error": "persistent agent must return an actions list"}], None)
        usage = normalize_usage(payload.get("usage")) if isinstance(payload, dict) else None
        return actions, usage

    def _read_stdout_line(self) -> str | None:
        """Read one newline-terminated line within ``timeout_seconds``.

        Returns the decoded line (without trailing newline) on success, ``""`` on
        EOF before a complete line, and ``None`` on timeout (process killed).

        Unlike a single ``select`` + ``readline()``, this re-selects with the
        remaining budget and only consumes non-blocking bytes, so a writer that
        emits a partial line and stalls still times out.
        """
        process = self._process
        assert process is not None and process.stdout is not None
        stdout = process.stdout
        deadline = time.monotonic() + self.timeout_seconds
        fd = stdout.fileno()
        was_blocking = os.get_blocking(fd)
        os.set_blocking(fd, False)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(fd, selectors.EVENT_READ)
                while True:
                    newline_at = self._stdout_buf.find(b"\n")
                    if newline_at >= 0:
                        line = self._stdout_buf[:newline_at]
                        self._stdout_buf = self._stdout_buf[newline_at + 1 :]
                        return line.decode("utf-8")

                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._kill_for_timeout()
                        return None
                    if not selector.select(remaining):
                        self._kill_for_timeout()
                        return None
                    try:
                        chunk = os.read(fd, 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        # EOF: surface any partial bytes so the caller can report
                        # invalid JSON; pure empty EOF becomes an early-exit.
                        if self._stdout_buf:
                            line = self._stdout_buf
                            self._stdout_buf = b""
                            return line.decode("utf-8")
                        return ""
                    self._stdout_buf += chunk
        finally:
            try:
                os.set_blocking(fd, was_blocking)
            except OSError:
                pass

    def _kill_for_timeout(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.kill()
            process.wait()
        self._stdout_buf = b""

    def _stderr_tail(self) -> str:
        if self._stderr_file is None:
            return ""
        self._stderr_file.flush()
        self._stderr_file.seek(0)
        return self._stderr_file.read()[-500:].decode("utf-8", errors="replace")


def should_continue_interaction(results: list[dict[str, Any]], *, max_rounds: int, round_index: int) -> bool:
    if round_index >= max_rounds - 1:
        return False
    if any(result.get("action", {}).get("type") == "end_turn" and result.get("accepted") for result in results):
        return False
    return any(
        result.get("accepted") and result.get("action", {}).get("type") in QUERY_ACTION_TYPES for result in results
    )
