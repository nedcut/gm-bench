"""OpenCode API keys (``--opencode-auth-file``) for paid Go and Zen models, and a spent Go window."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from gm_bench.agentic import opencode
from gm_bench.agentic.opencode import OpenCodeDriver
from tests.test_agentic_codex import _calls
from tests.test_agentic_codex import _fake_docker as _fake_docker_with_stdin
from tests.test_agentic_mcp import _FREE_USAGE_LIMIT_ERROR, _RATE_LIMIT_ERROR, _scripted_harness

DUMMY_KEY = "sk-opencode-dummy-not-a-real-key-0000"


def _key_file(tmp_path: Path) -> Path:
    path = tmp_path / "opencode-go-key"
    path.write_text(DUMMY_KEY + "\n")
    path.chmod(0o600)
    return path


def test_the_key_file_is_checked_without_echoing_it_and_go_models_need_one(tmp_path: Path) -> None:
    key = _key_file(tmp_path)
    OpenCodeDriver(auth_file=key).preflight("container")
    OpenCodeDriver(auth_file=key).check_model("opencode-go/kimi-k3")
    OpenCodeDriver(auth_file=key).check_model("opencode/some-paid-zen-model")
    # Free Zen models keep working with no key at all.
    OpenCodeDriver().preflight("container")
    OpenCodeDriver().check_model("opencode/space-bunny-free")
    with pytest.raises(ValueError, match="needs an OpenCode API key: pass --opencode-auth-file"):
        OpenCodeDriver().check_model("opencode-go/grok-4.7")
    # The key serves only OpenCode's own gateways.
    with pytest.raises(ValueError, match="not anthropic/claude-x"):
        OpenCodeDriver(auth_file=key).check_model("anthropic/claude-x")
    bad = tmp_path / "bad"
    bad.write_text(f"{DUMMY_KEY} second-token\n")
    with pytest.raises(ValueError, match="exactly one OpenCode API key") as excinfo:
        OpenCodeDriver(auth_file=bad).preflight("same-user")
    assert DUMMY_KEY not in str(excinfo.value)
    with pytest.raises(ValueError, match="is not a file"):
        OpenCodeDriver(auth_file=tmp_path / "missing").preflight("same-user")


def test_cli_refuses_a_go_model_without_a_key_and_hands_the_driver_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench import cli

    seen: dict = {}

    def fake_run_panel(seeds, **kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(opencode, "run_panel", fake_run_panel)
    base = ["agentic", "--seeds", "11", "--output", str(tmp_path / "run")]
    with pytest.raises(SystemExit, match="needs an OpenCode API key"):
        cli.main([*base, "--model", "opencode-go/glm-5.3"])
    assert seen == {}
    key = _key_file(tmp_path)
    with pytest.raises(SystemExit):
        cli.main([*base, "--model", "opencode-go/glm-5.3", "--opencode-auth-file", str(key)])
    assert seen["driver"].auth_file == key and seen["binary"] == "opencode"
    with pytest.raises(SystemExit, match="only for --harness opencode"):
        cli.main([*base, "--model", "gpt-x", "--harness", "codex", "--opencode-auth-file", str(key)])


def test_same_user_key_is_opencodes_auth_json_in_the_private_data_dir_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.episode import AgenticEpisode

    monkeypatch.setenv("OPENCODE_API_KEY", "sk-operator-env-key-must-not-pass")
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    episode = AgenticEpisode(1, seasons=1, ledger_path=tmp_path / "ledger.jsonl")
    driver = OpenCodeDriver(auth_file=_key_file(tmp_path))
    launch = opencode.HarnessLaunch(episode, binary="opencode", driver=driver)
    try:
        launch.prepare()
        auth = Path(launch.env["XDG_DATA_HOME"]) / "opencode" / "auth.json"
        assert json.loads(auth.read_text()) == {
            "opencode": {"type": "api", "key": DUMMY_KEY},
            "opencode-go": {"type": "api", "key": DUMMY_KEY},
        }
        assert auth.stat().st_mode & 0o777 == 0o600 and auth.parent.stat().st_mode & 0o077 == 0
        # Not in the scratch, not in the harness environment (which the agent's shell inherits).
        assert sorted(p.name for p in launch.scratch.iterdir()) == ["gm_bench_proxy.py", "opencode.json"]
        assert not any(DUMMY_KEY in value for value in launch.env.values())
        assert not [key for key in launch.env if key.startswith("OPENCODE_")]
        record = driver.run_record(launch)
        assert record["auth"] == "auth-file" and record["auth_providers"] == ["opencode", "opencode-go"]
        assert DUMMY_KEY not in json.dumps(record)
        home = Path(launch.env["HOME"])
    finally:
        launch.close()
    assert not home.exists()
    episode.close()
    # Without a file nothing is staged, and the record says so.
    without = opencode.OPENCODE_DRIVER.run_record(launch)
    assert (without["auth"], without["auth_providers"]) == ("none", [])


def test_container_key_reaches_only_the_home_volume(tmp_path: Path) -> None:
    from gm_bench.agentic import _proxy
    from gm_bench.agentic.episode import AgenticEpisode

    docker, log, stdin_dir = _fake_docker_with_stdin(tmp_path)
    image = {"image": "gm-bench-agentic-opencode:test", "image_id": "sha256:" + "a" * 64}
    episode = AgenticEpisode(8675309, seasons=1, ledger_path=tmp_path / "run" / "ledger.jsonl")
    key = _key_file(tmp_path)
    driver = OpenCodeDriver(auth_file=key)
    launch = opencode.HarnessLaunch(episode, isolation="container", image=image, docker=str(docker), driver=driver)
    try:
        launch.prepare()
        assert sorted(p.name for p in launch.scratch.iterdir()) == sorted(
            ["opencode.json", "gm_bench_proxy.py", _proxy.SECRET_FILENAME]
        )
        calls = _calls(log)
        [seed_index] = [i for i, call in enumerate(calls) if "-i" in call]
        seeding = calls[seed_index]
        assert seeding[seeding.index("--network") + 1] == "none" and "-e" not in seeding
        with tarfile.open(fileobj=io.BytesIO((stdin_dir / f"{seed_index}.bin").read_bytes())) as tar:
            members = {member.name: member for member in tar.getmembers()}
            assert sorted(members) == [".local/share/opencode", ".local/share/opencode/auth.json"]
            assert members[".local/share/opencode/auth.json"].mode == 0o600
            assert json.loads(tar.extractfile(".local/share/opencode/auth.json").read())["opencode-go"] == {
                "type": "api",
                "key": DUMMY_KEY,
            }
        argv, _on_kill = launch.command(
            driver.run_args(
                model="opencode-go/kimi-k3", variant=None, workdir=launch.workdir, brief="B", isolation="container"
            )
        )
        assert not any(DUMMY_KEY in arg for arg in argv)
        record = driver.run_record(launch)
        assert record["auth"] == "auth-file" and "opencode_home" not in record
    finally:
        launch.close()
    # Neither the key nor the file's path is on any docker command line.
    assert not any(DUMMY_KEY in arg or str(key) in arg for call in _calls(log) for arg in call)
    episode.close()


def test_a_key_the_agent_prints_is_redacted_from_the_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gm_bench.agentic.validate import validate_run

    calls: list[list[str]] = []
    scripted = _scripted_harness([{"phases": 4}], calls)

    def cat_auth(command, *, env, events_path, stderr_path, **kwargs):
        # The agent reads its harness's credential and prints it, to both streams.
        text = (Path(env["XDG_DATA_HOME"]) / "opencode" / "auth.json").read_text()
        with events_path.open("a") as events:
            part = {"type": "tool", "tool": "bash", "state": {"output": text}}
            events.write(json.dumps({"type": "tool_use", "sessionID": "ses_fake", "part": part}) + "\n")
        stderr_path.write_text(text)
        return scripted(command, env=env, events_path=events_path, stderr_path=stderr_path, **kwargs)

    monkeypatch.setattr(opencode, "_run_harness", cat_auth)
    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    run_dir = tmp_path / "run"
    payload = opencode.run_panel(
        [11],
        model="opencode-go/kimi-k3",
        run_dir=run_dir,
        seasons=1,
        binary="none",
        driver=OpenCodeDriver(auth_file=_key_file(tmp_path)),
    )
    assert "[REDACTED]" in (run_dir / "seed-11" / "opencode-events.jsonl").read_text()
    assert "[REDACTED]" in (run_dir / "seed-11" / "opencode-stderr.log").read_text()
    leaked = [path for path in run_dir.rglob("*") if path.is_file() and DUMMY_KEY in path.read_text()]
    assert leaked == []
    assert payload["episodes"][0]["harness_run"]["auth"] == "auth-file"
    assert payload["episodes"][0]["harness_run"]["tool_call_agreement"]["agree"] is True
    assert validate_run(run_dir)["ok"]


def test_a_go_model_without_a_key_is_refused_before_anything_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(opencode, "_run_harness", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="needs an OpenCode API key"):
        opencode.run_panel([11], model="opencode-go/kimi-k3", run_dir=tmp_path / "run", seasons=1, binary="none")
    assert not (tmp_path / "run").exists()


# The body shape OpenCode 1.18.32 reads for a spent Go window (``SessionRetry.retryable``:
# ``GoUsageLimitError`` in the body, ``metadata.limitName`` and ``metadata.workspace``,
# the reset in ``retry-after`` seconds). The exact message text is a stand-in.
_GO_USAGE_LIMIT_ERROR = json.loads(json.dumps(_FREE_USAGE_LIMIT_ERROR))
_GO_USAGE_LIMIT_ERROR["error"]["data"]["responseBody"] = json.dumps(
    {
        "type": "error",
        "error": {"type": "GoUsageLimitError", "message": "Usage limit reached."},
        "metadata": {"workspace": "wrk_fake", "limitName": "5-hour"},
    }
)
_GO_USAGE_LIMIT_ERROR["error"]["data"]["responseHeaders"]["retry-after"] = "7200"
_GO_USAGE_LIMIT_ERROR["error"]["data"]["metadata"]["url"] = "https://opencode.ai/zen/go/v1/chat/completions"


def test_a_spent_go_window_is_quota_exhaustion_with_its_reset_and_never_a_stall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = json.dumps(_GO_USAGE_LIMIT_ERROR)
    assert opencode.quota_exhaustion(["{}", line], now=1_790_000_000.0) == {
        "message_class": "go_usage_limit",
        "reset_at_utc": "2026-09-21T16:13:20+00:00",
    }
    assert not opencode.ended_in_provider_stall([line])
    # A plain 429 on the Go endpoint is still a transient stall.
    assert opencode.ended_in_provider_stall([json.dumps(_RATE_LIMIT_ERROR)])

    monkeypatch.setattr(opencode, "sandbox_problems", lambda scratch, env: [])
    driver = OpenCodeDriver(auth_file=_key_file(tmp_path))
    # A reset within the wait budget: paused until it plus a minute, resumed, finished.
    calls: list[list[str]] = []
    sleeps: list[float] = []
    script = [{"phases": 1, "error": _GO_USAGE_LIMIT_ERROR, "exit": 1}, {"phases": 3}]
    monkeypatch.setattr(opencode, "_run_harness", _scripted_harness(script, calls))
    result = opencode.run_episode(
        11,
        model="opencode-go/kimi-k3",
        run_dir=tmp_path / "paused",
        seasons=1,
        sleep=sleeps.append,
        clock=lambda: 1_790_000_000.0,
        driver=driver,
    )
    assert sleeps == [7260.0] and len(calls) == 2
    run = result["harness_run"]
    assert run["quota_pauses"][0]["message_class"] == "go_usage_limit"
    assert run["provider_stalls"] == 0 and run["nudges_used"] == 0 and run["ended_by_quota"] is None

    # A reset past the budget (a weekly or monthly window): the episode and the panel stop at once.
    calls.clear()
    sleeps.clear()
    monthly = json.loads(json.dumps(_GO_USAGE_LIMIT_ERROR))
    monthly["error"]["data"]["responseHeaders"]["retry-after"] = str(20 * 86400)
    monkeypatch.setattr(
        opencode, "_run_harness", _scripted_harness([{"phases": 1, "error": monthly, "exit": 1}], calls)
    )
    panel = opencode.run_panel(
        [11, 12],
        model="opencode-go/kimi-k3",
        run_dir=tmp_path / "stopped",
        seasons=1,
        binary="none",
        sleep=sleeps.append,
        driver=driver,
    )
    assert len(calls) == 1 and sleeps == []
    assert panel["episodes"][0]["harness_run"]["ended_by_quota"]["message_class"] == "go_usage_limit"
    assert panel["stopped_for_quota"]["episodes_not_run"] == 1
