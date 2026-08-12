from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from gm_bench.environment import load_environment_files
from gm_bench.providers import PROVIDERS


@pytest.fixture
def enable_env_file_loading(monkeypatch) -> None:
    """Opt back in to real env-file loading for the loader's own tests.

    The autouse ``block_real_provider_credentials`` fixture disables the
    loader suite-wide; the tests in this module exist to exercise it.
    """
    monkeypatch.delenv("GM_BENCH_DISABLE_ENV_FILES", raising=False)


def test_local_env_loads_before_shared_env_without_overriding_process(
    tmp_path, monkeypatch, enable_env_file_loading
) -> None:
    (tmp_path / ".env").write_text("SHARED=shared\nLOCAL_WINS=shared\nPROCESS_WINS=shared\n")
    (tmp_path / ".env.local").write_text(
        "# local secrets\nexport LOCAL_WINS=local\nQUOTED='secret value'\nPROCESS_WINS=local\n"
    )
    monkeypatch.delenv("SHARED", raising=False)
    monkeypatch.delenv("LOCAL_WINS", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.setenv("PROCESS_WINS", "process")

    loaded = load_environment_files(tmp_path)

    assert loaded == [tmp_path / ".env.local", tmp_path / ".env"]
    assert os.environ["SHARED"] == "shared"
    assert os.environ["LOCAL_WINS"] == "local"
    assert os.environ["QUOTED"] == "secret value"
    assert os.environ["PROCESS_WINS"] == "process"


def test_env_loader_ignores_comments_invalid_names_and_missing_files(
    tmp_path, monkeypatch, enable_env_file_loading
) -> None:
    (tmp_path / ".env.local").write_text("# comment\nnot an assignment\nBAD-NAME=x\nVALID=ok\n")
    monkeypatch.delenv("VALID", raising=False)

    loaded = load_environment_files(tmp_path)

    assert loaded == [tmp_path / ".env.local"]
    assert os.environ["VALID"] == "ok"
    assert "BAD-NAME" not in os.environ


def test_cli_provider_readiness_uses_local_env_file(tmp_path, monkeypatch, capsys, enable_env_file_loading) -> None:
    from gm_bench import cli

    (tmp_path / ".env.local").write_text("OPENROUTER_API_KEY=test-secret\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cli.main(["providers", "--json"])

    output = capsys.readouterr().out
    assert '"provider": "openrouter"' in output
    assert '"credential_present": true' in output
    assert "test-secret" not in output


def test_disable_switch_makes_the_loader_a_no_op(tmp_path, monkeypatch) -> None:
    """The suite-wide credential guard must hold at the loader's source.

    Patching one importer's reference (the pre-2026-08-05 guard) left every
    other ``from gm_bench.environment import load_environment_files`` call
    site live -- including the route-evidence collector and any subprocess.
    """
    (tmp_path / ".env.local").write_text("OPENROUTER_API_KEY=sk-live-should-never-load\n")
    monkeypatch.setenv("GM_BENCH_DISABLE_ENV_FILES", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert load_environment_files(tmp_path) == []
    assert "OPENROUTER_API_KEY" not in os.environ


def test_disable_switch_is_inherited_by_subprocess_entry_points(tmp_path) -> None:
    """A child process re-imports everything, so in-process patches vanish.

    Only something carried in the environment survives the fork; this pins
    that the guard actually crosses the process boundary.
    """
    (tmp_path / ".env.local").write_text("OPENROUTER_API_KEY=sk-live-should-never-load\n")
    env = {key: value for key, value in os.environ.items() if key != "OPENROUTER_API_KEY"}
    env["GM_BENCH_DISABLE_ENV_FILES"] = "1"
    repo_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (repo_root, env.get("PYTHONPATH"))))

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os\n"
            "from gm_bench.environment import load_environment_files\n"
            "loaded = load_environment_files(os.getcwd())\n"
            "print(len(loaded), 'OPENROUTER_API_KEY' in os.environ)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.split() == ["0", "False"]


def test_suite_guard_scrubs_all_registered_and_alias_credentials() -> None:
    credential_names = {
        "LLM_API_KEY",
        *(name for spec in PROVIDERS.values() for name in spec.credential_env),
    }
    assert {
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    } <= credential_names
    assert all(name not in os.environ for name in credential_names)
