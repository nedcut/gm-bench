from __future__ import annotations

import json
import multiprocessing
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from gm_bench import baseline_cache as baseline_cache_module
from gm_bench import cli as cli_module
from gm_bench.agents import AGENTS, ValueAgent
from gm_bench.baseline_cache import cache_key, get_cached_episode, load_cache, save_cache
from gm_bench.benchmark_config import BenchmarkConfig, config_from_dict, load_config
from gm_bench.contract import contract_fingerprint
from gm_bench.providers import build_provider_agent, resolve_provider
from gm_bench.runner import evaluate_against_baselines, run_many, run_many_cached_baselines, summarize_episodes


def _save_cache_after_barrier(cache: dict[str, dict[str, Any]], cache_path: str, barrier: Any) -> None:
    barrier.wait()
    save_cache(cache, cache_path)


def test_baseline_cache_tracks_the_score_affecting_contract() -> None:
    assert baseline_cache_module.simulation_fingerprint() == contract_fingerprint()[:12]


def test_provider_registry_resolves_openai() -> None:
    spec = resolve_provider("openai")
    assert spec.model_env == "OPENAI_MODEL"
    agent = build_provider_agent("openai", model="gpt-test")
    assert agent.name == "openai:gpt-test"


def test_provider_registry_resolves_gemini() -> None:
    spec = resolve_provider("gemini")
    assert spec.model_env == "GEMINI_MODEL"
    assert spec.default_model == "gemini-3.5-flash"
    agent = build_provider_agent("gemini")
    assert agent.name == "gemini:gemini-3.5-flash"
    assert agent.metadata["profile"] == "compact"


def test_provider_registry_resolves_direct_and_gateway_apis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GM_AGENT_STRICT", raising=False)
    anthropic = build_provider_agent("anthropic")
    assert anthropic.name == "anthropic:claude-sonnet-4-6"
    assert anthropic.metadata["transport"] == "direct-api"

    openrouter = build_provider_agent("openrouter", model="meta-llama/example")
    assert openrouter.name == "openrouter:meta-llama/example"
    assert openrouter.metadata["transport"] == "gateway-api"
    assert openrouter.metadata["provider_options"] == {
        "OPENROUTER_PROVIDER_SORT": "price",
        "OPENROUTER_ALLOW_FALLBACKS": "false",
        "OPENROUTER_REQUIRE_PARAMETERS": "false",
        "OPENROUTER_DATA_COLLECTION": "deny",
        "OPENROUTER_JSON_MODE": "false",
        # v6 execution rules: 4,096-token output ceiling, reasoning off where
        # the route allows it, and no paid retry.
        "OPENROUTER_MAX_TOKENS": "4096",
        "OPENROUTER_REASONING_ENABLED": "false",
        "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "0",
        "GM_AGENT_STRICT": "0",
    }


def test_protocol_repair_ignores_generic_no_usable_actions_fallback() -> None:
    from gm_bench.providers import _model_format_failed

    assert _model_format_failed([{"type": "noop", "model_error": "invalid JSON"}])
    assert _model_format_failed([{"type": "noop", "error": "external agent returned invalid JSON"}])
    assert not _model_format_failed([{"type": "noop", "model_error": "model produced no usable actions"}])


def test_build_provider_agent_defaults_to_no_paid_retry_and_clamps_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v6 buys one call per phase; an operator may replay the old lane, not exceed it."""
    monkeypatch.setenv("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS", "9")
    default_agent = build_provider_agent("openai", model="gpt-test")
    assert default_agent.metadata["protocol_repair_attempts"] == 0
    assert default_agent.metadata["provider_options"]["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] == "0"

    clamped = build_provider_agent("openai", model="gpt-test", extra_env={"GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "9"})
    assert clamped.metadata["protocol_repair_attempts"] == 1
    assert clamped.metadata["provider_options"]["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] == "1"


def test_external_agent_bounded_protocol_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    from gm_bench.agents import ExternalProcessAgent
    from gm_bench.providers import ProtocolRepairAgent

    calls: list[dict] = []

    def fake_run(*args, **kwargs):
        observation = json.loads(kwargs["input"])
        calls.append(observation)
        actions = [{"type": "noop", "model_error": "invalid JSON"}] if len(calls) == 1 else [{"type": "noop"}]
        return subprocess.CompletedProcess(
            args[0], 0, json.dumps({"actions": actions, "usage": {"api_calls": 1, "output_tokens": 10}}), ""
        )

    monkeypatch.setattr("gm_bench.agents.subprocess.run", fake_run)
    agent = ProtocolRepairAgent(ExternalProcessAgent("fake"), attempts=1)
    actions, usage = agent.act_with_usage({"phase": "draft"})

    assert actions == [{"type": "noop"}]
    assert calls[1]["protocol_repair"]["attempt"] == 1
    assert usage["api_calls"] == 2
    assert usage["output_tokens"] == 20
    assert usage["protocol_repair_attempts"] == 1
    assert usage["protocol_repairs_succeeded"] == 1


def test_protocol_repair_preserves_route_changes_and_does_not_publish_partial_cost() -> None:
    from gm_bench.providers import _merge_usage

    merged = _merge_usage(
        {
            "api_calls": 1,
            "input_tokens": 100,
            "output_tokens": 10,
            "cost_usd": 0.1,
            "upstream_provider": "provider-a",
        },
        {
            "api_calls": 1,
            "input_tokens": 120,
            "output_tokens": 12,
            "upstream_provider": "provider-b",
        },
    )

    assert merged["api_calls"] == 2
    assert merged["input_tokens"] == 220
    assert merged["output_tokens"] == 22
    assert "cost_usd" not in merged
    assert "upstream_provider" not in merged
    assert merged["upstream_providers"] == ["provider-a", "provider-b"]


def test_provider_environment_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_JSON_MODE", "true")
    monkeypatch.setenv("GM_BENCH_OUTPUT_BUDGET_CELL", "uncapped")
    inherited = build_provider_agent("openrouter", model="test")
    assert inherited.env["OPENROUTER_JSON_MODE"] == "true"
    assert inherited.metadata["provider_options"]["OPENROUTER_JSON_MODE"] == "true"
    assert inherited.metadata["provider_options"]["GM_BENCH_OUTPUT_BUDGET_CELL"] == "uncapped"

    configured = build_provider_agent("openrouter", model="test", extra_env={"OPENROUTER_JSON_MODE": "false"})
    assert configured.env["OPENROUTER_JSON_MODE"] == "false"
    assert configured.metadata["provider_options"]["OPENROUTER_JSON_MODE"] == "false"


def test_luna_configs_pin_reproducible_execution() -> None:
    for name, preset in (
        ("openrouter.luna.smoke.json", "smoke"),
        ("openrouter.luna.leaderboard.json", "leaderboard"),
    ):
        config = load_config(Path("examples") / name)
        payload = json.loads((Path("examples") / name).read_text())
        assert config.model == "openai/gpt-5.6-luna-20260709"
        assert config.preset == preset
        assert payload["workers"] == 1
        assert payload["require_clean"] is True
        assert config.extra_env["OPENROUTER_PROVIDER_ONLY"] == "OpenAI"
        assert config.extra_env["OPENROUTER_JSON_MODE"] == "true"
        assert config.extra_env["OPENROUTER_MAX_TOKENS"] == "2048"


def test_benchmark_config_applies_preset() -> None:
    config = BenchmarkConfig()
    config.apply_preset("smoke")
    assert config.seeds == [1]
    assert config.seasons == 1


def test_benchmark_config_parses_seed_ranges() -> None:
    config = config_from_dict({"seeds": "1-3,5"})
    assert config.seeds == [1, 2, 3, 5]


@pytest.mark.parametrize(
    ("baselines", "message"),
    [
        ("value", "must be a list"),
        (["value", 1], "only strings"),
        (["not-registered"], "unknown baseline"),
        (["value", "value"], "duplicate baselines"),
        ([], "must not be empty"),
    ],
)
def test_benchmark_config_rejects_invalid_baseline_panels_before_execution(baselines, message) -> None:
    with pytest.raises(ValueError, match=message):
        config_from_dict({"baselines": baselines})


def test_evaluate_rejects_invalid_baseline_before_candidate_execution() -> None:
    class CountingAgent(ValueAgent):
        def __init__(self) -> None:
            self.calls = 0

        def act(self, observation):
            self.calls += 1
            return super().act(observation)

    candidate = CountingAgent()
    with pytest.raises(ValueError, match="unknown baseline"):
        evaluate_against_baselines(candidate, [1], seasons=1, baseline_names=["typo"])
    assert candidate.calls == 0


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


def test_baseline_cache_merges_stale_writer_snapshots(tmp_path: Path) -> None:
    """A later process must not erase entries committed after its initial read."""
    cache_path = tmp_path / "cache.json"
    first_key = cache_key("value", 1, 2)
    second_key = cache_key("value", 2, 2)
    stale_first = {first_key: {"seed": 1, "final_score": 1.0}}
    stale_second = {second_key: {"seed": 2, "final_score": 2.0}}

    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    processes = [
        context.Process(target=_save_cache_after_barrier, args=(cache, str(cache_path), barrier))
        for cache in (stale_first, stale_second)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert set(load_cache(cache_path)) == {first_key, second_key}


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


def test_cli_providers_lists_api_providers() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "gm_bench", "providers"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "openai" in completed.stdout
    assert "gemini" in completed.stdout
    assert "anthropic" in completed.stdout
    assert "openrouter" in completed.stdout


def test_provider_help_reports_credential_names_without_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "do-not-print")
    completed = subprocess.run(
        [sys.executable, "-m", "gm_bench", "providers", "--json"],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    openrouter = next(row for row in payload if row["provider"] == "openrouter")
    assert openrouter["credential_env"] == ["OPENROUTER_API_KEY"]
    assert openrouter["credential_present"] is True
    assert "do-not-print" not in completed.stdout


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

    def fake_run(agent, seeds, seasons, repeats, **kwargs):
        del agent, repeats, kwargs
        captured["seeds"] = seeds
        captured["seasons"] = seasons
        return {"seeds": seeds, "seasons": seasons}

    def fake_evaluate(candidate, baselines, **kwargs):
        del candidate, kwargs
        captured["baselines"] = baselines
        return {}

    monkeypatch.setattr(cli_module, "build_provider_agent", lambda *args, **kwargs: DummyAgent())
    monkeypatch.setattr(cli_module, "run_resumable_candidate", fake_run)
    monkeypatch.setattr(cli_module, "evaluate_resumable_candidate", fake_evaluate)
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
    monkeypatch.setattr(
        cli_module,
        "run_resumable_candidate",
        lambda _agent, seeds, seasons, _repeats, **_kwargs: {"seeds": seeds, "seasons": seasons},
    )
    monkeypatch.setattr(cli_module, "evaluate_resumable_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli_module, "_maybe_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_module, "_print_evaluation", lambda result: None)

    cli_module.main(["model", "--config", str(config_path), "--no-log"])

    assert built["provider"] == "openai"


def test_cli_model_without_any_provider_exits_with_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_module.main(["model", "--preset", "smoke", "--no-log"])
    assert "no provider specified" in str(excinfo.value)


def test_baselines_from_cache_requires_full_seed_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Partial cache hits must not be treated as complete baseline rows."""
    import web.scripts.build_leaderboard as bl

    cache_path = tmp_path / "cache.json"
    seasons = 5
    # Only seed 11 is present — LEADERBOARD seeds are 11..18.
    save_cache(
        {cache_key("value", 11, seasons): {"seed": 11, "final_score": 10.0}},
        cache_path,
    )
    monkeypatch.setattr(bl, "load_cache", lambda: load_cache(cache_path))
    assert bl.baselines_from_cache() == []

    # Full coverage for one agent should produce a row.
    full = {
        cache_key("value", seed, seasons): {"seed": seed, "final_score": float(seed)}
        for seed in bl.LEADERBOARD["seeds"]
    }
    save_cache(full, cache_path)
    rows = bl.baselines_from_cache()
    assert len(rows) == 1
    assert rows[0]["agent"] == "value"
    assert rows[0]["mean_score"] == pytest.approx(sum(bl.LEADERBOARD["seeds"]) / len(bl.LEADERBOARD["seeds"]))


def test_baselines_from_sota_v2_artifacts_require_agreement() -> None:
    from gm_bench.contract import SOTA_V2_CONTRACT
    from web.scripts.build_leaderboard import baselines_from_sota_v2_artifacts

    def panel(scores: dict[str, tuple[float, float]]) -> dict:
        return {
            "run_info": {"benchmark_contract": dict(SOTA_V2_CONTRACT)},
            "baselines": [
                {"agent": agent, "summary": {"mean_score": mean, "score_stddev": std}}
                for agent, (mean, std) in scores.items()
            ],
        }

    agents = {
        "random": (96.715, 18.063),
        "conservative": (139.03, 18.297),
        "win-now": (275.834, 45.055),
        "rebuild": (138.745, 15.887),
        "value": (354.619, 31.492),
        "shrewd": (371.769, 47.86),
        "strategic": (402.025, 49.4),
        "pick-trader": (411.619, 50.64),
    }
    rows = baselines_from_sota_v2_artifacts([panel(agents), panel(agents)])
    assert rows[0]["agent"] == "pick-trader"
    assert rows[0]["mean_score"] == 411.619
    assert {row["agent"] for row in rows} == set(agents)

    disagree = dict(agents)
    disagree["pick-trader"] = (999.0, 1.0)
    with pytest.raises(SystemExit, match="disagree"):
        baselines_from_sota_v2_artifacts([panel(agents), panel(disagree)])

    with pytest.raises(SystemExit, match="complete baseline panel"):
        baselines_from_sota_v2_artifacts(
            [{"run_info": {"benchmark_contract": {"contract_fingerprint": "other"}}, "baselines": []}]
        )


def test_leaderboard_selects_official_then_newest_diagnostic() -> None:
    from web.scripts.build_leaderboard import select_model_payloads

    old = {"agent": "claude:sonnet", "run_info": {"timestamp_utc": "2026-07-11T00:00:00+00:00"}}
    new = {"agent": "claude:sonnet", "run_info": {"timestamp_utc": "2026-07-12T00:00:00+00:00"}}
    other = {"agent": "cursor:composer", "run_info": {"timestamp_utc": "2026-07-10T00:00:00+00:00"}}

    selected = select_model_payloads([(old, False, "old.json"), (new, False, "new.json"), (other, False, "other.json")])
    assert selected == [new, other]

    selected = select_model_payloads([(new, False, "new.json"), (old, True, "official.json")])
    assert selected == [old]

    current = {**new, "run_info": {"benchmark_contract": {"benchmark_version": "sota-v2"}}}
    historical = {**old, "run_info": {"benchmark_contract": {"benchmark_version": "sota-v1"}}}
    selected = select_model_payloads([(current, 2, "current.json"), (historical, 1, "archive.json")])
    assert selected == [current, historical]
