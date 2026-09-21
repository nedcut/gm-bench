"""OpenCode harness driver for GM-Bench 2.0.

Per episode the driver:

1. builds the episode engine in this process (the seed never touches a file
   the agent can find) and serves it as an MCP server over a private Unix
   socket;
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
from typing import Any, Callable

import gm_bench
from gm_bench.agentic import _proxy
from gm_bench.agentic.brief import nudge_message, task_brief
from gm_bench.agentic.contract import agentic_contract
from gm_bench.agentic.episode import DEFAULT_PHASE_GUARD_SECONDS, AgenticEpisode
from gm_bench.agentic.mcp_server import EPISODE_ENV, SocketMcpServer
from gm_bench.agents import external_agent_environment
from gm_bench.protocol import PHASES
from gm_bench.runner import summarize_episodes
from gm_bench.simulator import League
from gm_bench.telemetry import aggregate_usage

HARNESS_NAME = "opencode"
DEFAULT_MAX_NUDGES = 20
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


def opencode_config(socket_path: Path, *, python: str = "python3") -> dict[str, Any]:
    """The ``opencode.json`` written into the scratch directory.

    Everything in it is readable by the agent, so it names only the proxy
    script beside it and the socket the proxy connects to.
    """
    return {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "servers": {
                "gm-bench": {
                    "type": "local",
                    "command": [python, PROXY_FILENAME, str(socket_path)],
                    "codemode": False,
                }
            }
        },
    }


def stage_scratch(scratch: Path, socket_path: Path, env: dict[str, str]) -> None:
    """Write the proxy and the config into an otherwise empty scratch directory."""
    (scratch / PROXY_FILENAME).write_text(Path(_proxy.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    config = opencode_config(socket_path, python=harness_python(env))
    (scratch / "opencode.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


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
            totals["input"] += _int(tokens.get("input"))
            totals["output"] += _int(tokens.get("output"))
            max_output = max(max_output, _int(tokens.get("output")))
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
        "input_tokens": totals["input"],
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


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def usage_block(telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
    """The episode's ``usage`` block from the harness's session totals.

    OpenCode reports one total for the whole session, not one record per
    decision phase, so the block is one record with no season or phase. That
    total covers every one of the episode's ``decisions``, which is what the
    run summary divides by for its per-decision means; when the harness
    reported nothing, no decision has usage and the means read as unmeasured.
    Wall time is recorded on ``harness_run``, not as API latency, because the
    stream carries no per-call latency.
    """
    reported = telemetry["model_calls"] > 0
    record: dict[str, Any] = {
        "provider": HARNESS_NAME,
        "model": model,
        "api_calls": telemetry["model_calls"],
        "input_tokens": telemetry["input_tokens"],
        "output_tokens": telemetry["output_tokens"],
        "reasoning_tokens": telemetry["reasoning_tokens"],
        "cached_input_tokens": telemetry["cached_input_tokens"],
        "total_tokens": telemetry["input_tokens"] + telemetry["output_tokens"],
        "max_output_tokens_per_call": telemetry["max_output_tokens_per_call"],
        "season": None,
        "phase": None,
    }
    if telemetry["cost_usd"] is not None:
        record["cost_usd"] = telemetry["cost_usd"]
    usage = aggregate_usage([record])
    usage["decisions_with_usage"] = decisions if reported else 0
    usage["cost_decisions"] = decisions if reported and telemetry["cost_usd"] is not None else 0
    usage["harness"] = {
        "name": HARNESS_NAME,
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
) -> dict[str, Any]:
    episode_dir = episode_dir if episode_dir is not None else run_dir / f"seed-{seed}"
    if episode_dir.exists() and any(episode_dir.iterdir()):
        # The ledger is append-only, so a second episode in the same directory
        # would be written onto the first and neither would replay.
        raise FileExistsError(f"{episode_dir} already holds an episode; use an empty run directory")
    episode_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = episode_dir / "ledger.jsonl"
    events_path = episode_dir / "opencode-events.jsonl"
    stderr_path = episode_dir / "opencode-stderr.log"

    env = harness_environment()
    scratch = Path(tempfile.mkdtemp(prefix="gm-bench-agentic-"))
    # The socket lives in its own private directory with a short path (macOS
    # caps Unix socket paths at 104 bytes) and mode 0600, outside the scratch.
    socket_dir = Path(tempfile.mkdtemp(prefix="gmb-"))
    socket_path = socket_dir / "s"
    # The engine and the seed live here, in this process, for the whole
    # episode. Harness restarts and nudges reconnect to the same engine.
    episode = AgenticEpisode(
        seed, seasons, user_team_id, ledger_path=ledger_path, phase_guard_seconds=phase_guard_seconds
    )
    server = SocketMcpServer(episode, socket_path)
    server.start()
    try:
        problems = sandbox_problems(scratch, env)
        if problems:
            raise SandboxError("; ".join(problems))
        stage_scratch(scratch, socket_path, env)

        team_name = League.new(seed=seed, user_team_id=user_team_id).user_team.name
        brief = task_brief(seasons, team_name, user_team_id)
        base = [binary, "run", "--format", "json", "--pure", "--auto", "--dir", str(scratch), "--model", model]
        if variant:
            base += ["--variant", variant]
        command = base + [brief]
        timeout = episode_timeout_seconds or (seasons * len(PHASES) * phase_guard_seconds + 300.0)
        if progress is not None:
            progress({"seed": seed, "stage": "launch", "model": model, "scratch": str(scratch)})
        events_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        # The phase guard fires inside the engine on the next tool call, so a
        # harness that stops calling tools would otherwise sit until the
        # episode timeout. The driver polls the guard while the harness runs
        # and stops the harness once the phase has expired; the nudge below
        # resumes the session and its first call closes the phase as
        # ``guard`` with the notice.
        guard_kills = 0
        exit_code, timed_out, wall_seconds, stalled = _run_harness(
            command,
            cwd=scratch,
            env=env,
            events_path=events_path,
            stderr_path=stderr_path,
            timeout=timeout,
            stalled=episode.phase_expired,
        )
        guard_kills += int(stalled)
        # The nudge loop. OpenCode ends a run whenever the model answers with
        # text and no tool call; weak models do that mid-phase. Resume the same
        # session with a reminder, count it, and stop when the episode is done,
        # a nudge yields no new tool call, the cap is hit, or we cannot resume.
        nudges: list[dict[str, Any]] = []
        while not timed_out and len(nudges) < max_nudges:
            state = _engine_state(episode)
            if state["done"]:
                break
            session_id = parse_opencode_events(events_path.read_text(encoding="utf-8").splitlines())["session_id"]
            if not session_id:
                break
            number = len(nudges) + 1
            text = nudge_message(state["season"], state["phase"], seasons, number, max_nudges)
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
            nudge_exit, nudge_timed_out, nudge_wall, nudge_stalled = _run_harness(
                base + ["--session", session_id, text],
                cwd=scratch,
                env=env,
                events_path=events_path,
                stderr_path=stderr_path,
                timeout=max(timeout - wall_seconds, 60.0),
                stalled=episode.phase_expired,
            )
            wall_seconds += nudge_wall
            guard_kills += int(nudge_stalled)
            after = _engine_state(episode)
            progress_calls = after["tool_calls"] - state["tool_calls"]
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
                }
            )
            timed_out = timed_out or nudge_timed_out
            if progress_calls == 0:
                break
    finally:
        server.stop()
        shutil.rmtree(socket_dir, ignore_errors=True)
        if not keep_scratch:
            shutil.rmtree(scratch, ignore_errors=True)

    telemetry = parse_opencode_events(events_path.read_text(encoding="utf-8").splitlines())
    # A proxy that outlived the harness can still have a call in flight on a
    # connection thread; the server's dispatch lock is the only thing that
    # serializes the engine, so finalize under it. (Reached directly because
    # mcp_server.py is a contract source and an accessor would move the
    # fingerprint.)
    with server._lock:
        if not episode.done:
            episode.abandon()
        episode.harness_usage = usage_block(telemetry, model=model, decisions=seasons * len(PHASES))
        result = episode.result(agent_name=f"{HARNESS_NAME}:{model}")
    result["harness_run"] = {
        "harness": HARNESS_NAME,
        "command": command[:-1] + ["<task brief>"],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": round(wall_seconds, 3),
        "max_nudges": max_nudges,
        "nudges": nudges,
        "nudges_used": len(nudges),
        "nudges_without_progress": sum(1 for nudge in nudges if nudge["new_tool_calls"] == 0),
        "guard_kills": guard_kills,
        # Evidence paths are recorded relative to the run directory, so the
        # directory can be moved or handed over and still validate.
        "events_path": _recorded_path(events_path, run_dir),
        "ledger_path": _recorded_path(ledger_path, run_dir),
        "proxy_connections": server.connections,
        "scratch_dir": str(scratch) if keep_scratch else None,
        "event_types": telemetry["event_types"],
        # Gate 2 of the spec: the server ledger and the harness's own event
        # stream must agree on how many GM-Bench tools were called.
        "tool_call_agreement": tool_call_agreement(result["agentic"], telemetry),
    }
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
    poll_seconds: float = 5.0,
) -> tuple[int | None, bool, float, bool]:
    """Run one harness invocation, appending its streams to the episode's files.

    Returns ``(exit_code, timed_out, wall_seconds, stalled)``. ``stalled`` is
    polled every ``poll_seconds`` while the process runs; when it reports
    true the harness is killed and the flag is returned, distinct from the
    episode timeout so the caller can still nudge.
    """
    started = time.perf_counter()
    deadline = started + timeout
    timed_out = False
    was_stalled = False
    with events_path.open("a", encoding="utf-8") as events, stderr_path.open("a", encoding="utf-8") as errors:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=events, stderr=errors, text=True)
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                timed_out = True
                process.kill()
                exit_code: int | None = process.wait()
                break
            try:
                exit_code = process.wait(timeout=min(poll_seconds, remaining))
                break
            except subprocess.TimeoutExpired:
                if stalled is not None and stalled():
                    was_stalled = True
                    process.kill()
                    exit_code = process.wait()
                    break
    return exit_code, timed_out, time.perf_counter() - started, was_stalled


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
    progress: ProgressCallback | None = None,
    keep_scratch: bool = False,
) -> dict[str, Any]:
    """Run seeds serially (harness quotas are never parallelized) and summarize.

    A seed listed more than once (a within-seed noise probe) gets one
    directory per attempt: ``seed-11``, then ``seed-11-r2`` and so on.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    version = opencode_version(binary)
    episodes = []
    attempts: dict[int, int] = {}
    for seed in seeds:
        attempts[seed] = attempts.get(seed, 0) + 1
        suffix = "" if attempts[seed] == 1 else f"-r{attempts[seed]}"
        episodes.append(
            run_episode(
                seed,
                model=model,
                run_dir=run_dir,
                episode_dir=run_dir / f"seed-{seed}{suffix}",
                seasons=seasons,
                binary=binary,
                variant=variant,
                phase_guard_seconds=phase_guard_seconds,
                max_nudges=max_nudges,
                progress=progress,
                keep_scratch=keep_scratch,
            )
        )
    payload = {
        "agent": f"{HARNESS_NAME}:{model}",
        "lane": "agentic",
        "harness": {"name": HARNESS_NAME, "version": version, "model": model, "variant": variant},
        "contract": agentic_contract(),
        "seeds": list(seeds),
        "seasons": seasons,
        "phase_guard_seconds": phase_guard_seconds,
        "max_nudges": max_nudges,
        "episodes": episodes,
        "summary": summarize_episodes(episodes),
        "agentic_summary": _agentic_summary(episodes),
    }
    (run_dir / "run.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


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
        "compactions": sum(int(episode["usage"].get("harness", {}).get("compactions", 0)) for episode in episodes),
        "mean_wall_seconds": round(
            sum(float(episode["harness_run"]["wall_seconds"]) for episode in episodes) / len(episodes), 1
        ),
    }
