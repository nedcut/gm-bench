from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gm_bench.agents import ValueAgent
from gm_bench.baseline_cache import cache_key, get_cached_episode, load_cache, save_cache
from gm_bench.benchmark_config import BenchmarkConfig, config_from_dict, load_config
from gm_bench.providers import build_provider_agent, resolve_provider
from gm_bench.runner import evaluate_against_baselines, run_many_cached_baselines


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
