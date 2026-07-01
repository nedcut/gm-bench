"""Ollama-backed external agent for GM-Bench.

Usage:
    OLLAMA_MODEL=gemma4:e4b python -m gm_bench run \
      --agent-cmd "python examples/ollama_agent.py" --agent-timeout 120 \
      --seeds 1 --seasons 1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

try:
    from gm_agent_common import build_prompt, fallback_actions, parse_actions, strip_terminal_codes
except ModuleNotFoundError:
    from examples.gm_agent_common import build_prompt, fallback_actions, parse_actions, strip_terminal_codes


def main() -> None:
    observation = json.load(sys.stdin)
    model = os.environ.get("OLLAMA_MODEL", "gemma4:e4b")
    os.environ.setdefault("GM_AGENT_PROFILE", "tiny")
    if model.lower().startswith("qwen"):
        os.environ.setdefault("GM_AGENT_NO_THINK", "1")
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    timeout = float(os.environ.get("OLLAMA_TIMEOUT", "120"))
    prompt = build_prompt(observation)
    try:
        if os.environ.get("OLLAMA_TRANSPORT", "cli") == "http":
            content = generate_http(host, model, prompt, timeout, use_json_mode=True)
        else:
            content = generate_cli(model, prompt, timeout)
        try:
            print(json.dumps(parse_actions(content)))
        except ValueError as exc:
            repair_prompt = (
                f"{prompt}\n\nYour previous answer was invalid: {str(content)[:300]!r}. "
                "Return exactly one JSON object with an actions array and no other text."
            )
            if os.environ.get("OLLAMA_TRANSPORT", "cli") == "http":
                repaired = generate_http(host, model, repair_prompt, timeout, use_json_mode=False)
            else:
                repaired = generate_cli(model, repair_prompt, timeout)
            try:
                print(json.dumps(parse_actions(repaired)))
            except ValueError:
                snippet = str(repaired or content).replace("\n", " ")[:220]
                print(json.dumps(fallback_actions(observation, f"ollama_parse_error: {exc}; content={snippet!r}")))
    except (
        subprocess.TimeoutExpired,
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps(fallback_actions(observation, f"ollama_error: {exc}")))


def generate_cli(model: str, prompt: str, timeout: float) -> str:
    completed = subprocess.run(
        ["ollama", "run", model, prompt],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr[-500:])
    return strip_terminal_codes(completed.stdout)


def generate_http(host: str, model: str, prompt: str, timeout: float, use_json_mode: bool) -> str:
    payload: dict[str, object] = {
        "model": model,
        "stream": False,
        "prompt": prompt,
        "options": {
            "temperature": float(os.environ.get("OLLAMA_TEMPERATURE", "0.2")),
            "num_predict": int(os.environ.get("OLLAMA_NUM_PREDICT", "512")),
        },
    }
    if use_json_mode:
        payload["format"] = "json"
    request = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return extract_ollama_content(data)


def extract_ollama_content(data: dict[str, object]) -> str:
    message = data.get("message")
    candidates: list[object] = []
    if isinstance(message, dict):
        candidates.extend([message.get("content"), message.get("response")])
    candidates.extend([data.get("response"), data.get("content")])
    if isinstance(message, dict):
        candidates.extend([message.get("thinking"), message.get("reasoning")])
    candidates.append(data.get("thinking"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return json.dumps(data)[:1000]


if __name__ == "__main__":
    main()
