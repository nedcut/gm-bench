"""OpenRouter Chat Completions external agent for GM-Bench.

The benchmark-safe default disables provider fallbacks. Set
OPENROUTER_PROVIDER_ONLY to pin an upstream provider for canonical rows.
"""

from __future__ import annotations

import json
import math
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
        resolve_call_timeout,
        run_agent_main,
    )
except ModuleNotFoundError:
    from examples.gm_agent_common import (
        build_prompt,
        fallback_actions,
        make_usage,
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


def _finite_cost(value: Any) -> float | None:
    """Return an authoritative finite non-negative provider cost."""
    if isinstance(value, bool):
        return None
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(cost) or cost < 0:
        return None
    return cost


def _generation_cost(base_url: str, api_key: str, generation_id: str) -> float | None:
    """Recover asynchronously posted OpenRouter cost for one generation."""
    query = urllib.parse.urlencode({"id": generation_id})
    request = urllib.request.Request(
        f"{base_url}/generation?{query}",
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": "gm-bench-openrouter-agent/1"},
    )
    for delay in (0.0, 0.25, 0.5, 1.0, 2.0):
        if delay:
            time.sleep(delay)
        try:
            # Fixed provider HTTPS endpoint from operator config, not attacker-controlled input.
            with urllib.request.urlopen(request, timeout=30) as response:  # nosemgrep
                payload = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            continue
        record = payload.get("data") if isinstance(payload, dict) else None
        cost = _finite_cost(record.get("total_cost")) if isinstance(record, dict) else None
        if cost is not None:
            return cost
    return None


def _http_error_detail(exc: urllib.error.HTTPError, api_key: str) -> tuple[str, str | None]:
    """Return bounded, allowlisted OpenRouter error detail without request data."""
    parts = [f"HTTP {exc.code} {exc.reason}"]
    generation_id = exc.headers.get("X-Generation-Id") if exc.headers is not None else None
    try:
        payload = json.loads(exc.read(16_384).decode("utf-8", errors="replace"))
    except (OSError, ValueError, json.JSONDecodeError):
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        code = error.get("code")
        if isinstance(code, str | int) and not isinstance(code, bool):
            parts.append(f"code={code}")
        message = error.get("message")
        if isinstance(message, str) and message:
            cleaned = " ".join(message.split()).replace(api_key, "[redacted]")[:300]
            parts.append(f"message={cleaned}")
        metadata = error.get("metadata")
        if isinstance(metadata, dict):
            for label, key in (
                ("error_type", "error_type"),
                ("provider_code", "provider_code"),
                ("provider", "provider_name"),
            ):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    parts.append(f"{label}={value[:100]}")
    if isinstance(generation_id, str) and generation_id:
        parts.append(f"generation_id={generation_id[:200]}")
    return "; ".join(parts), generation_id if isinstance(generation_id, str) and generation_id else None


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
        reasoning_enabled = os.environ.get("OPENROUTER_REASONING_ENABLED")
        reasoning_effort = os.environ.get("OPENROUTER_REASONING_EFFORT")
        reasoning_max = os.environ.get("OPENROUTER_REASONING_MAX_TOKENS")
        if reasoning_enabled is not None or reasoning_effort or reasoning_max:
            reasoning: dict[str, Any] = {}
            if reasoning_enabled is not None:
                reasoning["enabled"] = _boolean("OPENROUTER_REASONING_ENABLED", False)
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
                "X-OpenRouter-Metadata": "enabled",
            },
            method="POST",
        )
        # Fixed provider HTTPS endpoint from operator config, not attacker-controlled input.  # nosemgrep
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_generation_id = response.headers.get("X-Generation-Id") if hasattr(response, "headers") else None
            data = json.loads(response.read().decode())
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        raw_usage = data.get("usage") or {}
        generation_id = response_generation_id or data.get("id")
        cost = _finite_cost(raw_usage.get("cost"))
        if cost is None and isinstance(generation_id, str) and generation_id:
            cost = _generation_cost(base_url, api_key, generation_id)
        prompt_details = raw_usage.get("prompt_tokens_details") or {}
        completion_details = raw_usage.get("completion_tokens_details") or {}
        usage = make_usage(
            provider="openrouter",
            model=data.get("model", model),
            api_calls=1,
            input_tokens=raw_usage.get("prompt_tokens"),
            output_tokens=raw_usage.get("completion_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
            cost_usd=cost,
            api_latency_ms=latency_ms,
        )
        assert usage is not None
        choice = data["choices"][0]
        for key, value in {
            "upstream_provider": data.get("provider"),
            "generation_id": generation_id,
            "cached_input_tokens": prompt_details.get("cached_tokens"),
            "reasoning_tokens": completion_details.get("reasoning_tokens"),
            # Truncation auditability: the cap-pressure rule needs per-call
            # evidence that no response hit the frozen output ceiling.
            "finish_reason": choice.get("finish_reason"),
            "native_finish_reason": choice.get("native_finish_reason"),
        }.items():
            if value is not None:
                usage[key] = value
        if cost is None:
            usage["telemetry_error"] = "OpenRouter returned no authoritative finite generation cost"
        # Forwarded verbatim: the harness's published repair rules decide what
        # this text means. Unusable content is model protocol behavior, scored
        # as a malformed decision, and never a provider infrastructure failure.
        content = choice["message"]["content"]
        return content if isinstance(content, str) else json.dumps(content), usage
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        detail, generation_id = _http_error_detail(exc, api_key)
        cost = _generation_cost(base_url, api_key, generation_id) if generation_id is not None else None
        usage = make_usage(
            provider="openrouter",
            model=model,
            api_calls=1,
            cost_usd=cost,
            api_latency_ms=latency_ms,
        )
        assert usage is not None
        usage["telemetry_error"] = f"api_error: {detail}"
        if generation_id is not None:
            usage["generation_id"] = generation_id
        return fallback_actions(observation, f"api_error: {detail}"), usage
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        if usage is None:
            usage = make_usage(provider="openrouter", model=model, api_calls=1, api_latency_ms=latency_ms)
        return fallback_actions(observation, f"api_error: {exc}"), usage


def main() -> None:
    run_agent_main(choose_actions)


if __name__ == "__main__":
    main()
