"""The Claude Code harness driver, proven against a fake ``claude`` that speaks the documented stream-json.

No test here runs the real Claude Code CLI or contacts a model. The fake
binary reads the staged ``--mcp-config`` file from its private
``CLAUDE_CONFIG_DIR``, launches the MCP proxy that file declares, makes
real GM-Bench tool calls through it, and prints the ``claude -p
--output-format stream-json --verbose`` messages typed by the Agent SDK
0.3.276 (Claude Code 2.1.276), with the 2.1.277+ rule that a resumed
session's result carries the session's whole total.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from gm_bench.agentic import claude, opencode
from gm_bench.agentic.claude import (
    ClaudeDriver,
    claude_version,
    ended_in_provider_stall,
    mcp_config,
    parse_claude_events,
    quota_exhaustion,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DUMMY_TOKEN = "sk-ant-oat01-dummy-not-a-real-token-0000"
DUMMY_KEY = "sk-ant-api03-dummy-not-a-real-key-0000"
MODEL = "claude-fake-5"
RESET = 1_790_000_000  # 2026-09-21T14:13:20Z, epoch seconds as rate_limit_event reports resetsAt
RESET_ISO = "2026-09-21T14:13:20+00:00"

# The fake ``claude``. Behaviour per invocation comes from the plan file named
# by FAKE_CLAUDE_PLAN: {"log": path, "state": path, "steps": [{"phases": n,
# "error": text | null, "status": http status, "assistant_error": category,
# "rate_limits": [rate_limit_info, ...], "park": bool, "silent": bool,
# "cat_auth": bool, "exit": code}, ...]}. Each phase is a get_status then an
# end_phase tool_use through the proxy the staged --mcp-config declares; each
# tool_use is its own assistant message (one API response). Like Claude Code
# under ``--permission-mode dontAsk``, it denies an MCP tool the allow list
# does not name. ``park`` reports a rejected window and then waits inside the
# process, as the Agent SDK does. ``cat_auth`` prints the credential from a
# Bash tool call.
FAKE_CLAUDE = r"""
import json, os, subprocess, sys, time, uuid
from pathlib import Path

argv = sys.argv[1:]
if argv == ["--version"]:
    print("2.1.281 (Claude Code)")
    sys.exit(0)
plan = json.loads(Path(os.environ["FAKE_CLAUDE_PLAN"]).read_text())
state_path = Path(plan["state"])
state = json.loads(state_path.read_text()) if state_path.exists() else {"invocations": 0, "totals": {}}
state["invocations"] += 1
invocation = state["invocations"]
step = plan["steps"][min(invocation, len(plan["steps"])) - 1]
config_dir = Path(os.environ["CLAUDE_CONFIG_DIR"])
split = argv.index("--")
options, prompt = argv[:split], argv[split + 1:]

def value(flag):
    return options[options.index(flag) + 1] if flag in options else None

with open(plan["log"], "a") as log:
    log.write(json.dumps({
        "argv": argv,
        "cwd": os.getcwd(),
        "HOME": os.environ.get("HOME"),
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "claude_env": sorted(k for k in os.environ if k.startswith(("CLAUDE", "ANTHROPIC"))),
        "config_files": sorted(p.name for p in config_dir.iterdir()),
    }) + "\n")
state_path.write_text(json.dumps(state))
if step.get("silent"):
    sys.exit(step.get("exit", 0))
assert len(prompt) == 1 and options[0] == "-p", argv
assert value("--output-format") == "stream-json" and "--verbose" in options

def emit(event):
    print(json.dumps(event), flush=True)

sessions = config_dir / "projects"
session = value("--resume")
if session is not None:
    if not (sessions / f"{session}.jsonl").exists():
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
              "errors": [f"No conversation found with session ID: {session}"], "session_id": session})
        sys.exit(1)
else:
    session = str(uuid.uuid4())
    sessions.mkdir(exist_ok=True)
    (sessions / f"{session}.jsonl").write_text("")
allowed = (value("--allowedTools") or "").split(",")
mcp_allowed = "mcp__gm-bench" in allowed or value("--permission-mode") == "bypassPermissions"
emit({"type": "system", "subtype": "init", "session_id": session, "claude_code_version": "2.1.281",
      "model": value("--model"), "permissionMode": value("--permission-mode"), "cwd": os.getcwd(),
      "tools": ["Bash", "Read", "mcp__gm-bench__get_status"], "apiKeySource": "none",
      "mcp_servers": [{"name": "gm-bench", "status": "connected"}]})
messages = 0
denials = []

def assistant(block, **extra):
    global messages
    messages += 1
    usage = {"input_tokens": 100, "cache_read_input_tokens": 400, "cache_creation_input_tokens": 50, "output_tokens": 1}
    message = {"id": f"msg_{invocation}_{messages}", "type": "message", "role": "assistant", "model": value("--model"),
               "content": [block], "stop_reason": None, "usage": usage}
    emit({"type": "assistant", "message": message, "parent_tool_use_id": None, "session_id": session, **extra})

def tool_result(tool_id, text, is_error=False):
    content = [{"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": is_error}]
    emit({"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None,
          "session_id": session})

if step.get("cat_auth"):
    tool_id = f"toolu_{invocation}_auth"
    assistant({"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": "env"}})
    text = " ".join(f"{k}={os.environ[k]}" for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY") if k in os.environ)
    tool_result(tool_id, text)
    sys.stderr.write("tool output: " + text + "\n")
if step.get("phases"):
    server = json.loads(Path(value("--mcp-config")).read_text())["mcpServers"]["gm-bench"]
    proxy = subprocess.Popen([server["command"], *server["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(payload):
        proxy.stdin.write(json.dumps(payload) + "\n")
        proxy.stdin.flush()
        return json.loads(proxy.stdout.readline())
    rpc({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    proxy.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    for phase in range(step["phases"]):
        for tool in ("get_status", "end_phase"):
            tool_id = f"toolu_{invocation}_{phase}_{tool}"
            assistant({"type": "tool_use", "id": tool_id, "name": f"mcp__gm-bench__{tool}", "input": {}})
            if not mcp_allowed:
                message = "Permission to use mcp__gm-bench__" + tool + " has been denied."
                emit({"type": "system", "subtype": "permission_denied", "tool_name": f"mcp__gm-bench__{tool}",
                      "tool_use_id": tool_id, "message": message, "session_id": session})
                denials.append({"tool_name": f"mcp__gm-bench__{tool}", "tool_use_id": tool_id, "tool_input": {}})
                tool_result(tool_id, message, is_error=True)
                continue
            reply = rpc({"jsonrpc": "2.0", "id": messages, "method": "tools/call", "params": {"name": tool, "arguments": {}}})
            tool_result(tool_id, reply["result"]["content"])
    proxy.stdin.close()
    proxy.wait(timeout=30)
for info in step.get("rate_limits") or []:
    emit({"type": "rate_limit_event", "rate_limit_info": info, "session_id": session})
if step.get("park"):
    # A rejected window parks the turn inside the process: no further message, no result.
    time.sleep(3600)
mine = {"inputTokens": 1000, "outputTokens": 50, "thinkingTokens": 20, "cacheReadInputTokens": 400,
        "cacheCreationInputTokens": 100, "costUSD": 0.5}
# 2.1.277+: a resumed session's result carries the session's whole total, restored from the transcript.
total = state["totals"].get(session) or {key: 0 for key in mine}
total = {key: total[key] + mine[key] for key in mine}
state["totals"][session] = total
state_path.write_text(json.dumps(state))
result = {"type": "result", "session_id": session, "num_turns": messages, "duration_ms": 1000,
          "duration_api_ms": 900, "total_cost_usd": total["costUSD"], "modelUsage": {value("--model"): total},
          "usage": {"input_tokens": 1000, "cache_read_input_tokens": 400, "cache_creation_input_tokens": 100,
                    "output_tokens": 50}, "permission_denials": denials, "stop_reason": "end_turn"}
if step.get("error"):
    assistant({"type": "text", "text": step["error"]}, error=step.get("assistant_error", "unknown"))
    emit({**result, "subtype": "success", "is_error": True, "api_error_status": step.get("status"),
          "result": step["error"]})
    sys.exit(step.get("exit", 1))
assistant({"type": "text", "text": "Done for now."})
emit({**result, "subtype": "success", "is_error": False, "result": "Done for now."})
sys.exit(step.get("exit", 0))
"""


def _fake_claude(tmp_path: Path, steps: list[dict], monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    binary = tmp_path / "fake-claude"
    binary.write_text(f"#!{sys.executable}\n{FAKE_CLAUDE}")
    binary.chmod(0o755)
    log = tmp_path / "claude-calls.jsonl"
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"log": str(log), "state": str(tmp_path / "state.json"), "steps": steps}))
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", str(plan))
    # Host Claude Code state that must not reach the harness (this very session sets some of it).
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "host-claude-config"))
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9/host-gateway")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # CI may install gm_bench into the system python; the sandbox check has its own tests.
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    return binary, log


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "operator-claude-token"
    path.write_text(DUMMY_TOKEN + "\n")
    return path


def _calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def _limit(status: str, *, kind: str = "five_hour", utilization: float = 1.0, **extra) -> dict:
    return {"status": status, "resetsAt": RESET, "rateLimitType": kind, "utilization": utilization, **extra}


# -- the full loop against the fake binary --------------------------------------


def test_claude_panel_plays_through_the_staged_proxy_nudges_by_resume_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from gm_bench.agentic.validate import validate_run

    # First run: one phase, then the model answers with text and exits 0. The nudge resumes and finishes.
    binary, log = _fake_claude(tmp_path, [{"phases": 1}, {"phases": 3}], monkeypatch)
    run_dir = tmp_path / "run"
    payload = claude.run_panel(
        [11], model=MODEL, run_dir=run_dir, seasons=1, binary=str(binary), token_file=_token_file(tmp_path)
    )
    assert payload["agent"] == f"claude:{MODEL}"
    assert payload["harness"] == {"name": "claude", "version": "2.1.281", "model": MODEL, "variant": None}
    [episode] = payload["episodes"]
    harness_run = episode["harness_run"]
    assert harness_run["events_path"] == "seed-11/claude-events.jsonl"
    # Every GM-Bench call the fake made through the proxy is in the ledger and in the event stream.
    assert harness_run["tool_call_agreement"] == {"ledger": 8, "harness": 8, "agree": True}
    assert episode["usage"]["harness"]["tool_events"] == {"gm-bench_end_phase": 4, "gm-bench_get_status": 4}
    assert episode["agentic"]["phases_ended_by"] == {"agent": 4}
    assert episode["failed_decisions"] == 0

    # The early stop was nudged by resuming the same session named by system/init.
    calls = _calls(log)
    first, nudge = calls
    init = json.loads((run_dir / "seed-11" / "claude-events.jsonl").read_text().splitlines()[0])
    assert init["subtype"] == "init"
    resume_at = nudge["argv"].index("--resume")
    assert nudge["argv"][resume_at + 1] == init["session_id"]
    assert nudge["argv"][-2] == "--" and "Reminder 1 of 20" in nudge["argv"][-1]
    assert harness_run["nudges_used"] == 1 and harness_run["nudges"][0]["new_tool_calls"] == 6
    # Same options on both invocations; the prompt is after "--", so no variadic option can swallow it.
    assert first["argv"][:-2] == nudge["argv"][:resume_at]
    assert first["argv"][-2] == "--"
    # The host's Claude Code state never reaches the harness: HOME is the scratch, CLAUDE_CONFIG_DIR a
    # private directory outside it (the same one for the resume, removed at episode end), only the handed-off
    # credential and the traffic switch among CLAUDE*/ANTHROPIC* variables, and exactly one staged file.
    assert first["CLAUDE_CONFIG_DIR"] == nudge["CLAUDE_CONFIG_DIR"]
    for call in calls:
        cwd = Path(call["cwd"]).resolve()
        assert Path(call["HOME"]).resolve() == cwd
        config_dir = Path(call["CLAUDE_CONFIG_DIR"]).resolve()
        assert not config_dir.is_relative_to(cwd) and config_dir != Path(os.environ["CLAUDE_CONFIG_DIR"]).resolve()
        assert not config_dir.exists()
        assert call["claude_env"] == [
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CONFIG_DIR",
        ]
        assert call["config_files"][0] == "mcp.json"
    # Usage is the session's running total (2.1.277+), not a sum of the two results: 2 x (1000 + 400 + 100).
    usage = episode["usage"]
    assert (usage["input_tokens"], usage["uncached_input_tokens"]) == (3000, 2000)
    assert (usage["cached_input_tokens"], usage["cache_write_input_tokens"]) == (800, 200)
    assert (usage["output_tokens"], usage["reasoning_tokens"]) == (100, 40)
    # Distinct assistant message ids: (2 tool calls + text) then (6 tool calls + text).
    assert usage["api_calls"] == 10 and usage["token_shape"] == "inclusive-v1"
    assert usage["harness"]["telemetry_reported"] is True and usage["harness"]["compactions"] == 0
    assert usage["harness"]["usage_complete"] is True and usage["harness"]["models"] == [MODEL]
    assert usage["cost_usd"] is None and usage["cost_decisions"] == 0
    assert usage["harness"]["harness_cost_estimate_usd"] == 1.0 and usage["harness"]["billed_by_harness"] is False
    assert harness_run["auth"] == "token-file" and harness_run["session_resume"] == "claude -p --resume"
    assert harness_run["permission_mode"] == "dontAsk" and harness_run["setting_sources"] == "user"
    assert json.loads(harness_run["harness_config"])["mcpServers"]["gm-bench"]["args"][0] == "gm_bench_proxy.py"
    assert DUMMY_TOKEN not in json.dumps(payload)

    report = validate_run(run_dir)
    assert report["ok"], report
    assert report["per_episode"][0]["harness_tool_calls"] == 8
    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["harness"]["name"] == "claude"
    assert validate_agentic_artifact(artifact)["ok"]


def test_claude_provider_stall_is_retried_by_resume_and_is_not_a_nudge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [
        {
            "phases": 1,
            "error": "API Error: Repeated 529 Overloaded errors",
            "status": 529,
            "assistant_error": "overloaded",
        },
        {"phases": 3},
    ]
    binary, log = _fake_claude(tmp_path, steps, monkeypatch)
    sleeps: list[float] = []
    result = claude.run_episode(
        11,
        model=MODEL,
        run_dir=tmp_path / "run",
        seasons=1,
        binary=str(binary),
        token_file=_token_file(tmp_path),
        max_nudges=5,
        max_provider_stalls=8,
        max_provider_stall_wait_seconds=3600.0,
        stall_backoff=lambda n: 7.0,
        sleep=sleeps.append,
        keep_scratch=True,
    )
    harness_run = result["harness_run"]
    assert sleeps == [7.0]
    assert harness_run["provider_stalls"] == 1 and harness_run["provider_stall_wait_seconds"] == 7.0
    assert harness_run["nudges_used"] == 0
    [retry] = harness_run["nudges"]
    assert retry["stall_retry"] is True and retry["provider_stall"] is False and retry["new_tool_calls"] == 6
    assert ["--resume" in call["argv"] for call in _calls(log)] == [False, True]
    assert result["failed_decisions"] == 0 and harness_run["tool_call_agreement"]["agree"] is True
    assert result["usage"]["harness"]["errors"] == 2  # the failed result and its assistant error frame
    # The kept scratch never held the config dir, so no credential outlives the episode.
    scratch = Path(harness_run["scratch_dir"])
    assert not (scratch / ".claude").exists()
    assert not any(DUMMY_TOKEN in path.read_text() for path in scratch.rglob("*") if path.is_file())


def test_usage_limit_within_the_wait_budget_pauses_then_resumes_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact

    steps = [
        {
            "phases": 1,
            "rate_limits": [_limit("allowed_warning", utilization=0.9), _limit("rejected")],
            "error": "You've hit your session limit",
            "status": 429,
            "assistant_error": "rate_limit",
        },
        {"phases": 3, "rate_limits": [_limit("allowed", utilization=0.02)]},
    ]
    binary, log = _fake_claude(tmp_path, steps, monkeypatch)
    sleeps: list[float] = []
    events: list[dict] = []
    run_dir = tmp_path / "run"
    payload = claude.run_panel(
        [11],
        model=MODEL,
        run_dir=run_dir,
        seasons=1,
        binary=str(binary),
        token_file=_token_file(tmp_path),
        max_provider_stall_wait_seconds=3600.0,
        sleep=sleeps.append,
        clock=lambda: RESET - 1000.0,
        progress=events.append,
    )
    [episode] = payload["episodes"]
    run = episode["harness_run"]
    # Until the reset plus a minute; never the 60 s stall ladder, although the status was 429.
    assert sleeps == [1060.0]
    assert run["provider_stalls"] == 0 and run["nudges_used"] == 0 and run["ended_by_quota"] is None
    [resume] = run["nudges"]
    assert resume["quota_resume"] is True and resume["new_tool_calls"] == 6
    assert ["--resume" in call["argv"] for call in _calls(log)] == [False, True]
    [pause] = run["quota_pauses"]
    assert pause["resets_at_utc"] == RESET_ISO and pause["message_class"] == "usage_limit"
    assert episode["failed_decisions"] == 0
    # The window the stream last reported, as a 0-100 percentage.
    assert run["quota_windows"] == [
        {"window_minutes": 300, "used_percent": 2.0, "resets_at_utc": RESET_ISO, "rate_limit_type": "five_hour"}
    ]
    assert any(e["stage"] == "quota_exhausted" and e["action"] == "pause" for e in events)
    assert not any(e["stage"] == "provider_stall" for e in events)
    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert validate_agentic_artifact(artifact, raw_run=run_dir)["ok"]


def test_usage_limit_beyond_the_wait_budget_stops_the_episode_and_the_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [{"phases": 1, "rate_limits": [_limit("rejected")], "error": "You've hit your weekly limit"}]
    binary, log = _fake_claude(tmp_path, steps, monkeypatch)
    sleeps: list[float] = []
    payload = claude.run_panel(
        [11, 12, 13],
        model=MODEL,
        run_dir=tmp_path / "run",
        seasons=1,
        binary=str(binary),
        token_file=_token_file(tmp_path),
        max_provider_stall_wait_seconds=3600.0,
        sleep=sleeps.append,
        # 20 hours before the reset: far beyond the 1 h budget.
        clock=lambda: RESET - 72_000.0,
    )
    assert sleeps == [] and len(_calls(log)) == 1 and len(payload["episodes"]) == 1
    run = payload["episodes"][0]["harness_run"]
    assert run["ended_by_quota"] == {"reset_at_utc": RESET_ISO, "message_class": "usage_limit"}
    assert payload["episodes"][0]["agentic"]["phases_ended_by"] == {"agent": 1, "harness_exit": 3}
    assert payload["stopped_for_quota"]["episodes_not_run"] == 2


def test_an_invocation_parked_on_a_rejected_window_is_stopped_and_paused_not_guard_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude Code can wait inside the process for a window to reset; the loop stops it and pauses itself."""
    steps = [{"phases": 1, "rate_limits": [_limit("rejected")], "park": True}, {"phases": 3}]
    binary, log = _fake_claude(tmp_path, steps, monkeypatch)
    monkeypatch.setattr(opencode, "HARNESS_POLL_SECONDS", 0.2)
    sleeps: list[float] = []
    result = claude.run_episode(
        11,
        model=MODEL,
        run_dir=tmp_path / "run",
        seasons=1,
        binary=str(binary),
        token_file=_token_file(tmp_path),
        max_provider_stall_wait_seconds=3600.0,
        sleep=sleeps.append,
        clock=lambda: RESET - 100.0,
    )
    run = result["harness_run"]
    assert sleeps == [160.0]
    assert run["guard_kills"] == 0 and run["exit_code"] != 0
    assert run["nudges"][0]["quota_resume"] is True and run["nudges"][0]["stalled"] is False
    assert result["failed_decisions"] == 0 and run["tool_call_agreement"]["agree"] is True
    # The killed invocation wrote no result: its input and cache tokens come from its frames.
    usage = result["usage"]
    assert usage["harness"]["usage_complete"] is False and usage["harness"]["invocations_without_result"] == 1
    assert usage["input_tokens"] == 1500 + 2 * 550


def test_a_silent_harness_is_not_nudged_and_its_usage_is_unmeasured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.validate import validate_run

    binary, log = _fake_claude(tmp_path, [{"silent": True}], monkeypatch)
    run_dir = tmp_path / "run"
    payload = claude.run_panel(
        [11], model=MODEL, run_dir=run_dir, seasons=1, binary=str(binary), token_file=_token_file(tmp_path)
    )
    [episode] = payload["episodes"]
    # No session id to resume: one launch, no nudge.
    assert len(_calls(log)) == 1 and episode["harness_run"]["nudges"] == []
    assert episode["failed_decisions"] == 4
    assert episode["usage"]["harness"]["telemetry_reported"] is False
    assert episode["usage"]["decisions_with_usage"] == 0
    assert episode["usage"]["harness"]["api_equivalent_cost_usd"] is None
    warnings = validate_run(run_dir)["warnings"]
    assert any("reported no token telemetry" in warning for warning in warnings)


@pytest.mark.parametrize("source", ["token-file", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"])
def test_a_claude_credential_the_agent_prints_is_redacted_from_the_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    from gm_bench.agentic.validate import validate_run

    binary, log = _fake_claude(tmp_path, [{"phases": 4, "cat_auth": True}], monkeypatch)
    token_file = None
    secret = DUMMY_KEY if source == "ANTHROPIC_API_KEY" else DUMMY_TOKEN
    if source == "token-file":
        token_file = _token_file(tmp_path)
    else:
        monkeypatch.setenv(source, secret)
    run_dir = tmp_path / "run"
    payload = claude.run_panel(
        [11], model=MODEL, run_dir=run_dir, seasons=1, binary=str(binary), token_file=token_file, keep_scratch=True
    )
    [call] = _calls(log)
    assert TOKEN_OR_KEY_ENV[source] in call["claude_env"]
    events = (run_dir / "seed-11" / "claude-events.jsonl").read_text()
    assert "[REDACTED]" in events and "[REDACTED]" in (run_dir / "seed-11" / "claude-stderr.log").read_text()
    leaked = [path for path in run_dir.rglob("*") if path.is_file() and secret in path.read_text()]
    assert leaked == []
    run = payload["episodes"][0]["harness_run"]
    assert run["auth"] == source and run["tool_call_agreement"]["agree"] is True
    assert payload["episodes"][0]["usage"]["harness"]["tool_events"]["Bash"] == 1
    assert validate_run(run_dir)["ok"]


TOKEN_OR_KEY_ENV = {
    "token-file": "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN": "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY",
}


# -- credentials and container refusal ----------------------------------------


def test_claude_needs_one_credential_and_prefers_the_subscription_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="needs credentials"):
        ClaudeDriver().preflight("same-user")
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    ClaudeDriver().preflight("same-user")
    assert ClaudeDriver().auth_source() == "ANTHROPIC_API_KEY"
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", DUMMY_TOKEN)
    assert ClaudeDriver().auth_source() == "CLAUDE_CODE_OAUTH_TOKEN"
    # Only the chosen credential reaches the harness, never both.
    env = ClaudeDriver().environment(dict(os.environ), tmp_path, "same-user")
    try:
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == DUMMY_TOKEN and "ANTHROPIC_API_KEY" not in env
    finally:
        os.rmdir(env["CLAUDE_CONFIG_DIR"])
    assert ClaudeDriver(token_file=_token_file(tmp_path)).auth_source() == "token-file"

    bad = tmp_path / "bad-token"
    bad.write_text(DUMMY_TOKEN + " second-line\n")
    with pytest.raises(ValueError, match="exactly one") as excinfo:
        ClaudeDriver(token_file=bad).preflight("same-user")
    assert DUMMY_TOKEN not in str(excinfo.value)
    bad.write_text("\n")
    with pytest.raises(ValueError, match="exactly one"):
        ClaudeDriver(token_file=bad).preflight("same-user")
    with pytest.raises(ValueError, match="is not a file"):
        ClaudeDriver(token_file=tmp_path / "missing").preflight("same-user")


def test_claude_refuses_container_isolation_until_the_credential_hand_off_is_decided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", DUMMY_TOKEN)
    for driver in (ClaudeDriver(), ClaudeDriver(token_file=_token_file(tmp_path))):
        with pytest.raises(ValueError, match="open decision") as excinfo:
            driver.preflight("container")
        assert "--isolation container is not available for --harness claude" in str(excinfo.value)
        with pytest.raises(ValueError, match="open decision"):
            driver.ensure_image(docker="docker", env={})
    # run_panel refuses before building anything or creating the run directory.
    run_dir = tmp_path / "run"
    with pytest.raises(ValueError, match="open decision"):
        claude.run_panel([11], model=MODEL, run_dir=run_dir, seasons=1, isolation="container", docker="no-docker")
    assert not run_dir.exists()
    with pytest.raises(ValueError, match="open decision"):
        claude.run_episode(11, model=MODEL, run_dir=run_dir, seasons=1, isolation="container")


# -- staging, version, parser ---------------------------------------------------


def test_claude_staging_keeps_host_config_out_and_the_mcp_config_to_one_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.episode import AgenticEpisode

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    episode = AgenticEpisode(8675309, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    driver = ClaudeDriver(token_file=_token_file(tmp_path))
    launch = opencode.HarnessLaunch(episode, binary="claude", driver=driver)
    try:
        # With a token file, the env API key is dropped too, so the file's token is what Claude Code uses.
        assert sorted(key for key in launch.env if key.startswith(("CLAUDE", "ANTHROPIC"))) == [
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CONFIG_DIR",
        ]
        home = Path(launch.env["CLAUDE_CONFIG_DIR"])
        assert not home.resolve().is_relative_to(launch.scratch.resolve()) and home != Path.home() / ".claude"
        assert launch.env["HOME"] == str(launch.scratch)
        launch.prepare()
        # The agent's working directory holds only the proxy: no config, no credential.
        assert sorted(p.name for p in launch.scratch.iterdir()) == ["gm_bench_proxy.py"]
        assert sorted(p.name for p in home.iterdir()) == ["mcp.json"]
        assert home.stat().st_mode & 0o077 == 0 and (home / "mcp.json").stat().st_mode & 0o077 == 0
        config = json.loads((home / "mcp.json").read_text())
        assert config == mcp_config(launch.server.address, python=opencode.harness_python(launch.env))
        assert config == {
            "mcpServers": {
                "gm-bench": {
                    "type": "stdio",
                    "command": config["mcpServers"]["gm-bench"]["command"],
                    "args": ["gm_bench_proxy.py", str(launch.server.address)],
                }
            }
        }
        rendered = (home / "mcp.json").read_text()
        assert "8675309" not in rendered and str(REPO_ROOT) not in rendered and sys.executable not in rendered
        argv, on_kill = launch.command(
            driver.run_args(
                model="claude-x", variant="low", workdir=launch.workdir, brief="BRIEF", isolation="same-user"
            )
        )
        assert on_kill is None
        assert argv == [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--mcp-config",
            str(home / "mcp.json"),
            "--strict-mcp-config",
            "--setting-sources",
            "user",
            "--disable-slash-commands",
            "--allowedTools",
            "mcp__gm-bench,Bash,Read,Edit,Write,Glob,Grep,NotebookEdit",
            "--permission-mode",
            "dontAsk",
            "--permission-prompts",
            "none",
            "--model",
            "claude-x",
            "--effort",
            "low",
            "--",
            "BRIEF",
        ]
        resume = driver.resume_args(
            model="claude-x", variant="low", workdir=launch.workdir, session_id="S", text="NUDGE", isolation="same-user"
        )
        assert resume == [*argv[1:-2], "--resume", "S", "--", "NUDGE"]
    finally:
        launch.close(keep_scratch=True)
    # The private config dir (MCP config, transcripts) is gone even with --keep-scratch.
    assert not home.exists()
    assert sorted(p.name for p in launch.scratch.iterdir()) == ["gm_bench_proxy.py"]
    episode.close()


def test_claude_version_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary, _log = _fake_claude(tmp_path, [{}], monkeypatch)
    assert claude_version(str(binary)) == "2.1.281"
    assert ClaudeDriver().version(str(binary)) == "2.1.281"
    assert claude_version(str(tmp_path / "no-such-claude")) is None


def _init(session: str = "s-1", version: str = "2.1.281") -> str:
    return json.dumps({"type": "system", "subtype": "init", "session_id": session, "claude_code_version": version})


def _assistant(message_id: str, *blocks: dict, model: str = MODEL, parent: str | None = None, **usage) -> str:
    counts = {"input_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
    message = {"id": message_id, "model": model, "content": list(blocks), "usage": counts | usage}
    return json.dumps({"type": "assistant", "message": message, "parent_tool_use_id": parent})


def _tool(tool_id: str, name: str) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": {}}


def _result(model_usage: dict, *, cost: float = 0.1, is_error: bool = False, **extra) -> str:
    return json.dumps(
        {"type": "result", "is_error": is_error, "total_cost_usd": cost, "modelUsage": model_usage, **extra}
    )


def _mu(inp: int, out: int, read: int = 0, write: int = 0, thinking: int = 0) -> dict:
    return {
        "inputTokens": inp,
        "outputTokens": out,
        "cacheReadInputTokens": read,
        "cacheCreationInputTokens": write,
        "thinkingTokens": thinking,
    }


def test_parse_claude_events_counts_tools_once_per_id_and_keeps_the_session_total() -> None:
    lines = [
        _init(),
        # One API response with two parallel tool calls arrives as two frames sharing a message id.
        _assistant(
            "msg_1", _tool("toolu_1", "mcp__gm-bench__get_status"), input_tokens=100, cache_read_input_tokens=50
        ),
        _assistant("msg_1", _tool("toolu_2", "Bash"), input_tokens=100, cache_read_input_tokens=50),
        # A subagent's GM-Bench call still reached the server.
        _assistant("msg_2", _tool("toolu_3", "mcp__gm-bench__scout"), model="claude-haiku-4-5", parent="toolu_2"),
        # Denied before it ran: never reached the server.
        _assistant("msg_3", _tool("toolu_4", "WebFetch")),
        json.dumps(
            {"type": "system", "subtype": "permission_denied", "tool_use_id": "toolu_4", "tool_name": "WebFetch"}
        ),
        json.dumps({"type": "system", "subtype": "compact_boundary", "compact_metadata": {"trigger": "auto"}}),
        json.dumps(
            {"type": "system", "subtype": "api_retry", "attempt": 1, "error_status": 529, "error": "overloaded"}
        ),
        "not json",
        _result({MODEL: _mu(100, 30, 40, 10, 5), "claude-haiku-4-5": _mu(20, 2)}, cost=0.2),
        # The resume: the session's whole total (2.1.277+), and a denial listed only on the result.
        _init(),
        _assistant(
            "msg_4", _tool("toolu_5", "mcp__gm-bench__end_phase"), input_tokens=300, cache_creation_input_tokens=7
        ),
        _assistant("msg_5", _tool("toolu_6", "mcp__other__thing")),
        _result(
            {MODEL: _mu(250, 60, 90, 17, 9), "claude-haiku-4-5": _mu(20, 2)},
            cost=0.5,
            permission_denials=[{"tool_use_id": "toolu_6", "tool_name": "mcp__other__thing", "tool_input": {}}],
        ),
    ]
    telemetry = parse_claude_events(lines)
    assert telemetry["session_id"] == "s-1"
    assert telemetry["harness_tool_events"] == {
        "Bash": 1,
        "gm-bench_end_phase": 1,
        "gm-bench_get_status": 1,
        "gm-bench_scout": 1,
    }
    assert telemetry["harness_tool_calls_skipped"] == {"WebFetch": 1, "other_thing": 1}
    assert opencode.harness_tool_calls(telemetry) == 3
    # The last result per session, not the sum: 250 + 20 uncached, 90 read, 17 written.
    assert (telemetry["input_tokens"], telemetry["uncached_input_tokens"]) == (377, 270)
    assert (telemetry["cached_input_tokens"], telemetry["cache_write_tokens"]) == (90, 17)
    assert (telemetry["output_tokens"], telemetry["reasoning_tokens"]) == (62, 9)
    assert telemetry["model_calls"] == 5 and telemetry["compactions"] == 1 and telemetry["api_retries"] == 1
    assert telemetry["max_request_input_tokens"] == {"claude-haiku-4-5": 10, MODEL: 307}
    assert telemetry["harness_cost_estimate_usd"] == 0.5 and telemetry["usage_complete"] is True
    assert telemetry["event_types"]["system/init"] == 2

    # Before 2.1.277 a resumed process counted only itself: the results add up.
    old = [line.replace('"2.1.281"', '"2.1.276"') for line in lines]
    assert parse_claude_events(old)["uncached_input_tokens"] == 120 + 270
    assert parse_claude_events(old)["harness_cost_estimate_usd"] == 0.7

    # A killed invocation (no result): its frames, once per message id; output is then a lower bound.
    killed = [*lines, _init(), _assistant("msg_6", _tool("toolu_7", "Bash"), input_tokens=1000, output_tokens=1)]
    partial = parse_claude_events(killed)
    assert partial["uncached_input_tokens"] == 270 + 1000 and partial["usage_complete"] is False
    assert partial["invocations_without_result"] == 1


def test_claude_usage_block_prices_each_model_and_publishes_no_cost() -> None:
    from web.scripts.build_study import _agentic_telemetry

    sonnet = "claude-sonnet-5-20260901"
    lines = [
        _init(),
        _assistant("m1", input_tokens=1000),
        _result({sonnet: _mu(200_000, 20_000, 700_000, 100_000, 8_000)}, cost=3.0),
    ]
    telemetry = parse_claude_events(lines)
    block = claude.usage_block(telemetry, model="sonnet", decisions=20)
    assert block["cost_usd"] is None and block["cost_decisions"] == 0
    assert block["token_shape"] == "inclusive-v1" and "max_output_tokens_per_call" not in block
    assert (block["input_tokens"], block["uncached_input_tokens"]) == (1_000_000, 200_000)
    assert (block["output_tokens"], block["reasoning_tokens"]) == (20_000, 8_000)
    harness = block["harness"]
    # 200k uncached at 2.00 + 700k cached at 0.20 + 100k written at 2.50 + 20k out at 10.00 (claude-sonnet-5).
    assert harness["api_equivalent_cost_usd"] == pytest.approx(0.4 + 0.14 + 0.25 + 0.2)
    assert harness["pricing_source"] == {
        "key": "claude-sonnet-5",
        "verified": "2026-09-23",
        "cached_input_rate": "cached",
        "cache_write_rate": "cache-write",
    }
    assert harness["cost_basis"] == "api-list-price-estimate" and harness["billed_by_harness"] is False
    # The entry names no long-context tier.
    assert harness["long_context_requests_possible"] is None
    assert harness["harness_cost_estimate_usd"] == 3.0 and harness["cost_reported_by_harness"] is False
    assert harness["models"] == [sonnet]

    # A subagent on another model is priced at its own entry (Haiku 4.5 has no cached rate: input rate).
    mixed = [
        _init(),
        _assistant("m1"),
        _result({sonnet: _mu(1_000_000, 0), "claude-haiku-4-5-20251001": _mu(0, 0, 1_000_000)}),
    ]
    both = claude.usage_block(parse_claude_events(mixed), model="sonnet", decisions=20)["harness"]
    assert both["api_equivalent_cost_usd"] == pytest.approx(2.0 + 1.0)
    assert [source["key"] for source in both["pricing_source"]["models"]] == ["claude-haiku-4-5", "claude-sonnet-5"]
    assert both["pricing_source"]["models"][0]["cached_input_rate"] == "input (no cached price)"
    # Any unpriced model with tokens: no estimate at all, rather than a partial one.
    unpriced = [_init(), _assistant("m1"), _result({sonnet: _mu(10, 1), "mystery-model-9000": _mu(10, 1)})]
    assert (
        claude.usage_block(parse_claude_events(unpriced), model="x", decisions=20)["harness"]["api_equivalent_cost_usd"]
        is None
    )

    episode = {"agentic": {"tool_calls": 8}, "harness_run": {"wall_seconds": 1.0}, "usage": block}
    site = _agentic_telemetry([episode])
    assert site["cost_usd"] is None and site["api_equivalent_cost_usd"] == pytest.approx(0.99)


# -- stalls and quota -------------------------------------------------------------


def _failed(text: str, *, status: int | None = None, category: str | None = None, **extra) -> list[str]:
    lines = [_init()]
    if category is not None:
        lines.append(json.dumps({"type": "assistant", "message": {"id": "m", "content": []}, "error": category}))
    lines.append(json.dumps({"type": "result", "is_error": True, "api_error_status": status, "result": text, **extra}))
    return lines


@pytest.mark.parametrize(
    ("text", "status", "category"),
    [
        ("API Error: Repeated 529 Overloaded errors", 529, "overloaded"),
        ("API Error: 500 Internal server error", 500, "server_error"),
        ("Request rejected (429)", 429, "rate_limit"),
        ("Server is temporarily limiting requests", None, None),
        ("Request timed out", None, None),
        ("API Error: No response from API", None, None),
        ("Unable to connect to API", None, None),
        ("Connection lost mid-response", None, None),
        ("something new", 503, None),
        ("something new", None, "overloaded"),
    ],
)
def test_retryable_claude_failures_are_provider_stalls(text: str, status: int | None, category: str | None) -> None:
    lines = _failed(text, status=status, category=category)
    assert ended_in_provider_stall(lines) and quota_exhaustion(lines) is None


@pytest.mark.parametrize(
    "text",
    [
        "Invalid API key · Fix external API key",
        "Not logged in · Please run /login",
        "API Error: 401 Invalid authentication credentials",
        "Prompt is too long",
        "Context limit reached · /compact or /clear to continue",
    ],
)
def test_non_retryable_claude_failures_are_the_harness_stopping(text: str) -> None:
    lines = _failed(text, status=401 if "401" in text else 400, category="invalid_request")
    assert not ended_in_provider_stall(lines) and quota_exhaustion(lines) is None


def test_only_a_failed_result_is_a_stall() -> None:
    retry = json.dumps({"type": "system", "subtype": "api_retry", "error_status": 529, "error": "overloaded"})
    done = _result({MODEL: _mu(1, 1)})
    assert not ended_in_provider_stall([_init(), retry, done])  # Claude Code retried and recovered
    assert not ended_in_provider_stall([_init(), retry])  # killed, no result: the harness stopping
    assert not ended_in_provider_stall([])


def test_usage_limits_are_quota_exhaustion_never_stalls() -> None:
    rejected = json.dumps({"type": "rate_limit_event", "rate_limit_info": _limit("rejected")})
    # Structured: the rejected window's reset, whatever the message says.
    lines = [_init(), rejected, *_failed("You've hit your session limit", status=429, category="rate_limit")[1:]]
    assert quota_exhaustion(lines) == {"message_class": "usage_limit", "reset_at_utc": RESET_ISO}
    assert not ended_in_provider_stall(lines)
    # The message alone: a usage limit with an unknown reset (the loop stops the episode).
    for text in ("You've hit your weekly limit", "You’ve hit your Opus limit", "You've hit your monthly spend limit"):
        assert quota_exhaustion(_failed(text)) == {"message_class": "usage_limit", "reset_at_utc": None}
    assert quota_exhaustion(_failed("Credit balance is too low")) == {
        "message_class": "credit_balance",
        "reset_at_utc": None,
    }
    # Overage carries on, or the window was allowed again: not blocked.
    overage = json.dumps({"type": "rate_limit_event", "rate_limit_info": _limit("rejected", overageStatus="allowed")})
    assert quota_exhaustion([_init(), overage]) is None
    allowed = json.dumps({"type": "rate_limit_event", "rate_limit_info": _limit("allowed", utilization=0.1)})
    assert quota_exhaustion([_init(), rejected, allowed]) is None
    # A rejection followed by a successful result did not stop anything.
    assert quota_exhaustion([_init(), rejected, _result({MODEL: _mu(1, 1)})]) is None
    # Parked: an open rejection and no result yet.
    driver = ClaudeDriver()
    assert driver.invocation_parked([_init(), rejected])
    assert not driver.invocation_parked([_init(), rejected, allowed])
    assert not driver.invocation_parked([_init(), rejected, _result({MODEL: _mu(1, 1)}, is_error=True)])
    assert driver.quota_exhausted([_init(), rejected], isolation="same-user", now=0.0)["reset_at_utc"] == RESET_ISO


def test_quota_windows_keep_the_latest_report_per_window() -> None:
    def event(info: dict) -> str:
        return json.dumps({"type": "rate_limit_event", "rate_limit_info": info})

    lines = [
        event(_limit("allowed", utilization=0.5)),
        event(_limit("allowed_warning", kind="seven_day", utilization=0.8)),
        event(_limit("allowed_warning", utilization=0.97)),
        event(_limit("rejected", kind="overage", utilization=1.0)),
        event({"status": "allowed", "rateLimitType": "five_hour"}),  # no utilization: ignored
        "not json",
    ]
    assert claude.quota_windows(lines) == [
        {"window_minutes": 300, "used_percent": 97.0, "resets_at_utc": RESET_ISO, "rate_limit_type": "five_hour"},
        {"window_minutes": 10080, "used_percent": 80.0, "resets_at_utc": RESET_ISO, "rate_limit_type": "seven_day"},
    ]
    # At or above 95% used, the panel pauses before the next episode, as for Codex.
    pause = opencode._quota_pause({"harness_run": {"quota_windows": claude.quota_windows(lines)}}, 0, 95.0, 600.0, 0)
    assert pause is not None and pause["used_percent"] == 97.0


# -- CLI ------------------------------------------------------------------------


def test_cli_dispatches_claude_and_refuses_container_and_missing_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench import cli

    seen: dict = {}

    def fake_run_panel(seeds, **kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(claude, "run_panel", fake_run_panel)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    token = _token_file(tmp_path)
    base = ["agentic", "--seeds", "11", "--model", "claude-x", "--output", str(tmp_path / "run")]
    with pytest.raises(SystemExit):
        cli.main([*base, "--harness", "claude", "--claude-token-file", str(token), "--variant", "low"])
    assert seen["token_file"] == str(token) and (seen["binary"], seen["variant"]) == ("claude", "low")
    seen.clear()
    with pytest.raises(SystemExit, match="only for --harness claude"):
        cli.main([*base, "--claude-token-file", str(token)])
    with pytest.raises(SystemExit, match="open decision"):
        cli.main([*base, "--harness", "claude", "--claude-token-file", str(token), "--isolation", "container"])
    with pytest.raises(SystemExit, match="needs credentials"):
        cli.main([*base, "--harness", "claude"])
    assert seen == {}
