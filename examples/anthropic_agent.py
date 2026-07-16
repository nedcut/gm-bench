"""Native Anthropic Messages API external agent for GM-Bench.

Required: ANTHROPIC_API_KEY.
Optional: ANTHROPIC_MODEL, ANTHROPIC_API_BASE, ANTHROPIC_MAX_TOKENS,
ANTHROPIC_TEMPERATURE, ANTHROPIC_TIMEOUT.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

try:
    from gm_agent_common import (
        build_prompt,
        fallback_actions,
        make_usage,
        parse_actions,
        resolve_call_timeout,
        run_agent_main,
    )
except ModuleNotFoundError:
    from examples.gm_agent_common import (
        build_prompt,
        fallback_actions,
        make_usage,
        parse_actions,
        resolve_call_timeout,
        run_agent_main,
    )


def choose_actions(observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if observation.get("phase") == "action_results":
        return [{"type": "end_turn"}], None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    base_url = os.environ.get("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1").rstrip("/")
    timeout = resolve_call_timeout("ANTHROPIC_TIMEOUT", 180.0)
    if not api_key:
        return fallback_actions(observation, "missing ANTHROPIC_API_KEY"), None

    started = time.perf_counter()
    try:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": int(os.environ.get("ANTHROPIC_MAX_TOKENS", "4096")),
            "system": "Return only a JSON object with an actions array of GM-Bench action objects.",
            "messages": [{"role": "user", "content": build_prompt(observation)}],
        }
        temperature = os.environ.get("ANTHROPIC_TEMPERATURE")
        if temperature is not None:
            payload["temperature"] = float(temperature)
        request = urllib.request.Request(
            f"{base_url}/messages",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        # Fixed provider HTTPS endpoint from operator config, not attacker-controlled input.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosemgrep
            data = json.loads(response.read().decode())
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        raw_usage = data.get("usage") or {}
        input_tokens = raw_usage.get("input_tokens")
        cache_read = raw_usage.get("cache_read_input_tokens")
        cache_creation = raw_usage.get("cache_creation_input_tokens")
        cached_input = sum(value for value in (cache_read, cache_creation) if isinstance(value, int)) or None
        output_tokens = raw_usage.get("output_tokens")
        total_tokens = None
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            total_tokens = input_tokens + output_tokens + (cached_input or 0)
        usage = make_usage(
            provider="anthropic",
            model=data.get("model", model),
            api_calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            api_latency_ms=latency_ms,
        )
        assert usage is not None
        if cached_input is not None:
            usage["cached_input_tokens"] = cached_input
        content = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return parse_actions(content), usage
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        usage = make_usage(provider="anthropic", model=model, api_calls=1, api_latency_ms=latency_ms)
        return fallback_actions(observation, f"api_error: {exc}"), usage


def main() -> None:
    run_agent_main(choose_actions)


if __name__ == "__main__":
    main()
