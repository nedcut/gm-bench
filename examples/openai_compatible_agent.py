"""OpenAI-compatible chat-completions external agent for GM-Bench.

Set:
    LLM_API_KEY
    LLM_MODEL

Optional:
    LLM_API_BASE=https://api.openai.com/v1
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

try:
    from gm_agent_common import build_prompt, emit, fallback_actions, make_usage, parse_actions
except ModuleNotFoundError:
    from examples.gm_agent_common import build_prompt, emit, fallback_actions, make_usage, parse_actions


def main() -> None:
    observation = json.load(sys.stdin)
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("LLM_MODEL", "gpt-4.1-mini")
    base_url = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1").rstrip("/")
    timeout = float(os.environ.get("LLM_TIMEOUT", "120"))
    if not api_key:
        emit(fallback_actions(observation, "missing LLM_API_KEY or OPENAI_API_KEY"))
        return

    payload = {
        "model": model,
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
        "messages": [
            {
                "role": "system",
                "content": "Return only a JSON object with an actions array of GM-Bench action objects.",
            },
            {"role": "user", "content": build_prompt(observation)},
        ],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        raw_usage = data.get("usage") or {}
        usage = make_usage(
            provider="openai",
            model=data.get("model", model),
            api_calls=1,
            input_tokens=raw_usage.get("prompt_tokens"),
            output_tokens=raw_usage.get("completion_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
            api_latency_ms=latency_ms,
        )
        content = data["choices"][0]["message"]["content"]
        emit(parse_actions(content), usage)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        usage = make_usage(provider="openai", model=model, api_calls=1, api_latency_ms=latency_ms)
        emit(fallback_actions(observation, f"api_error: {exc}"), usage)


if __name__ == "__main__":
    main()
