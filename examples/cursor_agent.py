"""Cursor CLI-backed external agent for GM-Bench.

This adapter calls `cursor-agent -p` once per benchmark decision point and
expects Cursor to return a JSON object with an `actions` array.

Example:
    CURSOR_MODEL=composer-2.5 python -m gm_bench run \
      --agent-cmd "python examples/cursor_agent.py" \
      --agent-timeout 180 --seeds 1 --seasons 1 --json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from gm_agent_common import build_prompt, emit, fallback_actions, make_usage, parse_actions, resolve_call_timeout
except ModuleNotFoundError:
    from examples.gm_agent_common import (
        build_prompt,
        emit,
        fallback_actions,
        make_usage,
        parse_actions,
        resolve_call_timeout,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "composer-2.5"


def main() -> None:
    observation = json.load(sys.stdin)
    os.environ.setdefault("GM_AGENT_PROFILE", "compact")
    timeout = resolve_call_timeout("CURSOR_AGENT_TIMEOUT", 180.0)
    model = os.environ.get("CURSOR_MODEL", DEFAULT_MODEL)
    prompt = (
        "You are competing in GM-Bench as a sports general manager. "
        "Do not inspect or edit files. Do not run shell commands. "
        "Use only the observation in the prompt. "
        "Return only JSON matching the schema.\n\n" + build_prompt(observation)
    )
    command = build_command(prompt, model)
    started = time.perf_counter()
    try:
        # Ask mode is read-only but can still open files; run in a throwaway
        # directory with no line of sight to this repo so the model cannot
        # read gm_bench/simulator.py and recompute the hidden valuations.
        with tempfile.TemporaryDirectory() as scratch:
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                cwd=scratch,
            )
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout)[-500:]
            emit(
                fallback_actions(observation, f"cursor_exit_{completed.returncode}: {detail}"),
                make_usage(provider="cursor", model=model, api_calls=1, api_latency_ms=latency_ms),
            )
            return
        text, usage = extract_cursor_result(completed.stdout, model, latency_ms)
        emit(parse_actions(text), usage)
    except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        emit(
            fallback_actions(observation, f"cursor_error: {exc}"),
            make_usage(provider="cursor", model=model, api_calls=1, api_latency_ms=latency_ms),
        )


def build_command(prompt: str, model: str) -> list[str]:
    return [
        "cursor-agent",
        "-p",
        "--trust",
        "--mode",
        "ask",
        "--model",
        model,
        "--output-format",
        "json",
        prompt,
    ]


def extract_cursor_result(stdout: str, model: str | None, wall_latency_ms: float) -> tuple[str, dict[str, Any] | None]:
    """Pull the result text plus usage from `cursor-agent -p --output-format json`."""
    fallback_usage = make_usage(provider="cursor", model=model, api_calls=1, api_latency_ms=wall_latency_ms)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout, fallback_usage
    if not isinstance(payload, dict):
        return stdout, fallback_usage

    text = payload.get("result") if isinstance(payload.get("result"), str) else stdout

    raw_usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    input_tokens = None
    if raw_usage:
        # Cache reads/writes are still context the model processed; fold them
        # into input so token counts are comparable across providers (mirrors
        # claude_agent.py's treatment of Claude's cache token fields).
        parts = [
            raw_usage.get("inputTokens"),
            raw_usage.get("cacheReadTokens"),
            raw_usage.get("cacheWriteTokens"),
        ]
        numeric = [part for part in parts if isinstance(part, (int, float))]
        input_tokens = int(sum(numeric)) if numeric else None
    output_tokens = raw_usage.get("outputTokens") if isinstance(raw_usage.get("outputTokens"), int) else None
    api_latency = payload.get("duration_api_ms") or payload.get("duration_ms")
    usage = make_usage(
        provider="cursor",
        model=model,
        api_calls=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        api_latency_ms=float(api_latency) if isinstance(api_latency, (int, float)) else wall_latency_ms,
    )
    return text, usage or fallback_usage


if __name__ == "__main__":
    main()
