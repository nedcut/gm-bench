"""OpenCode harness driver for GM-Bench 2.0.

Per episode the driver:

1. builds the episode engine in this process (the seed never touches a file
   the agent can find) and serves it as an MCP server over a private Unix
   socket, or, with the harness in a container, over a loopback TCP port
   that only accepts connections presenting a per-run secret;
2. creates an empty scratch directory holding only a standard-library proxy
   script and an ``opencode.json`` that launches it on the harness's own
   python3, with code mode off so one model tool call is one ledger entry;
3. proves the sandbox: no GM-Bench checkout above the scratch directory and
   ``gm_bench`` not importable from the harness's own environment;
4. runs ``opencode run --format json`` with the task brief, capturing its
   event stream, and nudges the session if it stops early;
5. closes any phase the harness walked away from as a failed decision, joins
   the harness's token telemetry, and scores.

The harness environment is the operator's environment minus private-seed
material, Python path overrides and the interpreter's virtualenv, so the
agent's shell cannot import the simulator. Nothing readable from the scratch
directory names the seed, the interpreter, or the repository.

``isolation`` says how the harness is separated from the driver, and the run
records what was actually done: ``same-user`` (a child process of the driver,
whose ``ps`` can show the driver's command line) or ``container`` (Docker,
see ``container.py``). Publication refuses to claim more than that record.

This module also holds the episode loop every harness shares (the server,
sandbox check, nudges, provider-stall retries, phase-guard watch, and
finalization). What differs per harness is a ``harness.HarnessDriver``:
:data:`OPENCODE_DRIVER` here, ``codex.CodexDriver`` for the Codex CLI,
``claude.ClaudeDriver`` for Claude Code.
``run_episode`` and ``run_panel`` take a ``driver`` and default to OpenCode.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

import gm_bench
from gm_bench.agentic import _proxy
from gm_bench.agentic.brief import nudge_message, task_brief
from gm_bench.agentic.container import (
    HOST_ALIAS,
    WORKDIR,
    ContainerHarness,
    container_egress_problems,
    container_sandbox_problems,
    ensure_image,
)
from gm_bench.agentic.contract import agentic_contract
from gm_bench.agentic.episode import DEFAULT_PHASE_GUARD_SECONDS, AgenticEpisode
from gm_bench.agentic.harness import HarnessDriver
from gm_bench.agentic.mcp_server import EPISODE_ENV, SocketMcpServer
from gm_bench.agents import external_agent_environment
from gm_bench.protocol import PHASES
from gm_bench.runner import summarize_episodes
from gm_bench.simulator import League
from gm_bench.telemetry import aggregate_usage

HARNESS_NAME = "opencode"
DEFAULT_MAX_NUDGES = 20
# A provider that throttles or fails transiently ends OpenCode's run the same
# way a model that stops does. When a run's last event is such an error (a
# "provider stall") the driver waits and resumes the session instead of
# counting the relaunch as a nudge: exponential backoff from 60 s, doubling,
# capped at 600 s, at most 48 retries and 6 hours of waiting per episode, so a
# run can wait out a provider's quota window (the wait is off the phase guard
# clock). Past either budget a stall is treated like any other harness exit.
PROVIDER_STALL_BACKOFF_START_SECONDS = 60.0
PROVIDER_STALL_BACKOFF_CAP_SECONDS = 600.0
DEFAULT_MAX_PROVIDER_STALLS = 48
DEFAULT_MAX_PROVIDER_STALL_WAIT_SECONDS = 6 * 3600.0
# Before the next episode, a subscription window at or above this share used
# (percent, as the harness reports it in ``harness_run.quota_windows``) pauses
# the panel until the window resets, plus QUOTA_RESET_MARGIN_SECONDS.
QUOTA_PAUSE_PERCENT = 95.0
QUOTA_RESET_MARGIN_SECONDS = 60.0
# How often the loop polls a running harness for the phase guard (and a parked invocation).
HARNESS_POLL_SECONDS = 5.0
# OpenCode retries a 429 inside the harness and prints nothing to its event
# stream while it does, so a rate-limited harness looks hung: no event, no
# tool call. An invocation that has appended no byte to the event stream and
# made no ledger tool call for this long since launch is a "silent harness":
# the driver stops it and treats it as a provider stall (backoff, retry, off
# the phase clock). Any event at all, even ``step_start`` for a slow first
# model call, means it is not silent; the phase guard stays the backstop for
# a harness that emits events but makes no tool call. 0 disables it.
SILENT_HARNESS_SECONDS = 240.0
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_RETRYABLE_MESSAGE_RE = re.compile(r"rate[ _-]?limit|overloaded|try again later", re.IGNORECASE)
# What the driver itself can do. ``separate-user`` is a valid statement in a
# published row (publication.ISOLATION_LEVELS) but no driver launches it yet.
DRIVER_ISOLATION = ("same-user", "container")
REPO_ROOT = Path(gm_bench.__file__).resolve().parent.parent
_SCRUBBED_ENV_VARS = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSAFEPATH", EPISODE_ENV)

ProgressCallback = Callable[[dict[str, Any]], None]


class SandboxError(RuntimeError):
    """The scratch environment could reach the simulator; the run must not start."""


# -- environment and sandbox --------------------------------------------------


def harness_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment the harness (and therefore the agent's shell) runs in."""
    env = external_agent_environment(dict(base) if base is not None else None)
    for key in _SCRUBBED_ENV_VARS:
        env.pop(key, None)
    for key in tuple(env):
        if key.startswith("GM_BENCH_"):
            env.pop(key)
    venv_bins = set()
    if sys.prefix != sys.base_prefix:
        venv_bins.add(str(Path(sys.prefix) / "bin"))
        venv_bins.add(str(Path(sys.prefix) / "Scripts"))
    parts = []
    for entry in env.get("PATH", "").split(os.pathsep):
        if not entry or entry in venv_bins:
            continue
        try:
            if Path(entry).resolve().is_relative_to(REPO_ROOT):
                continue
        except OSError:
            pass
        parts.append(entry)
    env["PATH"] = os.pathsep.join(parts)
    return env


def sandbox_problems(scratch: Path, env: dict[str, str]) -> list[str]:
    """Everything wrong with launching a harness in ``scratch`` under ``env``."""
    problems: list[str] = []
    scratch = scratch.resolve()
    if scratch.is_relative_to(REPO_ROOT):
        problems.append(f"scratch directory {scratch} is inside the GM-Bench checkout {REPO_ROOT}")
    for ancestor in (scratch, *scratch.parents):
        if (ancestor / "gm_bench" / "simulator.py").exists():
            problems.append(f"{ancestor} contains a gm_bench package above the scratch directory")
    if any(scratch.iterdir()):
        problems.append(f"scratch directory {scratch} is not empty")
    for name in ("python3", "python"):
        interpreter = shutil.which(name, path=env.get("PATH", ""))
        if interpreter is None:
            continue
        probe = subprocess.run(
            [interpreter, "-c", "import gm_bench"],
            cwd=scratch,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if probe.returncode == 0:
            problems.append(f"{interpreter} can import gm_bench from the harness environment")
    return problems


# -- configuration ------------------------------------------------------------


PROXY_FILENAME = "gm_bench_proxy.py"


def harness_python(env: dict[str, str]) -> str:
    """The interpreter the proxy runs on: the harness's own python3, never ours.

    Our interpreter's path would name the checkout or its virtualenv. The
    proxy is standard-library only, so any python3 on the harness PATH will
    do; the sandbox check has already proven that one cannot import gm_bench.
    """
    return (
        shutil.which("python3", path=env.get("PATH", ""))
        or shutil.which("python", path=env.get("PATH", ""))
        or "python3"
    )


def opencode_config(target: str | Path, *, python: str = "python3") -> dict[str, Any]:
    """The ``opencode.json`` written into the scratch directory.

    Everything in it is readable by the agent, so it names only the proxy
    script beside it and where the proxy connects: a socket path, or
    ``host:port`` for a containerized harness.
    """
    return {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "servers": {
                "gm-bench": {
                    "type": "local",
                    "command": [python, PROXY_FILENAME, str(target)],
                    "codemode": False,
                }
            }
        },
    }


def stage_scratch(
    scratch: Path,
    target: str | Path,
    env: dict[str, str],
    *,
    python: str | None = None,
    secret: str | None = None,
) -> None:
    """Write the proxy and the config into an otherwise empty scratch directory.

    ``secret`` (TCP transport only) is written beside the proxy, where the
    proxy reads it; it is never on any command line.
    """
    stage_proxy(scratch, secret=secret)
    config = opencode_config(target, python=python or harness_python(env))
    (scratch / "opencode.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def stage_proxy(scratch: Path, *, secret: str | None = None) -> None:
    """Copy the standard-library proxy into the scratch directory, and its secret beside it (TCP only)."""
    (scratch / PROXY_FILENAME).write_text(Path(_proxy.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    if secret is not None:
        secret_path = scratch / _proxy.SECRET_FILENAME
        secret_path.write_text(secret + "\n", encoding="utf-8")
        secret_path.chmod(0o600)


class HarnessLaunch:
    """Where the harness runs for one episode, and how the driver reaches it.

    ``same-user``: the harness is a child process of the driver in an empty
    scratch directory, and the proxy dials a Unix socket (mode 0600) in a
    private directory of its own. ``container``: the harness runs in Docker
    with only the scratch directory mounted, and the proxy dials a loopback
    TCP port on the host with a per-run secret (``container.py``). What the
    harness itself needs staged, and how it is invoked, comes from ``driver``
    (OpenCode by default).
    """

    def __init__(
        self,
        episode: AgenticEpisode,
        *,
        binary: str = "opencode",
        isolation: str = "same-user",
        image: dict[str, Any] | None = None,
        docker: str = "docker",
        scratch_prefix: str = "gm-bench-agentic-",
        driver: HarnessDriver | None = None,
        evidence_paths: tuple[Path, ...] = (),
    ) -> None:
        if isolation not in DRIVER_ISOLATION:
            raise ValueError(f"isolation must be one of {DRIVER_ISOLATION}, not {isolation!r}")
        if isolation == "container" and image is None:
            raise ValueError("container isolation needs the image description from container.ensure_image")
        self.driver = driver if driver is not None else OPENCODE_DRIVER
        self.isolation = isolation
        self.binary = binary
        self.docker = docker
        # Run-directory files the harness writes (its event stream and stderr),
        # for a driver whose ``cleanup`` must redact them.
        self.evidence_paths = evidence_paths
        self.container: ContainerHarness | None = None
        self.scratch = Path(tempfile.mkdtemp(prefix=scratch_prefix))
        self._socket_dir: Path | None = None
        self._secret: str | None = None
        # Containers or volumes ``close`` could not remove (container mode only).
        self.cleanup_problems: list[str] = []
        try:
            self.env = self.driver.environment(harness_environment(), self.scratch, isolation)
            if isolation == "container":
                assert image is not None
                self._secret = secrets.token_urlsafe(32)
                self.server = SocketMcpServer(episode, ("127.0.0.1", 0), secret=self._secret)
                self.server.start()
                self.container = ContainerHarness(
                    image, self.scratch, driver_port=self.server.address[1], docker=docker, env=self.env
                )
                self.workdir = WORKDIR
                self.transport = "tcp"
            else:
                # The socket lives in its own private directory with a short
                # path (macOS caps Unix socket paths at 104 bytes) and mode
                # 0600, outside the scratch.
                self._socket_dir = Path(tempfile.mkdtemp(prefix="gmb-"))
                self.server = SocketMcpServer(episode, self._socket_dir / "s")
                self.server.start()
                self.workdir = str(self.scratch)
                self.transport = "unix"
        except BaseException:
            server = getattr(self, "server", None)
            if server is not None:
                server.stop()
            # The original error is the one to raise.
            with contextlib.suppress(Exception):
                self.driver.cleanup(self)
            for directory in (self._socket_dir, self.scratch):
                if directory is not None:
                    shutil.rmtree(directory, ignore_errors=True)
            raise

    def prepare(self) -> None:
        """Prove the sandbox, then stage the proxy and config. Raises ``SandboxError``."""
        if self.container is not None:
            # Nothing on the host PATH runs in the container, so the host half
            # of the check is only about the scratch directory itself.
            problems = sandbox_problems(self.scratch, {"PATH": ""})
            problems += container_sandbox_problems(self.container.image, docker=self.docker, env=self.env)
            problems += container_egress_problems(
                self.container.image, self.container.driver_port, docker=self.docker, env=self.env
            )
        else:
            problems = sandbox_problems(self.scratch, self.env)
        if problems:
            raise SandboxError("; ".join(problems))
        self.driver.stage(self)

    @property
    def proxy_target(self) -> str:
        """What the staged proxy dials: the socket path, or ``host:port`` from inside the container."""
        if self.container is not None:
            return f"{HOST_ALIAS}:{self.server.address[1]}"
        return str(self.server.address)

    @property
    def proxy_python(self) -> str:
        """The interpreter the harness launches the proxy on: the container's, or the harness PATH's."""
        return "python3" if self.container is not None else harness_python(self.env)

    @property
    def secret(self) -> str | None:
        """The TCP transport's per-run secret; ``None`` on the Unix socket."""
        return self._secret

    def command(self, harness_args: list[str]) -> tuple[list[str], Callable[[], None] | None]:
        """The full host command for one harness invocation, and how to stop it if it is killed.

        Called once per invocation, just before it starts, so the driver's
        :meth:`HarnessDriver.before_invocation` runs here.
        """
        self.driver.before_invocation(self)
        if self.container is None:
            return [self.binary, *harness_args], None
        container = self.container
        argv, name = container.command([self.driver.container_executable, *harness_args])
        return argv, lambda: container.kill(name)

    def close(self, *, keep_scratch: bool = False) -> bool:
        """Stop the server (returns whether it drained), the containers, and remove temporary state."""
        try:
            drained = self.server.stop()
            # Before the home (a private directory or the container's volume) goes.
            with contextlib.suppress(Exception):
                self.driver.collect(self)
            if self.container is not None:
                self.cleanup_problems = self.container.close()
                for problem in self.cleanup_problems:
                    sys.stderr.write(f"gm-bench agentic: cleanup: {problem}\n")
        finally:
            try:
                self.driver.cleanup(self)
            finally:
                if self._socket_dir is not None:
                    shutil.rmtree(self._socket_dir, ignore_errors=True)
            if not keep_scratch:
                shutil.rmtree(self.scratch, ignore_errors=True)
        return drained


def opencode_version(binary: str = "opencode") -> str | None:
    try:
        completed = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (completed.stdout or completed.stderr).strip()
    return text.splitlines()[-1].strip() if text else None


# -- telemetry ----------------------------------------------------------------


def parse_opencode_events(lines: list[str]) -> dict[str, Any]:
    """Fold OpenCode's newline-delimited JSON event stream into telemetry.

    ``step_finish`` parts carry ``tokens`` ({input, output, reasoning,
    cache:{read, write}}) and ``cost``; each one is one model call. Tool
    parts are counted by tool name. Anything unrecognized is ignored, and the
    raw stream is kept on disk beside the result for later inspection.

    OpenCode's ``tokens.input`` is uncached input only and ``tokens.output``
    excludes reasoning (``getUsage`` in ``packages/opencode/src/session/session.ts``
    subtracts both). The telemetry is normalized to the shape every harness
    publishes (:data:`TOKEN_SHAPE`): ``input_tokens`` is the inclusive total
    (``input + cache.read + cache.write``), ``output_tokens`` includes
    reasoning (``output + reasoning``), and ``reasoning_tokens`` is a subset of
    it, never added on top. This is the accumulation T3 Code's OpenCode
    adapter does (``accumulateOpenCodeStepUsage``, MIT, Copyright (c) 2026 T3
    Tools Inc.). ``max_output_tokens_per_call`` is likewise per step, reasoning
    included.
    """
    totals = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    cost = 0.0
    saw_cost = False
    steps = 0
    max_output = 0
    tool_events: dict[str, int] = {}
    compactions = 0
    errors = 0
    session_id = None
    event_types: dict[str, int] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type", ""))
        event_types[kind] = event_types.get(kind, 0) + 1
        session_id = session_id or event.get("sessionID")
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        if kind == "step_finish" or part.get("type") == "step-finish":
            steps += 1
            tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
            step_output = _int(tokens.get("output")) + _int(tokens.get("reasoning"))
            totals["input"] += _int(tokens.get("input"))
            totals["output"] += step_output
            max_output = max(max_output, step_output)
            totals["reasoning"] += _int(tokens.get("reasoning"))
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            totals["cache_read"] += _int(cache.get("read"))
            totals["cache_write"] += _int(cache.get("write"))
            if isinstance(part.get("cost"), (int, float)) and not isinstance(part.get("cost"), bool):
                cost += float(part["cost"])
                saw_cost = True
        elif kind == "tool" or part.get("type") == "tool":
            name = str(part.get("tool") or event.get("tool") or "unknown")
            tool_events[name] = tool_events.get(name, 0) + 1
        elif "compact" in kind or "compact" in str(part.get("type", "")):
            compactions += 1
        elif kind == "error":
            errors += 1
    return {
        "model_calls": steps,
        "input_tokens": totals["input"] + totals["cache_read"] + totals["cache_write"],
        "uncached_input_tokens": totals["input"],
        "output_tokens": totals["output"],
        "reasoning_tokens": totals["reasoning"],
        "cached_input_tokens": totals["cache_read"],
        "cache_write_tokens": totals["cache_write"],
        "max_output_tokens_per_call": max_output,
        "cost_usd": round(cost, 6) if saw_cost else None,
        "harness_tool_events": dict(sorted(tool_events.items())),
        "compactions": compactions,
        "errors": errors,
        "session_id": session_id,
        "event_types": dict(sorted(event_types.items())),
    }


def provider_stall_backoff(consecutive: int) -> float:
    """Seconds to wait before retrying the ``consecutive``-th stall in a row (1-based): 60, 120, 240, 480, 600, 600..."""
    return min(PROVIDER_STALL_BACKOFF_START_SECONDS * 2 ** max(consecutive - 1, 0), PROVIDER_STALL_BACKOFF_CAP_SECONDS)


def ended_in_provider_stall(lines: list[str]) -> bool:
    """Whether one invocation's event stream ends in a retryable provider error.

    The last event must be an ``error`` whose data says ``isRetryable``, or
    carries a transient HTTP status (``RETRYABLE_STATUS_CODES``), or whose
    message reads as a rate limit, an overload, or "try again later". Any
    other ending, including a non-retryable error such as a 401, is the
    agent (or the harness) stopping.
    """
    last: dict[str, Any] | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            last = event
    if last is None or last.get("type") != "error":
        return False
    error = last.get("error") if isinstance(last.get("error"), dict) else {}
    data = error.get("data") if isinstance(error.get("data"), dict) else {}
    for source in (data, error):
        if source.get("isRetryable") is True:
            return True
        status = source.get("statusCode")
        if isinstance(status, int) and not isinstance(status, bool) and status in RETRYABLE_STATUS_CODES:
            return True
        message = source.get("message")
        if isinstance(message, str) and _RETRYABLE_MESSAGE_RE.search(message):
            return True
    return False


def _invocation_lines(events_path: Path, offset: int) -> list[str]:
    """The events one invocation appended, from the byte offset the file had before it."""
    with events_path.open("rb") as handle:
        handle.seek(offset)
        return handle.read().decode("utf-8", errors="replace").splitlines()


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


# The token shape every harness's usage block publishes. ``input_tokens`` is
# inclusive: ``uncached_input_tokens + cached_input_tokens +
# cache_write_input_tokens``. ``output_tokens`` includes reasoning, and
# ``reasoning_tokens`` is a subset of it, for display only. Blocks recorded
# before this shape carry no ``token_shape`` and used each harness's own
# convention (OpenCode: input uncached only, output without reasoning).
TOKEN_SHAPE = "inclusive-v1"


def normalized_tokens(telemetry: dict[str, Any]) -> dict[str, int]:
    """The published token counts from a parser's telemetry (already inclusive; uncached derived if absent)."""
    input_tokens = _int(telemetry.get("input_tokens"))
    cached = _int(telemetry.get("cached_input_tokens"))
    write = _int(telemetry.get("cache_write_tokens"))
    uncached = telemetry.get("uncached_input_tokens")
    return {
        "input_tokens": input_tokens,
        "uncached_input_tokens": _int(uncached) if uncached is not None else max(input_tokens - cached - write, 0),
        "cached_input_tokens": cached,
        "cache_write_input_tokens": write,
        "output_tokens": _int(telemetry.get("output_tokens")),
        "reasoning_tokens": _int(telemetry.get("reasoning_tokens")),
    }


def usage_block(
    telemetry: dict[str, Any], *, model: str, decisions: int, harness: str = HARNESS_NAME
) -> dict[str, Any]:
    """The episode's ``usage`` block from the harness's session totals.

    OpenCode reports one total for the whole session, not one record per
    decision phase, so the block is one record with no season or phase. That
    total covers every one of the episode's ``decisions``, which is what the
    run summary divides by for its per-decision means; when the harness
    reported nothing, no decision has usage and the means read as unmeasured.
    Wall time is recorded on ``harness_run``, not as API latency, because the
    stream carries no per-call latency. Token counts are in the shared
    :data:`TOKEN_SHAPE` (inclusive input, output including reasoning), with
    ``uncached_input_tokens`` and ``cache_write_input_tokens`` beside them.
    """
    reported = telemetry["model_calls"] > 0
    tokens = normalized_tokens(telemetry)
    # ``None`` where the harness cannot observe a single call's output (Codex): left out, not 0.
    max_output = telemetry["max_output_tokens_per_call"]
    record: dict[str, Any] = {
        "provider": harness,
        "model": model,
        "api_calls": telemetry["model_calls"],
        "input_tokens": tokens["input_tokens"],
        "output_tokens": tokens["output_tokens"],
        "reasoning_tokens": tokens["reasoning_tokens"],
        "cached_input_tokens": tokens["cached_input_tokens"],
        "total_tokens": tokens["input_tokens"] + tokens["output_tokens"],
        "max_output_tokens_per_call": max_output if max_output is not None else 0,
        "season": None,
        "phase": None,
    }
    if telemetry["cost_usd"] is not None:
        record["cost_usd"] = telemetry["cost_usd"]
    usage = aggregate_usage([record])
    if max_output is None:
        del usage["max_output_tokens_per_call"]
    # aggregate_usage keeps only its own count keys; the normalized shape adds these.
    usage["uncached_input_tokens"] = tokens["uncached_input_tokens"]
    usage["cache_write_input_tokens"] = tokens["cache_write_input_tokens"]
    usage["token_shape"] = TOKEN_SHAPE
    usage["decisions_with_usage"] = decisions if reported else 0
    usage["cost_decisions"] = decisions if reported and telemetry["cost_usd"] is not None else 0
    usage["harness"] = {
        "name": harness,
        "compactions": telemetry["compactions"],
        "errors": telemetry["errors"],
        "session_id": telemetry["session_id"],
        "tool_events": telemetry["harness_tool_events"],
        "cache_write_tokens": telemetry["cache_write_tokens"],
        "telemetry_reported": telemetry["model_calls"] > 0,
    }
    return usage


# -- episodes -----------------------------------------------------------------


def run_episode(
    seed: int,
    *,
    model: str,
    run_dir: Path,
    seasons: int = 5,
    user_team_id: int = 0,
    binary: str = "opencode",
    variant: str | None = None,
    phase_guard_seconds: float = DEFAULT_PHASE_GUARD_SECONDS,
    episode_timeout_seconds: float | None = None,
    max_nudges: int = DEFAULT_MAX_NUDGES,
    progress: ProgressCallback | None = None,
    keep_scratch: bool = False,
    episode_dir: Path | None = None,
    isolation: str = "same-user",
    image: dict[str, Any] | None = None,
    docker: str = "docker",
    max_provider_stalls: int = DEFAULT_MAX_PROVIDER_STALLS,
    max_provider_stall_wait_seconds: float = DEFAULT_MAX_PROVIDER_STALL_WAIT_SECONDS,
    silent_harness_seconds: float = SILENT_HARNESS_SECONDS,
    stall_backoff: Callable[[int], float] = provider_stall_backoff,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    driver: HarnessDriver | None = None,
) -> dict[str, Any]:
    driver = driver if driver is not None else OPENCODE_DRIVER
    episode_dir = episode_dir if episode_dir is not None else run_dir / f"seed-{seed}"
    if episode_dir.exists() and any(episode_dir.iterdir()):
        # The ledger is append-only, so a second episode in the same directory
        # would be written onto the first and neither would replay.
        raise FileExistsError(f"{episode_dir} already holds an episode; use an empty run directory")
    episode_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = episode_dir / "ledger.jsonl"
    events_path = episode_dir / driver.events_filename
    stderr_path = episode_dir / driver.stderr_filename

    # The engine and the seed live here, in this process, for the whole
    # episode. Harness restarts and nudges reconnect to the same engine.
    episode = AgenticEpisode(
        seed, seasons, user_team_id, ledger_path=ledger_path, phase_guard_seconds=phase_guard_seconds
    )
    launch = HarnessLaunch(
        episode,
        binary=binary,
        isolation=isolation,
        image=image,
        docker=docker,
        driver=driver,
        evidence_paths=(events_path, stderr_path),
    )
    server = launch.server
    scratch = launch.scratch

    guard_expired = _GuardWatch(episode, server.dispatch_lock)
    watch = _InvocationWatch(guard_expired, driver, events_path)
    silence = _SilenceWatch(episode, server.dispatch_lock, events_path, silent_harness_seconds)

    def poll() -> bool:
        # Silence first: a silent harness is a provider stall, not a guard stop.
        return silence() or watch()

    def take_silence_off_the_clock() -> None:
        # The silent window is provider time, like a backoff: no tool call
        # could have moved the phase during it, so it comes off that phase's
        # guard clock and repeated silent stalls do not run the phase out.
        with server.dispatch_lock:
            episode.exclude_from_phase_clock(silence.silent_for, reason="silent_harness")

    try:
        launch.prepare()

        team_name = League.new(seed=seed, user_team_id=user_team_id).user_team.name
        brief = task_brief(seasons, team_name, user_team_id)
        command, on_kill = launch.command(
            driver.run_args(model=model, variant=variant, workdir=launch.workdir, brief=brief, isolation=isolation)
        )
        timeout = episode_timeout_seconds or (seasons * len(PHASES) * phase_guard_seconds + 300.0)
        if progress is not None:
            progress({"seed": seed, "stage": "launch", "model": model, "scratch": str(scratch), "isolation": isolation})
        events_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        # The phase guard fires inside the engine on the next tool call, so a
        # harness that stops calling tools would otherwise sit until the
        # episode timeout. The driver polls the guard while the harness runs
        # and stops the harness once the current phase has run past it (the
        # guard is elapsed phase time, not idle time); the nudge below
        # resumes the session and its first call closes the phase as
        # ``guard`` with the notice.
        guard_kills = 0
        guard_expired.arm()
        offset = events_path.stat().st_size
        watch.start(offset)
        silence.start()
        exit_code, timed_out, wall_seconds, killed = _run_harness(
            command,
            cwd=scratch,
            env=launch.env,
            events_path=events_path,
            stderr_path=stderr_path,
            timeout=timeout,
            stalled=poll,
            on_kill=on_kill,
        )
        # A silent kill went through the same kill path but is not a guard stop.
        silent = killed and silence.fired
        silent_kills = int(silent)
        if silent:
            take_silence_off_the_clock()
        # Nor is a stop for a parked invocation (a spent usage window).
        stalled = killed and not watch.parked and not silent
        guard_kills += int(stalled)
        # Provider stalls: a run that ended on a retryable provider error (a
        # 429, an overload), or was stopped as silent, is retried after a
        # backoff and is not a nudge.
        last_stalled = silent or (
            not timed_out and not killed and driver.ended_in_provider_stall(_invocation_lines(events_path, offset))
        )
        provider_stalls = int(last_stalled)
        consecutive_stalls = int(last_stalled)
        stall_retries = 0
        stall_wait = 0.0
        # Quota exhaustion (a spent subscription window, e.g. Codex's "usage
        # limit ... try again at"): never a stall and never a nudge. If the
        # reset is within the wait budget the loop pauses until it and resumes
        # the session; otherwise the episode stops here, and run_panel stops.
        pending_quota = (
            None
            if timed_out or stalled
            else driver.quota_exhausted(_invocation_lines(events_path, offset), isolation=isolation, now=clock())
        )
        quota_pauses: list[dict[str, Any]] = []
        quota_wait = 0.0
        ended_by_quota: dict[str, Any] | None = None

        def can_retry_stall() -> bool:
            return (
                last_stalled
                and stall_retries < max_provider_stalls
                and stall_wait + stall_backoff(consecutive_stalls) <= max_provider_stall_wait_seconds
            )

        # The nudge loop. A harness ends a run whenever the model answers with
        # text and no tool call; weak models do that mid-phase. Resume the same
        # session with a reminder, count it, and stop when the episode is done,
        # a nudge yields no new tool call, the cap is hit, or we cannot resume.
        # A stall retry resumes the same way but counts against the stall
        # budget instead of ``max_nudges``, and its lack of progress does not
        # stop the loop while the stall budget lasts.
        nudges: list[dict[str, Any]] = []
        productive_nudges = 0
        while not timed_out:
            state = _engine_state(episode)
            if state["done"]:
                break
            quota_resume = False
            if pending_quota is not None:
                pause = _quota_exhaustion_pause(
                    pending_quota, clock(), max_provider_stall_wait_seconds - quota_wait, state
                )
                if pause is None:
                    ended_by_quota = {
                        "reset_at_utc": pending_quota.get("reset_at_utc"),
                        "message_class": pending_quota.get("message_class"),
                    }
                    if progress is not None:
                        progress({"seed": seed, "stage": "quota_exhausted", "action": "stop", **ended_by_quota})
                    break
                if progress is not None:
                    progress({"seed": seed, "stage": "quota_exhausted", "action": "pause", **pause})
                sleep(pause["wait_seconds"])
                # As for a stall: the wait does not count against the open phase.
                with server.dispatch_lock:
                    episode.exclude_from_phase_clock(pause["wait_seconds"])
                quota_wait += pause["wait_seconds"]
                quota_pauses.append(pause)
                pending_quota = None
                quota_resume = True
            session_id = driver.parse_events(events_path.read_text(encoding="utf-8").splitlines())["session_id"]
            retry = not quota_resume and can_retry_stall()
            # A launch stopped as silent before it printed anything has no
            # session to resume; since it made no tool call either, the retry
            # starts a new session with the task brief.
            new_session = not session_id and retry and silent
            if not session_id and not new_session:
                break
            if not retry and not quota_resume and productive_nudges >= max_nudges:
                break
            number = len(nudges) + 1
            backoff = 0.0
            if retry:
                backoff = float(stall_backoff(consecutive_stalls))
                if progress is not None:
                    progress(
                        {
                            "seed": seed,
                            "stage": "provider_stall",
                            "retry": stall_retries + 1,
                            "backoff_seconds": backoff,
                            "silent": silent,
                            "season": state["season"],
                            "phase": state["phase"],
                        }
                    )
                # Nothing polls the guard while no harness runs, and the wait
                # is taken off the engine's phase clock below; ``arm`` still
                # gives the resumed harness a full guard period if the phase
                # had already run past the guard before the stall.
                sleep(backoff)
                # The engine's own guard clock would count the wait against the
                # open phase and close it as ``guard`` on the next call.
                with server.dispatch_lock:
                    episode.exclude_from_phase_clock(backoff)
                stall_retries += 1
                stall_wait += backoff
            elif not quota_resume:
                productive_nudges += 1
            # A stall retry or a quota resume shows the next reminder's number without using it up.
            text = nudge_message(
                state["season"],
                state["phase"],
                seasons,
                min(productive_nudges + int(retry or quota_resume), max_nudges),
                max_nudges,
            )
            if progress is not None:
                progress(
                    {
                        "seed": seed,
                        "stage": "nudge",
                        "number": number,
                        "season": state["season"],
                        "phase": state["phase"],
                    }
                )
            guard_expired.arm()
            if new_session:
                args = driver.run_args(
                    model=model, variant=variant, workdir=launch.workdir, brief=brief, isolation=isolation
                )
            else:
                args = driver.resume_args(
                    model=model,
                    variant=variant,
                    workdir=launch.workdir,
                    session_id=session_id,
                    text=text,
                    isolation=isolation,
                )
            nudge_command, nudge_kill = launch.command(args)
            offset = events_path.stat().st_size
            watch.start(offset)
            silence.start()
            nudge_exit, nudge_timed_out, nudge_wall, nudge_killed = _run_harness(
                nudge_command,
                cwd=scratch,
                env=launch.env,
                events_path=events_path,
                stderr_path=stderr_path,
                timeout=max(timeout - wall_seconds, 60.0),
                stalled=poll,
                on_kill=nudge_kill,
            )
            nudge_stalled = nudge_killed and not watch.parked
            wall_seconds += nudge_wall
            silent = nudge_stalled and silence.fired
            silent_kills += int(silent)
            if silent:
                take_silence_off_the_clock()
            nudge_stalled = nudge_stalled and not silent
            guard_kills += int(nudge_stalled)
            after = _engine_state(episode)
            progress_calls = after["tool_calls"] - state["tool_calls"]
            last_stalled = silent or (
                not nudge_timed_out
                and not nudge_killed
                and driver.ended_in_provider_stall(_invocation_lines(events_path, offset))
            )
            pending_quota = (
                None
                if nudge_timed_out or nudge_stalled
                else driver.quota_exhausted(_invocation_lines(events_path, offset), isolation=isolation, now=clock())
            )
            provider_stalls += int(last_stalled)
            consecutive_stalls = consecutive_stalls + 1 if last_stalled else 0
            nudges.append(
                {
                    "number": number,
                    "season": state["season"],
                    "phase": state["phase"],
                    "new_tool_calls": progress_calls,
                    "phases_closed": after["phases_closed"] - state["phases_closed"],
                    "exit_code": nudge_exit,
                    "wall_seconds": round(nudge_wall, 3),
                    "stalled": nudge_stalled,
                    # This relaunch was a retry after a provider stall, and how long it waited first.
                    "stall_retry": retry,
                    "backoff_seconds": backoff,
                    # This relaunch itself ended on a retryable provider error,
                    # or (``silent``) was stopped for printing nothing at all.
                    "provider_stall": last_stalled,
                    # This relaunch resumed after a quota pause: neither a nudge nor a stall retry.
                    "quota_resume": quota_resume,
                    "silent": silent,
                    # Started a new session with the brief: the stopped launch
                    # was silent before it opened one.
                    "new_session": new_session,
                }
            )
            timed_out = timed_out or nudge_timed_out
            if progress_calls == 0 and not can_retry_stall() and pending_quota is None:
                break
    finally:
        server_drained = launch.close(keep_scratch=keep_scratch)

    telemetry = driver.parse_events(events_path.read_text(encoding="utf-8").splitlines())
    # server.stop() hung up on every proxy and joined its thread, so nothing
    # should be inside the engine now; the lock covers a join that timed out.
    with server.dispatch_lock:
        if not episode.done:
            episode.abandon()
        episode.harness_usage = driver.usage_block(telemetry, model=model, decisions=seasons * len(PHASES))
        result = episode.result(agent_name=f"{driver.name}:{model}")
    result["harness_run"] = {
        "harness": driver.name,
        # What the driver actually did, not what anyone claims later.
        "isolation": launch.isolation,
        "transport": launch.transport,
        "command": command[:-1] + ["<task brief>"],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": round(wall_seconds, 3),
        "max_nudges": max_nudges,
        "nudges": nudges,
        # Nudges counted against ``max_nudges``; stall retries are counted apart.
        "nudges_used": productive_nudges,
        "nudges_without_progress": sum(
            1
            for nudge in nudges
            if nudge["new_tool_calls"] == 0 and not nudge["provider_stall"] and not nudge["quota_resume"]
        ),
        # Invocations that ended on a retryable provider error, and the total backoff waited.
        "provider_stalls": provider_stalls,
        "provider_stall_wait_seconds": round(stall_wait, 3),
        # Invocations stopped for total silence (no event, no tool call for
        # ``silent_harness_seconds``); each is also one of ``provider_stalls``.
        "silent_harness_seconds": silent_harness_seconds,
        "silent_kills": silent_kills,
        "guard_kills": guard_kills,
        # Pauses for a spent subscription window inside this episode, and why it
        # stopped early if the window's reset was beyond the wait budget.
        "quota_pauses": quota_pauses,
        "ended_by_quota": ended_by_quota,
        # False when a proxy thread was still inside the engine after the
        # stop timeout; the dispatch lock above still ordered the finalize.
        "server_drained": server_drained,
        # Evidence paths are recorded relative to the run directory, so the
        # directory can be moved or handed over and still validate.
        "events_path": _recorded_path(events_path, run_dir),
        "ledger_path": _recorded_path(ledger_path, run_dir),
        "proxy_connections": server.connections,
        "proxy_connections_refused": server.rejected,
        "scratch_dir": str(scratch) if keep_scratch else None,
        "event_types": telemetry["event_types"],
        # Gate 2 of the spec: the server ledger and the harness's own event
        # stream must agree on how many GM-Bench tools were called.
        "tool_call_agreement": tool_call_agreement(result["agentic"], telemetry),
    }
    result["harness_run"].update(driver.run_record(launch))
    if launch.container is not None:
        # A container or home volume docker could not remove; empty when cleanup was complete.
        result["harness_run"]["container_cleanup_problems"] = launch.cleanup_problems
    (episode_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    episode.close()
    if progress is not None:
        progress(
            {"seed": seed, "stage": "done", "final_score": result["final_score"], "failed": result["failed_decisions"]}
        )
    return result


def _recorded_path(path: Path, run_dir: Path) -> str:
    try:
        return str(path.relative_to(run_dir))
    except ValueError:
        return str(path)


def _run_harness(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    events_path: Path,
    stderr_path: Path,
    timeout: float,
    stalled: Callable[[], bool] | None = None,
    poll_seconds: float | None = None,
    on_kill: Callable[[], None] | None = None,
) -> tuple[int | None, bool, float, bool]:
    """Run one harness invocation, appending its streams to the episode's files.

    Returns ``(exit_code, timed_out, wall_seconds, stalled)``. ``stalled`` is
    polled every ``poll_seconds`` while the process runs; when it reports
    true the harness is killed and the flag is returned, distinct from the
    episode timeout so the caller can still nudge. ``on_kill`` runs before
    either kill: killing the ``docker run`` client does not stop its
    container, so the container launcher removes it there.
    """
    poll_seconds = HARNESS_POLL_SECONDS if poll_seconds is None else poll_seconds
    started = time.perf_counter()
    deadline = started + timeout
    timed_out = False
    was_stalled = False
    with events_path.open("a", encoding="utf-8") as events, stderr_path.open("a", encoding="utf-8") as errors:
        # stdin is /dev/null, not the driver's own: a driver that read its
        # seeds from stdin must not hand the harness a descriptor on them.
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=events, stderr=errors, text=True
        )
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                timed_out = True
                # Stop the harness itself first: for a container the local
                # process is only the docker client, and killing it leaves the
                # harness running until ``docker rm``. Every tool call in that
                # window would reach the ledger but not the event stream.
                if on_kill is not None:
                    on_kill()
                process.kill()
                exit_code: int | None = process.wait()
                break
            try:
                exit_code = process.wait(timeout=min(poll_seconds, remaining))
                break
            except subprocess.TimeoutExpired:
                if stalled is not None and stalled():
                    was_stalled = True
                    if on_kill is not None:
                        on_kill()
                    process.kill()
                    exit_code = process.wait()
                    break
    return exit_code, timed_out, time.perf_counter() - started, was_stalled


class _InvocationWatch:
    """The stop poll for one invocation: the phase guard, then, for a driver that parks, a spent window.

    ``parked`` says which one stopped the harness, so the loop can treat a
    parked stop as quota exhaustion rather than a guard kill.
    """

    def __init__(self, guard: Callable[[], bool], driver: HarnessDriver, events_path: Path) -> None:
        self.guard = guard
        self.driver = driver
        self.events_path = events_path
        self.offset = 0
        self.parked = False

    def start(self, offset: int) -> None:
        self.offset = offset
        self.parked = False

    def __call__(self) -> bool:
        if self.guard():
            return True
        if self.driver.polls_for_park and self.driver.invocation_parked(
            _invocation_lines(self.events_path, self.offset)
        ):
            self.parked = True
            return True
        return False


class _GuardWatch:
    """The poll that tells ``_run_harness`` to stop a harness whose phase ran past the guard.

    Fires once per expired phase. The engine only closes an expired phase on
    the next tool call, so after a stop the phase is still expired when the
    nudge resumes the session; without this memory the poll would kill the
    resumed harness before its first call could close the phase. ``arm`` is
    called before each launch so a phase that expired without a stop (the
    harness exited on its own past the guard) is remembered the same way.
    A resumed harness that then makes no call for a whole further guard
    period is stopped again, so a hung nudge costs one guard period rather
    than the episode timeout.
    """

    def __init__(self, episode: AgenticEpisode, lock: threading.Lock) -> None:
        self.episode = episode
        self.lock = lock
        self.fired_for: tuple[int, int] | None = None
        self.fired_at = 0.0

    def arm(self) -> None:
        """Remember an already-expired phase before a launch, so the launch gets a full guard period."""
        with self.lock:
            if self.episode.phase_expired():
                self._remember((self.episode.season_index, self.episode.phase_index))

    def _remember(self, current: tuple[int, int]) -> None:
        self.fired_for = current
        self.fired_at = time.monotonic()

    def __call__(self) -> bool:
        # Under the dispatch lock, so a poll cannot land between the engine's
        # phase-transition writes and pair the new phase with the old start
        # time.
        with self.lock:
            if not self.episode.phase_expired():
                return False
            current = (self.episode.season_index, self.episode.phase_index)
            if current == self.fired_for and time.monotonic() - self.fired_at <= self.episode.phase_guard_seconds:
                return False
            self._remember(current)
            return True


class _SilenceWatch:
    """The poll that tells ``_run_harness`` to stop a harness that has said nothing at all.

    ``start`` is called before each launch. The watch fires once the
    invocation has appended no byte to the event stream and made no ledger
    tool call for ``seconds`` since that launch. Silence is measured from
    launch, not from the last event: once the invocation has emitted anything
    it is not silent for the rest of its run, and a harness that goes quiet
    after emitting events is the phase guard's to stop. Only the event stream
    counts; stderr does not.
    """

    def __init__(self, episode: AgenticEpisode, lock: threading.Lock, events_path: Path, seconds: float) -> None:
        self.episode = episode
        self.lock = lock
        self.events_path = events_path
        self.seconds = seconds
        self.start()

    def _calls(self) -> int:
        with self.lock:
            return sum(self.episode.tool_counts.values())

    def start(self) -> None:
        self.offset = self.events_path.stat().st_size if self.events_path.exists() else 0
        self.calls = self._calls()
        self.started = time.monotonic()
        self.heard = False
        self.fired = False
        self.silent_for = 0.0

    def __call__(self) -> bool:
        if self.seconds <= 0 or self.heard or self.fired:
            return False
        if self.events_path.stat().st_size > self.offset or self._calls() > self.calls:
            self.heard = True
            return False
        elapsed = time.monotonic() - self.started
        if elapsed < self.seconds:
            return False
        self.fired = True
        self.silent_for = elapsed
        return True


def _engine_state(episode: AgenticEpisode) -> dict[str, Any]:
    """Where the live episode stands, for the nudge loop's progress accounting."""
    return {
        "done": episode.done,
        "season": episode.season,
        "phase": episode.phase,
        "tool_calls": sum(episode.tool_counts.values()),
        "phases_closed": len(episode.phase_log),
    }


def harness_tool_calls(telemetry: dict[str, Any]) -> int:
    """How many GM-Bench tool calls the harness's own event stream recorded."""
    return sum(
        count for name, count in telemetry.get("harness_tool_events", {}).items() if name.startswith("gm-bench_")
    )


def tool_call_agreement(agentic: dict[str, Any], telemetry: dict[str, Any]) -> dict[str, Any]:
    """Compare the ledger's tool-call count with the harness's GM-Bench tool events."""
    harness = harness_tool_calls(telemetry)
    ledger = int(agentic.get("tool_calls", 0))
    return {"ledger": ledger, "harness": harness, "agree": ledger == harness}


def finalize_episode(ledger_path: Path, *, seed: int, seasons: int, user_team_id: int) -> AgenticEpisode:
    """Rebuild the episode from its ledger and close whatever the harness left open."""
    if ledger_path.exists() and ledger_path.stat().st_size > 0:
        episode = AgenticEpisode.from_ledger(ledger_path)
    else:
        # The harness never connected: every phase is a failed decision.
        episode = AgenticEpisode(seed, seasons, user_team_id, ledger_path=ledger_path)
    if not episode.done:
        episode.abandon()
    return episode


def run_panel(
    seeds: list[int],
    *,
    model: str,
    run_dir: Path,
    seasons: int = 5,
    binary: str = "opencode",
    variant: str | None = None,
    phase_guard_seconds: float = DEFAULT_PHASE_GUARD_SECONDS,
    max_nudges: int = DEFAULT_MAX_NUDGES,
    max_provider_stalls: int = DEFAULT_MAX_PROVIDER_STALLS,
    max_provider_stall_wait_seconds: float = DEFAULT_MAX_PROVIDER_STALL_WAIT_SECONDS,
    silent_harness_seconds: float = SILENT_HARNESS_SECONDS,
    progress: ProgressCallback | None = None,
    keep_scratch: bool = False,
    name_episodes_by_position: bool = False,
    isolation: str = "same-user",
    docker: str = "docker",
    driver: HarnessDriver | None = None,
    quota_pause_percent: float = QUOTA_PAUSE_PERCENT,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Run seeds serially (harness quotas are never parallelized) and summarize.

    A seed listed more than once (a within-seed noise probe) gets one
    directory per attempt: ``seed-11``, then ``seed-11-r2`` and so on.

    ``name_episodes_by_position`` names the directories ``episode-00``,
    ``episode-01``, ... instead, for private seeds: the harness's stdout and
    stderr are files in that directory, so a ``seed-<seed>`` name would show
    the seed in the harness's open-file table (``lsof``).

    With ``isolation="container"`` the harness image is built (or found) once
    and its id, base image, and the harness version it reports are recorded
    under ``harness.container``; ``binary`` is not used.

    ``driver`` selects the harness (OpenCode by default).

    A harness that reports its subscription's usage windows (Codex, in
    ``harness_run.quota_windows``) can pause the panel: before the next
    episode, if a window of the last episode is at or above
    ``quota_pause_percent`` used, the driver sleeps until that window resets
    plus a minute (the latest such reset), never longer than
    ``max_provider_stall_wait_seconds``, reports a ``quota_pause`` progress
    event, and records the pause in ``run.json`` ``quota_pauses``. The pause
    names the episode by position, never by seed. Pauses a harness took inside
    an episode for a spent window (``harness_run.quota_pauses``) are listed
    there too, with their ``episode`` position. An episode that stopped because
    its window's reset was beyond the wait budget (``harness_run.ended_by_quota``)
    stops the panel: no later seed starts, and ``run.json`` records
    ``stopped_for_quota`` with the reset time.
    """
    driver = driver if driver is not None else OPENCODE_DRIVER
    if isolation not in DRIVER_ISOLATION:
        raise ValueError(f"isolation must be one of {DRIVER_ISOLATION}, not {isolation!r}")
    driver.preflight(isolation)
    run_dir.mkdir(parents=True, exist_ok=True)
    image = None
    if isolation == "container":
        image = driver.ensure_image(docker=docker, env=harness_environment())
        version = image[driver.image_version_key]
    else:
        version = driver.version(binary)
    episodes = []
    attempts: dict[int, int] = {}
    width = max(2, len(str(len(seeds) - 1)))
    quota_pauses: list[dict[str, Any]] = []
    stopped_for_quota: dict[str, Any] | None = None
    for position, seed in enumerate(seeds):
        if episodes:
            pause = _quota_pause(
                episodes[-1], position - 1, quota_pause_percent, max_provider_stall_wait_seconds, clock()
            )
            if pause is not None:
                if progress is not None:
                    progress({"stage": "quota_pause", **pause})
                sleep(pause["wait_seconds"])
                quota_pauses.append(pause)
        attempts[seed] = attempts.get(seed, 0) + 1
        suffix = "" if attempts[seed] == 1 else f"-r{attempts[seed]}"
        name = f"episode-{position:0{width}d}" if name_episodes_by_position else f"seed-{seed}{suffix}"
        episodes.append(
            run_episode(
                seed,
                model=model,
                run_dir=run_dir,
                episode_dir=run_dir / name,
                seasons=seasons,
                binary=binary,
                variant=variant,
                phase_guard_seconds=phase_guard_seconds,
                max_nudges=max_nudges,
                max_provider_stalls=max_provider_stalls,
                max_provider_stall_wait_seconds=max_provider_stall_wait_seconds,
                silent_harness_seconds=silent_harness_seconds,
                progress=progress,
                keep_scratch=keep_scratch,
                isolation=isolation,
                image=image,
                docker=docker,
                sleep=sleep,
                clock=clock,
                driver=driver,
            )
        )
        run = episodes[-1].get("harness_run") or {}
        quota_pauses.extend({"episode": position, **pause} for pause in run.get("quota_pauses") or [])
        if run.get("ended_by_quota"):
            # Every later seed would hit the same spent window.
            stopped_for_quota = {
                "after_episode": position,
                "episodes_not_run": len(seeds) - position - 1,
                **run["ended_by_quota"],
            }
            if progress is not None:
                progress({"stage": "panel_stopped_for_quota", **stopped_for_quota})
            break
    harness: dict[str, Any] = {"name": driver.name, "version": version, "model": model, "variant": variant}
    if image is not None:
        harness["container"] = image
    payload = {
        "agent": f"{driver.name}:{model}",
        "lane": "agentic",
        "harness": harness,
        # Recorded by the driver from what it launched; agentic-redact will
        # not publish a stronger isolation than this.
        "isolation": isolation,
        "contract": agentic_contract(),
        "seeds": list(seeds),
        "seasons": seasons,
        "phase_guard_seconds": phase_guard_seconds,
        "max_nudges": max_nudges,
        "max_provider_stalls": max_provider_stalls,
        "max_provider_stall_wait_seconds": max_provider_stall_wait_seconds,
        "silent_harness_seconds": silent_harness_seconds,
        "episodes": episodes,
        "summary": summarize_episodes(episodes),
        "agentic_summary": _agentic_summary(episodes),
    }
    if quota_pauses or stopped_for_quota or any("quota_windows" in e.get("harness_run", {}) for e in episodes):
        payload["quota_pause_percent"] = quota_pause_percent
        payload["quota_pauses"] = quota_pauses
    if stopped_for_quota is not None:
        # The panel is incomplete: ``seeds`` lists every seed, ``episodes`` only those played.
        payload["stopped_for_quota"] = stopped_for_quota
    (run_dir / "run.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _quota_exhaustion_pause(
    quota: dict[str, Any], now: float, budget: float, state: dict[str, Any]
) -> dict[str, Any] | None:
    """The in-episode pause for a quota exhaustion, or ``None`` when the episode must stop.

    Pauses until the stated reset plus QUOTA_RESET_MARGIN_SECONDS (Codex states
    it to the minute). Stops when the reset is unknown, already past (the
    window was still spent after it), or further off than ``budget``.
    """
    reset = quota.get("reset_at_utc")
    if not isinstance(reset, str):
        return None
    try:
        wait = _dt.datetime.fromisoformat(reset).timestamp() + QUOTA_RESET_MARGIN_SECONDS - now
    except ValueError:
        return None
    if wait <= 0 or wait > budget:
        return None
    return {
        "during_episode": True,
        "season": state["season"],
        "phase": state["phase"],
        "message_class": quota.get("message_class"),
        "resets_at_utc": reset,
        "wait_seconds": round(wait, 3),
        "capped": False,
    }


def _quota_pause(
    episode: dict[str, Any], position: int, threshold: float, max_wait: float, now: float
) -> dict[str, Any] | None:
    """The pause before the next episode, if a window of ``episode`` is at or above ``threshold`` percent used."""
    exhausted = []
    for window in (episode.get("harness_run") or {}).get("quota_windows") or []:
        used = window.get("used_percent")
        reset = window.get("resets_at_utc")
        if not isinstance(used, (int, float)) or used < threshold or not isinstance(reset, str):
            continue
        try:
            resets_at = _dt.datetime.fromisoformat(reset).timestamp()
        except ValueError:
            continue
        exhausted.append((resets_at, window))
    if not exhausted:
        return None
    resets_at, window = max(exhausted, key=lambda item: item[0])
    wanted = resets_at + QUOTA_RESET_MARGIN_SECONDS - now
    if wanted <= 0:
        return None
    wait = min(wanted, max_wait)
    return {
        "after_episode": position,
        "window_minutes": window.get("window_minutes"),
        "used_percent": window.get("used_percent"),
        "resets_at_utc": window.get("resets_at_utc"),
        "wait_seconds": round(wait, 3),
        # The wait hit max_provider_stall_wait_seconds before the window reset.
        "capped": wait < wanted,
    }


def _compactions(episodes: list[dict[str, Any]]) -> int | None:
    """Total compactions, or ``None`` (unmeasured, not zero) if any episode's harness reports none (Codex)."""
    values = [(episode.get("usage") or {}).get("harness", {}).get("compactions", 0) for episode in episodes]
    if any(value is None for value in values):
        return None
    return sum(int(value) for value in values)


def _api_equivalent_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """The run's API-equivalent estimate, only for a harness that publishes one (Codex).

    Summed over the episodes that carry an estimate, with their count; it is a
    list-price estimate of the tokens used, never a billed cost (``cost_usd``).
    """
    harness = [(episode.get("usage") or {}).get("harness") or {} for episode in episodes]
    if not any("api_equivalent_cost_usd" in block for block in harness):
        return {}
    values = [block["api_equivalent_cost_usd"] for block in harness if block.get("api_equivalent_cost_usd") is not None]
    return {
        "api_equivalent_cost_usd": round(sum(values), 6) if values else None,
        "api_equivalent_cost_episodes": len(values),
        "api_equivalent_long_context_possible": any(block.get("long_context_requests_possible") for block in harness),
    }


def _agentic_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not episodes:
        return {}
    calls = [episode["agentic"]["tool_calls"] for episode in episodes]
    by_tool: dict[str, int] = {}
    for episode in episodes:
        for tool, count in episode["agentic"]["tool_calls_by_tool"].items():
            by_tool[tool] = by_tool.get(tool, 0) + count
    ended: dict[str, int] = {}
    for episode in episodes:
        for how, count in episode["agentic"]["phases_ended_by"].items():
            ended[how] = ended.get(how, 0) + count
    return {
        "mean_tool_calls_per_episode": round(sum(calls) / len(calls), 2),
        "tool_calls_by_tool": dict(sorted(by_tool.items())),
        "phases_ended_by": ended,
        "nudges_used": sum(int(episode["harness_run"].get("nudges_used", 0)) for episode in episodes),
        "provider_stalls": sum(int(episode["harness_run"].get("provider_stalls", 0)) for episode in episodes),
        "provider_stall_wait_seconds": round(
            sum(float(episode["harness_run"].get("provider_stall_wait_seconds", 0.0)) for episode in episodes), 1
        ),
        "silent_harness_kills": sum(int(episode["harness_run"].get("silent_kills", 0)) for episode in episodes),
        "compactions": _compactions(episodes),
        **_api_equivalent_summary(episodes),
        "mean_wall_seconds": round(
            sum(float(episode["harness_run"]["wall_seconds"]) for episode in episodes) / len(episodes), 1
        ),
    }


# -- the OpenCode driver ------------------------------------------------------


class OpenCodeDriver(HarnessDriver):
    """OpenCode behind the shared loop. Methods look up this module's functions at call time."""

    name = HARNESS_NAME
    default_binary = "opencode"
    container_executable = "opencode"
    image_version_key = "opencode_version"

    def version(self, binary: str) -> str | None:
        return opencode_version(binary)

    def ensure_image(self, *, docker: str, env: dict[str, str]) -> dict[str, Any]:
        return ensure_image(docker=docker, env=env)

    def stage(self, launch: HarnessLaunch) -> None:
        stage_scratch(launch.scratch, launch.proxy_target, launch.env, python=launch.proxy_python, secret=launch.secret)

    def run_args(self, *, model: str, variant: str | None, workdir: str, brief: str, isolation: str) -> list[str]:
        return [*self._base(model, variant, workdir), brief]

    def resume_args(
        self, *, model: str, variant: str | None, workdir: str, session_id: str, text: str, isolation: str
    ) -> list[str]:
        return [*self._base(model, variant, workdir), "--session", session_id, text]

    @staticmethod
    def _base(model: str, variant: str | None, workdir: str) -> list[str]:
        base = ["run", "--format", "json", "--pure", "--auto", "--dir", workdir, "--model", model]
        if variant:
            base += ["--variant", variant]
        return base

    def parse_events(self, lines: list[str]) -> dict[str, Any]:
        return parse_opencode_events(lines)

    def ended_in_provider_stall(self, lines: list[str]) -> bool:
        return ended_in_provider_stall(lines)

    def usage_block(self, telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
        return usage_block(telemetry, model=model, decisions=decisions)


OPENCODE_DRIVER = OpenCodeDriver()
