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
    seed_groups,
    seed_panel_sha256,
    validate_agentic_artifact,
)
from gm_bench.publication import canonical_sha256
from gm_bench.runner import summarize_episodes


def _write_run(tmp_path: Path, seeds: list[int], *, telemetry: bool = True) -> Path:
    """A run directory with real ledgers and event streams, as run_panel would write it, without a harness.

    A repeated seed gets its own attempt directory (``seed-11-r2``) and plays
    differently, so per-seed and per-episode means diverge.
    """
    run_dir = tmp_path / "run"
    episodes = []
    attempts: dict[int, int] = {}
    for seed in seeds:
        attempts[seed] = attempts.get(seed, 0) + 1
        name = f"seed-{seed}" if attempts[seed] == 1 else f"seed-{seed}-r{attempts[seed]}"
        ledger = run_dir / name / "ledger.jsonl"
        episode = AgenticEpisode(seed, seasons=1, ledger_path=ledger)
        if attempts[seed] == 1:
            roster = episode.call_tool("get_team", {})["data"]["roster"]
            episode.call_tool("set_lineup", {"player_ids": [p["id"] for p in roster][:18]})
        while not episode.done:
            episode.call_tool("end_phase", {})
        result = episode.result("opencode:fake/model")
        episode.close()
        calls = result["agentic"]["tool_calls"]
        events = ledger.with_name("opencode-events.jsonl")
        lines = [json.dumps({"type": "step_start", "sessionID": "ses_x", "part": {}})]
        for tool, count in result["agentic"]["tool_calls_by_tool"].items():
            part = {"type": "tool", "tool": f"gm-bench_{tool}"}
            lines.extend(json.dumps({"type": "tool", "sessionID": "ses_x", "part": part}) for _ in range(count))
        if telemetry:
            finish = {"type": "step-finish", "tokens": {"input": 1000, "output": 50}, "cost": 0.0}
            lines.append(json.dumps({"type": "step_finish", "sessionID": "ses_x", "part": finish}))
        events.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result["harness_run"] = {
            "harness": "opencode",
            "ledger_path": f"{name}/ledger.jsonl",
            "events_path": f"{name}/opencode-events.jsonl",
            "command": ["opencode", "run", "--dir", "/var/folders/xx/scratch", "<task brief>"],
            "tool_call_agreement": {"ledger": calls, "harness": calls, "agree": True},
            "exit_code": 0,
            "timed_out": False,
            "wall_seconds": 12.5,
            "nudges_used": 1,
            "nudges_without_progress": 0,
            "guard_kills": 0,
            "nudges": [{"number": 1, "season": 1, "phase": "draft", "new_tool_calls": 2, "phases_closed": 1}],
            "proxy_connections": 2,
        }
        result["usage"]["harness"] = {"telemetry_reported": telemetry, "compactions": 0, "session_id": "ses_x"}
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
        "summary": summarize_episodes(episodes),
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
    assert artifact["panel"] == {
        "seed_count": 2,
        "distinct_seeds": 2,
        "seeds": REDACTED_SEEDS,
        "sha256": seed_panel_sha256([12, 11]),
    }
    assert all("seed" not in episode for episode in artifact["episodes"])
    assert [episode["seed_group"] for episode in artifact["episodes"]] == [0, 1]
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


def test_redacted_artifact_never_carries_a_seed_in_its_validation_report(tmp_path: Path) -> None:
    """Ordinary warnings (here: no telemetry) used to be copied with a `seed N:` prefix."""
    seed = 8675309
    run_dir = _write_run(tmp_path, [seed], telemetry=False)
    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["validation"]["ok"]
    assert artifact["validation"]["warnings"] == ["episode 0: harness reported no token telemetry; usage is unmeasured"]
    assert str(seed) not in json.dumps(artifact)
    assert validate_agentic_artifact(artifact)["ok"]


def test_panel_grade_needs_distinct_seeds_isolation_and_redaction(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, [11])
    with pytest.raises(ValueError):
        compact_agentic_run(run_dir, isolation="laptop")
    artifact = compact_agentic_run(run_dir, isolation="container")
    assert artifact["grade"] == "smoke"  # one seed is never a panel

    artifact["grade"] = "panel"
    report = validate_agentic_artifact(artifact)
    assert not report["ok"]
    assert any(f"at least {PANEL_MIN_SEEDS} distinct seeds" in error for error in report["errors"])

    # Thirty-two copies of one seed are still one seed.
    repeated = json.loads(json.dumps(artifact))
    repeated["panel"]["seed_count"] = PANEL_MIN_SEEDS
    repeated["panel"]["distinct_seeds"] = 1
    repeated["episodes"] = [dict(repeated["episodes"][0], index=i) for i in range(PANEL_MIN_SEEDS)]
    report = validate_agentic_artifact(repeated)
    assert any(f"at least {PANEL_MIN_SEEDS} distinct seeds, has 1" in error for error in report["errors"])
    repeated["panel"]["distinct_seeds"] = PANEL_MIN_SEEDS  # claiming otherwise is caught by the groups
    report = validate_agentic_artifact(repeated)
    assert any("form 1 seed groups" in error for error in report["errors"])

    # A genuine 32-distinct-seed panel passes only with isolation and redaction.
    panel = json.loads(json.dumps(artifact))
    panel["panel"]["seed_count"] = panel["panel"]["distinct_seeds"] = PANEL_MIN_SEEDS
    panel["episodes"] = [dict(panel["episodes"][0], index=i, seed_group=i) for i in range(PANEL_MIN_SEEDS)]
    panel["isolation"] = "same-user"
    report = validate_agentic_artifact(panel)
    assert any("isolated from the driver" in error for error in report["errors"])
    panel["isolation"] = "container"
    panel["panel"]["seeds"] = list(range(PANEL_MIN_SEEDS))
    report = validate_agentic_artifact(panel)
    assert any("redacted seeds" in error for error in report["errors"])
    panel["panel"]["seeds"] = REDACTED_SEEDS
    assert validate_agentic_artifact(panel)["ok"], validate_agentic_artifact(panel)


def test_repeated_seed_run_is_checked_against_the_per_seed_mean(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, [11, 11, 12])
    raw = json.loads((run_dir / "run.json").read_text())
    scores = [episode["final_score"] for episode in raw["episodes"]]
    assert scores[0] != scores[1], "the repeat must play differently for the check to mean anything"
    per_seed = ((scores[0] + scores[1]) / 2 + scores[2]) / 2
    assert abs(raw["summary"]["mean_score"] - per_seed) < 1e-3
    assert abs(raw["summary"]["mean_score"] - sum(scores) / 3) > 1e-3

    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert artifact["panel"]["seed_count"] == 3 and artifact["panel"]["distinct_seeds"] == 2
    assert [episode["seed_group"] for episode in artifact["episodes"]] == seed_groups([11, 11, 12]) == [0, 0, 1]
    assert validate_agentic_artifact(artifact)["ok"], validate_agentic_artifact(artifact)
    assert any("repeated seeds" in warning for warning in artifact["validation"]["warnings"])


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

    scoreless = json.loads(json.dumps(artifact))
    del scoreless["episodes"][0]["final_score"]
    assert any("finite final_score" in e for e in validate_agentic_artifact(scoreless)["errors"])

    meanless = json.loads(json.dumps(artifact))
    del meanless["summary"]["mean_score"]
    assert any("mean_score must be a finite number" in e for e in validate_agentic_artifact(meanless)["errors"])
    meanless["summary"]["mean_score"] = float("nan")
    assert any("mean_score must be a finite number" in e for e in validate_agentic_artifact(meanless)["errors"])

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
