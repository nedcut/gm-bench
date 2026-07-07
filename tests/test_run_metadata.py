"""Tests for run provenance metadata and preset profile pinning."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from importlib.metadata import version

from gm_bench import __version__
from gm_bench import cli as cli_module
from gm_bench.benchmark_config import BenchmarkConfig, config_from_dict
from gm_bench.providers import build_provider_agent


def test_package_version_matches_pyproject() -> None:
    assert __version__ == version("gm-bench")


def test_provider_agent_carries_resolved_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GM_AGENT_PROFILE", raising=False)
    agent = build_provider_agent("openai", model="gpt-test")
    assert agent.metadata == {
        "provider": "openai",
        "model": "gpt-test",
        "profile": "compact",
        "agent_timeout": 120.0,
    }


def test_provider_agent_metadata_reflects_provider_default_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GM_AGENT_PROFILE", raising=False)
    agent = build_provider_agent("ollama")
    assert agent.metadata["profile"] == "tiny"


def test_explicit_profile_overrides_provider_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GM_AGENT_PROFILE", raising=False)
    agent = build_provider_agent("ollama", profile="compact")
    assert agent.metadata["profile"] == "compact"


def test_preset_pins_profile_when_unset() -> None:
    config = BenchmarkConfig()
    config.apply_preset("standard")
    assert config.profile == "compact"


def test_preset_does_not_override_explicit_profile() -> None:
    config = BenchmarkConfig(profile="tiny")
    config.apply_preset("standard")
    assert config.profile == "tiny"


def test_config_file_profile_wins_over_preset() -> None:
    config = config_from_dict({"preset": "smoke", "profile": "tiny"})
    assert config.profile == "tiny"


def test_cli_run_payload_includes_run_info() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gm_bench",
            "run",
            "--agent",
            "value",
            "--seeds",
            "1",
            "--seasons",
            "1",
            "--json",
            "--no-log",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    run_info = payload["run_info"]
    assert run_info["command"] == "run"
    assert run_info["agent"] == "value"
    assert run_info["provider"] is None
    assert "profile" not in run_info
    assert run_info["gm_bench_version"] == __version__
    assert "timestamp_utc" in run_info


def test_cli_model_run_info_records_resolved_provider_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GM_AGENT_PROFILE", raising=False)
    captured: dict[str, object] = {}

    monkeypatch.setattr(cli_module, "evaluate_against_baselines", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli_module, "_maybe_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_module, "_print_evaluation", lambda result: captured.update(result))

    cli_module.main(["model", "--provider", "openai", "--preset", "smoke", "--no-log"])

    run_info = captured["run_info"]
    assert run_info["command"] == "model"
    assert run_info["provider"] == "openai"
    assert run_info["model"] == "gpt-4.1-mini"
    # The smoke preset pins the compact profile even though a bare openai
    # default would also be compact; the point is the resolved value is stamped.
    assert run_info["profile"] == "compact"
    assert run_info["preset"] == "smoke"


def test_config_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="unknown profile"):
        config_from_dict({"provider": "ollama", "profile": "bogus", "seeds": [1]})
