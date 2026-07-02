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
import urllib.error
import urllib.request
from typing import Any

try:
    from gm_agent_common import build_prompt, fallback_actions, parse_actions, run_agent_main
except ModuleNotFoundError:
    from examples.gm_agent_common import build_prompt, fallback_actions, parse_actions, run_agent_main


def choose_actions(observation: dict[str, Any]) -> list[dict[str, Any]]:
    if observation.get("phase") == "action_results":
        return [{"type": "end_turn"}]
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("LLM_MODEL", "gpt-4.1-mini")
    base_url = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1").rstrip("/")
    timeout = float(os.environ.get("LLM_TIMEOUT", "120"))
    if not api_key:
        return fallback_actions(observation, "missing LLM_API_KEY or OPENAI_API_KEY")

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
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return parse_actions(content)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return fallback_actions(observation, f"api_error: {exc}")


def main() -> None:
    run_agent_main(choose_actions)


if __name__ == "__main__":
    main()
