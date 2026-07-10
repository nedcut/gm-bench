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
import tempfile
import time
from pathlib import Path
from typing import Any

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


def main() -> None:
    observation = json.load(sys.stdin)
    os.environ.setdefault("GM_AGENT_PROFILE", "tiny")
    timeout = resolve_call_timeout("CLAUDE_AGENT_TIMEOUT", 180.0)
    model = os.environ.get("CLAUDE_MODEL")
    prompt = (
        "You are competing in GM-Bench as a sports general manager. "
        "Do not inspect or edit files. Do not run shell commands. "
        "Use only the observation in the prompt. "
        "Return only JSON matching the schema.\n\n" + build_prompt(observation)
    )
    command = build_command(prompt)
    started = time.perf_counter()
    try:
        # Run from a throwaway directory: with cwd at the repo root the CLI
        # auto-injects project context (CLAUDE.md/AGENTS.md) into every call,
        # leaking benchmark-adjacent text into the model's context and paying
        # for it on every decision. Mirrors the codex adapter's isolation.
        with tempfile.TemporaryDirectory() as scratch:
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                cwd=scratch,
            )
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout)[-500:]
            emit(
                fallback_actions(observation, f"claude_exit_{completed.returncode}: {detail}"),
                make_usage(provider="claude", model=model, api_calls=1, api_latency_ms=latency_ms),
            )
            return
        text, usage = extract_claude_result(completed.stdout, model, latency_ms)
        emit(parse_actions(text), usage)
    except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        emit(
            fallback_actions(observation, f"claude_error: {exc}"),
            make_usage(provider="claude", model=model, api_calls=1, api_latency_ms=latency_ms),
        )


def schema_for_cli() -> str:
    """Return the action schema without its $schema declaration.

    The Claude CLI's structured-output validator cannot resolve the
    draft/2020-12 meta-schema reference and rejects the file wholesale;
    stripping the declaration leaves the constraints intact.
    """
    schema = json.loads(SCHEMA.read_text())
    schema.pop("$schema", None)
    return json.dumps(schema)


def build_command(prompt: str) -> list[str]:
    command = [
        "claude",
        "-p",
        # Safe mode drops CLAUDE.md, skills, plugins, hooks, and MCP servers
        # from the call: no user/project customization can leak into the
        # benchmark context, and the per-decision token overhead shrinks.
        "--safe-mode",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        # JSON output carries usage and total_cost_usd alongside the result
        # text, which is what makes the CLI lane priceable on the leaderboard.
        "--output-format",
        "json",
        "--json-schema",
        schema_for_cli(),
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


def extract_claude_result(stdout: str, model: str | None, wall_latency_ms: float) -> tuple[str, dict[str, Any] | None]:
    """Pull the result text plus usage/cost from `claude -p --output-format json`."""
    fallback_usage = make_usage(provider="claude", model=model, api_calls=1, api_latency_ms=wall_latency_ms)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout, fallback_usage
    if not isinstance(payload, dict):
        return stdout, fallback_usage

    text = stdout
    for key in ("result", "content", "message", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value
            break

    raw_usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    input_tokens = None
    if raw_usage:
        # Cache reads/writes are still context the model processed; fold them
        # into input so token counts are comparable across providers. Cost
        # comes from the CLI's own total_cost_usd, which already prices cache
        # traffic at its discounted rates.
        parts = [
            raw_usage.get("input_tokens"),
            raw_usage.get("cache_creation_input_tokens"),
            raw_usage.get("cache_read_input_tokens"),
        ]
        numeric = [part for part in parts if isinstance(part, (int, float))]
        input_tokens = int(sum(numeric)) if numeric else None
    cost = payload.get("total_cost_usd")
    api_latency = payload.get("duration_api_ms") or payload.get("duration_ms")
    usage = make_usage(
        provider="claude",
        model=payload.get("model") if isinstance(payload.get("model"), str) else model,
        api_calls=1,
        input_tokens=input_tokens,
        output_tokens=raw_usage.get("output_tokens") if isinstance(raw_usage.get("output_tokens"), int) else None,
        api_latency_ms=float(api_latency) if isinstance(api_latency, (int, float)) else wall_latency_ms,
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
    )
    return text, usage or fallback_usage


if __name__ == "__main__":
    main()
