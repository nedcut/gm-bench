"""Tests for run provenance metadata and preset profile pinning."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.metadata import version

import pytest

from gm_bench import __version__
from gm_bench import cli as cli_module
from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, BenchmarkConfig, config_from_dict, seed_panel_hash
from gm_bench.contract import benchmark_contract
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
        "session": False,
        "transport": "direct-api",
        "protocol_repair_attempts": 1,
        "provider_options": {"GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1"},
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
    assert run_info["benchmark_contract"] == benchmark_contract()
    assert run_info["seed_panel"]["name"] == "custom"
    assert run_info["seed_panel"]["count"] == 1
    assert "timestamp_utc" in run_info


def test_cli_model_run_info_records_resolved_provider_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GM_AGENT_PROFILE", raising=False)
    captured: dict[str, object] = {}

    monkeypatch.setattr(cli_module, "run_resumable_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli_module, "evaluate_resumable_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli_module, "_maybe_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_module, "_print_evaluation", lambda result: captured.update(result))

    cli_module.main(["model", "--provider", "openai", "--preset", "smoke", "--no-log"])

    run_info = captured["run_info"]
    assert run_info["command"] == "model"
    assert run_info["provider"] == "openai"
    assert run_info["model"] == "gpt-5.4-mini"
    # The smoke preset pins the compact profile even though a bare openai
    # default would also be compact; the point is the resolved value is stamped.
    assert run_info["profile"] == "compact"
    assert run_info["preset"] == "smoke"
    assert run_info["transport"] == "direct-api"
    assert run_info["benchmark_contract"] == benchmark_contract()
    assert run_info["seed_panel"]["name"] == "custom"


def test_cli_model_run_info_records_private_seed_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-111")
    captured: dict[str, object] = {}

    monkeypatch.setattr(cli_module, "run_resumable_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli_module, "evaluate_resumable_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli_module, "_maybe_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_module, "_print_evaluation", lambda result: captured.update(result))

    cli_module.main(["model", "--provider", "openai", "--preset", "leaderboard", "--no-log"])

    seed_panel = captured["run_info"]["seed_panel"]
    assert seed_panel["name"] == "private-env"
    assert seed_panel["count"] == 4
    assert seed_panel["sha256"] == seed_panel_hash([101, 102, 110, 111])


def test_config_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="unknown profile"):
        config_from_dict({"provider": "ollama", "profile": "bogus", "seeds": [1]})
