from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gm_bench import baseline_cache as baseline_cache_module
from gm_bench import cli as cli_module
from gm_bench.agents import AGENTS, ValueAgent
from gm_bench.baseline_cache import cache_key, get_cached_episode, load_cache, save_cache
from gm_bench.benchmark_config import BenchmarkConfig, config_from_dict, load_config
from gm_bench.contract import contract_fingerprint
from gm_bench.providers import build_provider_agent, resolve_provider
from gm_bench.runner import evaluate_against_baselines, run_many, run_many_cached_baselines, summarize_episodes


def test_baseline_cache_tracks_the_score_affecting_contract() -> None:
    assert baseline_cache_module.simulation_fingerprint() == contract_fingerprint()[:12]


def test_provider_registry_resolves_openai() -> None:
    spec = resolve_provider("openai")
    assert spec.model_env == "LLM_MODEL"
    agent = build_provider_agent("openai", model="gpt-test")
    assert agent.name == "openai:gpt-test"


def test_benchmark_config_applies_preset() -> None:
    config = BenchmarkConfig()
    config.apply_preset("smoke")
    assert config.seeds == [1]
    assert config.seasons == 1


def test_benchmark_config_parses_seed_ranges() -> None:
    config = config_from_dict({"seeds": "1-3,5"})
    assert config.seeds == [1, 2, 3, 5]


def test_benchmark_config_file_loads(tmp_path: Path) -> None:
    path = tmp_path / "bench.json"
    path.write_text(
        json.dumps(
            {
                "preset": "smoke",
                "provider": "openai",
                "model": "gpt-4.1-mini",
            }
        )
    )
    config = load_config(path)
    assert config.seeds == [1]
    assert config.provider == "openai"


def test_cache_invalidates_when_simulation_fingerprint_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "cache.json"
    episode = {"seed": 1, "final_score": 12.3, "strategy_score": 12.3, "protocol_penalty": 0.0}
    cache = {cache_key("value", 1, 2): episode}
    save_cache(cache, cache_path)

    monkeypatch.setattr(baseline_cache_module, "simulation_fingerprint", lambda: "deadbeefcafe")
    assert get_cached_episode("value", 1, 2, cache=load_cache(cache_path)) is None


def test_save_cache_prunes_entries_from_older_fingerprints(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    episode = {"seed": 1, "final_score": 1.0}
    stale = {"v1:000000000000:value:1:2": episode, cache_key("value", 1, 2): episode}
    save_cache(stale, cache_path)
    assert list(load_cache(cache_path)) == [cache_key("value", 1, 2)]


def test_cached_baseline_summary_matches_run_many_shape(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    live = run_many(AGENTS["value"](), seeds=[1], seasons=1)
    cached, _ = run_many_cached_baselines("value", [1], seasons=1, cache_path=cache_path)
    assert set(cached["summary"]) == set(live["summary"])
    assert cached["summary"] == summarize_episodes(cached["episodes"])


def test_baseline_cache_round_trip(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    episode = {"seed": 1, "final_score": 12.3, "strategy_score": 12.3, "protocol_penalty": 0.0}
    cache = {cache_key("value", 1, 2): episode}
    save_cache(cache, cache_path)
    loaded = load_cache(cache_path)
    assert get_cached_episode("value", 1, 2, cache=loaded) == episode


def test_run_many_cached_baselines_is_deterministic(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    first, _ = run_many_cached_baselines("value", [1, 2], seasons=2, cache_path=cache_path)
    second, hits = run_many_cached_baselines("value", [1, 2], seasons=2, cache_path=cache_path)
    assert first["summary"] == second["summary"]
    assert hits == 2


def test_evaluate_uses_baseline_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "cache.json"
    for name in ["random", "conservative"]:
        run_many_cached_baselines(name, [1], seasons=1, cache_path=cache_path)

    calls = {"count": 0}
    original = run_many_cached_baselines

    def counting_cached(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr("gm_bench.runner.run_many_cached_baselines", counting_cached)
    result = evaluate_against_baselines(
        ValueAgent(),
        seeds=[1],
        seasons=1,
        baseline_names=["random", "conservative"],
        use_baseline_cache=True,
        baseline_cache_path=cache_path,
    )
    assert calls["count"] == 2
    assert result["baseline_cache"]["hits"] == 2


def test_cli_model_help_lists_provider_command() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "gm_bench", "model", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--provider" in completed.stdout
    assert "--preset" in completed.stdout


def test_cli_providers_lists_openai() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "gm_bench", "providers"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "openai" in completed.stdout


def test_cli_cache_baselines_json(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gm_bench",
            "cache-baselines",
            "--baselines",
            "value",
            "--seeds",
            "1",
            "--seasons",
            "1",
            "--cache-path",
            str(cache_path),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["summary"]["value"] > 0
    assert cache_path.exists()


def test_cli_cache_baselines_accepts_preset(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gm_bench",
            "cache-baselines",
            "--preset",
            "smoke",
            "--cache-path",
            str(cache_path),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["seeds"] == [1]
    assert payload["seasons"] == 1
    assert payload["baselines"] == ["random", "conservative", "win-now", "rebuild"]


def test_cli_model_config_preserves_config_baselines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "bench.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai",
                "model": "gpt-test",
                "baselines": ["value"],
                "seeds": [1],
                "seasons": 1,
                "no_log": True,
            }
        )
    )
    captured: dict[str, object] = {}

    class DummyAgent:
        name = "openai:gpt-test"

    def fake_evaluate(agent, seeds, seasons, baselines, **kwargs):
        del agent, kwargs
        captured["seeds"] = seeds
        captured["seasons"] = seasons
        captured["baselines"] = baselines
        return {}

    monkeypatch.setattr(cli_module, "build_provider_agent", lambda *args, **kwargs: DummyAgent())
    monkeypatch.setattr(cli_module, "evaluate_against_baselines", fake_evaluate)
    monkeypatch.setattr(cli_module, "_maybe_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_module, "_print_evaluation", lambda result: None)

    cli_module.main(["model", "--provider", "openai", "--config", str(config_path), "--no-log"])

    assert captured == {"seeds": [1], "seasons": 1, "baselines": ["value"]}


def test_cli_model_config_supplies_provider_without_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "bench.json"
    config_path.write_text(json.dumps({"provider": "openai", "seeds": [1], "seasons": 1}))
    built: dict[str, object] = {}

    class DummyAgent:
        name = "openai:gpt-test"

    def fake_build(provider, **kwargs):
        built["provider"] = provider
        return DummyAgent()

    monkeypatch.setattr(cli_module, "build_provider_agent", fake_build)
    monkeypatch.setattr(cli_module, "evaluate_against_baselines", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli_module, "_maybe_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_module, "_print_evaluation", lambda result: None)

    cli_module.main(["model", "--config", str(config_path), "--no-log"])

    assert built["provider"] == "openai"


def test_cli_model_without_any_provider_exits_with_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_module.main(["model", "--preset", "smoke", "--no-log"])
    assert "no provider specified" in str(excinfo.value)
