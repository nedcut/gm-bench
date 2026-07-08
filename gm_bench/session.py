"""Persistent external-agent sessions with multi-round interaction."""

from __future__ import annotations

import json
import os
import selectors
import shlex
import subprocess
import tempfile
from typing import Any, TextIO

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
        self._process: subprocess.Popen[str] | None = None
        self._stderr_file: TextIO | None = None

    def start_episode(self, seed: int, seasons: int) -> None:
        run_env = os.environ.copy()
        run_env["GM_BENCH_SESSION"] = "1"
        if self.env:
            run_env.update(self.env)
        self._stderr_file = tempfile.TemporaryFile(mode="w+t")
        try:
            self._process = subprocess.Popen(
                shlex.split(self.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_file,
                text=True,
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
        line = json.dumps(payload, sort_keys=True)
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()

    def _read_response(self) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("persistent agent session is not started")
        with selectors.DefaultSelector() as selector:
            selector.register(self._process.stdout, selectors.EVENT_READ)
            if not selector.select(self.timeout_seconds):
                self._process.kill()
                self._process.wait()
                return ([{"type": "noop", "error": f"persistent agent timed out after {self.timeout_seconds}s"}], None)
        line = self._process.stdout.readline()
        if not line:
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

    def _stderr_tail(self) -> str:
        if self._stderr_file is None:
            return ""
        self._stderr_file.flush()
        self._stderr_file.seek(0)
        return self._stderr_file.read()[-500:]


def should_continue_interaction(results: list[dict[str, Any]], *, max_rounds: int, round_index: int) -> bool:
    if round_index >= max_rounds - 1:
        return False
    if any(result.get("action", {}).get("type") == "end_turn" and result.get("accepted") for result in results):
        return False
    return any(
        result.get("accepted") and result.get("action", {}).get("type") in QUERY_ACTION_TYPES for result in results
    )
