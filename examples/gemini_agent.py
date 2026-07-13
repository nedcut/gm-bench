"""Native Gemini generateContent external agent for GM-Bench.

Required: GEMINI_API_KEY or GOOGLE_API_KEY.
Optional: GEMINI_MODEL, GEMINI_API_BASE, GEMINI_TEMPERATURE, GEMINI_TIMEOUT.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
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

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    base_url = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    timeout = resolve_call_timeout("GEMINI_TIMEOUT", 180.0)
    if not api_key:
        return fallback_actions(observation, "missing GEMINI_API_KEY or GOOGLE_API_KEY"), None

    started = time.perf_counter()
    try:
        payload = {
            "systemInstruction": {
                "parts": [{"text": "Return only a JSON object with an actions array of GM-Bench action objects."}]
            },
            "contents": [{"role": "user", "parts": [{"text": build_prompt(observation)}]}],
            "generationConfig": {
                "temperature": float(os.environ.get("GEMINI_TEMPERATURE", "0.2")),
                "responseMimeType": "application/json",
            },
        }
        max_output_tokens = os.environ.get("GEMINI_MAX_OUTPUT_TOKENS")
        if max_output_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = int(max_output_tokens)
        encoded_model = urllib.parse.quote(model, safe="")
        request = urllib.request.Request(
            f"{base_url}/models/{encoded_model}:generateContent",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        raw_usage = data.get("usageMetadata") or {}
        input_tokens = raw_usage.get("promptTokenCount")
        total_tokens = raw_usage.get("totalTokenCount")
        output_tokens = None
        if isinstance(total_tokens, int) and isinstance(input_tokens, int):
            # Gemini bills thinking tokens as output; total minus prompt keeps
            # that spend visible instead of counting only visible candidates.
            output_tokens = max(0, total_tokens - input_tokens)
        usage = make_usage(
            provider="gemini",
            model=data.get("modelVersion", model),
            api_calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            api_latency_ms=latency_ms,
        )
        parts = data["candidates"][0]["content"]["parts"]
        content = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        return parse_actions(content), usage
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        usage = make_usage(provider="gemini", model=model, api_calls=1, api_latency_ms=latency_ms)
        return fallback_actions(observation, f"api_error: {exc}"), usage


def main() -> None:
    run_agent_main(choose_actions)


if __name__ == "__main__":
    main()
