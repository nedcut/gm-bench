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
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from gm_agent_common import build_prompt, emit, fallback_actions, make_usage, parse_actions, resolve_call_timeout
except ModuleNotFoundError:
    from examples.gm_agent_common import (
        build_prompt,
        emit,
        fallback_actions,
        make_usage,
        parse_actions,
        resolve_call_timeout,
    )


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "gm_actions.schema.json"
DEFAULT_MODEL = "gpt-5-mini"


def main() -> None:
    observation = json.load(sys.stdin)
    os.environ.setdefault("GM_AGENT_PROFILE", "tiny")
    timeout = resolve_call_timeout("CODEX_AGENT_TIMEOUT", 180.0)
    prompt = (
        "You are competing in GM-Bench as a sports general manager. "
        "Do not inspect or edit files. Do not run shell commands. "
        "Use only the observation in the prompt. "
        "Your final answer must be valid JSON matching the provided schema.\n\n" + build_prompt(observation)
    )
    model = os.environ.get("CODEX_MODEL", DEFAULT_MODEL)
    started = time.perf_counter()
    try:
        # Codex can read files (read-only sandbox); run it in a throwaway
        # directory with no line of sight to this repo so it cannot open
        # gm_bench/simulator.py and recompute the hidden partner/FA valuations
        # from the seed. build_command already points --cd at the scratch dir.
        with tempfile.TemporaryDirectory() as scratch:
            scratch_schema = Path(scratch) / SCHEMA.name
            shutil.copy2(SCHEMA, scratch_schema)
            command = build_command(scratch, schema_path=scratch_schema)
            with tempfile.NamedTemporaryFile("r", suffix=".json", delete=True, dir=scratch) as output:
                completed = subprocess.run(
                    [*command, "--json", "--output-last-message", output.name, prompt],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    check=False,
                    cwd=scratch,
                )
                content = output.read() or last_agent_message(completed.stdout)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        input_tokens, output_tokens = extract_token_usage(completed.stdout)
        usage = make_usage(
            provider="codex",
            model=model,
            api_calls=1,
            api_latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        if completed.returncode != 0:
            emit(
                fallback_actions(observation, f"codex_exit_{completed.returncode}: {completed.stderr[-300:]}"),
                usage,
            )
            return
        emit(parse_actions(content), usage)
    except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        emit(
            fallback_actions(observation, f"codex_error: {exc}"),
            make_usage(provider="codex", model=model, api_calls=1, api_latency_ms=latency_ms),
        )


def extract_token_usage(stdout: str) -> tuple[int | None, int | None]:
    """Sum token usage from `codex exec --json` turn.completed events.

    Codex reports reasoning_output_tokens as a subset of output_tokens (same
    convention as the OpenAI Responses API), so output_tokens is used as-is.
    Returns (None, None) when no usage event is present, so unmeasured stays
    distinct from zero.
    """
    input_tokens: int | None = None
    output_tokens: int | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        if isinstance(usage.get("input_tokens"), (int, float)):
            input_tokens = (input_tokens or 0) + int(usage["input_tokens"])
        if isinstance(usage.get("output_tokens"), (int, float)):
            output_tokens = (output_tokens or 0) + int(usage["output_tokens"])
    return input_tokens, output_tokens


def last_agent_message(stdout: str) -> str:
    """Fallback content path: pull the final agent message from --json events."""
    text = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text") or text
    return text or stdout


def build_command(
    cwd: str | os.PathLike[str] | None = None, schema_path: str | os.PathLike[str] | None = None
) -> list[str]:
    schema = Path(schema_path) if schema_path is not None else Path(cwd) / SCHEMA.name if cwd is not None else SCHEMA
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
        str(schema),
        "--color",
        "never",
    ]
    # Point Codex at a throwaway working directory so it cannot browse this
    # repo's source (the simulator that computes the "hidden" valuations).
    if cwd is not None:
        command.extend(["--cd", str(cwd)])
    model = os.environ.get("CODEX_MODEL", DEFAULT_MODEL)
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
