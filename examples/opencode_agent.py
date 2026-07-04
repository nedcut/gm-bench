"""opencode-backed external agent for GM-Bench.

Usage:
    OPENCODE_MODEL=opencode/deepseek-v4-flash-free python -m gm_bench run \
      --agent-cmd "python examples/opencode_agent.py" --agent-timeout 180 \
      --seeds 1 --seasons 1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

try:
    from gm_agent_common import build_prompt, emit, fallback_actions, make_usage, parse_actions
except ModuleNotFoundError:
    from examples.gm_agent_common import build_prompt, emit, fallback_actions, make_usage, parse_actions


def main() -> None:
    observation = json.load(sys.stdin)
    model = os.environ.get("OPENCODE_MODEL", "opencode/deepseek-v4-flash-free")
    timeout = float(os.environ.get("OPENCODE_TIMEOUT", "180"))
    command = ["opencode", "run", "--model", model, "--format", "json", "--pure", build_prompt(observation)]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False
        )
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        input_tokens, output_tokens, cost = extract_opencode_usage(completed.stdout)
        usage = make_usage(
            provider="opencode",
            model=model,
            api_calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            api_latency_ms=latency_ms,
            cost_usd=cost,
        )
        if completed.returncode != 0:
            emit(
                fallback_actions(observation, f"opencode_exit_{completed.returncode}: {completed.stderr[-300:]}"),
                usage,
            )
            return
        content = extract_opencode_text(completed.stdout)
        emit(parse_actions(content), usage)
    except (subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        emit(
            fallback_actions(observation, f"opencode_error: {exc}"),
            make_usage(provider="opencode", model=model, api_calls=1, api_latency_ms=latency_ms),
        )


def extract_opencode_text(stdout: str) -> str:
    texts: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event: Any = json.loads(line)
        except json.JSONDecodeError:
            texts.append(line)
            continue
        for key in ("text", "content", "message"):
            value = event.get(key)
            if isinstance(value, str):
                texts.append(value)
        data = event.get("data")
        if isinstance(data, dict):
            for key in ("text", "content", "message"):
                value = data.get(key)
                if isinstance(value, str):
                    texts.append(value)
            message = data.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    texts.append(content)
    return "\n".join(texts) if texts else stdout


def extract_opencode_usage(stdout: str) -> tuple[int | None, int | None, float | None]:
    """Best-effort scan of opencode's JSON event stream for token/cost fields.

    opencode step-finish events carry a `tokens` dict ({input, output, ...})
    and a numeric `cost`; sum whatever appears since event shapes vary across
    opencode versions.
    """
    input_tokens = 0
    output_tokens = 0
    cost = 0.0
    saw_tokens = False
    saw_cost = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for node in (event, event.get("data") if isinstance(event, dict) else None):
            if not isinstance(node, dict):
                continue
            tokens = node.get("tokens")
            if isinstance(tokens, dict):
                if isinstance(tokens.get("input"), (int, float)):
                    input_tokens += int(tokens["input"])
                    saw_tokens = True
                if isinstance(tokens.get("output"), (int, float)):
                    output_tokens += int(tokens["output"])
                    saw_tokens = True
            node_cost = node.get("cost")
            if isinstance(node_cost, (int, float)) and not isinstance(node_cost, bool):
                cost += float(node_cost)
                saw_cost = True
    return (
        input_tokens if saw_tokens else None,
        output_tokens if saw_tokens else None,
        round(cost, 6) if saw_cost else None,
    )


if __name__ == "__main__":
    main()
