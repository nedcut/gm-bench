"""Codex CLI harness driver for GM-Bench 2.0 (``gm-bench agentic --harness codex``).

The episode loop is the one every harness shares (``opencode.run_episode``:
engine and socket server in this process, sandbox check, nudges, provider
stall retries, the phase-guard watch, finalization). This module supplies
only what is specific to the Codex CLI, as a :class:`CodexDriver`.

What the driver relies on, checked against Codex CLI 0.156.1 (``codex
--version`` prints ``codex-cli 0.156.1``; the help of ``codex``, ``codex
exec``, ``codex exec resume``, ``codex mcp`` and ``codex login``, and the
source at tag ``rust-v0.156.1``: ``codex-rs/exec/src/exec_events.rs``,
``event_processor_with_jsonl_output.rs``, ``exec/src/lib.rs``,
``protocol/src/error.rs``, ``login/src/auth/storage.rs``,
``core/src/session/mod.rs``, ``ext/skills/src/host_roots.rs``):

- **Non-interactive run.** ``codex exec --json [OPTIONS] <prompt>`` runs one
  turn and prints JSON Lines on stdout. Headless ``exec`` never asks for
  approval (it forces ``approval_policy = never``), and with a prompt
  argument and a non-terminal stdin it reads stdin only to append it, so the
  driver's ``/dev/null`` adds nothing. ``--skip-git-repo-check`` is needed
  because the scratch directory is not a git repository. ``--model`` picks
  the model; ``--variant`` maps to ``-c model_reasoning_effort="<variant>"``.
- **Events.** ``thread.started`` (``thread_id``, the session id to resume),
  ``turn.started``, ``turn.completed`` (``usage``: ``input_tokens``,
  ``cached_input_tokens``, ``cache_write_input_tokens``, ``output_tokens``,
  ``reasoning_output_tokens``), ``turn.failed`` (``error.message`` only),
  ``item.started``/``item.updated``/``item.completed`` (an ``item`` with an
  ``id`` and a ``type``: ``mcp_tool_call`` with ``server`` and ``tool``,
  ``command_execution``, ``file_change``, ``web_search``,
  ``collab_tool_call``, ``agent_message``, ``reasoning``, ``todo_list``,
  ``error``), and ``error`` (``message``). Item ids restart at ``item_0`` in
  every process, so tool events are counted per invocation. Codex emits
  ``mcp_tool_call`` items for calls it refuses before dispatch too
  (``notify_mcp_tool_call_skip``: ``item.completed`` with ``status =
  "failed"`` and ``error.message`` such as ``MCP tool call requires
  approval, but approval policy is never``); those never reached the server
  and are counted apart, not as harness tool calls.
- **Usage is a running session total.** ``turn.completed.usage`` is the
  thread's cumulative token count (``usage_from_last_total``), and a resumed
  session restores that total from its saved rollout
  (``last_token_info_from_rollout``), so the episode total is the last
  ``turn.completed`` per thread, not a sum over invocations. A final
  invocation that fails before completing its turn is not in that total.
  ``input_tokens`` includes ``cached_input_tokens`` and
  ``cache_write_input_tokens``, and ``output_tokens`` includes
  ``reasoning_output_tokens`` (``codex-api/src/sse/responses.rs`` copies the
  Responses API's ``input_tokens``, ``output_tokens`` and their ``*_details``).
  The stream reports no cost, no per-model-call records and no compaction
  events, so the usage block's ``cost_usd`` is ``None`` (a ChatGPT plan is
  not billed per token; nothing was charged that the harness could report),
  ``api_calls`` counts completed turns, ``max_output_tokens_per_call`` is
  left out, and ``compactions`` is ``None`` (unmeasured, not zero). What the
  same tokens would cost at API list price, with cached input at the cached
  rate, is published beside it as ``harness.api_equivalent_cost_usd``
  (``cost_basis = "api-list-price-estimate"``, ``billed_by_harness =
  false``), never as ``cost_usd``.
- **Resume.** ``codex exec resume [OPTIONS] <session id> <prompt>`` continues
  the same session with its context, so a nudge or stall retry resumes the
  thread named by ``thread.started``. ``resume`` has no ``--sandbox`` or
  ``--cd`` flag, so every option the driver sets goes through ``-c`` and the
  process working directory, identically for both commands. Resume needs
  the session files under ``CODEX_HOME/sessions``, so ``--ephemeral`` is not
  used.
- **Errors and provider stalls.** A failed turn ends the process with
  ``turn.failed``; retryable upstream failures read as ``exceeded retry
  limit, last status: 429 ...``, ``unexpected status 503 ...``, ``rate limit
  exceeded: ...``, ``stream disconnected before completion: ...``,
  ``Connection failed: ...``, ``Error while reading the server response``,
  ``request timed out``, ``We're currently experiencing high demand``,
  or ``Selected model is at capacity``. Those map into the shared
  provider-stall retry; ``Quota exceeded``, a 401, or a context-window error
  do not.
- **Usage limit (quota exhaustion).** ``You’ve hit your usage limit. ...
  try again at Sep 24th, 2026 4:19 PM.`` (``UsageLimitReachedError`` in
  ``protocol/src/error.rs``) is not a transient stall: the subscription's
  window is spent until the stated time. Codex formats that time in the
  Codex process's local time zone as ``%b %-d<st|nd|rd|th>, %Y %-I:%M %p``,
  or ``%-I:%M %p`` alone when the reset is later the same local day, or
  says ``try again later`` when it does not know. :func:`quota_exhaustion`
  parses it (the host's zone in same-user isolation; UTC in a container,
  which sets no ``TZ``), and the shared loop pauses until the reset or
  stops the episode and the panel.
- **Configuration and what is not inherited.** ``CODEX_HOME`` (default
  ``~/.codex``) holds ``config.toml``, ``auth.json``, the session store,
  ``AGENTS.md``, skills, rules and plugins. The driver never uses the host's:
  in same-user isolation ``CODEX_HOME`` is a private directory (mode 0700)
  outside the scratch, removed when the episode ends, and ``HOME`` is the
  scratch directory itself, because Codex also loads user skills from
  ``$HOME/.agents/skills``; in a container the harness home is the
  per-episode volume (``/home/node/.codex``). Every other ``CODEX_*``
  variable is dropped from the harness environment. The staged
  ``config.toml`` holds exactly one MCP server entry, ``[mcp_servers.gm-bench]``
  with ``command`` (the harness's python3) and ``args``
  (``gm_bench_proxy.py`` and the socket path or ``host:port``), the same
  launch ``opencode_config`` declares, plus ``default_tools_approval_mode =
  "approve"``. That last key is required: ``exec`` forces ``approval_policy
  = never``, under which Codex auto-approves an MCP call only when the
  server's approval mode is ``approve`` or the sandbox has full disk write
  (``mcp_permission_prompt_is_auto_approved``); otherwise a tool without a
  ``readOnlyHint`` annotation (every GM-Bench tool) is refused with
  ``MCP tool call requires approval, but approval policy is never``. It
  approves this one server's tools only. Codex reports those calls as
  ``mcp_tool_call`` items with ``server = "gm-bench"``, recorded as
  ``gm-bench_<tool>`` so the ledger-versus-harness agreement counts them.
  Codex's own built-in tools stay as the harness ships them; they are part of
  the row identity (``codex/<version>``).
- **Sandbox.** Same-user: ``sandbox_mode = "workspace-write"`` (commands may
  write only the working directory and temp directories) with
  ``sandbox_workspace_write.network_access = true``, the least permission
  that still lets the agent run code in the scratch directory without a
  network rule the OpenCode lane does not have. In a container:
  ``sandbox_mode = "danger-full-access"``, because Codex's Linux sandbox
  needs user namespaces that Docker's default seccomp profile refuses; the
  container (no capabilities, unprivileged user, egress firewall, only the
  scratch directory and the home volume mounted) is the sandbox.
- **Authentication.** Codex reads ``CODEX_HOME/auth.json`` (the default file
  credential store) or, for ``exec``, a ``CODEX_API_KEY`` environment
  variable. Because the host ``~/.codex`` is not used, a ChatGPT login is not
  inherited. Same-user runs take either ``--codex-auth-file <path>`` (copied
  to ``auth.json`` in the private ``CODEX_HOME``, mode 0600, and deleted
  with it when the episode ends, even with ``--keep-scratch``) or
  ``CODEX_API_KEY`` in the operator's environment. Container runs pass no environment, so they need
  ``--codex-auth-file``: the file travels on the stdin of a throwaway
  ``docker run`` into the per-episode home volume (``ContainerHarness.seed_home``),
  never onto a command line, an environment variable, or the bind-mounted
  scratch directory, and is removed with the volume. The agent can read its
  own harness's credential (as it can read the proxy secret): that is the
  harness's key, not the benchmark's, and it gives no access to the seed.
  What the agent prints lands in the retained event stream
  (``command_execution.aggregated_output``), so when the episode ends the
  driver replaces every credential value (the file's ``OPENAI_API_KEY`` and
  ``tokens``, as staged and as Codex left them, and ``CODEX_API_KEY``) with
  ``[REDACTED]`` in ``codex-events.jsonl`` and ``codex-stderr.log``. A kept
  scratch directory is not redacted: it holds whatever the agent wrote.
  A ChatGPT ``auth.json`` carries a refresh token that Codex may rotate
  inside the episode; an API-key ``auth.json``
  (``{"auth_mode": "apikey", "OPENAI_API_KEY": "..."}``) does not have that
  problem.

Every Codex run spends the operator's OpenAI quota or money, and the driver
runs episodes serially: never run it in parallel.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from gm_bench.agentic import opencode
from gm_bench.agentic.container import CODEX_IMAGE, HOME, ensure_image
from gm_bench.agentic.harness import HarnessDriver
from gm_bench.agentic.opencode import PROXY_FILENAME, HarnessLaunch, stage_proxy
from gm_bench.telemetry import api_equivalent_cost_usd

HARNESS_NAME = "codex"
CODEX_HOME_DIRNAME = ".codex"
CONFIG_FILENAME = "config.toml"
AUTH_FILENAME = "auth.json"
MCP_SERVER_NAME = "gm-bench"
AUTH_ENV = "CODEX_API_KEY"
SAME_USER_SANDBOX = "workspace-write"
CONTAINER_SANDBOX = "danger-full-access"
CONTAINER_CODEX_HOME = f"{HOME}/{CODEX_HOME_DIRNAME}"
# Without it, ``codex exec`` (approval policy never) refuses every GM-Bench call in workspace-write.
TOOLS_APPROVAL_MODE = "approve"
REDACTED = "[REDACTED]"
# ``harness.cost_basis`` of the API-equivalent estimate: list price, not a bill.
COST_BASIS = "api-list-price-estimate"

# A terminal ``turn.failed``/``error`` message that reads as a transient provider failure.
_RETRYABLE_MESSAGE_RE = re.compile(
    r"rate limit|too many requests|status:?\s+(?:408|425|429|5\d\d)\b|stream disconnected|high demand"
    r"|at capacity|overloaded|connection failed|error while reading the server response|request timed out"
    r"|try again",
    re.IGNORECASE,
)

# A spent subscription window (``UsageLimitReachedError``): never a stall.
USAGE_LIMIT_RE = re.compile(r"\busage limit\b", re.IGNORECASE)
# Its reset time, as ``format_retry_timestamp`` writes it: ``Sep 24th, 2026 4:19 PM``, or ``4:19 PM`` on the same day.
TRY_AGAIN_AT_RE = re.compile(
    r"try again at\s+"
    r"(?:(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4}),?\s+)?"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<meridiem>[AaPp])\.?\s*[Mm]\.?",
    re.IGNORECASE,
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}

# ``error.message`` of an ``mcp_tool_call`` Codex refused before dispatching it
# (``notify_mcp_tool_call_skip`` in ``core/src/mcp_tool_call.rs``): it never reached the server.
_SKIPPED_CALL_RE = re.compile(
    r"requires approval|not available to the model|blocked by|user cancelled|approval (?:was )?(?:denied|rejected)",
    re.IGNORECASE,
)


# -- version and configuration ------------------------------------------------


def codex_version(binary: str = "codex") -> str | None:
    """The version ``codex --version`` reports (``codex-cli 0.156.1`` -> ``0.156.1``)."""
    try:
        completed = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (completed.stdout or completed.stderr).strip().splitlines()
    words = lines[-1].split() if lines else []
    return words[-1] if words else None


def codex_config(target: str | Path, *, python: str = "python3") -> dict[str, Any]:
    """The staged ``config.toml`` as data: one MCP server entry and nothing else.

    It launches the proxy beside the agent's working directory on the
    harness's own python3, pointed at the socket path or ``host:port``,
    exactly as ``opencode_config`` does, and approves that server's tools,
    which ``codex exec`` would otherwise refuse in ``workspace-write``.
    """
    server = {
        "command": python,
        "args": [PROXY_FILENAME, str(target)],
        "default_tools_approval_mode": TOOLS_APPROVAL_MODE,
    }
    return {"mcp_servers": {MCP_SERVER_NAME: server}}


def codex_config_toml(config: dict[str, Any]) -> str:
    """Render :func:`codex_config` as TOML (JSON string escapes are valid TOML basic strings)."""
    lines: list[str] = []
    for name, server in config["mcp_servers"].items():
        lines.append(f"[mcp_servers.{name}]")
        lines.append(f"command = {json.dumps(server['command'])}")
        lines.append(f"args = [{', '.join(json.dumps(arg) for arg in server['args'])}]")
        if "default_tools_approval_mode" in server:
            lines.append(f"default_tools_approval_mode = {json.dumps(server['default_tools_approval_mode'])}")
    return "\n".join(lines) + "\n"


def auth_secrets(data: bytes | str) -> set[str]:
    """The credential values in a Codex ``auth.json``: ``OPENAI_API_KEY`` and every string under ``tokens``."""
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.add(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload.get("OPENAI_API_KEY"))
    walk(payload.get("tokens"))
    # Short strings are not credentials, and replacing them would mangle unrelated text.
    return {value for value in found if len(value) >= 8}


def redact_file(path: Path, values: set[str]) -> bool:
    """Replace every value (raw and JSON-escaped) with ``[REDACTED]`` in ``path``; whether anything changed."""
    if not values or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    redacted = text
    # Longest first, so a value that contains another is replaced whole.
    for value in sorted(values, key=len, reverse=True):
        for form in {value, json.dumps(value)[1:-1]}:
            redacted = redacted.replace(form, REDACTED)
    if redacted == text:
        return False
    path.write_text(redacted, encoding="utf-8", errors="surrogateescape")
    return True


def read_auth_file(path: str | Path) -> bytes:
    """The operator's Codex ``auth.json``, checked for shape without echoing any of it."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError(f"--codex-auth-file {path} is not a file")
    data = path.read_bytes()
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(f"--codex-auth-file {path} is not JSON; expected a Codex auth.json") from None
    if not isinstance(payload, dict) or not (payload.get("OPENAI_API_KEY") or payload.get("tokens")):
        raise ValueError(f"--codex-auth-file {path} has neither OPENAI_API_KEY nor tokens; expected a Codex auth.json")
    return data


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


def _tool_name(item: dict[str, Any]) -> str | None:
    kind = item.get("type")
    if kind == "mcp_tool_call":
        return f"{item.get('server') or 'unknown'}_{item.get('tool') or 'unknown'}"
    if kind == "command_execution":
        return "shell"
    if kind == "file_change":
        return "apply_patch"
    if kind == "web_search":
        return "web_search"
    if kind == "collab_tool_call":
        return f"collab_{item.get('tool') or 'unknown'}"
    return None


def parse_codex_events(lines: list[str]) -> dict[str, Any]:
    """Fold ``codex exec --json`` output (every invocation of one episode) into telemetry.

    Same shape as ``opencode.parse_opencode_events``. Tool calls are counted
    once per item id within each invocation (an invocation starts at its
    ``thread.started``), from ``item.started`` as well as ``item.completed``,
    so a call cut off by a guard stop still counts: it reached the server.
    An ``mcp_tool_call`` that completed ``failed`` with one of Codex's
    pre-dispatch refusals (approval required, not available to the model,
    blocked, cancelled) never reached the server; it is counted in
    ``harness_tool_calls_skipped``, not as a tool event. Tokens are the last
    ``turn.completed`` usage per thread, because that usage is the thread's
    running total; ``max_turn_input_tokens`` is the largest growth of one
    thread's input total between consecutive ``turn.completed`` events, an
    upper bound on any one request's input. ``model_calls`` counts completed
    turns (the stream has no per-call records); cost, the largest single-call
    output, and compactions are not reported (``None``).
    """
    session_id: str | None = None
    thread: str | None = None
    totals: dict[str | None, dict[str, Any]] = {}
    tool_events: dict[str, int] = {}
    skipped: dict[str, int] = {}
    invocation_items: dict[str, str] = {}
    invocation_skipped: dict[str, str] = {}
    turns_started = turns_completed = turns_failed = errors = max_turn_input = 0
    event_types: dict[str, int] = {}

    def close_invocation() -> None:
        for name in invocation_items.values():
            tool_events[name] = tool_events.get(name, 0) + 1
        for name in invocation_skipped.values():
            skipped[name] = skipped.get(name, 0) + 1
        invocation_items.clear()
        invocation_skipped.clear()

    for event in _events(lines):
        kind = str(event.get("type", ""))
        event_types[kind] = event_types.get(kind, 0) + 1
        if kind == "thread.started":
            close_invocation()
            thread = event.get("thread_id") if isinstance(event.get("thread_id"), str) else None
            session_id = session_id or thread
        elif kind == "turn.started":
            turns_started += 1
        elif kind == "turn.completed":
            turns_completed += 1
            if isinstance(event.get("usage"), dict):
                previous = opencode._int((totals.get(thread) or {}).get("input_tokens"))
                delta = opencode._int(event["usage"].get("input_tokens")) - previous
                max_turn_input = max(max_turn_input, delta)
                totals[thread] = event["usage"]
        elif kind == "turn.failed":
            turns_failed += 1
            errors += 1
        elif kind == "error":
            errors += 1
        elif kind in ("item.started", "item.updated", "item.completed"):
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            name = _tool_name(item)
            if name is None:
                continue
            item_id = str(item.get("id"))
            if kind == "item.completed" and _skipped_before_dispatch(item):
                invocation_items.pop(item_id, None)
                invocation_skipped[item_id] = name
            elif item_id not in invocation_skipped:
                invocation_items[item_id] = name
    close_invocation()

    def total(key: str) -> int:
        return sum(opencode._int(usage.get(key)) for usage in totals.values())

    return {
        "model_calls": turns_completed,
        # Already the shared shape: input includes cached and cache-write tokens.
        "input_tokens": total("input_tokens"),
        "uncached_input_tokens": sum(
            max(
                opencode._int(usage.get("input_tokens"))
                - opencode._int(usage.get("cached_input_tokens"))
                - opencode._int(usage.get("cache_write_input_tokens")),
                0,
            )
            for usage in totals.values()
        ),
        "output_tokens": total("output_tokens"),
        "reasoning_tokens": total("reasoning_output_tokens"),
        "cached_input_tokens": total("cached_input_tokens"),
        "cache_write_tokens": total("cache_write_input_tokens"),
        # The largest one-turn growth of a thread's input total: an upper bound on
        # any single request's input (a turn may make several model requests).
        "max_turn_input_tokens": max_turn_input,
        # Not observable: the stream has no per-call records.
        "max_output_tokens_per_call": None,
        "cost_usd": None,
        "harness_tool_events": dict(sorted(tool_events.items())),
        "harness_tool_calls_skipped": dict(sorted(skipped.items())),
        # Not observable: ``codex exec --json`` emits no compaction event.
        "compactions": None,
        "errors": errors,
        "session_id": session_id,
        "event_types": dict(sorted(event_types.items())),
        "turns_started": turns_started,
        "turns_failed": turns_failed,
    }


def _skipped_before_dispatch(item: dict[str, Any]) -> bool:
    """An ``mcp_tool_call`` Codex refused itself: ``failed``, no server result, a skip message."""
    if item.get("type") != "mcp_tool_call" or item.get("status") != "failed" or item.get("result"):
        return False
    error = item.get("error") if isinstance(item.get("error"), dict) else {}
    message = error.get("message")
    return isinstance(message, str) and bool(_SKIPPED_CALL_RE.search(message))


def _terminal_message(lines: list[str]) -> str | None:
    """The message of an invocation's last event when it is ``turn.failed`` or ``error``."""
    events = _events(lines)
    if not events:
        return None
    last = events[-1]
    if last.get("type") == "turn.failed":
        error = last.get("error") if isinstance(last.get("error"), dict) else {}
        message = error.get("message")
    elif last.get("type") == "error":
        message = last.get("message")
    else:
        return None
    return message if isinstance(message, str) else None


def ended_in_provider_stall(lines: list[str]) -> bool:
    """Whether one invocation ended on a retryable provider error.

    The last event must be ``turn.failed`` (``error.message``) or ``error``
    (``message``) whose message reads as a transient failure (a 408, 425, 429
    or 5xx status, a rate limit, an overload or capacity notice, a dropped
    stream or connection, or a timeout). A usage limit is quota exhaustion
    (:func:`quota_exhaustion`), never a stall. Any other ending is the agent
    or the harness stopping.
    """
    message = _terminal_message(lines)
    if message is None or USAGE_LIMIT_RE.search(message):
        return False
    return bool(_RETRYABLE_MESSAGE_RE.search(message))


def parse_reset_time(message: str, *, tz: _dt.tzinfo | None = None, now: float | None = None) -> str | None:
    """The ``try again at`` time of a usage-limit message as an ISO UTC timestamp, or ``None`` if unparsable.

    ``tz`` is the zone Codex formatted the time in (default: this machine's
    local zone). A time without a date is on ``now``'s date in that zone.
    """
    match = TRY_AGAIN_AT_RE.search(message)
    if match is None:
        return None
    hour, minute = int(match["hour"]), int(match["minute"])
    if not (1 <= hour <= 12 and 0 <= minute <= 59):
        return None
    hour = hour % 12 + (12 if match["meridiem"].lower() == "p" else 0)
    zone = tz if tz is not None else _dt.datetime.now().astimezone().tzinfo
    try:
        if match["month"] is None:
            today = _dt.datetime.fromtimestamp(now if now is not None else _dt.datetime.now().timestamp(), zone)
            local = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            month = _MONTHS.get(match["month"][:3].lower())
            if month is None:
                return None
            local = _dt.datetime(int(match["year"]), month, int(match["day"]), hour, minute, tzinfo=zone)
    except (ValueError, OverflowError, OSError):
        return None
    return local.astimezone(_dt.timezone.utc).isoformat()


def quota_exhaustion(
    lines: list[str], *, tz: _dt.tzinfo | None = None, now: float | None = None
) -> dict[str, Any] | None:
    """``{"message_class": "usage_limit", "reset_at_utc": ...}`` when the invocation ended on a usage limit."""
    message = _terminal_message(lines)
    if message is None or not USAGE_LIMIT_RE.search(message):
        return None
    return {"message_class": "usage_limit", "reset_at_utc": parse_reset_time(message, tz=tz, now=now)}


def usage_block(telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
    """The shared usage block, labelled for what the Codex stream can and cannot report.

    Codex reports no cost, so ``cost_usd`` is ``None`` (unmeasured) and
    ``cost_decisions`` 0. Beside it, under ``harness``, sits the
    API-equivalent estimate (:func:`gm_bench.telemetry.api_equivalent_cost_usd`):
    the episode's tokens at ``pricing.json`` list prices, cached input at the
    cached rate, short-context rates throughout. It is what the tokens would
    have cost on the API, not what anyone was billed: ``billed_by_harness`` is
    false and ``cost_basis`` says so. ``long_context_requests_possible`` is
    true when some turn's input grew past the model's long-context threshold
    (then a request may have been billed at the higher tier and the estimate
    may be low); Codex reports turns, not requests, so it cannot be exact.
    An unpriced model, or a session with no usage, gets ``None``.
    """
    usage = opencode.usage_block(telemetry, model=model, decisions=decisions, harness=HARNESS_NAME)
    usage["cost_usd"] = None
    usage["cost_decisions"] = 0
    usage["harness"].update(
        {
            "api_calls_are": "completed turns",
            "turns_started": telemetry.get("turns_started", 0),
            "turns_failed": telemetry.get("turns_failed", 0),
            "cost_reported_by_harness": False,
            # mcp_tool_call items Codex refused before dispatch; never in the ledger.
            "tool_calls_skipped": telemetry.get("harness_tool_calls_skipped") or {},
            **api_equivalent_fields(telemetry, model),
        }
    )
    return usage


def api_equivalent_fields(telemetry: dict[str, Any], model: str) -> dict[str, Any]:
    """The ``harness`` fields that carry the API-equivalent estimate (``None`` values when there is none)."""
    estimate = None
    if telemetry.get("model_calls"):
        estimate = api_equivalent_cost_usd(
            opencode.normalized_tokens(telemetry)
            | {"max_request_input_tokens": telemetry.get("max_turn_input_tokens")},
            model,
        )
    if estimate is None:
        return {
            "api_equivalent_cost_usd": None,
            "cost_basis": None,
            "billed_by_harness": False,
            "pricing_source": None,
            "long_context_requests_possible": None,
        }
    return {
        "api_equivalent_cost_usd": estimate["usd"],
        "cost_basis": COST_BASIS,
        "billed_by_harness": False,
        # The pricing.json models key matched (GM_BENCH_PRICING may override it) and when it was checked.
        "pricing_source": {
            "key": estimate["pricing_key"],
            "verified": estimate["verified"],
            "cached_input_rate": estimate["cached_input_rate"],
            "cache_write_rate": estimate["cache_write_rate"],
        },
        "long_context_requests_possible": estimate["long_context_requests_possible"],
    }


# -- subscription quota windows -----------------------------------------------
#
# ``codex exec --json`` reports no rate limits, but Codex writes every
# ``token_count`` event, with the account's ``rate_limits`` snapshot, to the
# session rollout under ``CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl``
# (``RolloutItem::EventMsg``, persisted by ``should_persist_event_msg``; one
# JSON object per line: ``{"timestamp", "type": "event_msg", "payload":
# {"type": "token_count", "info", "rate_limits"}}``). A snapshot
# (``RateLimitSnapshot`` in ``codex-rs/protocol/src/protocol.rs``) has
# ``limit_id``, ``primary``/``secondary`` windows (``used_percent``,
# ``window_minutes``, ``resets_at`` in epoch seconds), ``plan_type`` and
# ``credits``. The reading below is a port of T3 Code's
# ``codexRateLimitsToWindows`` and ``mergeCodexRateLimits``
# (apps/server/src/provider/Layers/codexUsageLimits.ts in
# github.com/pingdotgg/t3code, MIT License, Copyright (c) 2026 T3 Tools Inc.):
# only the main allowance counts (``limit_id`` ``codex`` or absent; a
# model-specific snapshot never replaces it), a later snapshot's missing
# fields keep the earlier values, and ``primary``/``secondary`` are positions
# whose duration defaults to 5 hours and a week (a month for the free and go
# plans). Only windows and the plan type are kept: never credits, tokens, or
# anything else from the rollout.

ROLLOUT_GLOB = "rollout-*.jsonl"
SESSIONS_DIRNAME = "sessions"
_SESSION_MINUTES = 5 * 60
_WEEK_MINUTES = 7 * 24 * 60
_MONTH_MINUTES = 30 * 24 * 60


def merge_rate_limits(previous: dict[str, Any] | None, update: dict[str, Any]) -> dict[str, Any] | None:
    """Fold one ``rate_limits`` snapshot into the running one (``mergeCodexRateLimits``)."""
    if update.get("limit_id") and update.get("limit_id") != "codex":
        return previous
    if previous is None:
        return dict(update)
    merged = dict(previous)
    for key in ("limit_id", "plan_type", "rate_limit_reached_type", "primary", "secondary"):
        if key in update:
            merged[key] = update[key]
    return merged


def _utc(epoch: Any) -> str | None:
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or epoch <= 0:
        return None
    try:
        return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).replace(microsecond=0).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def quota_windows(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The main allowance's windows (``codexRateLimitsToWindows``): minutes, percent used (0-100), reset time."""
    if not snapshot or (snapshot.get("limit_id") and snapshot.get("limit_id") != "codex"):
        return []
    monthly = snapshot.get("plan_type") in ("free", "go")
    windows = []
    for position, fallback in (
        ("primary", _MONTH_MINUTES if monthly else _SESSION_MINUTES),
        ("secondary", _WEEK_MINUTES),
    ):
        window = snapshot.get(position)
        if not isinstance(window, dict):
            continue
        used = window.get("used_percent")
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
            continue
        minutes = window.get("window_minutes")
        windows.append(
            {
                "window_minutes": int(minutes)
                if isinstance(minutes, int) and not isinstance(minutes, bool)
                else fallback,
                "used_percent": round(min(max(float(used), 0.0), 100.0), 2),
                "resets_at_utc": _utc(window.get("resets_at")),
            }
        )
    return windows


def rollout_quota(lines: list[str]) -> dict[str, Any]:
    """``quota_windows`` and ``plan_type`` from rollout lines, merged in timestamp order; empty when none."""
    snapshots = []
    for order, line in enumerate(lines):
        if '"token_count"' not in line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = record.get("payload") if isinstance(record, dict) else None
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        limits = payload.get("rate_limits")
        if isinstance(limits, dict):
            snapshots.append((str(record.get("timestamp") or ""), order, limits))
    merged: dict[str, Any] | None = None
    for _stamp, _order, limits in sorted(snapshots, key=lambda item: (item[0], item[1])):
        merged = merge_rate_limits(merged, limits)
    windows = quota_windows(merged)
    if not windows:
        return {}
    plan = merged.get("plan_type") if merged else None
    return {"quota_windows": windows, "plan_type": plan if isinstance(plan, str) else None}


def read_rollout_quota(codex_home: Path) -> dict[str, Any]:
    """:func:`rollout_quota` over every plain rollout under ``codex_home/sessions`` (compressed ones are skipped)."""
    lines: list[str] = []
    for path in sorted((codex_home / SESSIONS_DIRNAME).rglob(ROLLOUT_GLOB)):
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                lines.extend(line for line in handle if '"token_count"' in line)
        except OSError:
            continue
    return rollout_quota(lines)


# -- the driver ---------------------------------------------------------------


class CodexDriver(HarnessDriver):
    """The Codex CLI behind the shared episode loop."""

    name = HARNESS_NAME
    default_binary = "codex"
    container_executable = "codex"
    image_version_key = CODEX_IMAGE.version_key

    def __init__(self, *, auth_file: str | Path | None = None) -> None:
        self.auth_file = Path(auth_file).expanduser() if auth_file is not None else None
        # Per launch (keyed by scratch directory): the private same-user CODEX_HOME,
        # and the credential values to redact from the evidence when the episode ends.
        self._homes: dict[Path, Path] = {}
        self._secrets: dict[Path, set[str]] = {}
        # Per launch: the subscription quota read from the session rollouts by ``collect``.
        self._quota: dict[Path, dict[str, Any]] = {}

    def auth_source(self, isolation: str) -> str:
        if self.auth_file is not None:
            return "auth-file"
        return AUTH_ENV if isolation == "same-user" and os.environ.get(AUTH_ENV) else "none"

    def preflight(self, isolation: str) -> None:
        if self.auth_file is not None:
            read_auth_file(self.auth_file)
            return
        if isolation == "container":
            raise ValueError(
                "--isolation container with --harness codex needs --codex-auth-file: the container gets no "
                "environment and no host home, so Codex has no credentials otherwise"
            )
        if not os.environ.get(AUTH_ENV):
            raise ValueError(
                f"--harness codex needs credentials: pass --codex-auth-file (a Codex auth.json) or set {AUTH_ENV}; "
                "the host ~/.codex login is deliberately not used"
            )

    def version(self, binary: str) -> str | None:
        return codex_version(binary)

    def ensure_image(self, *, docker: str, env: dict[str, str]) -> dict[str, Any]:
        return ensure_image(docker=docker, env=env, spec=CODEX_IMAGE)

    def environment(self, env: dict[str, str], scratch: Path, isolation: str) -> dict[str, str]:
        for key in tuple(env):
            if key.startswith("CODEX_") and (key != AUTH_ENV or self.auth_file is not None):
                env.pop(key)
        if isolation == "same-user":
            # No host ~/.codex (config, auth, AGENTS.md, rules, sessions) and no
            # host ~/.agents/skills: HOME is the scratch directory, and CODEX_HOME
            # a private directory outside it, so neither the credential nor
            # Codex's session logs sit in the agent's working directory.
            home = Path(tempfile.mkdtemp(prefix="gmb-codex-"))
            self._homes[scratch] = home
            env["HOME"] = str(scratch)
            env["CODEX_HOME"] = str(home)
        return env

    def _config_text(self, launch: HarnessLaunch) -> str:
        return codex_config_toml(codex_config(launch.proxy_target, python=launch.proxy_python))

    def stage(self, launch: HarnessLaunch) -> None:
        stage_proxy(launch.scratch, secret=launch.secret)
        files = {CONFIG_FILENAME: self._config_text(launch).encode("utf-8")}
        secrets = self._secrets.setdefault(launch.scratch, set())
        if launch.isolation == "same-user" and self.auth_file is None and launch.env.get(AUTH_ENV):
            secrets.add(launch.env[AUTH_ENV])
        if self.auth_file is not None:
            files[AUTH_FILENAME] = read_auth_file(self.auth_file)
            secrets.update(auth_secrets(files[AUTH_FILENAME]))
        if launch.container is not None:
            # Into the episode's home volume over stdin; never the bind-mounted scratch.
            launch.container.seed_home({f"{CODEX_HOME_DIRNAME}/{name}": data for name, data in files.items()})
            return
        home = self._homes[launch.scratch]
        for name, data in files.items():
            descriptor = os.open(home / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)

    @staticmethod
    def _options(model: str, variant: str | None, isolation: str) -> list[str]:
        sandbox = CONTAINER_SANDBOX if isolation == "container" else SAME_USER_SANDBOX
        options = ["--json", "--skip-git-repo-check", "--model", model, "-c", f"sandbox_mode={json.dumps(sandbox)}"]
        if sandbox == SAME_USER_SANDBOX:
            options += ["-c", "sandbox_workspace_write.network_access=true"]
        if variant:
            options += ["-c", f"model_reasoning_effort={json.dumps(variant)}"]
        return options

    def run_args(self, *, model: str, variant: str | None, workdir: str, brief: str, isolation: str) -> list[str]:
        return ["exec", *self._options(model, variant, isolation), brief]

    def resume_args(
        self, *, model: str, variant: str | None, workdir: str, session_id: str, text: str, isolation: str
    ) -> list[str]:
        return ["exec", "resume", *self._options(model, variant, isolation), session_id, text]

    def parse_events(self, lines: list[str]) -> dict[str, Any]:
        return parse_codex_events(lines)

    def ended_in_provider_stall(self, lines: list[str]) -> bool:
        return ended_in_provider_stall(lines)

    def quota_exhausted(self, lines: list[str], *, isolation: str, now: float) -> dict[str, Any] | None:
        # The container sets no TZ, so Codex there formats the reset in UTC.
        tz = _dt.timezone.utc if isolation == "container" else None
        return quota_exhaustion(lines, tz=tz, now=now)

    def usage_block(self, telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
        return usage_block(telemetry, model=model, decisions=decisions)

    def collect(self, launch: HarnessLaunch) -> None:
        # The rollouts are append-only, so reading once after the last
        # invocation sees every token_count the episode's invocations wrote.
        if launch.container is not None:
            lines = launch.container.home_lines(
                f"{CODEX_HOME_DIRNAME}/{SESSIONS_DIRNAME}", ROLLOUT_GLOB, '"token_count"'
            )
            self._quota[launch.scratch] = rollout_quota(lines) if lines is not None else {}
            return
        home = self._homes.get(launch.scratch)
        self._quota[launch.scratch] = read_rollout_quota(home) if home is not None else {}

    def run_record(self, launch: HarnessLaunch) -> dict[str, Any]:
        container = launch.container is not None
        quota = self._quota.pop(launch.scratch, {})
        return {
            # The subscription's usage windows as Codex last reported them (empty
            # for an API key, which has none), and the plan; never credits or tokens.
            "quota_windows": quota.get("quota_windows", []),
            "plan_type": quota.get("plan_type"),
            # The whole staged config; it names only the proxy and where it connects.
            "harness_config": self._config_text(launch),
            "codex_home": f"{CONTAINER_CODEX_HOME} (episode volume)"
            if container
            else "private directory outside the scratch (removed at episode end)",
            "sandbox_mode": CONTAINER_SANDBOX if container else SAME_USER_SANDBOX,
            "auth": self.auth_source(launch.isolation),
            "session_resume": "codex exec resume",
        }

    def cleanup(self, launch: HarnessLaunch) -> None:
        # The credential never outlives the episode, even with --keep-scratch:
        # the private home goes, and no credential value stays in the evidence.
        secrets = self._secrets.pop(launch.scratch, set())
        home = self._homes.pop(launch.scratch, None)
        if home is not None:
            auth = home / AUTH_FILENAME
            if auth.is_file():
                # Codex may have rotated a ChatGPT refresh token during the episode.
                secrets.update(auth_secrets(auth.read_bytes()))
            shutil.rmtree(home, ignore_errors=True)
        for path in launch.evidence_paths:
            redact_file(path, secrets)


# -- entry points -------------------------------------------------------------


def run_episode(
    seed: int,
    *,
    binary: str = "codex",
    auth_file: str | Path | None = None,
    driver: CodexDriver | None = None,
    isolation: str = "same-user",
    **kwargs: Any,
) -> dict[str, Any]:
    """``opencode.run_episode`` with the Codex driver."""
    driver = driver if driver is not None else CodexDriver(auth_file=auth_file)
    driver.preflight(isolation)
    return opencode.run_episode(seed, binary=binary, driver=driver, isolation=isolation, **kwargs)


def run_panel(
    seeds: list[int], *, binary: str = "codex", auth_file: str | Path | None = None, **kwargs: Any
) -> dict[str, Any]:
    """``opencode.run_panel`` with the Codex driver; seeds run serially."""
    return opencode.run_panel(seeds, binary=binary, driver=CodexDriver(auth_file=auth_file), **kwargs)
