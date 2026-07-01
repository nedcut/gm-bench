"""Claude Code-backed external agent for GM-Bench.

This adapter calls `claude -p` once per benchmark decision point and expects
Claude to return a JSON object with an `actions` array.

Example:
    CLAUDE_MODEL=sonnet python -m gm_bench run \
      --agent-cmd "python examples/claude_agent.py" \
      --agent-timeout 180 --seeds 1 --seasons 1 --json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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
    timeout = float(os.environ.get("CLAUDE_AGENT_TIMEOUT", "180"))
    prompt = (
        "You are competing in GM-Bench as a sports general manager. "
        "Do not inspect or edit files. Do not run shell commands. "
        "Use only the observation in the prompt. "
        "Return only JSON matching the schema.\n\n" + build_prompt(observation)
    )
    command = build_command(prompt)
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            cwd=ROOT,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout)[-500:]
            print(json.dumps(fallback_actions(observation, f"claude_exit_{completed.returncode}: {detail}")))
            return
        print(json.dumps(parse_actions(extract_claude_text(completed.stdout))))
    except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps(fallback_actions(observation, f"claude_error: {exc}")))


def build_command(prompt: str) -> list[str]:
    command = [
        "claude",
        "-p",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--output-format",
        "text",
        "--json-schema",
        SCHEMA.read_text(),
    ]
    model = os.environ.get("CLAUDE_MODEL")
    if model:
        command.extend(["--model", model])
    effort = os.environ.get("CLAUDE_EFFORT")
    if effort:
        command.extend(["--effort", effort])
    max_budget = os.environ.get("CLAUDE_MAX_BUDGET_USD")
    if max_budget:
        command.extend(["--max-budget-usd", max_budget])
    command.append(prompt)
    return command


def extract_claude_text(stdout: str) -> str:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout
    if isinstance(payload, dict):
        for key in ("result", "content", "message", "text"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return stdout


if __name__ == "__main__":
    main()
