"""Cursor CLI harness driver for GM-Bench 2.0 (``gm-bench agentic --harness cursor``).

The episode loop is the one every harness shares (``opencode.run_episode``:
engine and socket server in this process, sandbox check, nudges, provider
stall retries, the phase-guard watch, finalization). This module supplies
only what is specific to the Cursor CLI (``cursor-agent``), as a
:class:`CursorDriver`.

What the driver relies on, checked against Cursor CLI 2026.09.26-dd393fe
(``cursor-agent --version`` prints the bare version; ``cursor-agent --help``;
the bundled JavaScript under ``~/.local/share/cursor-agent/versions/``; and
live probes on composer-2.5 on 2026-09-27):

- **Non-interactive run.** ``cursor-agent -p --output-format stream-json
  [OPTIONS] <prompt>`` runs one query and prints one JSON object per line on
  stdout. ``--trust`` trusts the scratch directory without a prompt,
  ``--force`` runs every tool call without asking, ``--approve-mcps``
  approves the configured MCP server, and ``--sandbox disabled`` keeps the
  shell unsandboxed whatever a config says (same-user rows are smoke grade
  whatever the harness sandbox does). ``--model`` picks the model. Cursor
  names reasoning effort inside the model id (``gpt-5.6-sol-high``), so
  ``--variant`` is refused rather than mapped.
- **Events.** ``system``/``init`` (``session_id``, ``model``,
  ``apiKeySource``, ``permissionMode``); ``user``; ``thinking`` deltas;
  ``assistant`` (``message.content`` text); ``tool_call`` with ``subtype``
  ``started`` or ``completed``, a ``call_id``, and ``tool_call`` holding one
  ``<kind>ToolCall`` key (``shellToolCall``, ``readToolCall``, ...); and
  ``result`` (``is_error``, ``result``, ``session_id``, ``duration_ms``,
  ``usage``: ``inputTokens`` uncached, ``cacheReadTokens``,
  ``cacheWriteTokens``, ``outputTokens``). A GM-Bench call is an
  ``mcpToolCall`` whose ``args`` carry ``serverIdentifier`` (``gm-bench``)
  and ``toolName``; it is recorded as ``gm-bench_<tool>`` so the
  ledger-versus-harness agreement counts it. ``getMcpToolsToolCall`` is
  Cursor reading a tool's schema from its own cache; it never reaches the
  server and is recorded as ``get_mcp_tools``. Tool events are counted once
  per ``call_id``, from ``started`` as well as ``completed``, so a call cut
  off by a guard stop still counts.
- **Usage is per invocation.** A resumed session's ``result.usage`` covers
  only that process (checked: a resume reported 193 uncached input tokens
  after a first run's 5,114), so the episode total is the sum of every
  result. An invocation that was killed writes no result, and its tokens are
  lost: ``usage_complete`` is then false and the totals are a lower bound.
  The stream has no per-request records and no cost, so ``api_calls``
  counts completed invocations (turns), ``max_output_tokens_per_call`` is
  left out, compactions are ``None`` (unmeasured), and ``cost_usd`` is
  ``None``. The API-equivalent estimate sits beside it exactly as for Codex,
  and is ``None`` for a model ``pricing.json`` does not price (Cursor's own
  Composer models have no published per-token list price there).
- **Resume.** ``cursor-agent -p --resume <session id> ... <text>`` continues
  the chat with its context (checked live). Chats live under
  ``CURSOR_CONFIG_DIR/chats``, which is private to the episode.
- **Errors, provider stalls and usage limits.** A failed run prints its error
  as plain text on stderr and exits non-zero, with no ``result`` event (for
  example ``Cannot use this model: ...``). The driver notes the stderr size
  before every invocation (:meth:`CursorDriver.before_invocation`) and reads
  what that invocation added. It is a provider stall when that text (or a
  failed ``result``) reads as a transient failure: a 408, 425, 429 or 5xx,
  ``resource_exhausted``, ``unavailable``, a rate limit, an overload, a
  timeout, or a dropped connection. It is quota exhaustion when it reads as
  a spent plan allowance (``usage limit``, ``hit your ... limit``, ``spend
  limit``); Cursor states no reset time, so the shared loop stops the
  episode and the panel. Neither message has been seen live; the patterns
  are the CLI's gRPC status names and the other drivers' wording.
- **Configuration and what is not inherited.** Cursor reads its login from
  the macOS Keychain (or a file store), ``cli-config.json`` and chats from
  ``CURSOR_CONFIG_DIR`` (default ``~/.cursor``), projects, transcripts and
  terminals from ``CURSOR_DATA_DIR`` (default ``~/.cursor``), and user-level
  ``mcp.json``, rules, skills, hooks and agents from ``$HOME/.cursor``. The
  driver never uses the host's: ``HOME``, ``CURSOR_CONFIG_DIR`` and
  ``CURSOR_DATA_DIR`` are three directories inside one private directory
  (mode 0700) outside the scratch, removed when the episode ends;
  ``AGENT_CLI_CREDENTIAL_STORE=memory`` keeps the Keychain out of it;
  ``DIRENV_DISABLE=1`` stops Cursor loading an ``.envrc`` above the
  scratch; and every other ``CURSOR_*`` variable is dropped. The one MCP
  server is ``$HOME/.cursor/mcp.json``: ``gm-bench``, whose ``command`` is
  the harness's python3 and whose ``args`` are the proxy (by absolute path)
  and the socket path, the same launch ``opencode_config`` declares. Cursor
  writes its bundled skills to ``$HOME/.cursor/skills-cursor`` on every
  start; those are part of the harness, like Codex's and OpenCode's
  built-in tools.
- **The config directories between invocations.** The agent's shell runs as
  the same user, so between invocations it could add a project
  ``.cursor/`` (``mcp.json``, rules, hooks, permissions) or ``.cursorrules``
  to the scratch, or hooks, rules, skills, agents or commands to
  ``$HOME/.cursor``, and the next resume would load them. Before every
  invocation the driver removes those entries (:data:`HOME_CONFIG_ENTRIES`,
  :data:`SCRATCH_CONFIG_ENTRIES`), rewrites ``mcp.json``, and records what it
  found as ``harness_run.config_dir_findings``. In a container the image's
  launcher ``gmb-cursor`` does the same inside each invocation's fresh
  container, before it execs the CLI (below).
- **What reaches the prompt.** Cursor's servers add the account's
  cloud-synced User Rules to every prompt; the CLI never fetches them (it has
  no such request) and has no flag or setting to leave them out. So the
  driver proves the prompt instead. Cursor keeps each chat's context message
  in ``CURSOR_CONFIG_DIR/chats/*/*/store.db``; :func:`prompt_audit` lists
  its outermost sections and flags any outside :data:`HARNESS_SECTIONS`
  (User Rules, workspace rules, cloud instructions, memories, anything new),
  recording names and counts, never text, as ``harness_run.prompt_audit``.
  The servers also send seven rules of their own in the User Rules slot to
  every account, which the account cannot see or remove; those
  (:data:`CURSOR_DEFAULT_RULES`, matched by digest) count as the harness's
  only when the rules slot has exactly Cursor's recorded shape; any other
  shape is refused, never parsed leniently.
  The pre-panel prompt check (:meth:`CursorDriver.check_prompt`, on from the
  CLI) makes one one-word ``--mode ask`` call in a throwaway workspace with
  an episode's private directories and credential (but no MCP server;
  :func:`probe_prompt`) and refuses the panel if that prompt carries
  anything unexpected or any of the operator's own content; ``agentic-validate`` and the
  published-row check refuse a Cursor episode whose audit is missing or not
  clean (:func:`prompt_audit_problems`), whatever its isolation.
- **Authentication.** ``--cursor-token-file <path>`` holds one token: a
  Cursor API key (handed over as ``CURSOR_API_KEY``) or a session token, a
  JWT (three dot-separated parts, handed over as ``CURSOR_AUTH_TOKEN``);
  without the file, ``CURSOR_API_KEY`` or else ``CURSOR_AUTH_TOKEN`` from the
  operator's environment. The value sits in the harness's environment, which
  the agent's shell inherits and can print: that is the harness's key, not
  the benchmark's. When the episode ends the driver replaces it with
  ``[REDACTED]`` in ``cursor-events.jsonl`` and ``cursor-stderr.log``.
- **Container isolation** runs Cursor CLI 2026.09.26-dd393fe from its own
  pinned image (``container.CURSOR_IMAGE``: the release tarball for the build
  architecture, checked against its SHA-256 and unpacked root-owned under
  ``/opt/cursor-agent``, on the shared digest-pinned base with the egress
  firewall entrypoint, the unprivileged ``node`` user and Debian's python3
  for the proxy), with the same flags as same-user runs. The run records
  the image (tag, id, Dockerfile SHA-256, base image, the ``cursor_version``
  the image reports) under ``harness.container``, so a container row can be
  panel grade. It needs ``--cursor-token-file``: the container gets no
  environment, so the token travels on the stdin of a throwaway ``docker
  run`` into the episode's home volume (``ContainerHarness.seed_home``,
  ``/home/node/.gmb-cursor-token``, mode 0600, with the variable
  :func:`token_env` picks), never onto a command line, into a ``docker run
  -e`` variable, or into the bind-mounted scratch, and is removed with the
  volume. The staged ``mcp.json`` (the proxy under ``/work`` on the
  container's python3) is seeded the same way. Every invocation starts in
  the image's launcher ``gmb-cursor`` (``container.CURSOR_WRAPPER``), with
  the ``mcp.json`` text as its first argument. In that fresh container, where
  nothing the agent started in an earlier invocation still runs, it removes
  the same home and scratch entries the same-user guard does, restores
  ``mcp.json``, sets ``HOME``, ``CURSOR_CONFIG_DIR`` and ``CURSOR_DATA_DIR``
  to three directories of the volume, ``AGENT_CLI_CREDENTIAL_STORE=memory``
  and ``DIRENV_DISABLE=1``, exports the token, and execs the pinned CLI. It
  reports each removal on stderr, where the driver collects it into
  ``config_dir_findings``, and refuses to start the CLI (exit 96,
  ``gmb-cursor: refused:``) when one of those directories is a symlink or
  not a directory, an entry cannot be removed, or the token is missing.
  Cursor itself writes ``$HOME/.cursor`` on every start, so a read-only
  root-owned layout like Claude's cannot hold it. The prompt audit reads the
  chat stores out of the volume (``ContainerHarness.home_tree``) before the
  volume is removed, and gates publication exactly as it does same-user:
  Cursor's servers add the account's User Rules whatever the isolation. For
  the same reason the pre-panel prompt check runs for a container panel too,
  in the image (``probe_prompt`` with ``image``), where every other harness's
  container panel is recorded as not checked: a panel that would carry
  account rules is refused before its first episode, not found out after
  it.

Every Cursor run spends the operator's Cursor plan, and the driver runs
episodes serially: never run it in parallel.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from gm_bench.agentic import opencode
from gm_bench.agentic.codex import REDACTED, api_equivalent_fields, redact_file
from gm_bench.agentic.container import (
    CURSOR_CONFIG_DIR,
    CURSOR_HOME_ENTRIES,
    CURSOR_IMAGE,
    CURSOR_SCRATCH_ENTRIES,
    CURSOR_TOKEN_FILENAME,
    CURSOR_USER_DIR,
    CURSOR_WRAPPER_PATH,
    CURSOR_WRAPPER_PREFIX,
    ContainerHarness,
    ensure_image,
)
from gm_bench.agentic.harness import HarnessDriver
from gm_bench.agentic.opencode import PROXY_FILENAME, HarnessLaunch, stage_proxy
from gm_bench.agentic.prompt_check import OperatorMarkers, PromptCheckError, operator_content, operator_markers

HARNESS_NAME = "cursor"
MCP_SERVER_NAME = "gm-bench"
MCP_CONFIG_FILENAME = "mcp.json"
API_KEY_ENV = "CURSOR_API_KEY"
AUTH_TOKEN_ENV = "CURSOR_AUTH_TOKEN"
# No Keychain read or write, and no ``.envrc`` from above the scratch.
HARNESS_ENV = {"AGENT_CLI_CREDENTIAL_STORE": "memory", "DIRENV_DISABLE": "1"}
SANDBOX = "disabled"
# The private directory's layout: HOME, CURSOR_CONFIG_DIR, CURSOR_DATA_DIR.
_HOME, _CONFIG, _DATA = "home", "config", "data"
# What Cursor loads from ``$HOME/.cursor`` as configuration or instructions, besides mcp.json,
# and from the workspace; the same lists the container launcher clears.
HOME_CONFIG_ENTRIES = CURSOR_HOME_ENTRIES
SCRATCH_CONFIG_ENTRIES = CURSOR_SCRATCH_ENTRIES
CONFIG_DIR_GUARD = {
    "same-user": "home and project config entries removed and mcp.json rewritten before every invocation",
    "container": f"home and project config entries removed and mcp.json rewritten by {CURSOR_WRAPPER_PATH} "
    "inside every invocation's container",
}

# A failed run's text that reads as a transient provider failure.
_RETRYABLE_MESSAGE_RE = re.compile(
    r"rate[ _-]?limit|too many requests|resource[ _]exhausted|\b(?:408|425|429|500|502|503|504|529)\b"
    r"|overloaded|unavailable|high demand|at capacity|timed? ?out|deadline[ _]exceeded"
    r"|connection (?:error|reset|refused|closed|lost)|econnreset|network error|stream (?:closed|disconnected)",
    re.IGNORECASE,
)
# A spent plan allowance: never a stall, and Cursor states no reset time.
USAGE_LIMIT_RE = re.compile(
    r"usage limit|you(?:'|’)ve hit your\b[^.\n]*\blimit|spend(?:ing)? limit|out of (?:fast )?requests", re.IGNORECASE
)


# -- version and configuration ------------------------------------------------


def cursor_version(binary: str = "cursor-agent") -> str | None:
    """The version ``cursor-agent --version`` prints (``2026.09.26-dd393fe``)."""
    try:
        completed = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (completed.stdout or completed.stderr).strip().splitlines()
    return lines[-1].strip() if lines else None


def mcp_config(workdir: str | Path, target: str | Path, *, python: str = "python3") -> dict[str, Any]:
    """The staged ``$HOME/.cursor/mcp.json``: one stdio server, the proxy in the scratch, and nothing else."""
    server = {"command": python, "args": [str(Path(workdir) / PROXY_FILENAME), str(target)]}
    return {"mcpServers": {MCP_SERVER_NAME: server}}


def read_token_file(path: str | Path) -> str:
    """The operator's Cursor API key or session token, checked for shape without echoing any of it."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError(f"--cursor-token-file {path} is not a file")
    try:
        token = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        raise ValueError(f"--cursor-token-file {path} is not text; expected one Cursor API key or token") from None
    if not token or any(character.isspace() for character in token):
        raise ValueError(f"--cursor-token-file {path} must hold exactly one Cursor API key or token on one line")
    return token


def token_env(token: str) -> str:
    """Where a token goes: a session token (a JWT) is ``CURSOR_AUTH_TOKEN``, anything else ``CURSOR_API_KEY``."""
    return AUTH_TOKEN_ENV if token.count(".") == 2 and token.startswith("ey") else API_KEY_ENV


# -- telemetry ----------------------------------------------------------------


def _events(lines: list[str]) -> list[dict[str, Any]]:
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _tool_name(call: Any) -> str | None:
    """``mcpToolCall`` on gm-bench -> ``gm-bench_<tool>``; ``shellToolCall`` -> ``shell``; ``getMcpToolsToolCall`` -> ``get_mcp_tools``."""
    if not isinstance(call, dict):
        return None
    kinds = [key for key in call if key.endswith("ToolCall")]
    if not kinds:
        return None
    kind = kinds[0]
    if kind == "mcpToolCall":
        args = call[kind].get("args") if isinstance(call[kind], dict) else None
        args = args if isinstance(args, dict) else {}
        server = args.get("serverIdentifier") or args.get("providerIdentifier") or "unknown"
        return f"{server}_{args.get('toolName') or 'unknown'}"
    stem = kind[: -len("ToolCall")]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", stem).lower() or "unknown"


def _rejected(call: Any) -> bool:
    """A completed call whose result says Cursor refused it before running it (it never reached a server)."""
    for value in call.values() if isinstance(call, dict) else ():
        result = value.get("result") if isinstance(value, dict) else None
        if isinstance(result, dict) and any("reject" in key.lower() or "denied" in key.lower() for key in result):
            return True
    return False


def parse_cursor_events(lines: list[str]) -> dict[str, Any]:
    """Fold ``cursor-agent -p --output-format stream-json`` output (every invocation of one episode) into telemetry.

    Same shape as ``opencode.parse_opencode_events``. Tokens are the sum of
    every ``result.usage`` (each covers one invocation); an invocation with
    no result adds none and marks the usage incomplete. ``model_calls``
    counts results with usage; ``model_steps`` the distinct
    ``model_call_id`` values on tool events (a lower bound on model requests).
    """
    session_id: str | None = None
    tool_calls: dict[str, str] = {}
    rejected: set[str] = set()
    steps: set[str] = set()
    event_types: dict[str, int] = {}
    totals = dict.fromkeys(("uncached", "cache_read", "cache_write", "output"), 0)
    results = without_result = errors = max_turn_input = 0
    invocation_open = False

    for event in _events(lines):
        kind = str(event.get("type", ""))
        subtype = event.get("subtype")
        label = f"{kind}/{subtype}" if kind in ("system", "tool_call") and subtype else kind
        event_types[label] = event_types.get(label, 0) + 1
        if kind == "system" and subtype == "init":
            without_result += int(invocation_open)
            invocation_open = True
            if isinstance(event.get("session_id"), str):
                session_id = event["session_id"]
        elif kind == "tool_call":
            call_id = event.get("call_id")
            name = _tool_name(event.get("tool_call"))
            if not call_id or name is None:
                continue
            if isinstance(event.get("model_call_id"), str):
                steps.add(event["model_call_id"])
            tool_calls[str(call_id)] = name
            if subtype == "completed" and _rejected(event.get("tool_call")):
                rejected.add(str(call_id))
        elif kind == "result":
            invocation_open = False
            if event.get("is_error"):
                errors += 1
            usage = event.get("usage")
            if not isinstance(usage, dict):
                continue
            results += 1
            turn = {
                "uncached": opencode._int(usage.get("inputTokens")),
                "cache_read": opencode._int(usage.get("cacheReadTokens")),
                "cache_write": opencode._int(usage.get("cacheWriteTokens")),
                "output": opencode._int(usage.get("outputTokens")),
            }
            for key, value in turn.items():
                totals[key] += value
            max_turn_input = max(max_turn_input, turn["uncached"] + turn["cache_read"] + turn["cache_write"])
    without_result += int(invocation_open)

    tool_events: dict[str, int] = {}
    skipped: dict[str, int] = {}
    for call_id, name in tool_calls.items():
        bucket = skipped if call_id in rejected else tool_events
        bucket[name] = bucket.get(name, 0) + 1

    return {
        "model_calls": results,
        "model_steps": len(steps),
        # The shared shape: input includes cache reads and writes.
        "input_tokens": totals["uncached"] + totals["cache_read"] + totals["cache_write"],
        "uncached_input_tokens": totals["uncached"],
        "output_tokens": totals["output"],
        # Not reported separately: output includes whatever reasoning the model did.
        "reasoning_tokens": 0,
        "cached_input_tokens": totals["cache_read"],
        "cache_write_tokens": totals["cache_write"],
        # The largest one-invocation input: an upper bound on any single request's input.
        "max_turn_input_tokens": max_turn_input,
        "max_output_tokens_per_call": None,
        "cost_usd": None,
        "harness_tool_events": dict(sorted(tool_events.items())),
        "harness_tool_calls_skipped": dict(sorted(skipped.items())),
        "compactions": None,
        "errors": errors,
        "session_id": session_id,
        "event_types": dict(sorted(event_types.items())),
        "invocations_with_result": results,
        "invocations_without_result": without_result,
        "usage_complete": without_result == 0,
    }


def _ending_text(lines: list[str], stderr: str) -> str | None:
    """What one invocation said on failing: a failed ``result``'s text, else its stderr; ``None`` if it succeeded."""
    events = _events(lines)
    results = [event for event in events if event.get("type") == "result"]
    if results:
        last = results[-1]
        return str(last.get("result") or "") + " " + stderr if last.get("is_error") else None
    return stderr.strip() or None


def quota_exhaustion(lines: list[str], stderr: str) -> dict[str, Any] | None:
    """``{"message_class": "usage_limit", "reset_at_utc": None}`` when the invocation ended on a spent allowance."""
    text = _ending_text(lines, stderr)
    if text is None or not USAGE_LIMIT_RE.search(text):
        return None
    return {"message_class": "usage_limit", "reset_at_utc": None}


def ended_in_provider_stall(lines: list[str], stderr: str) -> bool:
    """Whether one invocation failed on a transient provider error (never a usage limit)."""
    text = _ending_text(lines, stderr)
    if text is None or USAGE_LIMIT_RE.search(text):
        return False
    return bool(_RETRYABLE_MESSAGE_RE.search(text))


def usage_block(telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
    """The shared usage block, labelled for what the Cursor stream can and cannot report (as Codex's)."""
    usage = opencode.usage_block(telemetry, model=model, decisions=decisions, harness=HARNESS_NAME)
    usage["cost_usd"] = None
    usage["cost_decisions"] = 0
    usage["harness"].update(
        {
            "api_calls_are": "completed invocations (results); the stream has no per-request records",
            "model_steps": telemetry.get("model_steps", 0),
            "usage_complete": telemetry.get("usage_complete", True),
            "invocations_without_result": telemetry.get("invocations_without_result", 0),
            "cost_reported_by_harness": False,
            "tool_calls_skipped": telemetry.get("harness_tool_calls_skipped") or {},
            **api_equivalent_fields(telemetry, model),
        }
    )
    return usage


# The context sections Cursor itself adds to every prompt: environment facts, where its own
# transcripts live, its bundled skills, its dynamic tool namespaces, the MCP server's own
# instructions (ours), and workspace facts. Anything else (User Rules, workspace rules, cloud
# instructions, memories, an unknown section) came from outside the harness.
HARNESS_SECTIONS = frozenset(
    {
        "user_info",
        "agent_transcripts",
        "agent_skills",
        "dynamic_tools",
        "mcp_instructions",
        "project_layout",
        "git_status",
    }
)
# The User Rules Cursor's servers put in every account's prompt, by the SHA-256 of their stripped
# text. None appears in the account's Rules settings and they cannot be removed, so they are part
# of the harness. Recorded 2026-09-27 on cursor-agent 2026.09.26-dd393fe; a changed wording no
# longer matches and is refused like any other rule until it is reviewed and added here.
CURSOR_DEFAULT_RULES = {
    "9496d9d5bfea9732e466b0c8df8eeef83568d4ad16ab5b0457e35c55dfcab82f": "<committing-changes-with-git>",
    "4f776713eb215e255e1ff6e8e7c69f38f905fd97f1a0e89eb1d0eb8ccb31f444": "<creating-pull-requests>",
    "1f2c2198b1fa552463f85850e2e15fd0299407b0f579cb5ebe8a7873653285bc": "Follow ALL user, tool, system, and skill instructions",
    "4e1b31065d865dd99c504452e4ad79afd63bb2b8c8309a312a5dccdadac1e971": "IMPORTANT: This is a real environment",
    "881a46d23dedda90405a6cf4452bf11aa36ac1ada919ee4c8243f98e9f0fb6ef": "When communicating with the user:",
    "3d37d95b73104a0c134c9288e7f46980293d5aef6d51560b5afbb62fad51381e": "Reason about conversation history",
    "9f07ab247a8191d90790e85c9a503fe195d83913d0af612e992ab82ffe0d0ceb": "**Always follow these principles when writing code**",
}
PROBE_PROMPT = "Reply with the single word ok."


_SECTION_OPEN_RE = re.compile(r"<([a-z][a-z0-9_-]*)(?:\s[^>]*)?>")


def top_level_sections(text: str) -> list[str]:
    """The outermost ``<section>...</section>`` names in a context message, in order."""
    sections = []
    position = 0
    while (match := _SECTION_OPEN_RE.search(text, position)) is not None:
        close = text.find(f"</{match.group(1)}>", match.end())
        if close < 0:
            position = match.end()
            continue
        sections.append(match.group(1))
        position = close + len(match.group(1)) + 3
    return sections


def _context_messages(config_dir: Path) -> list[str]:
    """Every context message (a message carrying ``<user_info>``) in every chat store under ``config_dir/chats``.

    Cursor writes one per chat today; a resume that wrote another would be
    audited too. A message without ``<user_info>`` is the brief, a nudge or
    a tool result and is not treated as context.
    """
    found = []
    for store in sorted(config_dir.glob("chats/*/*/store.db")):
        try:
            connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
            try:
                rows = connection.execute("SELECT data FROM blobs").fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            continue
        for (data,) in rows:
            if not isinstance(data, bytes) or not data.startswith(b"{") or b"<user_info>" not in data:
                continue
            try:
                content = json.loads(data).get("content")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                continue
            if isinstance(content, str):
                found.append(content)
    return found


# The exact shape of Cursor's rules slot, recorded 2026-09-27 on cursor-agent 2026.09.26-dd393fe:
# ``<rules>``, this preamble, ``<user_rules description=...>``, then ``<user_rule>`` elements and
# nothing else. Anything that differs (attributes, text, another subsection, a stray rule tag) is
# not parsed leniently: the slot is counted as unrecognised and refused.
_RULES_PREAMBLE = (
    "The rules section has a number of possible rules/memories/context that you should consider. "
    "In each subsection, we provide instructions about what information the subsection contains "
    "and how you should consider/follow the contents of the subsection."
)
_USER_RULES_OPENERS = (
    '<user_rules description="These are rules set by the user that you should follow if appropriate.">',
    "<user_rules>",
)
_RULES_BLOCK_RE = re.compile(r"<rules>(.*?)</rules>", re.DOTALL)
_RULE_TAG_RE = re.compile(r"</?(?:rules|user_rules|user_rule)\b[^>]*>")
_USER_RULE_RE = re.compile(r"\s*<user_rule>(.*?)</user_rule>", re.DOTALL)
_ANY_USER_RULE_RE = re.compile(r"<user_rule(?:\s[^>]*)?>(.*?)</user_rule>", re.DOTALL)


def _parse_rules_block(body: str) -> list[str] | None:
    """The User Rules in one ``<rules>`` body of exactly Cursor's shape, or ``None`` for any other shape."""
    rest = body.strip()
    if rest.startswith(_RULES_PREAMBLE):
        rest = rest[len(_RULES_PREAMBLE) :].lstrip()
    opener = next((opener for opener in _USER_RULES_OPENERS if rest.startswith(opener)), None)
    if opener is None or not rest.endswith("</user_rules>"):
        return None
    rest = rest[len(opener) : -len("</user_rules>")]
    rules, position = [], 0
    while (match := _USER_RULE_RE.match(rest, position)) is not None:
        rules.append(match.group(1))
        position = match.end()
    return rules if not rest[position:].strip() else None


def _rules_slots(message: str) -> tuple[list[str], int]:
    """Every User Rule in the message, and how many rules slots or stray rule tags are not Cursor's exact shape.

    Rules are counted leniently (any ``<user_rule ...>`` anywhere) so an
    unrecognised shape still reports what it carried; only an exact shape
    can pass.
    """
    unrecognised = sum(_parse_rules_block(body) is None for body in _RULES_BLOCK_RE.findall(message))
    unrecognised += len(_RULE_TAG_RE.findall(_RULES_BLOCK_RE.sub("", message)))
    return _ANY_USER_RULE_RE.findall(message), unrecognised


def _rule_digest(rule: str) -> str:
    return hashlib.sha256(rule.strip().encode("utf-8")).hexdigest()


def prompt_audit(config_dir: Path, markers: OperatorMarkers | None = None) -> dict[str, Any] | None:
    """What Cursor put in the episode's prompt besides the brief; ``None`` when no chat store was readable.

    ``sections``: every outermost section of the context messages;
    ``unexpected``: those not in :data:`HARNESS_SECTIONS`, plus ``rules``
    unless every rules slot has exactly Cursor's shape and holds nothing but
    :data:`CURSOR_DEFAULT_RULES`; ``default_rules``: how many of those it
    held; ``user_rules`` and ``user_rule_characters``: every other User Rule;
    ``unrecognised_rules``: rules slots or rule tags in any other shape.
    Names and counts only, never text.
    """
    messages = _context_messages(config_dir)
    if not messages:
        return None
    sections = sorted({name for message in messages for name in top_level_sections(message)})
    slots = [_rules_slots(message) for message in messages]
    others = [[rule for rule in rules if _rule_digest(rule) not in CURSOR_DEFAULT_RULES] for rules, _ in slots]
    unrecognised = max(count for _, count in slots)
    rules_clean = unrecognised == 0 and not any(others)
    unexpected = {name for name in sections if name not in HARNESS_SECTIONS and name != "rules"}
    if not rules_clean:
        unexpected.add("rules")
    return {
        "sections": sections,
        "unexpected": sorted(unexpected),
        "default_rules": max(len(rules) - len(other) for (rules, _), other in zip(slots, others)),
        "user_rules": max(len(other) for other in others),
        "user_rule_characters": max(sum(len(rule) for rule in other) for other in others),
        "unrecognised_rules": unrecognised,
        "operator_content": operator_content(messages, operator_markers() if markers is None else markers),
    }


def prompt_audit_problems(harness_name: str | None, harness_run: dict[str, Any]) -> list[str]:
    """Why a Cursor episode's prompt cannot be trusted: no audit, or sections from outside the harness."""
    if harness_name != HARNESS_NAME:
        return []
    audit = harness_run.get("prompt_audit")
    if not isinstance(audit, dict):
        return ["no prompt audit: nothing shows the prompt held only the harness's own context"]
    problems = []
    if audit.get("unexpected") or audit.get("user_rules") or audit.get("unrecognised_rules"):
        unexpected = audit.get("unexpected") or ["rules"]
        problems.append(
            f"prompt carried context from outside the harness: {', '.join(unexpected)} "
            f"({audit.get('user_rules', 0)} User Rules that are not Cursor's defaults, "
            f"{audit.get('unrecognised_rules', 0)} rules slots in an unrecognised shape)"
        )
    problems += [f"prompt carried the operator's content: {found}" for found in audit.get("operator_content") or []]
    return problems


def volume_prompt_audit(harness: ContainerHarness) -> dict[str, Any] | None:
    """:func:`prompt_audit` of a container episode's chats, read out of its home volume before it is removed.

    The chat stores come back as a tar stream (``ContainerHarness.home_tree``).
    Only its regular files, by relative paths, are written, into a private
    temporary directory removed as soon as the audit has read them.
    """
    archive = harness.home_tree(f"{CURSOR_CONFIG_DIR}/chats")
    if archive is None:
        return None
    with tempfile.TemporaryDirectory(prefix="gmb-cursor-audit-") as directory:
        root = Path(directory)
        try:
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                for member in tar:
                    parts = PurePosixPath(member.name).parts
                    source = tar.extractfile(member) if member.isfile() else None
                    if source is None or member.name.startswith("/") or ".." in parts:
                        continue
                    target = root.joinpath(*parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read())
        except tarfile.TarError:
            return None
        return prompt_audit(root / CURSOR_CONFIG_DIR)


def probe_prompt(
    *,
    model: str,
    binary: str = "cursor-agent",
    token_file: str | Path | None = None,
    image: dict[str, Any] | None = None,
    docker: str = "docker",
) -> dict[str, Any]:
    """Ask Cursor for one word in a throwaway workspace and audit that prompt.

    The workspace gets an episode's private ``HOME`` and ``CURSOR_CONFIG_DIR``
    and its credential handling, but not the staged ``mcp.json``, ``--force``
    or ``--approve-mcps``: the call runs in ``--mode ask`` with no MCP
    server. That keeps it to one tiny model call on the operator's plan, enough for a panel to refuse to
    start before it spends an episode on a prompt that carries someone's
    rules; each episode's own prompt is audited again when it ends. With
    ``image`` the call runs in that harness image, exactly as a container
    episode's invocations do, with its own home volume; the one host port the
    egress rule leaves open is a listener that never answers.
    Raises ``ValueError`` when the call fails or leaves no readable chat.
    """
    driver = CursorDriver(token_file=token_file)
    scratch = Path(tempfile.mkdtemp(prefix="gmb-cursor-probe-"))
    harness: ContainerHarness | None = None
    listener: socket.socket | None = None
    try:
        env = driver.environment(opencode.harness_environment(), scratch, "same-user" if image is None else "container")
        options = ["-p", "--output-format", "stream-json", "--trust", "--mode", "ask", "--model", model, PROBE_PROMPT]
        name = None
        if image is None:
            argv = [binary, *options]
        else:
            listener = socket.create_server(("127.0.0.1", 0))
            harness = ContainerHarness(image, scratch, driver_port=listener.getsockname()[1], docker=docker, env=env)
            harness.seed_home(driver._home_files(None))
            # An empty mcp.json argument: the launcher leaves no MCP server configured.
            argv, name = harness.command([CURSOR_WRAPPER_PATH, "", *options])
        try:
            completed = subprocess.run(
                argv, cwd=scratch, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            if harness is not None and name is not None:
                harness.kill(name)
            raise PromptCheckError(f"Cursor prompt check could not run: {exc}") from None
        audit = prompt_audit(driver._homes[scratch] / _CONFIG) if harness is None else volume_prompt_audit(harness)
        if completed.returncode != 0 or audit is None:
            # Redact the whole stderr before cutting it, so no token straddles the cut.
            detail = completed.stderr
            for secret in driver._secrets.get(scratch, set()):
                detail = detail.replace(secret, REDACTED)
            detail = detail.strip()[-300:]
            raise PromptCheckError(
                f"Cursor prompt check failed (exit {completed.returncode}): {detail or 'no chat recorded'}"
            )
        return audit
    finally:
        if harness is not None:
            harness.close()
        if listener is not None:
            listener.close()
        driver._secrets.pop(scratch, None)
        private = driver._homes.pop(scratch, None)
        if private is not None:
            shutil.rmtree(private, ignore_errors=True)
        shutil.rmtree(scratch, ignore_errors=True)


# -- the driver ---------------------------------------------------------------


class CursorDriver(HarnessDriver):
    """The Cursor CLI behind the shared episode loop."""

    name = HARNESS_NAME
    default_binary = "cursor-agent"
    # The image's launcher: it clears the config the agent could add, exports the token, and execs the CLI.
    container_executable = CURSOR_WRAPPER_PATH
    image_version_key = CURSOR_IMAGE.version_key

    def __init__(self, *, token_file: str | Path | None = None) -> None:
        self.token_file = Path(token_file).expanduser() if token_file is not None else None
        # Per launch (keyed by scratch directory): the private directory, the credential
        # to redact, where it came from, the staged config, and what the guards found.
        self._homes: dict[Path, Path] = {}
        self._secrets: dict[Path, set[str]] = {}
        self._sources: dict[Path, str] = {}
        self._configs: dict[Path, dict[str, Any]] = {}
        self._findings: dict[Path, list[str]] = {}
        self._audits: dict[Path, dict[str, Any] | None] = {}
        # The mcp.json text the container launcher restores, per working directory.
        self._mcp_args: dict[str, str] = {}
        # The episode's stderr log and its size when the current invocation started.
        self._stderr: tuple[Path, int] | None = None

    def auth_source(self, env: dict[str, str] | None = None) -> str:
        env = os.environ if env is None else env
        if self.token_file is not None:
            return "token-file"
        for key in (API_KEY_ENV, AUTH_TOKEN_ENV):
            if env.get(key):
                return key
        return "none"

    def preflight(self, isolation: str) -> None:
        if isolation == "container" and self.token_file is None:
            raise ValueError(
                "--isolation container with --harness cursor needs --cursor-token-file (a Cursor API key or session "
                "token): the container gets no environment and no host login, so the CLI has no credential otherwise"
            )
        if self.token_file is not None:
            read_token_file(self.token_file)
            return
        if self.auth_source() == "none":
            raise ValueError(
                f"--harness cursor needs credentials: pass --cursor-token-file (a Cursor API key or session token) "
                f"or set {API_KEY_ENV} or {AUTH_TOKEN_ENV}; the host's Cursor login is deliberately not used"
            )

    def version(self, binary: str) -> str | None:
        return cursor_version(binary)

    def check_prompt(
        self,
        *,
        binary: str,
        model: str,
        variant: str | None,
        image: dict[str, Any] | None = None,
        docker: str = "docker",
    ) -> dict[str, Any]:
        """Cursor builds its prompt on its servers, so no loopback capture: audit a one-word chat instead.

        A container panel is checked too, in its image: the account's User
        Rules reach the prompt from Cursor's servers whatever the isolation.
        """
        audit = probe_prompt(model=model, binary=binary, token_file=self.token_file, image=image, docker=docker)
        problems = prompt_audit_problems(HARNESS_NAME, {"prompt_audit": audit})
        if audit["user_rules"]:
            problems.append(
                "Cursor's servers add the account's User Rules to every prompt: clear them in Cursor Settings > "
                "Rules (keep a copy to restore afterwards) and run again. A rule that is not there may be one of "
                "Cursor's defaults reworded: review it before adding its digest to CURSOR_DEFAULT_RULES"
            )
        return {
            "checked": True,
            "method": "one-word prompt; the context Cursor recorded",
            **audit,
            "problems": problems,
        }

    def ensure_image(self, *, docker: str, env: dict[str, str]) -> dict[str, Any]:
        return ensure_image(docker=docker, env=env, spec=CURSOR_IMAGE)

    def environment(self, env: dict[str, str], scratch: Path, isolation: str) -> dict[str, str]:
        if isolation == "container":
            # This is only the docker client's environment; the container gets none of it.
            # The token reaches the harness through the home volume (``stage``).
            if self.token_file is None:
                raise ValueError("--isolation container with --harness cursor needs --cursor-token-file")
            for key in tuple(env):
                if key.startswith("CURSOR_"):
                    env.pop(key)
            self._sources[scratch] = "token-file"
            self._secrets.setdefault(scratch, set()).add(read_token_file(self.token_file))
            return env
        source = self.auth_source(env)
        self._sources[scratch] = source
        credential: tuple[str, str] | None = None
        if self.token_file is not None:
            token = read_token_file(self.token_file)
            credential = (token_env(token), token)
        elif source != "none":
            credential = (source, env[source])
        for key in tuple(env):
            if key.startswith("CURSOR_"):
                env.pop(key)
        # No host ~/.cursor (login, config, chats, rules, skills, hooks, MCP servers):
        # three private directories outside the scratch.
        private = Path(tempfile.mkdtemp(prefix="gmb-cursor-"))
        self._homes[scratch] = private
        for name in (_HOME, _CONFIG, _DATA):
            (private / name).mkdir(mode=0o700)
        (private / _HOME / ".cursor").mkdir(mode=0o700)
        env["HOME"] = str(private / _HOME)
        env["CURSOR_CONFIG_DIR"] = str(private / _CONFIG)
        env["CURSOR_DATA_DIR"] = str(private / _DATA)
        env.update(HARNESS_ENV)
        if credential is not None:
            env[credential[0]] = credential[1]
            self._secrets.setdefault(scratch, set()).add(credential[1])
        return env

    def _mcp_path(self, launch: HarnessLaunch) -> Path:
        return self._homes[launch.scratch] / _HOME / ".cursor" / MCP_CONFIG_FILENAME

    def _home_files(self, config: dict[str, Any] | None) -> dict[str, bytes]:
        """What ``seed_home`` writes into a container's home volume: the token (under its variable), and mcp.json."""
        assert self.token_file is not None
        token = read_token_file(self.token_file)
        files = {CURSOR_TOKEN_FILENAME: f"{token_env(token)}\n{token}\n".encode()}
        if config is not None:
            files[f"{CURSOR_USER_DIR}/{MCP_CONFIG_FILENAME}"] = json.dumps(config, indent=2).encode()
        return files

    def stage(self, launch: HarnessLaunch) -> None:
        stage_proxy(launch.scratch, secret=launch.secret)
        config = mcp_config(launch.workdir, launch.proxy_target, python=launch.proxy_python)
        self._configs[launch.scratch] = config
        self._findings[launch.scratch] = []
        if launch.container is not None:
            # Into the episode's home volume over the docker client's stdin: never a command line,
            # an environment variable, or the bind-mounted scratch. gmb-cursor exports the token.
            launch.container.seed_home(self._home_files(config))
            self._mcp_args[launch.workdir] = json.dumps(config, indent=2)
            return
        self._write_mcp_config(self._mcp_path(launch), config)

    @staticmethod
    def _write_mcp_config(path: Path, config: dict[str, Any]) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)

    def before_invocation(self, launch: HarnessLaunch) -> None:
        """Undo whatever the agent added to the config it could reach, and mark where this invocation's stderr starts.

        In a container ``gmb-cursor`` does the undoing, inside the invocation's own container.
        """
        stderr = launch.evidence_paths[1] if len(launch.evidence_paths) > 1 else None
        if stderr is not None:
            self._stderr = (stderr, stderr.stat().st_size if stderr.is_file() else 0)
        private = self._homes.get(launch.scratch)
        config = self._configs.get(launch.scratch)
        if launch.container is not None or private is None or config is None:
            return
        findings = self._findings.setdefault(launch.scratch, [])
        home = private / _HOME / ".cursor"
        places = [(home, name, "$HOME/.cursor") for name in HOME_CONFIG_ENTRIES]
        places += [(launch.scratch, name, "the scratch") for name in SCRATCH_CONFIG_ENTRIES]
        for directory, name, where in places:
            path = directory / name
            if path.exists() or path.is_symlink():
                findings.append(f"removed {name} from {where} before a launch")
                _remove(path)
        mcp = home / MCP_CONFIG_FILENAME
        if not mcp.is_file() or mcp.is_symlink() or mcp.read_text(encoding="utf-8") != json.dumps(config, indent=2):
            findings.append(f"restored {MCP_CONFIG_FILENAME} before a launch")
            _remove(mcp)
            self._write_mcp_config(mcp, config)

    def _invocation_stderr(self) -> str:
        if self._stderr is None:
            return ""
        path, offset = self._stderr
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                return handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _options(model: str, variant: str | None) -> list[str]:
        if variant:
            raise ValueError("--harness cursor takes no --variant: Cursor names the effort in the model id")
        return [
            "-p",
            "--output-format",
            "stream-json",
            "--trust",
            "--force",
            "--approve-mcps",
            "--sandbox",
            SANDBOX,
            "--model",
            model,
        ]

    def _launcher_args(self, workdir: str, isolation: str) -> list[str]:
        """In a container, gmb-cursor's first argument: the mcp.json it restores before every launch."""
        return [self._mcp_args[workdir]] if isolation == "container" else []

    def run_args(self, *, model: str, variant: str | None, workdir: str, brief: str, isolation: str) -> list[str]:
        return [*self._launcher_args(workdir, isolation), *self._options(model, variant), brief]

    def resume_args(
        self, *, model: str, variant: str | None, workdir: str, session_id: str, text: str, isolation: str
    ) -> list[str]:
        options = self._options(model, variant)
        return [*self._launcher_args(workdir, isolation), *options, "--resume", session_id, text]

    def parse_events(self, lines: list[str]) -> dict[str, Any]:
        return parse_cursor_events(lines)

    def ended_in_provider_stall(self, lines: list[str]) -> bool:
        return ended_in_provider_stall(lines, self._invocation_stderr())

    def quota_exhausted(self, lines: list[str], *, isolation: str, now: float) -> dict[str, Any] | None:
        return quota_exhaustion(lines, self._invocation_stderr())

    def usage_block(self, telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
        return usage_block(telemetry, model=model, decisions=decisions)

    def collect(self, launch: HarnessLaunch) -> None:
        if launch.container is None:
            private = self._homes.get(launch.scratch)
            self._audits[launch.scratch] = prompt_audit(private / _CONFIG) if private is not None else None
            return
        self._audits[launch.scratch] = volume_prompt_audit(launch.container)
        stderr = launch.evidence_paths[1] if len(launch.evidence_paths) > 1 else None
        if stderr is not None and stderr.is_file():
            # What gmb-cursor removed or restored before a launch, and any launch it refused. The
            # agent names what it planted, so a line can carry the token; run.json is not redacted later.
            secrets = self._secrets.get(launch.scratch, set())
            for line in stderr.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.startswith(CURSOR_WRAPPER_PREFIX):
                    continue
                for secret in secrets:
                    line = line.replace(secret, REDACTED)
                self._findings.setdefault(launch.scratch, []).append(line.strip())

    def run_record(self, launch: HarnessLaunch) -> dict[str, Any]:
        config = self._configs.pop(launch.scratch, None)
        container = launch.container is not None
        return {
            # The whole staged mcp.json; it names only the proxy and where it connects.
            "harness_config": json.dumps(config, indent=2) if config is not None else None,
            "cursor_home": "HOME, CURSOR_CONFIG_DIR and CURSOR_DATA_DIR in the episode volume (removed at episode end)"
            if container
            else "private HOME, CURSOR_CONFIG_DIR and CURSOR_DATA_DIR outside the scratch (removed at episode end)",
            "config_dir_guard": CONFIG_DIR_GUARD[launch.isolation],
            "config_dir_findings": self._findings.pop(launch.scratch, []),
            # The sections Cursor put in the prompt besides the brief (names and counts only); None if unread.
            "prompt_audit": self._audits.pop(launch.scratch, None),
            "sandbox": SANDBOX,
            "permissions": "--force --approve-mcps --trust",
            "credential_store": HARNESS_ENV["AGENT_CLI_CREDENTIAL_STORE"],
            "auth": self._sources.pop(launch.scratch, "none"),
            "credential_handoff": "home volume over docker run stdin, exported by gmb-cursor"
            if container
            else "harness environment",
            "session_resume": "cursor-agent -p --resume",
        }

    def cleanup(self, launch: HarnessLaunch) -> None:
        # The private directory (chats, transcripts, any credential) never outlives the
        # episode, even with --keep-scratch, and no credential value stays in the evidence.
        # (A container's home volume goes with the container, before this runs.)
        secrets = self._secrets.pop(launch.scratch, set())
        self._mcp_args.pop(getattr(launch, "workdir", ""), None)
        private = self._homes.pop(launch.scratch, None)
        if private is not None:
            shutil.rmtree(private, ignore_errors=True)
        self._stderr = None
        for path in launch.evidence_paths:
            redact_file(path, secrets)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


# -- entry points -------------------------------------------------------------


def run_episode(
    seed: int,
    *,
    binary: str = "cursor-agent",
    token_file: str | Path | None = None,
    driver: CursorDriver | None = None,
    isolation: str = "same-user",
    **kwargs: Any,
) -> dict[str, Any]:
    """``opencode.run_episode`` with the Cursor driver."""
    driver = driver if driver is not None else CursorDriver(token_file=token_file)
    driver.preflight(isolation)
    return opencode.run_episode(seed, binary=binary, driver=driver, isolation=isolation, **kwargs)


def run_panel(
    seeds: list[int], *, binary: str = "cursor-agent", token_file: str | Path | None = None, **kwargs: Any
) -> dict[str, Any]:
    """``opencode.run_panel`` with the Cursor driver; seeds run serially."""
    return opencode.run_panel(seeds, binary=binary, driver=CursorDriver(token_file=token_file), **kwargs)
