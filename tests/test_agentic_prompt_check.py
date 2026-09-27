"""The pre-panel prompt check: a loopback capture server, the operator-content search, and the gates.

The harness here is a stand-in ``claude`` that sends one Messages request to
``ANTHROPIC_BASE_URL``, as Claude Code does, carrying whatever system text
the test gives it. No real harness runs and no provider is contacted.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from gm_bench.agentic import claude, codex, opencode
from gm_bench.agentic.container import ContainerError
from gm_bench.agentic.prompt_check import (
    OperatorMarkers,
    PromptCheckError,
    operator_content,
    operator_markers,
    prompt_check_problems,
    run_prompt_check,
)

OPERATOR_LINE = "Always sign every commit message with the operator's favourite haiku."

FAKE_HARNESS = r"""
import json, os, sys, urllib.request
if sys.argv[1:] == ["--version"]:
    print("0.0.1 (Fake)")
    sys.exit(0)
if os.environ.get("FAKE_SILENT"):
    sys.exit(3)
body = {"model": "m", "stream": False, "system": os.environ.get("FAKE_SYSTEM", "You are a harness."),
        "messages": [{"role": "user", "content": sys.argv[-1]}]}
request = urllib.request.Request(os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
reply = json.loads(urllib.request.urlopen(request, timeout=30).read())
print(json.dumps({"type": "result", "result": reply["content"][0]["text"]}))
"""


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, claude.ClaudeDriver]:
    binary = tmp_path / "fake-claude"
    binary.write_text(f"#!{sys.executable}\n{FAKE_HARNESS}")
    binary.chmod(0o755)
    token = tmp_path / "token"
    token.write_text("sk-ant-oat01-dummy-not-real\n")
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    for key in ("FAKE_SYSTEM", "FAKE_SILENT"):
        monkeypatch.delenv(key, raising=False)
    return str(binary), claude.ClaudeDriver(token_file=token)


MARKERS = OperatorMarkers(home="/Users/operator", lines={OPERATOR_LINE: ".agents/AGENTS.md"})


def test_a_clean_prompt_is_captured_on_the_loopback_and_passes(fake_claude) -> None:
    binary, driver = fake_claude
    check = run_prompt_check(driver, binary=binary, model="m", markers=MARKERS)
    assert check["checked"] is True and check["model_requests"] == 1 and check["exit_code"] == 0
    # The real brief was sent, and nothing else was contacted.
    assert check["request_characters"] > 1000 and check["refused_hosts"] == []
    assert check["operator_content"] == [] and check["problems"] == []


def test_operator_content_in_the_prompt_is_a_problem(fake_claude, monkeypatch: pytest.MonkeyPatch) -> None:
    binary, driver = fake_claude
    monkeypatch.setenv("FAKE_SYSTEM", f"Instructions from: /Users/operator/.agents/AGENTS.md\n{OPERATOR_LINE}")
    check = run_prompt_check(driver, binary=binary, model="m", markers=MARKERS)
    assert check["problems"] == [
        "the operator's home directory /Users/operator appears 1 time(s)",
        "1 line(s) of ~/.agents/AGENTS.md",
    ]


def test_a_harness_that_sends_nothing_proves_nothing(fake_claude, monkeypatch: pytest.MonkeyPatch) -> None:
    binary, driver = fake_claude
    monkeypatch.setenv("FAKE_SILENT", "1")
    check = run_prompt_check(driver, binary=binary, model="m", markers=MARKERS)
    assert check["model_requests"] == 0
    assert check["problems"] == [
        "the harness sent no readable model request to the capture server (exit 3), so nothing shows what it would send"
    ]


def test_run_panel_refuses_a_dirty_prompt_before_anything_runs(
    fake_claude, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary, driver = fake_claude
    monkeypatch.setenv("FAKE_SYSTEM", OPERATOR_LINE)
    monkeypatch.setattr("gm_bench.agentic.prompt_check.operator_markers", lambda home=None: MARKERS)
    events: list[dict] = []
    run_dir = tmp_path / "run"
    with pytest.raises(PromptCheckError, match=r"claude prompt check: 1 line\(s\) of ~/.agents/AGENTS.md"):
        opencode.run_panel(
            [11],
            model="m",
            run_dir=run_dir,
            seasons=1,
            binary=binary,
            driver=driver,
            prompt_check=True,
            progress=events.append,
        )
    assert not run_dir.exists()
    assert events == [{"stage": "prompt_check", "checked": True, "problems": ["1 line(s) of ~/.agents/AGENTS.md"]}]


def test_a_container_run_is_recorded_as_not_checked(fake_claude, tmp_path: Path) -> None:
    binary, driver = fake_claude
    events: list[dict] = []
    # The check is decided before the image build, which fails here without Docker.
    with pytest.raises(ContainerError):
        opencode.run_panel(
            [11],
            model="m",
            run_dir=tmp_path / "run",
            seasons=1,
            binary=binary,
            driver=driver,
            isolation="container",
            docker=str(tmp_path / "no-docker"),
            prompt_check=True,
            progress=events.append,
        )
    assert events[0] == {"stage": "prompt_check", "checked": False, "problems": []}


def test_operator_markers_read_instruction_files_and_skills_but_not_bundled_ones(tmp_path: Path) -> None:
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "AGENTS.md").write_text(f"# Short title\n\n{OPERATOR_LINE}\n- short line\n")
    for root, name, description in (
        (".claude/skills/pdf", "pdf", "Read, split and merge PDF files for the operator's workflow."),
        (".codex/skills/.system/imagegen", "imagegen", "Generate images; bundled with every Codex install."),
        (".agents/skills/tiny", "tiny", "Too short."),
    ):
        (tmp_path / root).mkdir(parents=True)
        (tmp_path / root / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\nBody\n")
    markers = operator_markers(tmp_path)
    assert markers.home == str(tmp_path)
    assert markers.lines == {OPERATOR_LINE: ".agents/AGENTS.md"}
    assert markers.skills == {"Read, split and merge PDF files for the operator's workflow.": "pdf"}
    text = "Available skills: pdf - Read, split and merge PDF files for the operator's workflow."
    assert operator_content([text], markers) == ["the operator's skills pdf"]
    assert operator_content(["nothing of theirs"], markers) == []


def test_each_driver_redirects_only_its_model_endpoint() -> None:
    args = ["exec", "--json", "--model", "m", "BRIEF"]
    redirected, env = codex.CodexDriver().capture_overrides(args, model="m", base_url="http://127.0.0.1:9")
    assert env == {} and redirected[0] == "exec" and redirected[-4:] == args[1:]
    assert redirected[1:7] == [
        "-c",
        'openai_base_url="http://127.0.0.1:9/v1"',
        "-c",
        'chatgpt_base_url="http://127.0.0.1:9/backend-api/"',
        "-c",
        "features.enable_request_compression=false",
    ]
    assert claude.ClaudeDriver().capture_overrides(["-p"], model="m", base_url="u") == (
        ["-p"],
        {"ANTHROPIC_BASE_URL": "u"},
    )
    _args, env = opencode.OPENCODE_DRIVER.capture_overrides(["run"], model="opencode/free", base_url="u")
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"]) == {
        "provider": {"opencode": {"options": {"baseURL": "u/v1", "apiKey": "gm-bench-prompt-check"}}}
    }


def test_same_user_opencode_gets_a_private_home_and_no_operator_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.episode import AgenticEpisode

    monkeypatch.setenv("OPENCODE_CONFIG", str(Path.home() / ".config" / "opencode" / "opencode.json"))
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(Path.home() / ".config" / "opencode"))
    episode = AgenticEpisode(1, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    launch = opencode.HarnessLaunch(episode, binary="opencode", driver=opencode.OPENCODE_DRIVER)
    try:
        home = Path(launch.env["HOME"])
        assert home != Path.home() and not home.resolve().is_relative_to(launch.scratch.resolve())
        assert home.stat().st_mode & 0o077 == 0
        for key, name in (
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_STATE_HOME", "state"),
            ("XDG_CACHE_HOME", "cache"),
        ):
            assert launch.env[key] == str(home / name) and (home / name).is_dir()
        assert not [key for key in launch.env if key.startswith("OPENCODE_")]
        assert launch.driver.run_record(launch)["opencode_home"].startswith("private HOME")
    finally:
        launch.close()
    assert not home.exists()
    episode.close()


def test_recorded_check_problems_block_validation_and_publication_but_absence_does_not() -> None:
    assert prompt_check_problems({}) == [] and prompt_check_problems({"prompt_check": None}) == []
    assert prompt_check_problems({"prompt_check": {"checked": False, "reason": "container", "problems": []}}) == []
    dirty = {"prompt_check": {"checked": True, "problems": ["1 line(s) of ~/AGENTS.md"]}}
    assert prompt_check_problems(dirty) == ["prompt check: 1 line(s) of ~/AGENTS.md"]
    assert os.sep in MARKERS.home
