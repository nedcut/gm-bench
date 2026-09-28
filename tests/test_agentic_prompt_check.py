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
    CONTAINER_NOT_CHECKED,
    OperatorMarkers,
    PromptCheckError,
    empty_home_environment,
    home_only_lines,
    operator_content,
    operator_markers,
    prompt_check_problems,
    run_prompt_check,
    unchecked_same_user,
)

OPERATOR_LINE = "Always sign every commit message with the operator's favourite haiku."

FAKE_HARNESS = r"""
import datetime, glob, json, os, sys, urllib.request, uuid
if sys.argv[1:] == ["--version"]:
    print("0.0.1 (Fake)")
    sys.exit(0)
if os.environ.get("FAKE_SILENT"):
    sys.exit(3)
# A runtime the harness needs from a path the operator's environment names (a version manager, say).
if os.environ.get("FAKE_RUNTIME") and not os.path.exists(os.environ["FAKE_RUNTIME"]):
    sys.exit(4)
# What changes from launch to launch and is nobody's content, as a real harness's system prompt has.
system = os.environ.get("FAKE_SYSTEM", "You are a harness.")
system += f"\nWorking directory: {os.getcwd()}\nSession: {uuid.uuid4()}\nToday is {datetime.datetime.now().isoformat()}"
# Plugins from wherever an inherited variable points: a location no marker list names.
if os.environ.get("XDG_CONFIG_HOME"):
    for skill in sorted(glob.glob(os.path.join(os.environ["XDG_CONFIG_HOME"], "fakeharness/plugins/*/SKILL.md"))):
        system += "\n" + open(skill).read()
body = {"model": "m", "stream": False, "system": system,
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
    for key in ("FAKE_SYSTEM", "FAKE_SILENT", "FAKE_RUNTIME", "XDG_CONFIG_HOME"):
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


def _operator_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home for the operator, current for the test, with a plugin skill where no marker list looks."""
    home = tmp_path / "operator-home"
    skill = home / ".config" / "fakeharness" / "plugins" / "pstack" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: poteto-mode\ndescription: The operator's own working style.\n---\n"
        "Always delegate to subagents and never ask before reversible work.\n"
    )
    monkeypatch.setenv("HOME", str(home))
    # An inherited variable pointing into the home: the Claude driver passes XDG_CONFIG_HOME through.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    return home


def test_prompt_content_only_the_operators_home_explains_is_caught_wherever_it_was_read(
    fake_claude, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary, driver = fake_claude
    home = _operator_home(tmp_path, monkeypatch)
    check = run_prompt_check(driver, binary=binary, model="m", markers=MARKERS, home=home)
    # The marker search knows nothing of this location; the empty-home run does.
    assert check["operator_content"] == []
    assert check["empty_home"]["model_requests"] == 1
    assert check["empty_home"]["lines_only_with_operator_home"] == 4
    [problem] = check["problems"]
    assert problem.startswith("4 prompt line(s) (")
    assert "appear only when the harness can see the operator's home" in problem
    assert '"Always delegate to subagents and never ask before reversi..."' in problem


def test_the_empty_home_run_hides_every_variable_that_points_into_the_home(tmp_path: Path) -> None:
    home, empty = Path("/Users/operator"), tmp_path / "empty"
    env = empty_home_environment(
        home,
        empty,
        {
            "HOME": "/Users/operator",
            "XDG_CONFIG_HOME": "/Users/operator/.config",
            "SOME_TOOL_DIRS": "/opt/x:/Users/operator/tools",
            "PATH": "/Users/operator/.local/bin:/usr/bin",
            "OTHER": "/Users/operator-2/x",
            "TOKEN": "keep",
        },
    )
    assert env == {
        "HOME": str(empty),
        "XDG_CONFIG_HOME": f"{empty}/.config",
        "SOME_TOOL_DIRS": f"/opt/x:{empty}/tools",
        "PATH": "/Users/operator/.local/bin:/usr/bin",
        "OTHER": "/Users/operator-2/x",
        "TOKEN": "keep",
    }


def test_a_harness_that_cannot_start_with_an_empty_home_fails_the_check(
    fake_claude, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary, driver = fake_claude
    home = tmp_path / "operator-home"
    (home / "runtime").mkdir(parents=True)
    monkeypatch.setenv("FAKE_RUNTIME", str(home / "runtime"))
    check = run_prompt_check(driver, binary=binary, model="m", markers=MARKERS, home=home)
    assert check["model_requests"] == 1 and check["empty_home"]["model_requests"] == 0
    assert check["problems"] == [
        "with an empty home the harness sent no readable model request (exit 4), so nothing shows which of its "
        "prompt came from the operator's home"
    ]


def test_launch_to_launch_noise_is_not_operator_content() -> None:
    real = [
        "cwd /private/var/folders/ab/T/gm-bench-agentic-x1y2/\nsession 0b7c3e2a-1d4f-4c55-9a8e-3f1b2c4d5e6f",
        "Today's date is 2026-09-28. Server http://127.0.0.1:53211/v1 at 14:02:11 id toolu_01AbCdEfGhIjKlMnOp",
    ]
    empty = [
        "cwd /tmp/gm-bench-agentic-zz99/\nsession 11111111-2222-3333-4444-555555555555",
        "Today's date is 2026-09-29. Server http://127.0.0.1:60001/v1 at 09:15:00 id toolu_01ZyXwVuTsRqPoNmLk",
    ]
    assert home_only_lines(real, empty) == []
    assert home_only_lines([*real, "Sign every commit with a haiku."], empty) == ["Sign every commit with a haiku."]


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


# A stand-in ``opencode`` with OpenCode 1.18.32's start-up for a model missing from its bundled
# catalog snapshot: it downloads the catalog from models.opencode.ai into its cache through the
# proxy, but a launch that started without a cached catalog fails at start-up (model not found,
# reported as "Unexpected server error") before any model request. A resumed launch finds the cache.
FAKE_OPENCODE = r"""
import json, os, socket, sys, urllib.parse, urllib.request
if sys.argv[1:] == ["--version"]:
    print("1.18.32")
    sys.exit(0)
proxy = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
def connect(host):
    tunnel = socket.create_connection((proxy.hostname, proxy.port), timeout=30)
    tunnel.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
    status = tunnel.recv(4096).split(b"\r\n", 1)[0]
    if b" 200 " not in status:
        return None
    tunnel.sendall(b"GET /api.json HTTP/1.1\r\n\r\n")
    data = b""
    while chunk := tunnel.recv(65536):
        data += chunk
    return data
connect("telemetry.example")
cache = os.path.join(os.environ["XDG_CACHE_HOME"], "opencode", "models.json")
cached = os.path.exists(cache)
catalog = connect("models.opencode.ai")
if catalog:
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    open(cache, "wb").write(catalog)
if not cached:
    print(json.dumps({"type": "error", "sessionID": "ses_check", "error": {"name": "UnknownError",
          "data": {"message": "Unexpected server error. Check server logs for details."}}}))
    sys.exit(1)
if sys.argv[sys.argv.index("--session") + 1] != "ses_check":
    sys.exit(5)
config = json.loads(os.environ["OPENCODE_CONFIG_CONTENT"])["provider"]["opencode"]["options"]
body = {"model": "m", "messages": [{"role": "system", "content": "You are OpenCode."},
                                   {"role": "user", "content": sys.argv[-1]}]}
request = urllib.request.Request(config["baseURL"] + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
urllib.request.urlopen(request, timeout=30).read()
print(json.dumps({"type": "text", "sessionID": "ses_check"}))
"""


def test_opencode_gets_its_model_catalog_and_is_resumed_after_a_start_up_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket
    import threading

    from gm_bench.agentic import prompt_check

    # Stands in for models.opencode.ai:443, so the tunnel is followed without the network.
    catalog, dial = socket.create_server(("127.0.0.1", 0)), socket.create_connection
    dialed: list[tuple[str, int]] = []

    def serve() -> None:
        while True:
            try:
                connection, _ = catalog.accept()
            except OSError:
                return
            with connection:
                connection.recv(4096)
                connection.sendall(b"HTTP/1.1 200 OK\r\n\r\n{}")

    threading.Thread(target=serve, daemon=True).start()

    def create_connection(address: tuple[str, int], timeout: float) -> socket.socket:
        dialed.append(address)
        return dial(catalog.getsockname(), timeout=timeout)

    monkeypatch.setattr(prompt_check.socket, "create_connection", create_connection)
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    binary = tmp_path / "fake-opencode"
    binary.write_text(f"#!{sys.executable}\n{FAKE_OPENCODE}")
    binary.chmod(0o755)
    try:
        check = run_prompt_check(
            opencode.OPENCODE_DRIVER, binary=str(binary), model="opencode/new-free", markers=MARKERS
        )
    finally:
        catalog.close()
    # The catalog host alone was passed through; everything else is still refused.
    assert dialed and set(dialed) == {("models.opencode.ai", 443)}
    assert check["forwarded_hosts"] == ["models.opencode.ai"]
    assert check["refused_hosts"] == ["telemetry.example"]
    # The first launch failed at start-up; the session it opened was resumed, as an episode's is.
    assert check["stall_retries"] == 1 and check["empty_home"]["stall_retries"] == 1
    assert check["model_requests"] == 1 and check["exit_code"] == 0 and check["problems"] == []


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
    # The image is built first (the check may run in it); without Docker nothing else runs.
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
    assert events == []
    # Given the image, a harness whose prompt is built from its home records the run as not checked.
    image = {"image": "gm-bench-agentic-claude:test", "image_id": "sha256:" + "d" * 64}
    check = driver.check_prompt(binary=binary, model="m", variant=None, image=image)
    assert check == {"checked": False, "reason": CONTAINER_NOT_CHECKED, "problems": []}


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


def test_operator_markers_also_read_plugins_rules_memories_imports_and_opencode_instructions(tmp_path: Path) -> None:
    lines = {
        ".claude/rules/style.md": "Rules: prefer the smallest correct change to any file.",
        ".claude/projects/-work/memory/MEMORY.md": "Memory: the operator's benchmark runs must stay serial.",
        "notes/imported.md": "Imported: a line CLAUDE.md pulls in from outside ~/.claude.",
        ".config/opencode/extra.md": "OpenCode instructions: a file named by opencode.json.",
    }
    for relative, line in lines.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(line + "\n")
    (tmp_path / ".claude" / "CLAUDE.md").write_text("# Mine\n@~/notes/imported.md\n")
    (tmp_path / ".config" / "opencode" / "opencode.json").write_text(json.dumps({"instructions": ["extra.md"]}))
    plugin = tmp_path / ".claude" / "plugins" / "cache" / "market" / "pstack" / "abc123" / "skills" / "poteto"
    plugin.mkdir(parents=True)
    (plugin / "SKILL.md").write_text(
        "---\nname: poteto-mode\ndescription: The operator's own agent working style.\n---\n"
    )
    catalogue = tmp_path / ".claude" / "plugins" / "marketplaces" / "market" / "skills" / "other"
    catalogue.mkdir(parents=True)
    (catalogue / "SKILL.md").write_text(
        "---\nname: other\ndescription: A catalogued plugin nobody installed here.\n---\n"
    )
    markers = operator_markers(tmp_path)
    assert markers.lines == {line: relative for relative, line in lines.items()}
    assert markers.skills == {"The operator's own agent working style.": "poteto-mode"}


def test_a_same_user_row_whose_check_was_skipped_cannot_be_published() -> None:
    new_driver = {"driver_files": ["gm_bench/agentic/opencode.py", "gm_bench/agentic/prompt_check.py"]}
    skipped = {"isolation": "same-user", "driver": new_driver, "prompt_check": None}
    assert unchecked_same_user(skipped) == (
        "prompt check was skipped (--skip-prompt-check): a same-user row must show what its harness would send the model"
    )
    assert unchecked_same_user({"isolation": "same-user", "prompt_check": None})
    assert unchecked_same_user({**skipped, "prompt_check": {"checked": False, "reason": "no capture override"}})
    assert unchecked_same_user({**skipped, "prompt_check": {"checked": True, "problems": []}}) is None
    # A container run (or one understated as same-user, which still records why it was not checked).
    assert unchecked_same_user({**skipped, "isolation": "container"}) is None
    assert unchecked_same_user({**skipped, "prompt_check": {"checked": False, "reason": CONTAINER_NOT_CHECKED}}) is None
    # Recorded before the check existed: no key, and a driver without the module.
    assert (
        unchecked_same_user({"isolation": "same-user", "driver": {"driver_files": ["gm_bench/agentic/opencode.py"]}})
        is None
    )


def test_committed_rows_still_validate() -> None:
    from gm_bench.agentic.publication import validate_agentic_artifact

    rows = sorted((Path(__file__).resolve().parents[1] / "results" / "agentic").glob("*.json"))
    assert rows
    for row in rows:
        artifact = json.loads(row.read_text())
        assert unchecked_same_user(artifact) is None, row.name
        assert validate_agentic_artifact(artifact)["ok"], row.name
