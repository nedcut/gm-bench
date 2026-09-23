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
    load_lane_config,
    seed_groups,
    seed_panel_sha256,
    validate_agentic_artifact,
)
from gm_bench.publication import canonical_sha256
from gm_bench.runner import summarize_episodes

LANE_PANEL_SHA256 = json.loads(Path("config/bench_v2_lane.json").read_text())["seed_panel"]["artifact_panel_sha256"]


def _panel_row(tmp_path: Path) -> dict:
    """A panel-grade row on the lane's frozen panel, built from a one-seed run without any private seed."""
    artifact = compact_agentic_run(_write_run(tmp_path, [11]), isolation="separate-user")
    artifact["grade"] = "panel"
    artifact["panel"].update(seed_count=PANEL_MIN_SEEDS, distinct_seeds=PANEL_MIN_SEEDS, sha256=LANE_PANEL_SHA256)
    artifact["episodes"] = [dict(artifact["episodes"][0], index=i, seed_group=i) for i in range(PANEL_MIN_SEEDS)]
    return artifact


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
    panel["panel"]["sha256"] = LANE_PANEL_SHA256  # and only on the lane's frozen panel
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


def test_artifact_is_checked_against_its_raw_run_when_given(tmp_path: Path) -> None:
    """Offline checks see only the artifact; with the raw run, a forged grade or seed group cannot pass."""
    run_dir = _write_run(tmp_path, [11, 11, 12])
    artifact = compact_agentic_run(run_dir, isolation="same-user")
    assert validate_agentic_artifact(artifact, raw_run=run_dir)["ok"]
    assert validate_agentic_artifact(artifact, raw_run=run_dir / "run.json")["ok"]

    forged = json.loads(json.dumps(artifact))
    forged["episodes"][1]["seed_group"] = 2  # a copied episode claiming its own seed
    forged["panel"]["distinct_seeds"] = 3
    forged["summary"]["mean_score"] = sum(e["final_score"] for e in forged["episodes"]) / 3
    assert validate_agentic_artifact(forged)["ok"], "internally consistent, so the offline check passes"
    report = validate_agentic_artifact(forged, raw_run=run_dir)
    assert any("fresh redaction" in error and "episodes" in error and "panel" in error for error in report["errors"])

    raw = json.loads((run_dir / "run.json").read_text())
    raw["max_nudges"] = 21
    (run_dir / "run.json").write_text(json.dumps(raw, sort_keys=True))
    report = validate_agentic_artifact(artifact, raw_run=run_dir)
    assert report["errors"] == ["publication.raw_artifact_sha256 does not match the raw run.json"]


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
    main(["agentic-validate", str(out), "--raw", str(run_dir)])
    assert "OK" in capsys.readouterr().out
    main(["agentic-validate", str(run_dir)])
    assert "OK" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["agentic-validate", str(out), "--raw", str(tmp_path / "run" / "nowhere.json")])


def test_panel_row_must_carry_the_lanes_frozen_panel(tmp_path: Path) -> None:
    lane = load_lane_config()
    assert lane is not None, "the checkout's config/bench_v2_lane.json must load"
    assert lane["seed_panel"]["count"] == PANEL_MIN_SEEDS
    panel = _panel_row(tmp_path)
    assert validate_agentic_artifact(panel)["ok"], validate_agentic_artifact(panel)

    other_panel = json.loads(json.dumps(panel))
    other_panel["panel"]["sha256"] = seed_panel_sha256(list(range(1, PANEL_MIN_SEEDS + 1)))
    report = validate_agentic_artifact(other_panel)
    assert report["errors"] == [
        "panel.sha256 is not the lane's frozen private panel (config/bench_v2_lane.json seed_panel.artifact_panel_sha256)"
    ]

    # A larger panel clears the 32-seed floor but is not the lane's panel.
    wider = json.loads(json.dumps(panel))
    wider["panel"]["seed_count"] = wider["panel"]["distinct_seeds"] = PANEL_MIN_SEEDS + 1
    wider["episodes"].append(dict(wider["episodes"][0], index=PANEL_MIN_SEEDS, seed_group=PANEL_MIN_SEEDS))
    wider["summary"]["mean_score"] = wider["episodes"][0]["final_score"]
    report = validate_agentic_artifact(wider)
    assert report["errors"] == [
        f"panel grade has {PANEL_MIN_SEEDS + 1} distinct seeds; the lane's frozen private panel has {PANEL_MIN_SEEDS}"
    ]

    # An explicit lane overrides the checkout's, and a lane without the panel digest fails closed.
    moved = {"seed_panel": {"artifact_panel_sha256": "0" * 64, "count": PANEL_MIN_SEEDS}}
    assert any("not the lane's frozen" in e for e in validate_agentic_artifact(panel, lane=moved)["errors"])
    assert any("has no seed_panel" in e for e in validate_agentic_artifact(panel, lane={})["errors"])


def test_panel_row_without_a_lane_config_fails_closed(tmp_path: Path, monkeypatch) -> None:
    from gm_bench.agentic import publication

    monkeypatch.setattr(publication, "_CHECKOUT_ROOT", tmp_path / "not-a-checkout")
    assert load_lane_config() is None
    report = validate_agentic_artifact(_panel_row(tmp_path))
    assert any("bench_v2_lane.json not found" in error for error in report["errors"])


def test_smoke_rows_are_exempt_from_the_lane_panel_check(tmp_path: Path) -> None:
    artifact = compact_agentic_run(_write_run(tmp_path, [11, 12]), isolation="same-user")
    assert artifact["grade"] == "smoke"
    assert artifact["panel"]["sha256"] != LANE_PANEL_SHA256
    assert validate_agentic_artifact(artifact)["ok"]
    moved = {"seed_panel": {"artifact_panel_sha256": "0" * 64, "count": PANEL_MIN_SEEDS}}
    assert validate_agentic_artifact(artifact, lane=moved)["ok"]
    committed = Path("results/agentic/opencode-1.18.31-big-pickle-smoke-8x5.json")
    assert validate_agentic_artifact(json.loads(committed.read_text()))["ok"]


def test_cli_validate_and_redact_apply_the_lane_panel_check(tmp_path: Path, capsys) -> None:
    from gm_bench.cli import main

    good = tmp_path / "good.json"
    good.write_text(json.dumps(_panel_row(tmp_path)))
    main(["agentic-validate", str(good)])
    assert "(panel artifact), OK" in capsys.readouterr().out

    off_panel = _panel_row(tmp_path)
    off_panel["panel"]["sha256"] = "f" * 64
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(off_panel))
    with pytest.raises(SystemExit):
        main(["agentic-validate", str(bad)])
    assert "not the lane's frozen private panel" in capsys.readouterr().out
