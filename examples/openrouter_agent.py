"""OpenRouter Chat Completions external agent for GM-Bench.

The benchmark-safe default disables provider fallbacks. Set
OPENROUTER_PROVIDER_ONLY to pin an upstream provider for canonical rows.
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


def _boolean(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def provider_preferences() -> dict[str, Any]:
    """Build explicit OpenRouter routing controls from non-secret env vars."""
    preferences: dict[str, Any] = {
        "allow_fallbacks": _boolean("OPENROUTER_ALLOW_FALLBACKS", False),
        "require_parameters": _boolean("OPENROUTER_REQUIRE_PARAMETERS", False),
        "data_collection": os.environ.get("OPENROUTER_DATA_COLLECTION", "deny"),
        "sort": os.environ.get("OPENROUTER_PROVIDER_SORT", "price"),
    }
    only = _csv("OPENROUTER_PROVIDER_ONLY")
    quantizations = _csv("OPENROUTER_QUANTIZATIONS")
    if only:
        preferences["only"] = only
    if quantizations:
        preferences["quantizations"] = quantizations
    if "OPENROUTER_ZDR" in os.environ:
        preferences["zdr"] = _boolean("OPENROUTER_ZDR", False)
    return preferences


def choose_actions(observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if observation.get("phase") == "action_results":
        return [{"type": "end_turn"}], None

    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL", "openai/gpt-5.4-mini")
    base_url = os.environ.get("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1").rstrip("/")
    timeout = resolve_call_timeout("OPENROUTER_TIMEOUT", 180.0)
    if not api_key:
        return fallback_actions(observation, "missing OPENROUTER_API_KEY"), None

    started = time.perf_counter()
    usage: dict[str, Any] | None = None
    try:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return only a JSON object with an actions array."},
                {"role": "user", "content": build_prompt(observation)},
            ],
            "provider": provider_preferences(),
        }
        if _boolean("OPENROUTER_JSON_MODE", False):
            payload["response_format"] = {"type": "json_object"}
        max_tokens = os.environ.get("OPENROUTER_MAX_TOKENS")
        if max_tokens is not None:
            resolved_max_tokens = int(max_tokens)
            if resolved_max_tokens < 1:
                raise ValueError("OPENROUTER_MAX_TOKENS must be >= 1")
            payload["max_tokens"] = resolved_max_tokens
        reasoning_effort = os.environ.get("OPENROUTER_REASONING_EFFORT")
        reasoning_max = os.environ.get("OPENROUTER_REASONING_MAX_TOKENS")
        if reasoning_effort or reasoning_max:
            reasoning: dict[str, Any] = {}
            if reasoning_effort:
                reasoning["effort"] = reasoning_effort
            if reasoning_max:
                resolved_reasoning_max = int(reasoning_max)
                if resolved_reasoning_max < 1:
                    raise ValueError("OPENROUTER_REASONING_MAX_TOKENS must be >= 1")
                reasoning["max_tokens"] = resolved_reasoning_max
            payload["reasoning"] = reasoning
        temperature = os.environ.get("OPENROUTER_TEMPERATURE")
        if temperature is not None:
            payload["temperature"] = float(temperature)
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/nedcut/gm-bench",
                "X-OpenRouter-Title": "GM-Bench",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode())
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        raw_usage = data.get("usage") or {}
        prompt_details = raw_usage.get("prompt_tokens_details") or {}
        completion_details = raw_usage.get("completion_tokens_details") or {}
        usage = make_usage(
            provider="openrouter",
            model=data.get("model", model),
            api_calls=1,
            input_tokens=raw_usage.get("prompt_tokens"),
            output_tokens=raw_usage.get("completion_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
            cost_usd=raw_usage.get("cost"),
            api_latency_ms=latency_ms,
        )
        assert usage is not None
        for key, value in {
            "upstream_provider": data.get("provider"),
            "generation_id": data.get("id"),
            "cached_input_tokens": prompt_details.get("cached_tokens"),
            "reasoning_tokens": completion_details.get("reasoning_tokens"),
        }.items():
            if value is not None:
                usage[key] = value
        content = data["choices"][0]["message"]["content"]
        try:
            return parse_actions(content), usage
        except ValueError as exc:
            # An authenticated, metered response with unusable content is model
            # protocol behavior, not provider infrastructure failure. Keep it
            # as a scored failed decision without tripping the quota breaker.
            return fallback_actions(observation, f"protocol_error: {exc}"), usage
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        if usage is None:
            usage = make_usage(provider="openrouter", model=model, api_calls=1, api_latency_ms=latency_ms)
        return fallback_actions(observation, f"api_error: {exc}"), usage


def main() -> None:
    run_agent_main(choose_actions)


if __name__ == "__main__":
    main()
