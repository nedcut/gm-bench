from __future__ import annotations

import os

from gm_bench.environment import load_environment_files


def test_local_env_loads_before_shared_env_without_overriding_process(tmp_path, monkeypatch) -> None:
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


def test_env_loader_ignores_comments_invalid_names_and_missing_files(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env.local").write_text("# comment\nnot an assignment\nBAD-NAME=x\nVALID=ok\n")
    monkeypatch.delenv("VALID", raising=False)

    loaded = load_environment_files(tmp_path)

    assert loaded == [tmp_path / ".env.local"]
    assert os.environ["VALID"] == "ok"
    assert "BAD-NAME" not in os.environ


def test_cli_provider_readiness_uses_local_env_file(tmp_path, monkeypatch, capsys) -> None:
    from gm_bench import cli

    (tmp_path / ".env.local").write_text("OPENROUTER_API_KEY=test-secret\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cli.main(["providers", "--json"])

    output = capsys.readouterr().out
    assert '"provider": "openrouter"' in output
    assert '"credential_present": true' in output
    assert "test-secret" not in output
