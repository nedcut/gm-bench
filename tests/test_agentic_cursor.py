"""The Cursor CLI harness driver, proven against a fake ``cursor-agent`` that speaks its stream-json.

No test here runs the real Cursor CLI or contacts a model. The fake binary
reads the staged ``$HOME/.cursor/mcp.json``, launches the MCP proxy it
declares, makes real GM-Bench tool calls through it, and prints the
``cursor-agent -p --output-format stream-json`` events recorded from Cursor
CLI 2026.09.26-dd393fe: ``system``/``init``, ``tool_call`` started/completed
with ``mcpToolCall`` and ``getMcpToolsToolCall``, and a ``result`` whose
``usage`` covers only that process. Failures are plain text on stderr.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from gm_bench.agentic import cursor, opencode
from gm_bench.agentic.cursor import (
    CursorDriver,
    ended_in_provider_stall,
    parse_cursor_events,
    prompt_audit,
    prompt_audit_problems,
    quota_exhaustion,
    token_env,
)
from gm_bench.agentic.prompt_check import OperatorMarkers, operator_content

DUMMY_KEY = "key_dummy-not-a-real-cursor-api-key-0000"
DUMMY_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJkdW1teSI6dHJ1ZX0.dummy-signature-0000"
MODEL = "composer-fake"

# The fake ``cursor-agent``. Behaviour per invocation comes from the plan file
# named by FAKE_CURSOR_PLAN: {"log": path, "state": path, "steps": [{"phases":
# n, "stderr": text, "exit": code, "cat_env": bool, "tamper": bool}, ...],
# "rules": [text, ...]}; the rules are account User Rules the server adds to
# every prompt, including the driver's one-word ``--mode ask`` prompt check,
# which is answered without using up a step.
# Each phase is a get_status then an end_phase through the proxy the staged
# mcp.json declares, the first preceded by a schema lookup, as Cursor does.
# ``stderr`` fails the run the way the CLI does: text on stderr, no result.
FAKE_CURSOR = r"""
import json, os, subprocess, sys, uuid
from pathlib import Path

argv = sys.argv[1:]
if argv == ["--version"]:
    print("2026.09.26-dd393fe")
    sys.exit(0)
plan = json.loads(Path(os.environ["FAKE_CURSOR_PLAN"]).read_text())
home = Path(os.environ["HOME"])
config_dir = Path(os.environ["CURSOR_CONFIG_DIR"])

def emit(event):
    print(json.dumps(event), flush=True)

def record_context(session):
    # Cursor keeps the chat, with the prompt context, in a store under CURSOR_CONFIG_DIR.
    chat = config_dir / "chats" / "workspace" / session
    chat.mkdir(parents=True, exist_ok=True)
    db = __import__("sqlite3").connect(chat / "store.db")
    db.execute("CREATE TABLE IF NOT EXISTS blobs (id TEXT, data BLOB)")
    # The rules slot in the shape Cursor sends it: preamble, described <user_rules>, bare <user_rule>s.
    rules = "\n\n".join(f"<user_rule>{rule}</user_rule>" for rule in plan.get("rules", []))
    slot = f"<rules>\n{plan['preamble']}\n\n\n{plan['user_rules_open']}\n{rules}\n</user_rules>\n</rules>\n"
    context = "<user_info>OS</user_info>\n" + (slot if rules else "")
    context += "<agent_skills>bundled</agent_skills>"
    db.execute("INSERT INTO blobs VALUES (?, ?)", ("c", json.dumps({"role": "user", "content": context}).encode()))
    db.commit()
    db.close()

if "--mode" in argv:
    with open(plan["log"] + ".probes", "a") as log:
        log.write(json.dumps({"argv": argv, "cursor_env": sorted(k for k in os.environ if k.startswith("CURSOR"))}) + "\n")
    if plan.get("probe_stderr"):
        sys.stderr.write(plan["probe_stderr"].replace("$KEY", os.environ.get("CURSOR_API_KEY", "")))
        sys.exit(1)
    session = str(uuid.uuid4())
    record_context(session)
    emit({"type": "system", "subtype": "init", "session_id": session, "model": "Composer Fake"})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": "ok", "session_id": session,
          "usage": {"inputTokens": 10, "outputTokens": 1, "cacheReadTokens": 0, "cacheWriteTokens": 0}})
    sys.exit(0)
state_path = Path(plan["state"])
state = json.loads(state_path.read_text()) if state_path.exists() else {"invocations": 0}
state["invocations"] += 1
invocation = state["invocations"]
state_path.write_text(json.dumps(state))
step = plan["steps"][min(invocation, len(plan["steps"])) - 1]

def value(flag):
    return argv[argv.index(flag) + 1] if flag in argv else None

with open(plan["log"], "a") as log:
    log.write(json.dumps({
        "argv": argv,
        "cwd": os.getcwd(),
        "env": {k: os.environ[k] for k in os.environ if k in ("HOME", "CURSOR_CONFIG_DIR", "CURSOR_DATA_DIR")},
        "cursor_env": sorted(k for k in os.environ if k.startswith("CURSOR")),
        "store": os.environ.get("AGENT_CLI_CREDENTIAL_STORE"),
        "home_cursor": sorted(p.name for p in (home / ".cursor").iterdir()),
        "scratch": sorted(p.name for p in Path.cwd().iterdir()),
        "mcp": json.loads((home / ".cursor" / "mcp.json").read_text()),
    }) + "\n")
assert argv[0] == "-p" and value("--output-format") == "stream-json" and "--approve-mcps" in argv

session = value("--resume") or str(uuid.uuid4())
emit({"type": "system", "subtype": "init", "apiKeySource": "env", "cwd": os.getcwd(), "session_id": session,
      "model": "Composer Fake", "permissionMode": "default"})
emit({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": argv[-1]}]},
      "session_id": session})
record_context(session)

def call(call_id, tool_call, step):
    step_id = f"{session}-{invocation}-{step}"
    for subtype in ("started", "completed"):
        emit({"type": "tool_call", "subtype": subtype, "call_id": call_id, "tool_call": tool_call,
              "model_call_id": step_id, "session_id": session})

if step.get("cat_env"):
    text = " ".join(f"{k}={os.environ[k]}" for k in ("CURSOR_API_KEY", "CURSOR_AUTH_TOKEN") if k in os.environ)
    call(f"tool_{invocation}_env", {"shellToolCall": {"args": {"command": "env"}, "result": {"success": {"stdout": text}}}}, 0)
    sys.stderr.write("shell: " + text + "\n")
if step.get("phases"):
    server = json.loads((home / ".cursor" / "mcp.json").read_text())["mcpServers"]["gm-bench"]
    proxy = subprocess.Popen([server["command"], *server["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(payload):
        proxy.stdin.write(json.dumps(payload) + "\n")
        proxy.stdin.flush()
        return json.loads(proxy.stdout.readline())
    rpc({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    proxy.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    call(f"tool_{invocation}_schema", {"getMcpToolsToolCall": {"args": {"server": "gm-bench", "toolName": "get_status"}}}, 0)
    number = 0
    for phase in range(step["phases"]):
        for tool in ("get_status", "end_phase"):
            number += 1
            reply = rpc({"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": {"name": tool, "arguments": {}}})
            args = {"name": f"gm-bench-{tool}", "args": {}, "providerIdentifier": "gm-bench", "toolName": tool,
                    "serverIdentifier": "gm-bench"}
            call(f"tool_{invocation}_{number}", {"mcpToolCall": {"args": args, "result": {"success": reply["result"]}}},
                 number)
    proxy.stdin.close()
    proxy.wait(timeout=30)
if step.get("tamper"):
    project = Path.cwd() / ".cursor"
    project.mkdir(exist_ok=True)
    (project / "mcp.json").write_text('{"mcpServers": {"other": {"command": "sh"}}}')
    (home / ".cursor" / "hooks.json").write_text('{"hooks": {}}')
    staged = home / ".cursor" / "mcp.json"
    data = json.loads(staged.read_text())
    data["mcpServers"]["other"] = {"command": "sh", "args": ["-c", "id"]}
    staged.write_text(json.dumps(data))
if step.get("stderr"):
    sys.stderr.write(step["stderr"] + "\n")
    sys.exit(step.get("exit", 1))
emit({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done for now."}]},
      "session_id": session})
emit({"type": "result", "subtype": "success", "duration_ms": 1000, "duration_api_ms": 1000, "is_error": False,
      "result": "Done for now.", "session_id": session, "request_id": str(uuid.uuid4()),
      "usage": {"inputTokens": 1000, "outputTokens": 50, "cacheReadTokens": 4000, "cacheWriteTokens": 100}})
sys.exit(step.get("exit", 0))
"""


def _fake_cursor(
    tmp_path: Path, steps: list[dict], monkeypatch: pytest.MonkeyPatch, *, rules: list[str] | None = None
) -> tuple[Path, Path]:
    binary = tmp_path / "fake-cursor-agent"
    binary.write_text(f"#!{sys.executable}\n{FAKE_CURSOR}")
    binary.chmod(0o755)
    log = tmp_path / "cursor-calls.jsonl"
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "log": str(log),
                "state": str(tmp_path / "state.json"),
                "steps": steps,
                "rules": rules or [],
                "preamble": cursor._RULES_PREAMBLE,
                "user_rules_open": cursor._USER_RULES_OPENERS[0],
            }
        )
    )
    monkeypatch.setenv("FAKE_CURSOR_PLAN", str(plan))
    # Host Cursor state that must not reach the harness.
    monkeypatch.setenv("CURSOR_CONFIG_DIR", str(tmp_path / "host-cursor-config"))
    monkeypatch.setenv("CURSOR_API_BASE_URL", "http://127.0.0.1:9/host-gateway")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("CURSOR_AUTH_TOKEN", raising=False)
    # CI may install gm_bench into the system python; the sandbox check has its own tests.
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    return binary, log


def _token_file(tmp_path: Path, token: str = DUMMY_KEY) -> Path:
    path = tmp_path / "operator-cursor-token"
    path.write_text(token + "\n")
    return path


def _calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


# -- the full loop against the fake binary --------------------------------------


def test_cursor_panel_plays_through_the_staged_proxy_nudges_by_resume_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from gm_bench.agentic.validate import validate_run

    # First run: one phase, then the model answers with text. The nudge resumes and finishes.
    binary, log = _fake_cursor(tmp_path, [{"phases": 1}, {"phases": 3}], monkeypatch)
    run_dir = tmp_path / "run"
    payload = cursor.run_panel(
        [11],
        model=MODEL,
        run_dir=run_dir,
        seasons=1,
        binary=str(binary),
        token_file=_token_file(tmp_path),
        prompt_check=True,
    )
    assert payload["agent"] == f"cursor:{MODEL}"
    assert payload["harness"] == {"name": "cursor", "version": "2026.09.26-dd393fe", "model": MODEL, "variant": None}
    [episode] = payload["episodes"]
    harness_run = episode["harness_run"]
    assert harness_run["events_path"] == "seed-11/cursor-events.jsonl"
    # Every GM-Bench call is in the ledger and the stream; the schema lookups never reached the server.
    assert harness_run["tool_call_agreement"] == {"ledger": 8, "harness": 8, "agree": True}
    assert episode["usage"]["harness"]["tool_events"] == {
        "get_mcp_tools": 2,
        "gm-bench_end_phase": 4,
        "gm-bench_get_status": 4,
    }
    assert episode["agentic"]["phases_ended_by"] == {"agent": 4}
    assert episode["failed_decisions"] == 0

    first, nudge = _calls(log)
    init = json.loads((run_dir / "seed-11" / "cursor-events.jsonl").read_text().splitlines()[0])
    resume_at = nudge["argv"].index("--resume")
    assert nudge["argv"][resume_at + 1] == init["session_id"]
    assert "Reminder 1 of 20" in nudge["argv"][-1]
    assert first["argv"][:-1] == nudge["argv"][:resume_at]
    assert first["argv"][:-1] == [
        "-p",
        "--output-format",
        "stream-json",
        "--trust",
        "--force",
        "--approve-mcps",
        "--sandbox",
        "disabled",
        "--model",
        MODEL,
    ]
    # No host Cursor state: HOME, CURSOR_CONFIG_DIR and CURSOR_DATA_DIR are private, outside the
    # scratch, the same for the resume, gone after the episode; only the handed-off credential remains.
    assert first["env"] == nudge["env"]
    for call in _calls(log):
        cwd = Path(call["cwd"]).resolve()
        for path in call["env"].values():
            assert not Path(path).resolve().is_relative_to(cwd) and not Path(path).exists()
        assert call["env"]["CURSOR_CONFIG_DIR"] != str(tmp_path / "host-cursor-config")
        assert call["cursor_env"] == ["CURSOR_API_KEY", "CURSOR_CONFIG_DIR", "CURSOR_DATA_DIR"]
        assert call["store"] == "memory"
        [server] = call["mcp"]["mcpServers"].values()
        assert list(call["mcp"]["mcpServers"]) == ["gm-bench"] and sorted(server) == ["args", "command"]
        assert Path(server["args"][0]).resolve() == cwd / "gm_bench_proxy.py" and len(server["args"]) == 2
    # Usage is summed over the two results (each covers one process). Model steps: (schema + 2 calls) + (schema + 6).
    usage = episode["usage"]
    assert (usage["input_tokens"], usage["uncached_input_tokens"]) == (10200, 2000)
    assert (usage["cached_input_tokens"], usage["cache_write_input_tokens"]) == (8000, 200)
    assert usage["output_tokens"] == 100 and usage["api_calls"] == 2
    assert usage["harness"]["usage_complete"] is True and usage["harness"]["model_steps"] == 10
    assert usage["cost_usd"] is None and usage["harness"]["api_equivalent_cost_usd"] is None
    assert harness_run["auth"] == "token-file" and harness_run["session_resume"] == "cursor-agent -p --resume"
    assert harness_run["prompt_audit"] == {
        "sections": ["agent_skills", "user_info"],
        "unexpected": [],
        "default_rules": 0,
        "user_rules": 0,
        "user_rule_characters": 0,
        "unrecognised_rules": 0,
        "operator_content": [],
    }
    assert payload["prompt_check"]["checked"] is True and payload["prompt_check"]["problems"] == []
    # The one-word prompt check ran first, in the same credential setup, before any episode.
    [probe] = [json.loads(line) for line in Path(f"{log}.probes").read_text().splitlines()]
    assert probe["argv"][-1] == cursor.PROBE_PROMPT and probe["cursor_env"] == first["cursor_env"]
    assert harness_run["config_dir_findings"] == []
    assert DUMMY_KEY not in json.dumps(payload)

    report = validate_run(run_dir)
    assert report["ok"], report
    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["harness"]["name"] == "cursor"
    assert validate_agentic_artifact(artifact)["ok"]


def test_a_stderr_rate_limit_is_a_provider_stall_retried_by_resume_not_a_nudge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [{"phases": 1, "stderr": "ConnectError: [resource_exhausted] Rate limit exceeded, please try later"}]
    binary, log = _fake_cursor(tmp_path, [*steps, {"phases": 3}], monkeypatch)
    sleeps: list[float] = []
    result = cursor.run_episode(
        11,
        model=MODEL,
        run_dir=tmp_path / "run",
        seasons=1,
        binary=str(binary),
        token_file=_token_file(tmp_path),
        max_provider_stalls=8,
        max_provider_stall_wait_seconds=3600.0,
        stall_backoff=lambda n: 7.0,
        sleep=sleeps.append,
    )
    harness_run = result["harness_run"]
    assert sleeps == [7.0] and harness_run["provider_stalls"] == 1 and harness_run["nudges_used"] == 0
    [retry] = harness_run["nudges"]
    assert retry["stall_retry"] is True and retry["new_tool_calls"] == 6
    assert ["--resume" in call["argv"] for call in _calls(log)] == [False, True]
    assert result["failed_decisions"] == 0 and harness_run["tool_call_agreement"]["agree"] is True
    # The failed invocation wrote no result: its tokens are unknown.
    assert result["usage"]["harness"]["usage_complete"] is False


def test_a_usage_limit_on_stderr_stops_the_episode_and_the_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [{"phases": 1, "stderr": "You've hit your usage limit for this billing cycle."}]
    binary, log = _fake_cursor(tmp_path, steps, monkeypatch)
    payload = cursor.run_panel(
        [11, 12], model=MODEL, run_dir=tmp_path / "run", seasons=1, binary=str(binary), token_file=_token_file(tmp_path)
    )
    assert len(payload["episodes"]) == 1 and len(_calls(log)) == 1
    run = payload["episodes"][0]["harness_run"]
    assert run["ended_by_quota"] == {"reset_at_utc": None, "message_class": "usage_limit"}
    assert run["provider_stalls"] == 0 and run["nudges"] == []


@pytest.mark.parametrize(("token", "variable"), [(DUMMY_KEY, "CURSOR_API_KEY"), (DUMMY_JWT, "CURSOR_AUTH_TOKEN")])
def test_a_cursor_credential_the_agent_prints_is_redacted_from_the_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str, variable: str
) -> None:
    binary, log = _fake_cursor(tmp_path, [{"phases": 4, "cat_env": True}], monkeypatch)
    run_dir = tmp_path / "run"
    payload = cursor.run_panel(
        [11],
        model=MODEL,
        run_dir=run_dir,
        seasons=1,
        binary=str(binary),
        token_file=_token_file(tmp_path, token),
        keep_scratch=True,
    )
    [call] = _calls(log)
    assert variable in call["cursor_env"]
    assert "[REDACTED]" in (run_dir / "seed-11" / "cursor-events.jsonl").read_text()
    assert "[REDACTED]" in (run_dir / "seed-11" / "cursor-stderr.log").read_text()
    assert [path for path in run_dir.rglob("*") if path.is_file() and token in path.read_text()] == []
    assert payload["episodes"][0]["usage"]["harness"]["tool_events"]["shell"] == 1


def test_config_the_agent_adds_between_invocations_is_removed_before_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary, log = _fake_cursor(tmp_path, [{"phases": 1, "tamper": True}, {"phases": 3}], monkeypatch)
    payload = cursor.run_panel(
        [11], model=MODEL, run_dir=tmp_path / "run", seasons=1, binary=str(binary), token_file=_token_file(tmp_path)
    )
    first, nudge = _calls(log)
    assert nudge["home_cursor"] == ["mcp.json"] and nudge["scratch"] == ["gm_bench_proxy.py"]
    assert list(nudge["mcp"]["mcpServers"]) == ["gm-bench"] and nudge["mcp"] == first["mcp"]
    assert payload["episodes"][0]["harness_run"]["config_dir_findings"] == [
        "removed hooks.json from $HOME/.cursor before a launch",
        "removed .cursor from the scratch before a launch",
        "restored mcp.json before a launch",
    ]


# -- credentials, isolation, CLI ------------------------------------------------


def test_cursor_needs_a_credential_and_refuses_container_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("CURSOR_AUTH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="needs credentials"):
        CursorDriver().preflight("same-user")
    monkeypatch.setenv("CURSOR_AUTH_TOKEN", DUMMY_JWT)
    CursorDriver().preflight("same-user")
    assert CursorDriver().auth_source() == "CURSOR_AUTH_TOKEN"
    monkeypatch.setenv("CURSOR_API_KEY", DUMMY_KEY)
    assert CursorDriver().auth_source() == "CURSOR_API_KEY"
    with pytest.raises(ValueError, match="same-user isolation only"):
        CursorDriver(token_file=_token_file(tmp_path)).preflight("container")
    bad = tmp_path / "bad-token"
    bad.write_text(DUMMY_KEY + " second\n")
    with pytest.raises(ValueError, match="exactly one") as excinfo:
        CursorDriver(token_file=bad).preflight("same-user")
    assert DUMMY_KEY not in str(excinfo.value)
    assert token_env(DUMMY_JWT) == "CURSOR_AUTH_TOKEN" and token_env(DUMMY_KEY) == "CURSOR_API_KEY"
    with pytest.raises(ValueError, match="no --variant"):
        CursorDriver().run_args(model=MODEL, variant="high", workdir="/w", brief="B", isolation="same-user")


def test_cli_dispatches_cursor_and_refuses_its_wrong_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gm_bench import cli

    seen: dict = {}

    def fake_run_panel(seeds, **kwargs):
        seen.update(kwargs, seeds=seeds)
        raise SystemExit(0)

    monkeypatch.setattr(cursor, "run_panel", fake_run_panel)
    token = _token_file(tmp_path)
    base = ["agentic", "--model", MODEL, "--output", str(tmp_path / "run")]
    with pytest.raises(SystemExit):
        cli.main([*base, "--harness", "cursor", "--cursor-token-file", str(token)])
    assert seen["binary"] == "cursor-agent" and seen["token_file"] == str(token)
    for extra, message in (
        (["--harness", "cursor", "--cursor-token-file", str(token), "--variant", "high"], "no --variant"),
        (["--harness", "cursor", "--cursor-token-file", str(token), "--isolation", "container"], "same-user"),
        (["--harness", "codex", "--cursor-token-file", str(token)], "only for --harness cursor"),
    ):
        with pytest.raises(SystemExit, match=message):
            cli.main([*base, *extra])

    def refused(seeds, **kwargs):
        raise cursor.PromptCheckError("Cursor prompt check: prompt carried context from outside the harness: rules")

    monkeypatch.setattr(cursor, "run_panel", refused)
    with pytest.raises(SystemExit, match="gm-bench agentic: Cursor prompt check: .*rules"):
        cli.main([*base, "--harness", "cursor", "--cursor-token-file", str(token)])


# -- parser -----------------------------------------------------------------------


def _event(kind: str, **fields) -> str:
    return json.dumps({"type": kind, **fields})


def test_parse_counts_each_call_once_and_marks_a_killed_invocation_incomplete() -> None:
    mcp = {"mcpToolCall": {"args": {"serverIdentifier": "gm-bench", "toolName": "get_status"}}}
    lines = [
        _event("system", subtype="init", session_id="s-1"),
        _event("tool_call", subtype="started", call_id="a", tool_call=mcp, model_call_id="r-0"),
        _event("tool_call", subtype="completed", call_id="a", tool_call=mcp, model_call_id="r-0"),
        _event("tool_call", subtype="started", call_id="b", tool_call={"readToolCall": {"args": {}}}),
        _event(
            "tool_call",
            subtype="completed",
            call_id="c",
            tool_call={
                "mcpToolCall": {"args": {"serverIdentifier": "gm-bench", "toolName": "x"}, "result": {"rejected": {}}}
            },
        ),
        _event("result", is_error=False, usage={"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 90}),
        # Killed mid-call: started, never completed, no result.
        _event("system", subtype="init", session_id="s-1"),
        _event("tool_call", subtype="started", call_id="d", tool_call=mcp),
        "not json",
    ]
    telemetry = parse_cursor_events(lines)
    assert telemetry["harness_tool_events"] == {"gm-bench_get_status": 2, "read": 1}
    assert telemetry["harness_tool_calls_skipped"] == {"gm-bench_x": 1}
    assert (telemetry["input_tokens"], telemetry["uncached_input_tokens"], telemetry["output_tokens"]) == (100, 10, 2)
    assert telemetry["model_calls"] == 1 and telemetry["max_turn_input_tokens"] == 100
    assert telemetry["usage_complete"] is False and telemetry["invocations_without_result"] == 1
    assert telemetry["session_id"] == "s-1"


@pytest.mark.parametrize(
    "stderr",
    [
        "ConnectError: [resource_exhausted] Too many requests",
        "ConnectError: [unavailable] upstream connect error",
        "Error: 503 Service Unavailable",
        "request timed out",
    ],
)
def test_transient_stderr_failures_are_provider_stalls(stderr: str) -> None:
    lines = [_event("system", subtype="init", session_id="s")]
    assert ended_in_provider_stall(lines, stderr)
    assert quota_exhaustion(lines, stderr) is None


def test_usage_limits_and_ordinary_endings_are_never_stalls() -> None:
    lines = [_event("system", subtype="init", session_id="s")]
    limit = "You've hit your usage limit. Upgrade to continue."
    assert not ended_in_provider_stall(lines, limit)
    assert quota_exhaustion(lines, limit) == {"message_class": "usage_limit", "reset_at_utc": None}
    assert not ended_in_provider_stall(lines, "Cannot use this model: nope. Available models: auto")
    ok = [*lines, _event("result", is_error=False, usage={})]
    # A successful result ends the invocation cleanly whatever stderr holds.
    assert not ended_in_provider_stall(ok, "warning: 429 earlier, retried")
    assert quota_exhaustion(ok, "usage limit") is None


def test_prompt_audit_names_sections_and_counts_rules_never_copies_them(tmp_path: Path) -> None:
    chat = tmp_path / "chats" / "w" / "s"
    chat.mkdir(parents=True)
    db = sqlite3.connect(chat / "store.db")
    db.execute("CREATE TABLE blobs (id TEXT, data BLOB)")
    content = (
        "<user_info>x <b>y</b></user_info>\nNote: text between sections.\n"
        "<rules><user_rules><user_rule>one</user_rule><user_rule>three</user_rule></user_rules></rules>"
        "<agent_skills><agent_skill>s</agent_skill></agent_skills><cloud_instructions>c</cloud_instructions>"
    )
    db.execute("INSERT INTO blobs VALUES ('a', ?)", (json.dumps({"role": "user", "content": content}).encode(),))
    db.execute("INSERT INTO blobs VALUES ('b', ?)", (b"\x00binary",))
    db.commit()
    db.close()
    audit = prompt_audit(tmp_path, OperatorMarkers(home="/no-such-operator-home"))
    assert audit == {
        "sections": ["agent_skills", "cloud_instructions", "rules", "user_info"],
        "unexpected": ["cloud_instructions", "rules"],
        "default_rules": 0,
        "user_rules": 2,
        "user_rule_characters": 8,
        "unrecognised_rules": 0,
        "operator_content": [],
    }
    assert "three" not in json.dumps(audit)
    assert prompt_audit(tmp_path / "missing") is None
    # The operator's own instruction lines in Cursor's context are caught like any harness's.
    markers = OperatorMarkers(home="/h", lines={"Text between sections, long enough to be distinctive.": "AGENTS.md"})
    content_with_line = content.replace(
        "text between sections.", "Text between sections, long enough to be distinctive."
    )
    assert operator_content([content_with_line], markers) == ["1 line(s) of ~/AGENTS.md"]
    assert prompt_audit_problems("cursor", {"prompt_audit": audit}) == [
        "prompt carried context from outside the harness: cloud_instructions, rules "
        "(2 User Rules that are not Cursor's defaults, 0 rules slots in an unrecognised shape)"
    ]
    assert prompt_audit_problems("cursor", {}) and prompt_audit_problems("claude", {}) == []


def test_cursors_own_default_rules_are_the_harness_and_any_other_rule_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default, mine = "Cursor ships this rule to every account.", "Always commit with a haiku."
    monkeypatch.setattr(cursor, "CURSOR_DEFAULT_RULES", {hashlib.sha256(default.encode()).hexdigest(): "d"})
    chat = tmp_path / "chats" / "w" / "s"
    chat.mkdir(parents=True)

    def audit(rules: str, extra: str = "") -> dict:
        db = sqlite3.connect(chat / "store.db")
        db.execute("DROP TABLE IF EXISTS blobs")
        db.execute("CREATE TABLE blobs (id TEXT, data BLOB)")
        content = f"<user_info>OS</user_info>\n<rules>{extra}<user_rules>{rules}</user_rules></rules>"
        db.execute("INSERT INTO blobs VALUES ('a', ?)", (json.dumps({"content": content}).encode(),))
        db.commit()
        db.close()
        return prompt_audit(tmp_path)

    clean = audit(f"<user_rule>\n{default}\n</user_rule>")
    assert clean["unexpected"] == [] and (clean["default_rules"], clean["user_rules"]) == (1, 0)
    assert prompt_audit_problems("cursor", {"prompt_audit": clean}) == []
    # One of the account's own rules next to the default, or a default reworded: refused.
    for rules in (
        f"<user_rule>{default}</user_rule><user_rule>{mine}</user_rule>",
        f"<user_rule>{default}!</user_rule>",
    ):
        dirty = audit(rules)
        assert dirty["unexpected"] == ["rules"] and dirty["user_rules"] == 1
    # Anything else under <rules> (memories, workspace rules) is refused even with only default User Rules.
    assert audit(f"<user_rule>{default}</user_rule>", "<memories>m</memories>")["unexpected"] == ["rules"]


def _audit_content(tmp_path: Path, *contents: str) -> dict:
    chat = tmp_path / "chats" / "w" / "s"
    chat.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(chat / "store.db")
    db.execute("DROP TABLE IF EXISTS blobs")
    db.execute("CREATE TABLE blobs (id TEXT, data BLOB)")
    for index, content in enumerate(contents):
        db.execute("INSERT INTO blobs VALUES (?, ?)", (str(index), json.dumps({"content": content}).encode()))
    db.commit()
    db.close()
    return prompt_audit(tmp_path)


def test_the_rules_gate_accepts_only_cursors_exact_shape_and_refuses_every_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default, mine = "Cursor ships this rule to every account.", "Always commit with a haiku."
    monkeypatch.setattr(cursor, "CURSOR_DEFAULT_RULES", {hashlib.sha256(default.encode()).hexdigest(): "d"})
    preamble, described = cursor._RULES_PREAMBLE, cursor._USER_RULES_OPENERS[0]
    rule = f"<user_rule>{default}</user_rule>"

    # The shape Cursor sends (recorded from real chat stores): preamble, described <user_rules>, bare rules.
    exact = (
        f"<user_info>OS</user_info>\n<rules>\n{preamble}\n\n\n{described}\n{rule}\n\n{rule}\n</user_rules>\n</rules>\n"
    )
    clean = _audit_content(tmp_path, exact)
    assert clean["unexpected"] == [] and clean["default_rules"] == 2
    assert (clean["user_rules"], clean["unrecognised_rules"]) == (0, 0)
    assert prompt_audit_problems("cursor", {"prompt_audit": clean}) == []

    refused = {
        "text directly inside <rules>": f"<rules>Be terse.<user_rules>{rule}</user_rules></rules>",
        "text after <user_rules>": f"<rules><user_rules>{rule}</user_rules>Be terse.</rules>",
        "a reworded preamble": f"<rules>{preamble} Also be terse.<user_rules>{rule}</user_rules></rules>",
        "text in <user_rules> without a <user_rule>": f"<rules><user_rules>{rule}Be terse.</user_rules></rules>",
        "only text in <user_rules>": "<rules><user_rules>Be terse.</user_rules></rules>",
        "<rules> with an attribute": f'<rules id="1"><user_rules>{rule}</user_rules></rules>',
        "<user_rules> with another attribute": f'<rules><user_rules id="1">{rule}</user_rules></rules>',
        "<user_rule> with an attribute": f'<rules><user_rules><user_rule id="1">{default}</user_rule></user_rules></rules>',
        "an unclosed <rules>": f"<rules><user_rules>{rule}</user_rules>",
        "a second <user_rules>": f"<rules><user_rules>{rule}</user_rules><user_rules>{rule}</user_rules></rules>",
        "a rule outside <rules>": f"<rules><user_rules>{rule}</user_rules></rules><user_rule>{default}</user_rule>",
        "a second, odd rules block": f"<rules><user_rules>{rule}</user_rules></rules><rules>Be terse.</rules>",
    }
    for shape, slot in refused.items():
        audit = _audit_content(tmp_path, f"<user_info>OS</user_info>\n{slot}")
        assert "rules" in audit["unexpected"], shape
        assert audit["unrecognised_rules"] >= 1, shape
        assert prompt_audit_problems("cursor", {"prompt_audit": audit}), shape
        assert "Be terse" not in json.dumps(audit), shape

    # A non-default rule counts even when it hides in an attributed tag.
    hidden = _audit_content(
        tmp_path,
        f'<user_info>OS</user_info>\n<rules id="1"><user_rules>{rule}<user_rule>{mine}</user_rule></user_rules></rules>',
    )
    assert (hidden["user_rules"], hidden["user_rule_characters"]) == (1, len(mine))
    # Every context message is audited, not just a chat's first.
    later = _audit_content(
        tmp_path,
        "<user_info>OS</user_info>",
        f"<user_info>OS</user_info><rules><user_rules><user_rule>{mine}</user_rule></user_rules></rules>",
    )
    assert later["unexpected"] == ["rules"] and later["user_rules"] == 1
    # An audit that counts a foreign rule is refused even if its unexpected list is empty.
    assert prompt_audit_problems("cursor", {"prompt_audit": {"unexpected": [], "user_rules": 1}})
    assert prompt_audit_problems("cursor", {"prompt_audit": {"unexpected": [], "unrecognised_rules": 1}})


def test_a_panel_whose_prompt_carries_account_rules_is_refused_before_it_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary, log = _fake_cursor(tmp_path, [{"phases": 4}], monkeypatch, rules=["Always commit with a haiku."])
    run_dir = tmp_path / "run"
    with pytest.raises(
        cursor.PromptCheckError, match=r"outside the harness: rules \(1 User Rules that.*Cursor Settings"
    ):
        cursor.run_panel(
            [11],
            model=MODEL,
            run_dir=run_dir,
            seasons=1,
            binary=str(binary),
            token_file=_token_file(tmp_path),
            prompt_check=True,
        )
    assert not run_dir.exists() and not log.exists()


def test_an_episode_whose_prompt_carried_rules_fails_validation_and_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.publication import compact_agentic_run, validate_agentic_artifact
    from gm_bench.agentic.validate import validate_run

    # A run without the prompt check (or rules the account gained after it passed).
    binary, _log = _fake_cursor(tmp_path, [{"phases": 4}], monkeypatch, rules=["Be terse."])
    run_dir = tmp_path / "run"
    payload = cursor.run_panel(
        [11], model=MODEL, run_dir=run_dir, seasons=1, binary=str(binary), token_file=_token_file(tmp_path)
    )
    assert payload["episodes"][0]["harness_run"]["prompt_audit"]["unexpected"] == ["rules"]
    report = validate_run(run_dir)
    assert not report["ok"]
    assert any("outside the harness: rules" in problem for problem in report["per_episode"][0]["problems"])
    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["episodes"][0]["harness_run"]["prompt_audit"]["user_rules"] == 1
    errors = validate_agentic_artifact(artifact)["errors"]
    assert any("outside the harness: rules" in error for error in errors)


def test_a_failed_prompt_check_redacts_a_token_that_straddles_the_stderr_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary, _log = _fake_cursor(tmp_path, [{}], monkeypatch)
    plan_path = Path(os.environ["FAKE_CURSOR_PLAN"])
    plan = json.loads(plan_path.read_text())
    # The key starts before the last 300 characters and ends inside them.
    plan["probe_stderr"] = "E" * 50 + "$KEY" + "z" * 280
    plan_path.write_text(json.dumps(plan))
    with pytest.raises(cursor.PromptCheckError) as raised:
        cursor.probe_prompt(model=MODEL, binary=str(binary), token_file=_token_file(tmp_path))
    message = str(raised.value)
    assert "z" * 280 in message
    assert not any(DUMMY_KEY[i : i + 8] in message for i in range(len(DUMMY_KEY) - 7))


def test_cursor_version_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary, _log = _fake_cursor(tmp_path, [{}], monkeypatch)
    assert CursorDriver().version(str(binary)) == "2026.09.26-dd393fe"
    assert os.environ["FAKE_CURSOR_PLAN"]
