"""The committed 2.0 artifact: bound to its raw run, redacted, graded by the spec's rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gm_bench.agentic.contract import agentic_contract
from gm_bench.agentic.episode import AgenticEpisode
from gm_bench.agentic.publication import (
    PANEL_MIN_SEEDS,
    REDACTED_SEEDS,
    compact_agentic_run,
    is_agentic_artifact,
    seed_panel_sha256,
    validate_agentic_artifact,
)
from gm_bench.publication import canonical_sha256


def _write_run(tmp_path: Path, seeds: list[int]) -> Path:
    """A run directory with real ledgers, as run_panel would write it, without a harness."""
    run_dir = tmp_path / "run"
    episodes = []
    for seed in seeds:
        ledger = run_dir / f"seed-{seed}" / "ledger.jsonl"
        episode = AgenticEpisode(seed, seasons=1, ledger_path=ledger)
        roster = episode.call_tool("get_team", {})["data"]["roster"]
        episode.call_tool("set_lineup", {"player_ids": [p["id"] for p in roster][:18]})
        while not episode.done:
            episode.call_tool("end_phase", {})
        result = episode.result("opencode:fake/model")
        episode.close()
        calls = result["agentic"]["tool_calls"]
        result["harness_run"] = {
            "ledger_path": str(ledger),
            "events_path": str(ledger.with_name("opencode-events.jsonl")),
            "command": ["opencode", "run", "--dir", "/var/folders/xx/scratch", "<task brief>"],
            "tool_call_agreement": {"ledger": calls, "harness": calls, "agree": True},
            "exit_code": 0,
            "timed_out": False,
            "wall_seconds": 12.5,
            "nudges_used": 1,
            "nudges_without_progress": 0,
            "nudges": [{"number": 1, "season": 1, "phase": "draft", "new_tool_calls": 2, "phases_closed": 1}],
            "proxy_connections": 2,
        }
        result["usage"]["harness"] = {"telemetry_reported": True, "compactions": 0, "session_id": "ses_x"}
        episodes.append(result)
    run = {
        "agent": "opencode:fake/model",
        "lane": "agentic",
        "harness": {"name": "opencode", "version": "1.18.30", "model": "fake/model", "variant": None},
        "contract": agentic_contract(),
        "seeds": seeds,
        "seasons": 1,
        "phase_guard_seconds": 1200.0,
        "max_nudges": 20,
        "episodes": episodes,
        "summary": {"mean_score": sum(e["final_score"] for e in episodes) / len(episodes)},
        "agentic_summary": {"nudges_used": len(episodes)},
    }
    (run_dir / "run.json").write_text(json.dumps(run, sort_keys=True), encoding="utf-8")
    return run_dir


def test_compact_artifact_is_bound_redacted_and_validates(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, [11, 12])
    raw = json.loads((run_dir / "run.json").read_text())
    artifact = compact_agentic_run(run_dir, isolation="same-user")

    assert is_agentic_artifact(artifact)
    assert artifact["publication"]["raw_artifact_sha256"] == canonical_sha256(raw)
    assert artifact["grade"] == "smoke"
    assert artifact["panel"] == {"seed_count": 2, "seeds": REDACTED_SEEDS, "sha256": seed_panel_sha256([12, 11])}
    assert all("seed" not in episode for episode in artifact["episodes"])
    assert artifact["episodes"][0]["harness_run"]["nudges"][0]["phase"] == "draft"
    assert "session_id" not in artifact["episodes"][0]["usage"]["harness"]
    text = json.dumps(artifact)
    assert "ledger_path" not in text and "/var/folders" not in text and str(tmp_path) not in text
    report = validate_agentic_artifact(artifact)
    assert report["ok"], report

    public = compact_agentic_run(run_dir, isolation="same-user", public_seeds=True)
    assert public["panel"]["seeds"] == [11, 12]
    assert [episode["seed"] for episode in public["episodes"]] == [11, 12]
    assert validate_agentic_artifact(public)["ok"]


def test_panel_grade_needs_isolation_size_and_redaction(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, [11])
    with pytest.raises(ValueError):
        compact_agentic_run(run_dir, isolation="laptop")
    artifact = compact_agentic_run(run_dir, isolation="container")
    assert artifact["grade"] == "smoke"  # one seed is never a panel

    artifact["grade"] = "panel"
    report = validate_agentic_artifact(artifact)
    assert not report["ok"]
    assert any(f"at least {PANEL_MIN_SEEDS} seeds" in error for error in report["errors"])

    artifact["panel"]["seed_count"] = PANEL_MIN_SEEDS
    artifact["episodes"] = artifact["episodes"] * PANEL_MIN_SEEDS
    artifact["isolation"] = "same-user"
    report = validate_agentic_artifact(artifact)
    assert any("isolated from the driver" in error for error in report["errors"])
    artifact["isolation"] = "container"
    artifact["panel"]["seeds"] = [11] * PANEL_MIN_SEEDS
    report = validate_agentic_artifact(artifact)
    assert any("redacted seeds" in error for error in report["errors"])
    artifact["panel"]["seeds"] = REDACTED_SEEDS
    assert validate_agentic_artifact(artifact)["ok"]


def test_validation_catches_contract_drift_paths_and_tampering(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, [11])
    artifact = compact_agentic_run(run_dir, isolation="same-user")

    drifted = json.loads(json.dumps(artifact))
    drifted["contract"]["agentic_fingerprint"] = "0" * 16
    assert any("contract.agentic_fingerprint" in e for e in validate_agentic_artifact(drifted)["errors"])

    leaky = json.loads(json.dumps(artifact))
    leaky["note"] = "raw at /Users/someone/runs/x.json"
    assert any("local filesystem path" in e for e in validate_agentic_artifact(leaky)["errors"])

    tampered = json.loads(json.dumps(artifact))
    tampered["episodes"][0]["final_score"] += 5
    assert any("mean_score" in e for e in validate_agentic_artifact(tampered)["errors"])

    disagreeing = json.loads(json.dumps(artifact))
    disagreeing["episodes"][0]["harness_run"]["tool_call_agreement"]["agree"] = False
    assert any("disagree" in e for e in validate_agentic_artifact(disagreeing)["errors"])

    unvalidated = json.loads(json.dumps(artifact))
    unvalidated["validation"]["ok"] = False
    assert any("validation.ok" in e for e in validate_agentic_artifact(unvalidated)["errors"])


def test_cli_redact_then_validate_round_trip(tmp_path: Path, capsys) -> None:
    from gm_bench.cli import main

    run_dir = _write_run(tmp_path, [11])
    out = tmp_path / "results" / "agentic" / "row.json"
    main(["agentic-redact", str(run_dir), "--output", str(out), "--isolation", "same-user"])
    assert "smoke grade, 1 seeds" in capsys.readouterr().out
    main(["agentic-validate", str(out)])
    assert "OK" in capsys.readouterr().out
    main(["agentic-validate", str(run_dir)])
    assert "OK" in capsys.readouterr().out
