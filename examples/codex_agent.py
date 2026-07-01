"""Codex CLI-backed external agent for GM-Bench.

This adapter calls `codex exec` once per benchmark decision point and expects
Codex to return a JSON object with an `actions` array.

Example:
    CODEX_MODEL=gpt-5-mini python -m gm_bench run \
      --agent-cmd "python examples/codex_agent.py" \
      --agent-timeout 180 --seeds 1 --seasons 1 --json

Local OSS/Ollama mode:
    CODEX_OSS=1 CODEX_LOCAL_PROVIDER=ollama CODEX_MODEL=gemma4:e4b python -m gm_bench run \
      --agent-cmd "python examples/codex_agent.py" \
      --agent-timeout 240 --seeds 1 --seasons 1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from gm_agent_common import build_prompt, fallback_actions, parse_actions
except ModuleNotFoundError:
    from examples.gm_agent_common import build_prompt, fallback_actions, parse_actions


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "gm_actions.schema.json"


def main() -> None:
    observation = json.load(sys.stdin)
    os.environ.setdefault("GM_AGENT_PROFILE", "tiny")
    timeout = float(os.environ.get("CODEX_AGENT_TIMEOUT", "180"))
    command = build_command()
    prompt = (
        "You are competing in GM-Bench as a sports general manager. "
        "Do not inspect or edit files. Do not run shell commands. "
        "Use only the observation in the prompt. "
        "Your final answer must be valid JSON matching the provided schema.\n\n"
        + build_prompt(observation)
    )
    try:
        with tempfile.NamedTemporaryFile("r", suffix=".json", delete=True) as output:
            completed = subprocess.run(
                [*command, "--output-last-message", output.name, prompt],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                cwd=ROOT,
            )
            content = output.read() or completed.stdout
        if completed.returncode != 0:
            print(json.dumps(fallback_actions(observation, f"codex_exit_{completed.returncode}: {completed.stderr[-300:]}")))
            return
        print(json.dumps(parse_actions(content)))
    except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps(fallback_actions(observation, f"codex_error: {exc}")))


def build_command() -> list[str]:
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--output-schema",
        str(SCHEMA),
        "--color",
        "never",
        "--cd",
        str(ROOT),
    ]
    model = os.environ.get("CODEX_MODEL")
    if model:
        command.extend(["--model", model])
    effort = os.environ.get("CODEX_EFFORT")
    if effort:
        command.extend(["--config", f'model_reasoning_effort="{effort}"'])
    if os.environ.get("CODEX_OSS") == "1":
        command.append("--oss")
    local_provider = os.environ.get("CODEX_LOCAL_PROVIDER")
    if local_provider:
        command.extend(["--local-provider", local_provider])
    return command


if __name__ == "__main__":
    main()
