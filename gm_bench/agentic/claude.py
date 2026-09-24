"""Claude Code harness driver for GM-Bench 2.0 (``gm-bench agentic --harness claude``).

The episode loop is the one every harness shares (``opencode.run_episode``:
engine and socket server in this process, sandbox check, nudges, provider
stall retries, the phase-guard watch, finalization). This module supplies
only what is specific to the Claude Code CLI, as a :class:`ClaudeDriver`.

Proven only against a stand-in ``claude`` (``tests/test_agentic_claude.py``);
no live episode has run. What the driver relies on was read from Claude Code
2.1.281 (``claude --version`` prints ``2.1.281 (Claude Code)``; ``claude
--help``, ``claude auth --help``, ``claude setup-token --help``), the Claude
Code documentation (CLI reference, headless mode, authentication, errors,
Agent SDK cost tracking) as of 2026-09-24, and the Agent SDK's ``sdk.d.ts``
at 0.3.276 (Claude Code 2.1.276), which types the stream-json messages:

- **Non-interactive run.** ``claude -p --output-format stream-json
  --verbose [OPTIONS] -- <prompt>`` runs one query and prints one JSON
  object per line on stdout, ending with a ``result`` message. The prompt
  goes after ``--`` because ``--mcp-config`` and ``--allowedTools`` take
  variadic values that would otherwise swallow it. ``--model`` picks the
  model; ``--variant`` maps to ``--effort <level>`` (low, medium, high,
  xhigh, max).
- **Events.** ``system``/``init`` (``session_id``, ``claude_code_version``,
  ``model``, ``tools``, ``mcp_servers``, ``permissionMode``,
  ``apiKeySource``); ``assistant`` (a Messages API ``message`` with ``id``,
  ``model``, ``content`` blocks such as ``tool_use`` with ``id`` and
  ``name``, and ``usage``; one frame per content block, so several frames
  share one ``message.id``, and ``parent_tool_use_id`` is set inside a
  subagent; an optional ``error`` category: ``rate_limit``, ``overloaded``,
  ``server_error``, ``authentication_failed``, ``billing_error``, ...);
  ``user`` (``tool_result`` blocks); ``system``/``api_retry``
  (``error_status``, ``error``); ``system``/``compact_boundary``;
  ``system``/``permission_denied`` (``tool_use_id``, ``tool_name``);
  ``rate_limit_event`` (``rate_limit_info``: ``status`` ``allowed``,
  ``allowed_warning`` or ``rejected``, ``resetsAt`` in epoch seconds,
  ``rateLimitType`` such as ``five_hour`` or ``seven_day``, ``utilization``
  as a 0-1 fraction, and overage fields); and ``result`` (``is_error``,
  ``api_error_status``, ``result`` text or ``errors``, ``session_id``,
  ``total_cost_usd``, ``usage``, ``modelUsage``, ``permission_denials``).
  MCP tools are named ``mcp__<server>__<tool>``; GM-Bench calls are
  ``mcp__gm-bench__<tool>`` and are recorded as ``gm-bench_<tool>`` so the
  ledger-versus-harness agreement counts them. Tool-use ids are unique
  across the session, so a call is counted once per id.
- **Usage.** ``modelUsage`` (per model: ``inputTokens`` uncached,
  ``cacheReadInputTokens``, ``cacheCreationInputTokens``, ``outputTokens``
  with ``thinkingTokens`` already inside it) covers every model call of the
  query, subagents and compaction included; ``usage`` covers only the main
  loop, so it is the fallback. Since Claude Code 2.1.277 a resumed session's
  result carries the session's whole total, restored from the transcript
  that a normal exit saved (before 2.1.277 each process counted only
  itself), so the episode's tokens are the last result per session on
  those versions and a sum of results before them, picked by each
  invocation's ``claude_code_version``. An invocation that was killed (the
  phase guard, the episode timeout, a parked quota stop) writes no result
  and saves no total, so its tokens are recovered from its assistant frames,
  counted once per ``message.id``: exact for input and cache tokens, but
  output there is a placeholder (the count at ``message_start``), so such
  an episode's output is a lower bound and ``usage_complete`` is false.
  ``model_calls`` counts distinct ``message.id`` values (API responses,
  subagents included); the largest single request's input (input plus cache
  reads and writes on one message) is exact. ``max_output_tokens_per_call``
  is left out (per-frame output is a placeholder). Compactions are counted
  from ``compact_boundary``.
- **Cost.** ``total_cost_usd`` and ``modelUsage.costUSD`` are Claude Code's
  client-side estimates from its bundled price table, "not a billing
  statement" by Anthropic's own documentation, and on a Claude subscription
  nothing is billed per token at all. So, as for Codex, ``cost_usd`` is
  ``None`` and the list-price estimate from ``pricing.json`` is published
  beside it as ``harness.api_equivalent_cost_usd`` (``cost_basis =
  "api-list-price-estimate"``, ``billed_by_harness = false``), priced per
  model in ``modelUsage`` (a subagent may run on another model). The
  harness's own estimate is kept as ``harness.harness_cost_estimate_usd``
  for comparison only. Cache writes are priced at the entry's 5-minute
  write rate; Claude Code writes 1-hour cache entries on a subscription and
  the stream does not split them out, so the estimate may be low there.
- **Resume.** ``claude -p --resume <session id> ... -- <text>`` continues the
  same session with its context and the same MCP configuration. The session
  id is the ``session_id`` of the latest ``system``/``init``. Session
  transcripts live under ``CLAUDE_CONFIG_DIR``, so
  ``--no-session-persistence`` is not used.
- **Errors and provider stalls.** A run that fails ends with a ``result``
  whose ``is_error`` is true. It is a provider stall when its
  ``api_error_status`` is 408, 425, 429, 5xx or 529, when an assistant frame
  of the invocation carries the ``rate_limit``, ``overloaded`` or
  ``server_error`` category, or when its text reads as a transient failure
  (``API Error: Repeated 529 Overloaded errors``, ``API Error: 500 Internal
  server error``, ``Request rejected (429)``, ``Server is temporarily
  limiting requests``, ``Request timed out``, ``API Error: No response from
  API``, ``Unable to connect to API``, a lost or stalled connection).
  Authentication, billing and context-window errors are not.
- **Usage limit (quota exhaustion).** A spent subscription window shows as a
  ``rate_limit_event`` with ``status`` ``rejected`` (not covered by overage)
  and, per the error reference, a message such as ``You've hit your session
  limit`` or ``You've hit your weekly limit``. Inside the Agent SDK a
  rejected window parks the turn (no further messages and no result; the
  observation is T3 Code's, ``apps/server/src/provider/Layers/ClaudeAdapter.ts``
  in github.com/pingdotgg/t3code, MIT License, Copyright (c) 2026 T3 Tools
  Inc., whose rule for what blocks is ported below). So the driver both
  reads the ending and polls the running invocation
  (:meth:`ClaudeDriver.invocation_parked`): an open rejection with no result
  yet stops the process, and :func:`quota_exhaustion` reports the reset from
  ``resetsAt`` (epoch seconds, so no time zone is involved), or none, in
  which case the shared loop stops the episode and the panel. ``Credit
  balance is too low`` (an API key out of credit) stops them the same way,
  with no reset. The streamed windows (latest ``utilization`` and
  ``resetsAt`` per ``rateLimitType``) are recorded as
  ``harness_run.quota_windows``, which feeds the panel's between-episode
  quota pause exactly as Codex's do.
- **Configuration and what is not inherited.** Claude Code keeps its
  settings, credentials (the macOS Keychain entry is keyed to the config
  directory), ``CLAUDE.md``, skills, plugins, hooks, auto memory, MCP servers
  and session transcripts under ``CLAUDE_CONFIG_DIR`` (default
  ``~/.claude``). The driver never uses the host's: in same-user isolation
  ``CLAUDE_CONFIG_DIR`` is a private directory (mode 0700) outside the
  scratch, removed when the episode ends, and ``HOME`` is the scratch
  directory itself; every other ``CLAUDE_*``, ``CLAUDECODE`` and
  ``ANTHROPIC_*`` variable is dropped from the harness environment (only
  the credential the driver hands off is set). ``--setting-sources user``
  loads only that private directory's settings (none are staged), so the
  scratch directory's ``.claude/settings.json`` and ``settings.local.json``, which the
  agent could write between invocations, are never loaded.
  ``--strict-mcp-config`` with ``--mcp-config <private>/mcp.json`` loads
  exactly one MCP server, ``gm-bench``: ``command`` is the harness's
  python3, ``args`` are ``gm_bench_proxy.py`` and the socket path, the same
  launch ``opencode_config`` declares. ``--disable-slash-commands`` turns
  off every skill and custom command, bundled ones included.
  ``CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`` stops the auto-updater (a
  harness that upgrades itself mid-panel would change the row identity),
  telemetry and error reporting. Machine-wide managed settings, if an
  administrator installed any, still apply; nothing can turn them off.
- **Permissions.** ``--permission-mode dontAsk`` with ``--allowedTools
  mcp__gm-bench,Bash,Read,Edit,Write,Glob,Grep,NotebookEdit`` and
  ``--permission-prompts none``: the GM-Bench tools and the code tools run
  without a prompt, and anything else (web fetch and search, any other MCP
  server) is denied at once and recorded (``permission_denials``), never
  waited on. ``bypassPermissions`` was not chosen: it switches off the
  permission layer for every tool, which the documentation recommends only
  for sandboxes without internet access; ``dontAsk`` approves exactly the
  tools the lane needs. Neither confines reads or shell commands to the
  scratch directory (a bare ``Bash`` rule allows any command), so same-user
  rows stay ``smoke`` grade exactly as OpenCode's and Codex's do.
- **Authentication.** Because ``CLAUDE_CONFIG_DIR`` is private, the host's
  ``/login`` (Keychain) credential is not found and is never read. The
  harness gets one credential, deliberately: ``--claude-token-file <path>``
  (a file holding a ``claude setup-token`` token, a one-year OAuth token
  that draws on the operator's Claude subscription and can only make model
  requests), handed to the harness as ``CLAUDE_CODE_OAUTH_TOKEN``; or, in
  same-user runs without the file, ``CLAUDE_CODE_OAUTH_TOKEN`` or else
  ``ANTHROPIC_API_KEY`` (API billing) from the operator's environment, never
  both. The value sits in the harness's environment, which the agent's
  shell inherits and can print: that is the harness's key, not the
  benchmark's, and gives no access to the seed. When the episode ends the
  driver replaces the value with ``[REDACTED]`` in ``claude-events.jsonl``
  and ``claude-stderr.log``. A kept scratch directory is not redacted.
  ``--bare`` is not used: it would drop the subscription token (bare mode
  reads only ``ANTHROPIC_API_KEY`` or ``apiKeyHelper``).
- **Container isolation** is refused. How a Claude credential should reach a
  container (a setup-token written into the home volume, an API key, or
  something else) is an open decision for the operator, so
  :meth:`ClaudeDriver.preflight` and :meth:`ClaudeDriver.ensure_image` stop
  before anything runs, and there is no Claude image.

Every Claude run spends the operator's Claude subscription quota or API
money, and the driver runs episodes serially: never run it in parallel.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from gm_bench.agentic import opencode
from gm_bench.agentic.codex import COST_BASIS, redact_file
from gm_bench.agentic.harness import HarnessDriver
from gm_bench.agentic.opencode import PROXY_FILENAME, HarnessLaunch, stage_proxy
from gm_bench.telemetry import api_equivalent_cost_usd

HARNESS_NAME = "claude"
MCP_CONFIG_FILENAME = "mcp.json"
MCP_SERVER_NAME = "gm-bench"
_MCP_PREFIX = "mcp__"
TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
API_KEY_ENV = "ANTHROPIC_API_KEY"
PERMISSION_MODE = "dontAsk"
# The GM-Bench server's tools and the code tools the agent may use in its scratch directory.
ALLOWED_TOOLS = (f"{_MCP_PREFIX}{MCP_SERVER_NAME}", "Bash", "Read", "Edit", "Write", "Glob", "Grep", "NotebookEdit")
# Only the private CLAUDE_CONFIG_DIR's settings; never the scratch's .claude/ (project, local).
SETTING_SOURCES = "user"
# Set in the harness environment: no auto-update mid-panel, no telemetry or error reports.
HARNESS_ENV = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
# From this version a resumed session's result carries the session's whole total.
RESUME_RESTORES_TOTALS = (2, 1, 277)
CONTAINER_REFUSAL = (
    "--isolation container is not available for --harness claude: how a Claude credential reaches the "
    "container (a setup-token in the episode's home volume, an API key, or something else) is an open "
    "decision for the operator, and no Claude image exists. Run --isolation same-user, which is smoke grade "
    "(docs/agentic_lane.md, Claude Code harness)"
)

# The ``api_error_status`` of a failed result that is a transient provider failure (529: overloaded).
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504, 529})
# Assistant-frame ``error`` categories (``SDKAssistantMessageError``) that are transient.
RETRYABLE_ERROR_CATEGORIES = frozenset({"rate_limit", "overloaded", "server_error"})
# A failed result's text that reads as a transient provider failure (the errors reference).
_RETRYABLE_MESSAGE_RE = re.compile(
    r"overloaded|rate[ _-]?limit|request rejected \(429\)|temporarily limiting requests"
    r"|api error:? (?:408|425|429|5\d\d)\b|internal server error|no response from api|unable to connect to api"
    r"|request timed out|connection (?:lost|closed)|response stalled|stopped arriving",
    re.IGNORECASE,
)
# A spent subscription window or spend limit (``You've hit your session limit``): never a stall.
USAGE_LIMIT_RE = re.compile(r"you(?:'|’)ve hit your\b[^.\n]*\b(?:limit|budget)\b|usage limit", re.IGNORECASE)
# An API key out of credit: no reset the driver can wait for.
CREDIT_RE = re.compile(r"credit balance is too low", re.IGNORECASE)

# ``rateLimitType`` to window length in minutes; ``overage`` is spend, not a window.
_WINDOW_MINUTES = {
    "five_hour": 5 * 60,
    "seven_day": 7 * 24 * 60,
    "seven_day_opus": 7 * 24 * 60,
    "seven_day_sonnet": 7 * 24 * 60,
    "seven_day_overage_included": 7 * 24 * 60,
}


# -- version and configuration ------------------------------------------------


def claude_version(binary: str = "claude") -> str | None:
    """The version ``claude --version`` reports (``2.1.281 (Claude Code)`` -> ``2.1.281``)."""
    try:
        completed = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"\b\d+\.\d+\.\d+\S*", completed.stdout or completed.stderr or "")
    return match.group(0) if match else None


def _version_tuple(version: Any) -> tuple[int, ...] | None:
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version) if isinstance(version, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def mcp_config(target: str | Path, *, python: str = "python3") -> dict[str, Any]:
    """The staged ``--mcp-config`` file as data: one stdio server and nothing else.

    It launches the proxy beside the agent's working directory on the
    harness's own python3, pointed at the socket path, exactly as
    ``opencode_config`` does.
    """
    server = {"type": "stdio", "command": python, "args": [PROXY_FILENAME, str(target)]}
    return {"mcpServers": {MCP_SERVER_NAME: server}}


def read_token_file(path: str | Path) -> str:
    """The operator's ``claude setup-token`` token, checked for shape without echoing any of it."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError(f"--claude-token-file {path} is not a file")
    try:
        token = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        raise ValueError(f"--claude-token-file {path} is not text; expected one `claude setup-token` token") from None
    if not token or any(character.isspace() for character in token):
        raise ValueError(f"--claude-token-file {path} must hold exactly one `claude setup-token` token on one line")
    return token


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


def _is_init(event: dict[str, Any]) -> bool:
    return event.get("type") == "system" and event.get("subtype") == "init"


def _invocations(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The events split per process: each invocation starts at its ``system``/``init``."""
    groups: list[list[dict[str, Any]]] = []
    for event in events:
        if _is_init(event) or not groups:
            groups.append([])
        groups[-1].append(event)
    return groups


def _tool_name(name: Any) -> str:
    """``mcp__gm-bench__get_status`` -> ``gm-bench_get_status``; built-ins keep their names."""
    name = str(name or "unknown")
    if name.startswith(_MCP_PREFIX):
        server, _, tool = name[len(_MCP_PREFIX) :].partition("__")
        return f"{server or 'unknown'}_{tool or 'unknown'}"
    return name


_TOKEN_KEYS = ("uncached", "cache_read", "cache_write", "output", "reasoning")


def _zero() -> dict[str, int]:
    return dict.fromkeys(_TOKEN_KEYS, 0)


def _model_usage(result: dict[str, Any], fallback_model: str) -> dict[str, dict[str, int]]:
    """Per-model tokens of one result: ``modelUsage``, else the main-loop ``usage``."""
    found: dict[str, dict[str, int]] = {}
    model_usage = result.get("modelUsage")
    if isinstance(model_usage, dict):
        for model, usage in model_usage.items():
            if not isinstance(usage, dict):
                continue
            found[str(model)] = {
                "uncached": opencode._int(usage.get("inputTokens")),
                "cache_read": opencode._int(usage.get("cacheReadInputTokens")),
                "cache_write": opencode._int(usage.get("cacheCreationInputTokens")),
                "output": opencode._int(usage.get("outputTokens")),
                "reasoning": opencode._int(usage.get("thinkingTokens")),
            }
    if not any(any(tokens.values()) for tokens in found.values()) and isinstance(result.get("usage"), dict):
        usage = result["usage"]
        found = {fallback_model: _frame_tokens(usage)}
    return found if any(any(tokens.values()) for tokens in found.values()) else {}


def _frame_tokens(usage: dict[str, Any]) -> dict[str, int]:
    """A Messages API ``usage`` object (input is uncached; output may be a placeholder on a frame)."""
    return {
        "uncached": opencode._int(usage.get("input_tokens")),
        "cache_read": opencode._int(usage.get("cache_read_input_tokens")),
        "cache_write": opencode._int(usage.get("cache_creation_input_tokens")),
        "output": opencode._int(usage.get("output_tokens")),
        "reasoning": 0,
    }


def _add(into: dict[str, dict[str, int]], tokens: dict[str, dict[str, int]]) -> None:
    for model, counts in tokens.items():
        target = into.setdefault(model, _zero())
        for key in _TOKEN_KEYS:
            target[key] += counts.get(key, 0)


def parse_claude_events(lines: list[str]) -> dict[str, Any]:
    """Fold ``claude -p --output-format stream-json`` output (every invocation of one episode) into telemetry.

    Same shape as ``opencode.parse_opencode_events``, plus ``tokens_by_model``
    (for the per-model estimate), ``max_request_input_tokens``, and what the
    stream could not report. Tool calls are counted once per ``tool_use``
    id, so a call cut off by a guard stop still counts: it reached the
    server. A call Claude Code denied before running it (a
    ``permission_denied`` event or an entry in ``permission_denials``)
    never reached the server; it is counted in ``harness_tool_calls_skipped``.
    Tokens: per session, the last result on a version that restores totals
    on resume, otherwise the sum of the results; plus, for an invocation
    that wrote no result, its assistant frames once per ``message.id``.
    """
    events = _events(lines)
    session_id: str | None = None
    sessions: dict[str | None, dict[str, dict[str, int]]] = {}
    session_cost: dict[str | None, float] = {}
    unreported: dict[str, dict[str, int]] = {}
    tool_uses: dict[str, str] = {}
    denied: set[str] = set()
    message_ids: set[str] = set()
    max_request_input: dict[str, int] = {}
    event_types: dict[str, int] = {}
    compactions = errors = api_retries = results = without_result = 0
    saw_cost = False

    for invocation in _invocations(events):
        init = invocation[0] if _is_init(invocation[0]) else {}
        version = _version_tuple(init.get("claude_code_version"))
        # Unknown version: the version the driver was written against, which restores totals.
        cumulative = version is None or version >= RESUME_RESTORES_TOTALS
        session = init.get("session_id") if isinstance(init.get("session_id"), str) else None
        frames: dict[str, tuple[str, dict[str, int]]] = {}
        result: dict[str, Any] | None = None
        for event in invocation:
            kind = str(event.get("type", ""))
            subtype = event.get("subtype")
            label = f"{kind}/{subtype}" if kind == "system" and subtype else kind
            event_types[label] = event_types.get(label, 0) + 1
            if isinstance(event.get("session_id"), str):
                session = session or event["session_id"]
            if kind == "system" and subtype == "compact_boundary":
                compactions += 1
            elif kind == "system" and subtype == "api_retry":
                api_retries += 1
            elif kind == "system" and subtype == "permission_denied" and event.get("tool_use_id"):
                denied.add(str(event["tool_use_id"]))
            elif kind == "assistant":
                message = event.get("message") if isinstance(event.get("message"), dict) else {}
                if event.get("error"):
                    errors += 1
                message_id = message.get("id")
                model = str(message.get("model") or init.get("model") or "unknown")
                if isinstance(message_id, str):
                    message_ids.add(message_id)
                    if isinstance(message.get("usage"), dict):
                        tokens = _frame_tokens(message["usage"])
                        frames[message_id] = (model, tokens)
                        request = tokens["uncached"] + tokens["cache_read"] + tokens["cache_write"]
                        max_request_input[model] = max(max_request_input.get(model, 0), request)
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id"):
                        tool_uses[str(block["id"])] = _tool_name(block.get("name"))
            elif kind == "result":
                result = event
        if session is not None:
            session_id = session
        if result is None:
            without_result += 1
        else:
            results += 1
            if result.get("is_error"):
                errors += 1
            for denial in result.get("permission_denials") or []:
                if isinstance(denial, dict) and denial.get("tool_use_id"):
                    denied.add(str(denial["tool_use_id"]))
        reported = _model_usage(result, str(init.get("model") or "unknown")) if result is not None else {}
        if reported:
            if cumulative:
                sessions[session] = reported
            else:
                _add(sessions.setdefault(session, {}), reported)
            cost = result.get("total_cost_usd") if result is not None else None
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                saw_cost = True
                session_cost[session] = float(cost) + (0.0 if cumulative else session_cost.get(session, 0.0))
        else:
            # Killed (no result) or a zeroed crash result: the frames are what is left.
            for model, tokens in frames.values():
                _add(unreported, {model: tokens})

    by_model: dict[str, dict[str, int]] = {}
    for tokens in sessions.values():
        _add(by_model, tokens)
    _add(by_model, unreported)
    by_model = {model: tokens for model, tokens in sorted(by_model.items()) if any(tokens.values())}

    tool_events: dict[str, int] = {}
    skipped: dict[str, int] = {}
    for tool_id, name in tool_uses.items():
        bucket = skipped if tool_id in denied else tool_events
        bucket[name] = bucket.get(name, 0) + 1

    def total(key: str) -> int:
        return sum(tokens[key] for tokens in by_model.values())

    return {
        "model_calls": len(message_ids),
        # The shared shape: input includes cache reads and writes; output includes thinking.
        "input_tokens": total("uncached") + total("cache_read") + total("cache_write"),
        "uncached_input_tokens": total("uncached"),
        "output_tokens": total("output"),
        "reasoning_tokens": total("reasoning"),
        "cached_input_tokens": total("cache_read"),
        "cache_write_tokens": total("cache_write"),
        "tokens_by_model": by_model,
        # The largest single API request's input, per model (exact: frame input and cache counts are final).
        "max_request_input_tokens": dict(sorted(max_request_input.items())),
        # Not observable: per-frame output_tokens is the placeholder from message_start.
        "max_output_tokens_per_call": None,
        # Claude Code's client-side estimate; never published as cost_usd.
        "cost_usd": None,
        "harness_cost_estimate_usd": round(sum(session_cost.values()), 6) if saw_cost else None,
        "harness_tool_events": dict(sorted(tool_events.items())),
        "harness_tool_calls_skipped": dict(sorted(skipped.items())),
        "compactions": compactions,
        "errors": errors,
        "api_retries": api_retries,
        "session_id": session_id,
        "event_types": dict(sorted(event_types.items())),
        "invocations_with_result": results,
        "invocations_without_result": without_result,
        # False when some invocation's tokens came from frames alone (output there is a lower bound).
        "usage_complete": not unreported,
    }


def _last_result(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("type") == "result":
            return event
    return None


def _result_text(result: dict[str, Any]) -> str:
    parts = [result.get("result")]
    parts.extend(result.get("errors") or [])
    return " ".join(part for part in parts if isinstance(part, str))


def _blocks(info: dict[str, Any]) -> bool:
    """A ``rate_limit_info`` that stops requests: rejected, and no provisioned overage carries on (T3 Code's rule)."""
    overage = (
        info.get("overageStatus") in ("allowed", "allowed_warning")
        or info.get("isUsingOverage") is True
        or info.get("overageInUse") is True
    )
    return info.get("status") == "rejected" and not overage


def _open_rejections(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Rejected windows not cleared by a later ``allowed`` report of the same type, by ``rateLimitType``."""
    rejected: dict[str, dict[str, Any]] = {}
    for event in events:
        info = event.get("rate_limit_info") if event.get("type") == "rate_limit_event" else None
        if not isinstance(info, dict):
            continue
        kind = str(info.get("rateLimitType") or "unknown")
        if _blocks(info):
            rejected[kind] = info
        else:
            # Allowed again, or rejected with overage carrying on.
            rejected.pop(kind, None)
    return rejected


def _utc(epoch: Any) -> str | None:
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or epoch <= 0:
        return None
    try:
        return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).replace(microsecond=0).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def quota_exhaustion(lines: list[str]) -> dict[str, Any] | None:
    """``{"message_class", "reset_at_utc"}`` when the invocation ended (or parked) on a spent window.

    ``usage_limit``: an open rejected window with no successful result, or a
    failed result whose text is a usage or spend limit; the reset is the
    latest ``resetsAt`` of the open rejections (``None`` when unknown).
    ``credit_balance``: an API key out of credit, which has no reset.
    """
    events = _events(lines)
    result = _last_result(events)
    failed = result is not None and bool(result.get("is_error"))
    text = _result_text(result) if failed and result is not None else ""
    if failed and CREDIT_RE.search(text):
        return {"message_class": "credit_balance", "reset_at_utc": None}
    rejections = _open_rejections(events)
    if not ((rejections and (result is None or failed)) or (failed and USAGE_LIMIT_RE.search(text))):
        return None
    resets = [info.get("resetsAt") for info in rejections.values()]
    resets = [value for value in resets if _utc(value) is not None]
    return {"message_class": "usage_limit", "reset_at_utc": _utc(max(resets)) if resets else None}


def ended_in_provider_stall(lines: list[str]) -> bool:
    """Whether one invocation ended on a retryable provider error.

    The invocation's result must be an error with a transient
    ``api_error_status`` (408, 425, 429, 5xx, 529), an assistant frame with
    a transient error category, or a transient message. A usage limit is
    quota exhaustion (:func:`quota_exhaustion`), never a stall; an
    invocation without a result is the harness stopping.
    """
    events = _events(lines)
    result = _last_result(events)
    if result is None or not result.get("is_error") or quota_exhaustion(lines) is not None:
        return False
    status = result.get("api_error_status")
    if isinstance(status, int) and not isinstance(status, bool) and status in RETRYABLE_STATUS_CODES:
        return True
    if any(event.get("type") == "assistant" and event.get("error") in RETRYABLE_ERROR_CATEGORIES for event in events):
        return True
    return bool(_RETRYABLE_MESSAGE_RE.search(_result_text(result)))


def quota_windows(lines: list[str]) -> list[dict[str, Any]]:
    """The subscription windows the stream reported: the latest ``utilization`` and reset per ``rateLimitType``."""
    latest: dict[str, dict[str, Any]] = {}
    for event in _events(lines):
        info = event.get("rate_limit_info") if event.get("type") == "rate_limit_event" else None
        if not isinstance(info, dict) or info.get("rateLimitType") not in _WINDOW_MINUTES:
            continue
        used = info.get("utilization")
        if isinstance(used, bool) or not isinstance(used, (int, float)):
            continue
        latest[info["rateLimitType"]] = {
            "window_minutes": _WINDOW_MINUTES[info["rateLimitType"]],
            # utilization is a 0-1 fraction on the stream.
            "used_percent": round(min(max(float(used) * 100.0, 0.0), 100.0), 2),
            "resets_at_utc": _utc(info.get("resetsAt")),
            "rate_limit_type": info["rateLimitType"],
        }
    return [latest[kind] for kind in _WINDOW_MINUTES if kind in latest]


def usage_block(telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
    """The shared usage block, labelled for what the Claude stream can and cannot report.

    ``cost_usd`` is ``None`` and ``cost_decisions`` 0: Claude Code's cost is a
    client-side estimate, and a subscription is not billed per token. Beside
    it, under ``harness``, sit the API-equivalent estimate at ``pricing.json``
    list prices (per model, cached input at the cached rate) and Claude Code's
    own estimate, both labelled as never billed.
    """
    usage = opencode.usage_block(telemetry, model=model, decisions=decisions, harness=HARNESS_NAME)
    usage["cost_usd"] = None
    usage["cost_decisions"] = 0
    usage["harness"].update(
        {
            "api_calls_are": "API responses (distinct assistant message ids, subagents included)",
            "models": sorted(telemetry.get("tokens_by_model") or {}),
            "usage_complete": telemetry.get("usage_complete", True),
            "invocations_without_result": telemetry.get("invocations_without_result", 0),
            "api_retries": telemetry.get("api_retries", 0),
            "cost_reported_by_harness": False,
            "harness_cost_estimate_usd": telemetry.get("harness_cost_estimate_usd"),
            # tool_use blocks Claude Code denied before running them; never in the ledger.
            "tool_calls_skipped": telemetry.get("harness_tool_calls_skipped") or {},
            **api_equivalent_fields(telemetry),
        }
    )
    return usage


def api_equivalent_fields(telemetry: dict[str, Any]) -> dict[str, Any]:
    """The ``harness`` estimate fields, priced per model; ``None`` values when any model with tokens is unpriced."""
    none = {
        "api_equivalent_cost_usd": None,
        "cost_basis": None,
        "billed_by_harness": False,
        "pricing_source": None,
        "long_context_requests_possible": None,
    }
    by_model = telemetry.get("tokens_by_model") or {}
    if not telemetry.get("model_calls") or not by_model:
        return none
    priced = []
    for model, tokens in sorted(by_model.items()):
        estimate = api_equivalent_cost_usd(
            {
                "input_tokens": tokens["uncached"] + tokens["cache_read"] + tokens["cache_write"],
                "cached_input_tokens": tokens["cache_read"],
                "cache_write_input_tokens": tokens["cache_write"],
                "output_tokens": tokens["output"],
                "max_request_input_tokens": (telemetry.get("max_request_input_tokens") or {}).get(model),
            },
            model,
        )
        if estimate is None:
            return none
        priced.append((model, estimate))
    sources = [
        {
            "model": model,
            "key": estimate["pricing_key"],
            "verified": estimate["verified"],
            "cached_input_rate": estimate["cached_input_rate"],
            "cache_write_rate": estimate["cache_write_rate"],
        }
        for model, estimate in priced
    ]
    flags = [estimate["long_context_requests_possible"] for _model, estimate in priced]
    return {
        "api_equivalent_cost_usd": round(sum(estimate["usd"] for _model, estimate in priced), 6),
        "cost_basis": COST_BASIS,
        "billed_by_harness": False,
        # One entry: the Codex shape. Several models (a subagent on another model): one entry per model.
        "pricing_source": {k: v for k, v in sources[0].items() if k != "model"}
        if len(sources) == 1
        else {"models": sources},
        "long_context_requests_possible": True
        if any(flags)
        else (None if any(flag is None for flag in flags) else False),
    }


# -- the driver ---------------------------------------------------------------


class ClaudeDriver(HarnessDriver):
    """The Claude Code CLI behind the shared episode loop (same-user isolation only)."""

    name = HARNESS_NAME
    default_binary = "claude"
    container_executable = "claude"
    image_version_key = "claude_version"
    polls_for_park = True

    def __init__(self, *, token_file: str | Path | None = None) -> None:
        self.token_file = Path(token_file).expanduser() if token_file is not None else None
        # Per launch (keyed by scratch directory): the private CLAUDE_CONFIG_DIR, the
        # credential value to redact from the evidence, and the quota windows read by ``collect``.
        self._homes: dict[Path, Path] = {}
        self._secrets: dict[Path, set[str]] = {}
        self._quota: dict[Path, list[dict[str, Any]]] = {}
        self._sources: dict[Path, str] = {}

    def auth_source(self, env: dict[str, str] | None = None) -> str:
        env = os.environ if env is None else env
        if self.token_file is not None:
            return "token-file"
        if env.get(TOKEN_ENV):
            return TOKEN_ENV
        return API_KEY_ENV if env.get(API_KEY_ENV) else "none"

    def preflight(self, isolation: str) -> None:
        if isolation == "container":
            raise ValueError(CONTAINER_REFUSAL)
        if self.token_file is not None:
            read_token_file(self.token_file)
            return
        if self.auth_source() == "none":
            raise ValueError(
                f"--harness claude needs credentials: pass --claude-token-file (a `claude setup-token` token) or set "
                f"{TOKEN_ENV} or {API_KEY_ENV}; the host's Claude Code login is deliberately not used"
            )

    def version(self, binary: str) -> str | None:
        return claude_version(binary)

    def ensure_image(self, *, docker: str, env: dict[str, str]) -> dict[str, Any]:
        raise ValueError(CONTAINER_REFUSAL)

    def environment(self, env: dict[str, str], scratch: Path, isolation: str) -> dict[str, str]:
        if isolation != "same-user":
            raise ValueError(CONTAINER_REFUSAL)
        source = self.auth_source(env)
        self._sources[scratch] = source
        # Exactly one credential reaches the harness: the file's token, else the operator's
        # subscription token, else their API key.
        credential: tuple[str, str] | None = None
        if self.token_file is not None:
            credential = (TOKEN_ENV, read_token_file(self.token_file))
        elif source in (TOKEN_ENV, API_KEY_ENV):
            credential = (source, env[source])
        for key in tuple(env):
            if key.startswith(("CLAUDE_", "ANTHROPIC_")) or key == "CLAUDECODE":
                env.pop(key)
        # No host ~/.claude (settings, login, CLAUDE.md, skills, plugins, hooks, memory,
        # sessions): HOME is the scratch directory and CLAUDE_CONFIG_DIR a private
        # directory outside it, so neither the transcripts nor the config sit in the
        # agent's working directory.
        home = Path(tempfile.mkdtemp(prefix="gmb-claude-"))
        self._homes[scratch] = home
        env["HOME"] = str(scratch)
        env["CLAUDE_CONFIG_DIR"] = str(home)
        env.update(HARNESS_ENV)
        if credential is not None:
            env[credential[0]] = credential[1]
            self._secrets.setdefault(scratch, set()).add(credential[1])
        return env

    def _config(self, launch: HarnessLaunch) -> dict[str, Any]:
        return mcp_config(launch.proxy_target, python=launch.proxy_python)

    def stage(self, launch: HarnessLaunch) -> None:
        stage_proxy(launch.scratch, secret=launch.secret)
        path = self._homes[launch.scratch] / MCP_CONFIG_FILENAME
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(self._config(launch), handle, indent=2)

    def _options(self, model: str, variant: str | None, workdir: str) -> list[str]:
        config = self._homes[Path(workdir)] / MCP_CONFIG_FILENAME
        options = [
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            # Variadic: the next option ends its value list.
            "--mcp-config",
            str(config),
            "--strict-mcp-config",
            "--setting-sources",
            SETTING_SOURCES,
            "--disable-slash-commands",
            "--allowedTools",
            ",".join(ALLOWED_TOOLS),
            "--permission-mode",
            PERMISSION_MODE,
            "--permission-prompts",
            "none",
            "--model",
            model,
        ]
        if variant:
            options += ["--effort", variant]
        return options

    def run_args(self, *, model: str, variant: str | None, workdir: str, brief: str, isolation: str) -> list[str]:
        return [*self._options(model, variant, workdir), "--", brief]

    def resume_args(
        self, *, model: str, variant: str | None, workdir: str, session_id: str, text: str, isolation: str
    ) -> list[str]:
        return [*self._options(model, variant, workdir), "--resume", session_id, "--", text]

    def parse_events(self, lines: list[str]) -> dict[str, Any]:
        return parse_claude_events(lines)

    def ended_in_provider_stall(self, lines: list[str]) -> bool:
        return ended_in_provider_stall(lines)

    def quota_exhausted(self, lines: list[str], *, isolation: str, now: float) -> dict[str, Any] | None:
        return quota_exhaustion(lines)

    def invocation_parked(self, lines: list[str]) -> bool:
        events = _events(lines)
        return bool(_open_rejections(events)) and _last_result(events) is None

    def usage_block(self, telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
        return usage_block(telemetry, model=model, decisions=decisions)

    def collect(self, launch: HarnessLaunch) -> None:
        events = launch.evidence_paths[0] if launch.evidence_paths else None
        lines = events.read_text(encoding="utf-8").splitlines() if events is not None and events.is_file() else []
        self._quota[launch.scratch] = quota_windows(lines)

    def run_record(self, launch: HarnessLaunch) -> dict[str, Any]:
        return {
            # The subscription's windows as the stream last reported them (empty for an
            # API key, which reports none); the stream names no plan.
            "quota_windows": self._quota.pop(launch.scratch, []),
            "plan_type": None,
            # The whole staged MCP config; it names only the proxy and where it connects.
            "harness_config": json.dumps(self._config(launch), indent=2),
            "claude_config_dir": "private directory outside the scratch (removed at episode end)",
            "permission_mode": PERMISSION_MODE,
            "allowed_tools": list(ALLOWED_TOOLS),
            "setting_sources": SETTING_SOURCES,
            "auth": self._sources.pop(launch.scratch, "none"),
            "session_resume": "claude -p --resume",
        }

    def cleanup(self, launch: HarnessLaunch) -> None:
        # The config dir (transcripts, any credential Claude Code stored) never outlives
        # the episode, even with --keep-scratch, and no credential value stays in the evidence.
        secrets = self._secrets.pop(launch.scratch, set())
        home = self._homes.pop(launch.scratch, None)
        if home is not None:
            shutil.rmtree(home, ignore_errors=True)
        for path in launch.evidence_paths:
            redact_file(path, secrets)


# -- entry points -------------------------------------------------------------


def run_episode(
    seed: int,
    *,
    binary: str = "claude",
    token_file: str | Path | None = None,
    driver: ClaudeDriver | None = None,
    isolation: str = "same-user",
    **kwargs: Any,
) -> dict[str, Any]:
    """``opencode.run_episode`` with the Claude Code driver."""
    driver = driver if driver is not None else ClaudeDriver(token_file=token_file)
    driver.preflight(isolation)
    return opencode.run_episode(seed, binary=binary, driver=driver, isolation=isolation, **kwargs)


def run_panel(
    seeds: list[int], *, binary: str = "claude", token_file: str | Path | None = None, **kwargs: Any
) -> dict[str, Any]:
    """``opencode.run_panel`` with the Claude Code driver; seeds run serially."""
    return opencode.run_panel(seeds, binary=binary, driver=ClaudeDriver(token_file=token_file), **kwargs)
