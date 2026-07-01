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
from typing import Any

try:
    from gm_agent_common import build_prompt, fallback_actions, parse_actions
except ModuleNotFoundError:
    from examples.gm_agent_common import build_prompt, fallback_actions, parse_actions


def main() -> None:
    observation = json.load(sys.stdin)
    model = os.environ.get("OPENCODE_MODEL", "opencode/deepseek-v4-flash-free")
    timeout = float(os.environ.get("OPENCODE_TIMEOUT", "180"))
    command = ["opencode", "run", "--model", model, "--format", "json", "--pure", build_prompt(observation)]
    try:
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        if completed.returncode != 0:
            print(json.dumps(fallback_actions(observation, f"opencode_exit_{completed.returncode}: {completed.stderr[-300:]}")))
            return
        content = extract_opencode_text(completed.stdout)
        print(json.dumps(parse_actions(content)))
    except (subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps(fallback_actions(observation, f"opencode_error: {exc}")))


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


if __name__ == "__main__":
    main()
