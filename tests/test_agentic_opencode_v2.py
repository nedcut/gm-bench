"""The OpenCode 2.x driver: its command line, workspace, error shapes and token telemetry."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from gm_bench.agentic import opencode
from gm_bench.agentic.opencode import OPENCODE_DRIVER, OpenCodeDriver
from tests.test_agentic_mcp import _scripted_harness

# The real export, taken before ``conftest`` stubs it out for every test.
_EXPORT_SESSION = opencode.export_session

# One invocation as OpenCode 2.0.27 printed it (``run --format json``, trimmed): a tool step
# with its ``step_finish``, then the closing text step, whose ``step_finish`` never comes.
_STEP_START = {"type": "step_start", "timestamp": 1, "sessionID": "ses_v2", "part": {"type": "step-start"}}
_TOOL_USE = {
    "type": "tool_use",
    "timestamp": 2,
    "sessionID": "ses_v2",
    "part": {"type": "tool", "tool": "shell", "state": {"status": "completed", "input": {"command": "pwd"}}},
}
_STEP_FINISH = {
    "type": "step_finish",
    "timestamp": 3,
    "sessionID": "ses_v2",
    "part": {
        "type": "step-finish",
        "reason": "tool-calls",
        "cost": 0,
        "tokens": {"input": 4710, "output": 27, "reasoning": 0, "cache": {"read": 518, "write": 0}},
    },
}
_TEXT = {"type": "text", "timestamp": 4, "sessionID": "ses_v2", "part": {"type": "text", "text": "done"}}
_STREAM = [json.dumps(event) for event in (_STEP_START, _TOOL_USE, _STEP_FINISH, _STEP_START, _TEXT)]
# ``opencode session export ses_v2`` for the same session (trimmed): both steps' usage.
_EXPORT = {
    "info": {
        "id": "ses_v2",
        "cost": 0,
        # The session total also counts OpenCode's side requests (the title); not used.
        "tokens": {"input": 4783, "output": 48, "reasoning": 0, "cache": {"read": 6395, "write": 0}},
    },
    "messages": [
        {"type": "user", "id": "msg_1", "text": "brief"},
        {
            "type": "assistant",
            "id": "msg_2",
            "finish": "tool-calls",
            "cost": 0,
            "tokens": {"input": 4710, "output": 27, "reasoning": 0, "cache": {"read": 518, "write": 0}},
        },
        {
            "type": "assistant",
            "id": "msg_3",
            "finish": "stop",
            "cost": 0.0125,
            "tokens": {"input": 51, "output": 15, "reasoning": 4, "cache": {"read": 5228, "write": 7}},
        },
        {
            "type": "compaction",
            "id": "msg_4",
            "status": "completed",
            "cost": 0.001,
            "tokens": {"input": 100, "output": 20, "reasoning": 0, "cache": {"read": 0, "write": 0}},
        },
        {"type": "idle", "id": "msg_5", "outcome": "succeeded"},
    ],
}


def _error(kind: str, message: str = "m", **extra) -> str:
    return json.dumps(
        {"type": "error", "timestamp": 9, "sessionID": "ses_v2", "error": {"type": kind, "message": message, **extra}}
    )


def test_run_and_resume_use_a_private_server_and_carry_no_removed_flags() -> None:
    args = OPENCODE_DRIVER.run_args(model="opencode/m", variant=None, workdir="/w", brief="B", isolation="same-user")
    assert args == ["run", "--format", "json", "--auto", "--model", "opencode/m", "B"]
    resume = OPENCODE_DRIVER.resume_args(
        model="opencode/m", variant="high", workdir="/w", session_id="ses_v2", text="T", isolation="container"
    )
    assert resume == [
        "run", "--format", "json", "--auto", "--model", "opencode/m#high", "--session", "ses_v2", "T",
    ]  # fmt: skip
    # OpenCode 2 rejects these with its help text and launches nothing.
    for removed in ("--pure", "--dir", "--variant"):
        assert removed not in args + resume


def test_the_workspace_is_the_scratch_through_pwd(tmp_path: Path) -> None:
    driver = OpenCodeDriver()
    scratch = tmp_path / "scratch"
    env = driver.environment({"PWD": "/operator/checkout", "OPENCODE_CONFIG": "x"}, scratch, "same-user")
    try:
        # OpenCode 2 reads PWD before the working directory; the operator's must not reach it.
        assert env["PWD"] == str(scratch)
        assert "OPENCODE_CONFIG" not in env and env["HOME"] != str(Path.home())
    finally:
        driver.cleanup(type("L", (), {"scratch": scratch, "evidence_paths": ()})())
    # A container starts in the mounted scratch; the docker client's environment keeps its own PWD.
    assert OpenCodeDriver().environment({"PWD": "/x"}, scratch, "container") == {"PWD": "/x"}


def test_opencode_2_transient_errors_are_stalls_and_final_ones_are_refusals() -> None:
    start = json.dumps(_STEP_START)
    for kind in sorted(opencode.RETRYABLE_ERROR_TYPES):
        assert opencode.ended_in_provider_stall([start, json.dumps(_TOOL_USE), _error(kind)]), kind
        assert opencode.provider_error([_error(kind)]) is None
    # A transient status or message counts whatever the type says.
    assert opencode.ended_in_provider_stall([json.dumps(_TOOL_USE), _error("unknown", status=503)])
    assert opencode.ended_in_provider_stall([json.dumps(_TOOL_USE), _error("unknown", "Model is overloaded")])
    # A final provider error ends the episode as the provider's, with its status.
    refused = _error("provider.invalid-request", "This Go model requires Global regions", status=400)
    assert not opencode.ended_in_provider_stall([json.dumps(_TOOL_USE), refused])
    assert opencode.provider_error([refused]) == {
        "status_code": 400,
        "message": "This Go model requires Global regions",
    }
    assert opencode.provider_error([_error("provider.auth", "Unauthorized", status=401)])["status_code"] == 401
    # Not provider errors at all: the run's own interruption, an unknown failure.
    assert opencode.provider_error([_error("aborted", "Session interrupted: x")]) is None
    assert opencode.provider_error([_error("unknown", "Prompt was not promoted")]) is None
    # Recovered (not the last event): neither.
    assert not opencode.ended_in_provider_stall([_error("provider.rate-limit"), start])


def test_an_unresolved_model_at_startup_is_a_stall_only_before_the_invocation_acted() -> None:
    # What 2.0.27 printed for ``--model nope/nope`` in a fresh home: the only event.
    no_route = _error("provider.no-route", "Model unavailable: nope/nope")
    assert opencode.ended_in_provider_stall([no_route])
    assert opencode.ended_in_startup_server_error([json.dumps(_STEP_START), no_route])
    # After a tool call it is the provider refusing, not a startup race.
    acted = [json.dumps(_STEP_START), json.dumps(_TOOL_USE), no_route]
    assert not opencode.ended_in_provider_stall(acted)
    assert opencode.provider_error(acted)["message"] == "Model unavailable: nope/nope"


def test_a_free_allowance_spent_on_opencode_2_is_quota_exhaustion() -> None:
    body = json.dumps({"type": "error", "error": {"type": "FreeUsageLimitError", "message": "Free usage exceeded"}})
    line = _error("provider.quota", "Free usage exceeded", status=429, response={"body": body})
    assert opencode.quota_exhaustion([line]) == {"message_class": "free_usage_limit", "reset_at_utc": None}
    assert not opencode.ended_in_provider_stall([line]) and opencode.provider_error([line]) is None


def test_session_export_usage_counts_every_step_the_stream_dropped() -> None:
    stream = opencode.parse_opencode_events(_STREAM)
    # The stream saw one step; the closing one never printed its usage.
    assert (stream["model_calls"], stream["output_tokens"]) == (1, 27)
    usage = opencode.session_export_usage(_EXPORT)
    assert usage == {
        "model_calls": 2,
        "input_tokens": 4710 + 518 + 51 + 5228 + 7 + 100,
        "uncached_input_tokens": 4710 + 51 + 100,
        "output_tokens": 27 + 15 + 4 + 20,
        "reasoning_tokens": 4,
        "cached_input_tokens": 518 + 5228,
        "cache_write_tokens": 7,
        "max_output_tokens_per_call": 27,
        "cost_usd": 0.0135,
        "compactions": 1,
    }
    for export in (None, [], {"info": {}}, {"messages": "x"}):
        assert opencode.session_export_usage(export) is None


def _launch(tmp_path: Path, binary: str = "opencode"):
    from gm_bench.agentic.episode import AgenticEpisode

    episode = AgenticEpisode(1, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    events = tmp_path / "opencode-events.jsonl"
    events.write_text("\n".join(_STREAM) + "\n")
    driver = OpenCodeDriver()
    launch = opencode.HarnessLaunch(episode, binary=binary, driver=driver, evidence_paths=(events,))
    return episode, driver, launch


def test_export_session_runs_the_export_in_the_private_home(tmp_path: Path) -> None:
    log = tmp_path / "export-call.json"
    fake = tmp_path / "fake-opencode"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"open({str(log)!r}, 'w').write(json.dumps([sys.argv[1:], os.environ['XDG_DATA_HOME']]))\n"
        f"print(json.dumps({_EXPORT!r}))\n"
    )
    fake.chmod(0o755)
    episode, driver, launch = _launch(tmp_path, str(fake))
    try:
        export, problem = _EXPORT_SESSION(launch, "ses_v2")
        assert (export, problem) == (_EXPORT, None)
        args, data_home = json.loads(log.read_text())
        assert args == ["session", "export", "ses_v2", "--standalone"]
        assert data_home == launch.env["XDG_DATA_HOME"]
    finally:
        launch.close()
        episode.close()
    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(4)\n")
    episode, driver, launch = _launch(tmp_path)
    launch.binary = str(fake)
    try:
        assert _EXPORT_SESSION(launch, "ses_v2") == (None, "session export exited 4")
        launch.binary = str(tmp_path / "missing")
        assert _EXPORT_SESSION(launch, "ses_v2")[1].startswith("session export could not start")
    finally:
        launch.close()
        episode.close()


def test_final_telemetry_prefers_the_session_store_and_says_when_it_could_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exported: list[str] = []
    monkeypatch.setattr(opencode, "export_session", lambda launch, sid: (exported.append(sid) or _EXPORT, None))
    episode, driver, launch = _launch(tmp_path)
    launch.close()
    episode.close()
    assert exported == ["ses_v2"]
    telemetry = driver.final_telemetry(launch, opencode.parse_opencode_events(_STREAM))
    usage = opencode.usage_block(telemetry, model="m", decisions=4)
    assert usage["api_calls"] == 2 and usage["output_tokens"] == 66
    assert usage["harness"]["token_source"] == "session_export" and "session_export_error" not in usage["harness"]
    # The stream's tool counts and session id are kept.
    assert usage["harness"]["tool_events"] == {"shell": 1} and usage["harness"]["session_id"] == "ses_v2"

    # Without the store: the stream's counts, labelled as such, with the reason.
    monkeypatch.setattr(opencode, "export_session", lambda launch, sid: (None, "session export exited 1"))
    episode, driver, launch = _launch(tmp_path / "again")
    launch.close()
    episode.close()
    usage = opencode.usage_block(
        driver.final_telemetry(launch, opencode.parse_opencode_events(_STREAM)), model="m", decisions=4
    )
    assert usage["api_calls"] == 1 and usage["output_tokens"] == 27
    assert usage["harness"]["token_source"] == "event_stream"
    assert usage["harness"]["session_export_error"] == "session export exited 1"


def test_an_episode_records_the_session_stores_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gm_bench.agentic.validate import validate_run

    monkeypatch.setattr(opencode, "export_session", lambda launch, sid: (_EXPORT, None))
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    monkeypatch.setattr(opencode, "_run_harness", _scripted_harness([{"phases": 4}], []))
    run_dir = tmp_path / "run"
    payload = opencode.run_panel([11], model="opencode/m", run_dir=run_dir, seasons=1, binary="none")
    usage = payload["episodes"][0]["usage"]
    assert usage["api_calls"] == 2 and usage["harness"]["token_source"] == "session_export"
    assert validate_run(run_dir)["ok"]


def test_opencode_version_reads_the_2x_wording(tmp_path: Path) -> None:
    fake = tmp_path / "opencode"
    for printed, expected in (("opencode v2.0.27", "2.0.27"), ("1.18.31", "1.18.31")):
        fake.write_text(f"#!{sys.executable}\nprint({printed!r})\n")
        fake.chmod(0o755)
        assert opencode.opencode_version(str(fake)) == expected


def test_a_call_opencode_refused_on_its_schema_is_skipped_not_counted() -> None:
    def tool(name: str, status: str, error: str | None = None) -> str:
        state = {"status": status, "input": {}} | ({"error": error} if error is not None else {})
        return json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": name, "state": state}})

    refused = 'Invalid arguments for tool "gm-bench_trade":\n- partner_team_id: Missing key\n\nUpdate the arguments.'
    telemetry = opencode.parse_opencode_events(
        [
            tool("gm-bench_trade", "error", refused),
            # The engine's own rejection reached the server: still a call.
            tool("gm-bench_trade", "error", '{"ok": false, "message": "partner rejects the offer"}'),
            tool("gm-bench_get_status", "completed"),
            # A refusal naming another tool is not this call's.
            tool("gm-bench_draft", "error", refused),
            # Arguments that were not JSON: OpenCode refused them before the tool ran.
            tool(
                "gm-bench_scout",
                "error",
                "Tool call arguments were malformed JSON and were not executed. Retry with valid JSON.",
            ),
        ]
    )
    assert telemetry["harness_tool_events"] == {"gm-bench_draft": 1, "gm-bench_get_status": 1, "gm-bench_trade": 1}
    assert telemetry["harness_tool_calls_skipped"] == {"gm-bench_scout": 1, "gm-bench_trade": 1}
    assert opencode.harness_tool_calls(telemetry) == 3


def test_a_resumed_run_validates_and_publishes_its_resumes_by_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.publication import compact_agentic_run
    from gm_bench.agentic.validate import validate_run

    monkeypatch.setattr(opencode, "export_session", lambda launch, sid: (_EXPORT, None))
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    monkeypatch.setattr(opencode, "_run_harness", _scripted_harness([{"phases": 4}, {"phases": 4}], []))
    run_dir = tmp_path / "run"
    opencode.run_panel([11, 12], model="opencode/m", run_dir=run_dir, seasons=1, binary="none")
    # As a kill mid-episode leaves it: no run.json, and the second episode without its result.
    (run_dir / "run.json").unlink()
    (run_dir / "seed-12" / "result.json").unlink()

    monkeypatch.setattr(opencode, "_run_harness", _scripted_harness([{"phases": 4}], []))
    payload = opencode.run_panel([11, 12], model="opencode/m", run_dir=run_dir, seasons=1, binary="none", resume=True)

    assert [episode["seed"] for episode in payload["episodes"]] == [11, 12]
    assert validate_run(run_dir)["ok"]
    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["resumes"] == [
        {
            "resumed_at_utc": payload["resumes"][0]["resumed_at_utc"],
            "reused": [0],
            "set_aside": [{"episode": 1, "reason": "unfinished"}],
        }
    ]
