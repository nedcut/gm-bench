"""Persistent external-agent sessions with multi-round interaction."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

from gm_bench.agents import Agent
from gm_bench.protocol import QUERY_ACTION_TYPES


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

    def start_episode(self, seed: int, seasons: int) -> None:
        run_env = os.environ.copy()
        run_env["GM_BENCH_SESSION"] = "1"
        if self.env:
            run_env.update(self.env)
        self._process = subprocess.Popen(
            shlex.split(self.command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=run_env,
        )
        self._send({"event": "start", "seed": seed, "seasons": seasons})

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        self._send({"event": "observation", "payload": observation})
        return self._read_actions()

    def act_on_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._send({"event": "action_results", "results": results})
        return self._read_actions()

    def end_episode(self) -> None:
        if self._process is None:
            return
        try:
            self._send({"event": "end"})
        finally:
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def _send(self, payload: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("persistent agent session is not started")
        line = json.dumps(payload, sort_keys=True)
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()

    def _read_actions(self) -> list[dict[str, Any]]:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("persistent agent session is not started")
        line = self._process.stdout.readline()
        if not line:
            stderr = self._process.stderr.read(-1) if self._process.stderr else ""
            raise RuntimeError(f"persistent agent exited early: {stderr[-500:]}")
        payload = json.loads(line)
        actions = payload.get("actions", payload)
        if isinstance(actions, dict) and isinstance(actions.get("actions"), list):
            actions = actions["actions"]
        if not isinstance(actions, list):
            return [{"type": "noop", "error": "persistent agent must return an actions list"}]
        return actions


def should_continue_interaction(results: list[dict[str, Any]], *, max_rounds: int, round_index: int) -> bool:
    if round_index >= max_rounds - 1:
        return False
    if any(result.get("action", {}).get("type") == "end_turn" and result.get("accepted") for result in results):
        return False
    return any(
        result.get("accepted") and result.get("action", {}).get("type") in QUERY_ACTION_TYPES for result in results
    )
