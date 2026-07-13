"""OpenAI-compatible chat-completions external agent for GM-Bench.

Set:
    OPENAI_API_KEY
    OPENAI_MODEL

Optional:
    OPENAI_API_BASE=https://api.openai.com/v1
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


# Session mode (GM_BENCH_SESSION=1) keeps this process alive for a whole
# episode, so the conversation accumulates across decision points: the model
# sees its full trajectory instead of relying on the memo action. The process
# is per-episode (the runner clones and restarts it per seed), so module
# state needs no reset.
SESSION_MODE = os.environ.get("GM_BENCH_SESSION") == "1"
_SYSTEM_MESSAGE = {
    "role": "system",
    "content": "Return only a JSON object with an actions array of GM-Bench action objects.",
}
_history: list[dict[str, str]] = []


def choose_actions(
    observation: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if observation.get("phase") == "action_results" and not SESSION_MODE:
        return [{"type": "end_turn"}], None
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    model = os.environ.get("OPENAI_MODEL") or os.environ.get("LLM_MODEL", "gpt-5.4-mini")
    base_url = os.environ.get("OPENAI_API_BASE") or os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
    base_url = base_url.rstrip("/")
    timeout = resolve_call_timeout("OPENAI_TIMEOUT", 120.0)
    if not api_key:
        return fallback_actions(observation, "missing OPENAI_API_KEY"), None

    if observation.get("phase") == "action_results":
        user_content = (
            "Results of your previous actions:\n"
            + json.dumps(observation.get("action_results", []), sort_keys=True)
            + "\nReply with a JSON object with an actions array; use end_turn to stop this window."
        )
    else:
        user_content = build_prompt(observation)
    messages = [_SYSTEM_MESSAGE, *(_history if SESSION_MODE else []), {"role": "user", "content": user_content}]
    started = time.perf_counter()
    try:
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if os.environ.get("OPENAI_JSON_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}:
            payload["response_format"] = {"type": "json_object"}
        temperature = os.environ.get("OPENAI_TEMPERATURE") or os.environ.get("LLM_TEMPERATURE")
        if temperature is not None:
            payload["temperature"] = float(temperature)
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        raw_usage = data.get("usage") or {}
        prompt_details = raw_usage.get("prompt_tokens_details") or {}
        completion_details = raw_usage.get("completion_tokens_details") or {}
        usage = make_usage(
            provider="openai",
            model=data.get("model", model),
            api_calls=1,
            input_tokens=raw_usage.get("prompt_tokens"),
            output_tokens=raw_usage.get("completion_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
            api_latency_ms=latency_ms,
        )
        assert usage is not None
        if prompt_details.get("cached_tokens") is not None:
            usage["cached_input_tokens"] = prompt_details["cached_tokens"]
        if completion_details.get("reasoning_tokens") is not None:
            usage["reasoning_tokens"] = completion_details["reasoning_tokens"]
        content = data["choices"][0]["message"]["content"]
        if SESSION_MODE:
            # Only successful exchanges enter the history so a transient API
            # failure does not leave a dangling unanswered user turn.
            _history.append({"role": "user", "content": user_content})
            _history.append({"role": "assistant", "content": content})
        return parse_actions(content), usage
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        usage = make_usage(provider="openai", model=model, api_calls=1, api_latency_ms=latency_ms)
        return fallback_actions(observation, f"api_error: {exc}"), usage


def main() -> None:
    run_agent_main(choose_actions)


if __name__ == "__main__":
    main()
