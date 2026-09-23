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
  every process, so tool events are counted per invocation.
- **Usage is a running session total.** ``turn.completed.usage`` is the
  thread's cumulative token count (``usage_from_last_total``), and a resumed
  session restores that total from its saved rollout
  (``last_token_info_from_rollout``), so the episode total is the last
  ``turn.completed`` per thread, not a sum over invocations. A final
  invocation that fails before completing its turn is not in that total.
  ``input_tokens`` includes ``cached_input_tokens``. The stream reports no
  cost, no per-model-call records and no compaction events, so
  ``cost_usd`` is ``None`` (the usage block then falls back to
  ``gm_bench/pricing.json`` list prices where the model is priced, which
  overstates cost for cached input and for a ChatGPT subscription, which is
  not billed per token), ``api_calls`` counts completed turns, and
  ``compactions`` is ``None`` (unmeasured, not zero).
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
  ``Selected model is at capacity``, or ``You've hit your usage limit ...
  try again at ...``. Those map into the shared provider-stall retry;
  ``Quota exceeded``, a 401, or a context-window error do not.
- **Configuration and what is not inherited.** ``CODEX_HOME`` (default
  ``~/.codex``) holds ``config.toml``, ``auth.json``, the session store,
  ``AGENTS.md``, skills, rules and plugins. The driver never uses the host's:
  in same-user isolation ``CODEX_HOME`` is ``<scratch>/.codex`` and ``HOME``
  is the scratch directory itself, because Codex also loads user skills from
  ``$HOME/.agents/skills``; in a container the harness home is the
  per-episode volume (``/home/node/.codex``). Every other ``CODEX_*``
  variable is dropped from the harness environment. The staged
  ``config.toml`` holds exactly one MCP server entry, ``[mcp_servers.gm-bench]``
  with ``command`` (the harness's python3) and ``args``
  (``gm_bench_proxy.py`` and the socket path or ``host:port``), the same
  launch ``opencode_config`` declares. Codex reports those calls as
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
  to ``<scratch>/.codex/auth.json``, mode 0600, and deleted when the episode
  ends even with ``--keep-scratch``) or ``CODEX_API_KEY`` in the operator's
  environment. Container runs pass no environment, so they need
  ``--codex-auth-file``: the file travels on the stdin of a throwaway
  ``docker run`` into the per-episode home volume (``ContainerHarness.seed_home``),
  never onto a command line, an environment variable, or the bind-mounted
  scratch directory, and is removed with the volume. The agent can read its
  own harness's credential (as it can read the proxy secret): that is the
  harness's key, not the benchmark's, and it gives no access to the seed.
  A ChatGPT ``auth.json`` carries a refresh token that Codex may rotate
  inside the episode; an API-key ``auth.json``
  (``{"auth_mode": "apikey", "OPENAI_API_KEY": "..."}``) does not have that
  problem.

Every Codex run spends the operator's OpenAI quota or money, and the driver
runs episodes serially: never run it in parallel.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from gm_bench.agentic import opencode
from gm_bench.agentic.container import CODEX_IMAGE, HOME, ensure_image
from gm_bench.agentic.harness import HarnessDriver
from gm_bench.agentic.opencode import PROXY_FILENAME, HarnessLaunch, stage_proxy

HARNESS_NAME = "codex"
CODEX_HOME_DIRNAME = ".codex"
CONFIG_FILENAME = "config.toml"
AUTH_FILENAME = "auth.json"
MCP_SERVER_NAME = "gm-bench"
AUTH_ENV = "CODEX_API_KEY"
SAME_USER_SANDBOX = "workspace-write"
CONTAINER_SANDBOX = "danger-full-access"
CONTAINER_CODEX_HOME = f"{HOME}/{CODEX_HOME_DIRNAME}"

# A terminal ``turn.failed``/``error`` message that reads as a transient provider failure.
_RETRYABLE_MESSAGE_RE = re.compile(
    r"rate limit|too many requests|status:?\s+(?:408|425|429|5\d\d)\b|stream disconnected|high demand"
    r"|at capacity|overloaded|connection failed|error while reading the server response|request timed out"
    r"|usage limit|try again",
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
    exactly as ``opencode_config`` does.
    """
    return {"mcp_servers": {MCP_SERVER_NAME: {"command": python, "args": [PROXY_FILENAME, str(target)]}}}


def codex_config_toml(config: dict[str, Any]) -> str:
    """Render :func:`codex_config` as TOML (JSON string escapes are valid TOML basic strings)."""
    lines: list[str] = []
    for name, server in config["mcp_servers"].items():
        lines.append(f"[mcp_servers.{name}]")
        lines.append(f"command = {json.dumps(server['command'])}")
        lines.append(f"args = [{', '.join(json.dumps(arg) for arg in server['args'])}]")
    return "\n".join(lines) + "\n"


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
    Tokens are the last ``turn.completed`` usage per thread, because that
    usage is the thread's running total. ``model_calls`` counts completed
    turns (the stream has no per-call records), cost and compactions are not
    reported (``None``).
    """
    session_id: str | None = None
    thread: str | None = None
    totals: dict[str | None, dict[str, Any]] = {}
    tool_events: dict[str, int] = {}
    invocation_items: dict[str, str] = {}
    turns_started = turns_completed = turns_failed = errors = 0
    event_types: dict[str, int] = {}

    def close_invocation() -> None:
        for name in invocation_items.values():
            tool_events[name] = tool_events.get(name, 0) + 1
        invocation_items.clear()

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
                totals[thread] = event["usage"]
        elif kind == "turn.failed":
            turns_failed += 1
            errors += 1
        elif kind == "error":
            errors += 1
        elif kind in ("item.started", "item.updated", "item.completed"):
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            name = _tool_name(item)
            if name is not None:
                invocation_items[str(item.get("id"))] = name
    close_invocation()

    def total(key: str) -> int:
        return sum(opencode._int(usage.get(key)) for usage in totals.values())

    return {
        "model_calls": turns_completed,
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "reasoning_tokens": total("reasoning_output_tokens"),
        "cached_input_tokens": total("cached_input_tokens"),
        "cache_write_tokens": total("cache_write_input_tokens"),
        # Not observable: the stream has no per-call records.
        "max_output_tokens_per_call": 0,
        "cost_usd": None,
        "harness_tool_events": dict(sorted(tool_events.items())),
        # Not observable: ``codex exec --json`` emits no compaction event.
        "compactions": None,
        "errors": errors,
        "session_id": session_id,
        "event_types": dict(sorted(event_types.items())),
        "turns_started": turns_started,
        "turns_failed": turns_failed,
    }


def ended_in_provider_stall(lines: list[str]) -> bool:
    """Whether one invocation ended on a retryable provider error.

    The last event must be ``turn.failed`` (``error.message``) or ``error``
    (``message``) whose message reads as a transient failure (a 408, 425, 429
    or 5xx status, a rate or usage limit, an overload or capacity notice, a
    dropped stream or connection, or a timeout). Any other ending is the
    agent or the harness stopping.
    """
    events = _events(lines)
    if not events:
        return False
    last = events[-1]
    if last.get("type") == "turn.failed":
        error = last.get("error") if isinstance(last.get("error"), dict) else {}
        message = error.get("message")
    elif last.get("type") == "error":
        message = last.get("message")
    else:
        return False
    return isinstance(message, str) and bool(_RETRYABLE_MESSAGE_RE.search(message))


def usage_block(telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
    """The shared usage block, labelled for what the Codex stream can and cannot report."""
    usage = opencode.usage_block(telemetry, model=model, decisions=decisions, harness=HARNESS_NAME)
    usage["harness"].update(
        {
            "api_calls_are": "completed turns",
            "turns_started": telemetry.get("turns_started", 0),
            "turns_failed": telemetry.get("turns_failed", 0),
            "cost_reported_by_harness": False,
        }
    )
    return usage


# -- the driver ---------------------------------------------------------------


class CodexDriver(HarnessDriver):
    """The Codex CLI behind the shared episode loop."""

    name = HARNESS_NAME
    default_binary = "codex"
    container_executable = "codex"
    image_version_key = CODEX_IMAGE.version_key

    def __init__(self, *, auth_file: str | Path | None = None) -> None:
        self.auth_file = Path(auth_file).expanduser() if auth_file is not None else None

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
            # host ~/.agents/skills: the harness's home is the scratch directory.
            env["HOME"] = str(scratch)
            env["CODEX_HOME"] = str(scratch / CODEX_HOME_DIRNAME)
        return env

    def _config_text(self, launch: HarnessLaunch) -> str:
        return codex_config_toml(codex_config(launch.proxy_target, python=launch.proxy_python))

    def stage(self, launch: HarnessLaunch) -> None:
        stage_proxy(launch.scratch, secret=launch.secret)
        files = {f"{CODEX_HOME_DIRNAME}/{CONFIG_FILENAME}": self._config_text(launch).encode("utf-8")}
        if self.auth_file is not None:
            files[f"{CODEX_HOME_DIRNAME}/{AUTH_FILENAME}"] = read_auth_file(self.auth_file)
        if launch.container is not None:
            # Into the episode's home volume over stdin; never the bind-mounted scratch.
            launch.container.seed_home(files)
            return
        home = launch.scratch / CODEX_HOME_DIRNAME
        home.mkdir(mode=0o700)
        for name, data in files.items():
            path = launch.scratch / name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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

    def usage_block(self, telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
        return usage_block(telemetry, model=model, decisions=decisions)

    def run_record(self, launch: HarnessLaunch) -> dict[str, Any]:
        container = launch.container is not None
        return {
            # The whole staged config; it names only the proxy and where it connects.
            "harness_config": self._config_text(launch),
            "codex_home": f"{CONTAINER_CODEX_HOME} (episode volume)" if container else CODEX_HOME_DIRNAME,
            "sandbox_mode": CONTAINER_SANDBOX if container else SAME_USER_SANDBOX,
            "auth": self.auth_source(launch.isolation),
            "session_resume": "codex exec resume",
        }

    def cleanup(self, launch: HarnessLaunch) -> None:
        # The credential never outlives the episode, even with --keep-scratch.
        (launch.scratch / CODEX_HOME_DIRNAME / AUTH_FILENAME).unlink(missing_ok=True)


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
