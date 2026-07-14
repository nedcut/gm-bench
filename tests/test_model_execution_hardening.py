from __future__ import annotations

import json
from pathlib import Path

import pytest

from gm_bench import cli


class _DummyAgent:
    name = "openai:cli-model"
    metadata = {
        "provider": "openai",
        "model": "cli-model",
        "profile": "compact",
        "transport": "direct-api",
    }


class _FailingAgent(_DummyAgent):
    def act_with_usage(self, observation: dict[str, object]) -> tuple[list[dict[str, str]], None]:
        return [{"type": "noop", "model_error": "quota exhausted"}], None


def _evaluation(*, failed: int = 0, illegal: int = 0, penalty: float = 0.0) -> dict[str, object]:
    decisions = 4
    return {
        "candidate": {
            "summary": {
                "decisions": decisions,
                "failed_decisions": failed,
                "illegal_actions": illegal,
                "total_protocol_penalty": penalty,
                "usage": {
                    "decisions_with_usage": decisions,
                    "cost_decisions": decisions,
                    "cost_usd": 0.01,
                    "model": "cli-model",
                    "provider": "openai",
                    "upstream_providers": [],
                },
            }
        }
    }


def test_cli_overrides_config_and_honors_config_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "nested" / "result.json"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "provider": "openai",
                "model": "config-model",
                "preset": "standard",
                "no_log": True,
                "output": str(output),
            }
        )
    )
    built: dict[str, object] = {}

    def fake_build(provider: str, **kwargs: object) -> _DummyAgent:
        built.update(provider=provider, **kwargs)
        return _DummyAgent()

    monkeypatch.setattr(cli, "preflight_provider", lambda provider: None)
    monkeypatch.setattr(cli, "build_provider_agent", fake_build)
    monkeypatch.setattr(cli, "run_resumable_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli, "evaluate_resumable_candidate", lambda *args, **kwargs: _evaluation())
    monkeypatch.setattr(cli, "log_payload", lambda *args, **kwargs: pytest.fail("config no_log was ignored"))
    monkeypatch.setattr(cli, "_print_evaluation", lambda result: None)

    cli.main(["model", "--config", str(config), "--model", "cli-model"])

    assert built["model"] == "cli-model"
    assert json.loads(output.read_text())["candidate"]["summary"]["failed_decisions"] == 0


def test_failed_smoke_exits_nonzero_after_atomic_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "failed.json"
    monkeypatch.setattr(cli, "preflight_provider", lambda provider: None)
    monkeypatch.setattr(cli, "build_provider_agent", lambda *args, **kwargs: _DummyAgent())
    monkeypatch.setattr(cli, "run_resumable_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli, "evaluate_resumable_candidate", lambda *args, **kwargs: _evaluation(failed=1))
    monkeypatch.setattr(cli, "_print_evaluation", lambda result: None)

    with pytest.raises(SystemExit, match="failed_decisions=1"):
        cli.main(
            [
                "model",
                "--provider",
                "openai",
                "--preset",
                "smoke",
                "--no-log",
                "--output",
                str(output),
            ]
        )

    assert json.loads(output.read_text())["candidate"]["summary"]["failed_decisions"] == 1


def test_clean_gate_keeps_illegal_actions_as_scored_model_outcomes() -> None:
    result = _evaluation(illegal=2, penalty=5.0)
    result["run_info"] = {"provider": "openai"}

    assert cli._model_clean_errors(result) == []


def test_leaderboard_openrouter_requires_canonical_pin() -> None:
    class Agent:
        metadata = {
            "provider": "openrouter",
            "provider_options": {"OPENROUTER_ALLOW_FALLBACKS": "false"},
        }

    assert cli._openrouter_route_config_errors(Agent(), "leaderboard") == [
        "OPENROUTER_PROVIDER_ONLY must name exactly one upstream provider",
        "OPENROUTER_EXPECTED_ENDPOINT_NAME must pin an exact endpoint",
    ]


def test_atomic_output_replaces_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text("stale")
    cli._write_json_atomic(path, {"ok": True})
    assert json.loads(path.read_text()) == {"ok": True}


@pytest.mark.parametrize("provider", ["claude", "codex", "cursor", "opencode"])
def test_subscription_cli_providers_reject_parallel_workers(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "preflight_provider", lambda selected: None)
    monkeypatch.setattr(cli, "build_provider_agent", lambda *args, **kwargs: _DummyAgent())

    with pytest.raises(SystemExit, match="must run serially"):
        cli.main(["model", "--provider", provider, "--workers", "2", "--no-log"])


def test_session_lane_honors_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "preflight_provider", lambda selected: None)
    monkeypatch.setattr(cli, "build_provider_agent", lambda *args, **kwargs: _FailingAgent())

    def exercise(agent: object, *args: object, **kwargs: object) -> None:
        agent.act_with_usage({})
        agent.act_with_usage({})

    monkeypatch.setattr(cli, "evaluate_against_baselines", exercise)

    with pytest.raises(SystemExit, match="2 consecutive model failures"):
        cli.main(["model", "--provider", "openai", "--session", "--no-log"])


def test_fail_fast_below_one_is_rejected_at_the_cli(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["model", "--provider", "openai", "--fail-fast", "0", "--no-log"])
    assert excinfo.value.code == 2
    assert "fail-fast threshold must be >= 1" in capsys.readouterr().err
