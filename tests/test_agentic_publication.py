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
    REFERENCE_AGENT,
    REFERENCE_FLOOR_AGENT,
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
    artifact = compact_agentic_run(_write_run(tmp_path, [11], isolation="container"), isolation="container")
    artifact["grade"] = "panel"
    artifact["panel"].update(seed_count=PANEL_MIN_SEEDS, distinct_seeds=PANEL_MIN_SEEDS, sha256=LANE_PANEL_SHA256)
    artifact["episodes"] = [dict(artifact["episodes"][0], index=i, seed_group=i) for i in range(PANEL_MIN_SEEDS)]
    artifact["reference"] = fixture_reference(artifact)
    return artifact


def fixture_reference(artifact: dict, *, reference_mean: float = 249.18) -> dict:
    """A reference block coherent with a hand-built panel row; real ones come from a raw run."""
    by_group: dict[int, list[float]] = {}
    for episode in artifact["episodes"]:
        by_group.setdefault(episode["seed_group"], []).append(episode["final_score"])
    row_mean = sum(sum(v) / len(v) for v in by_group.values()) / len(by_group)
    lift = round(row_mean - reference_mean, 3)
    return {
        "agent": REFERENCE_AGENT,
        "mean_score": reference_mean,
        "floor": {"agent": REFERENCE_FLOOR_AGENT, "mean_score": 90.367},
        "seasons": artifact["seasons"],
        "num_seeds": len(by_group),
        "paired_lift_mean": lift,
        "paired_lift_stddev": 20.0,
        "paired_lift_ci95": [round(lift - 7.0, 3), round(lift + 7.0, 3)],
        "sign_flip_p_value": 0.5,
        "significant_at_95": lift - 7.0 > 0.0 or lift + 7.0 < 0.0,
        "candidate_seed_win_rate": 0.25,
        "per_seed": [],
    }


def _write_run(
    tmp_path: Path, seeds: list[int], *, telemetry: bool = True, idle: bool = False, isolation: str | None = None
) -> Path:
    """A run directory with real ledgers and event streams, as run_panel would write it, without a harness.

    A repeated seed gets its own attempt directory (``seed-11-r2``) and plays
    differently, so per-seed and per-episode means diverge. With ``idle``
    every episode only ends phases, which a 1.0 agent returning no actions
    reproduces exactly.
    """
    run_dir = tmp_path / "run"
    episodes = []
    attempts: dict[int, int] = {}
    for seed in seeds:
        attempts[seed] = attempts.get(seed, 0) + 1
        name = f"seed-{seed}" if attempts[seed] == 1 else f"seed-{seed}-r{attempts[seed]}"
        ledger = run_dir / name / "ledger.jsonl"
        episode = AgenticEpisode(seed, seasons=1, ledger_path=ledger)
        if attempts[seed] == 1 and not idle:
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
        if isolation is not None:
            result["harness_run"]["isolation"] = isolation
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
    if isolation is not None:
        run["isolation"] = isolation
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
    run_dir = _write_run(tmp_path, [11], isolation="container")
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
    report = validate_agentic_artifact(panel)
    assert report["errors"] == [
        "panel grade needs the reference block: the predeclared pick-trader contrast on the same seeds"
    ]
    panel["reference"] = fixture_reference(panel)  # and with the reference contrast
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
    wider["reference"] = fixture_reference(wider)
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


# The reference contrast. Panel grade is reached on public seeds 1 to 3 by
# lowering the seed floor and pointing the lane at those seeds' digest, so no
# private seed is ever needed; the scripted baselines are free and offline.
PUBLIC_SEEDS = [1, 2, 3]
PUBLIC_LANE = {
    "panel_design": {"reference_agent": REFERENCE_AGENT},
    "seed_panel": {"artifact_panel_sha256": seed_panel_sha256(PUBLIC_SEEDS), "count": len(PUBLIC_SEEDS)},
}


@pytest.fixture
def public_panel(monkeypatch) -> dict:
    """Make a 3-public-seed run panel grade and the lane's panel, for the length of one test."""
    from gm_bench.agentic import publication

    monkeypatch.setattr(publication, "PANEL_MIN_SEEDS", len(PUBLIC_SEEDS))
    monkeypatch.setattr(publication, "load_lane_config", lambda path=None: PUBLIC_LANE)
    return PUBLIC_LANE


def test_panel_redaction_embeds_the_pick_trader_contrast_without_seeds_or_paths(
    tmp_path: Path, public_panel: dict
) -> None:
    run_dir = _write_run(tmp_path, PUBLIC_SEEDS, isolation="container")
    artifact = compact_agentic_run(run_dir, isolation="container")
    assert artifact["grade"] == "panel"
    reference = artifact["reference"]
    assert list(reference) == [
        "agent",
        "mean_score",
        "floor",
        "seasons",
        "num_seeds",
        "paired_lift_mean",
        "paired_lift_stddev",
        "paired_lift_ci95",
        "sign_flip_p_value",
        "significant_at_95",
        "candidate_seed_win_rate",
        "per_seed",
    ]
    assert reference["agent"] == "pick-trader" and reference["floor"]["agent"] == "random"
    assert reference["num_seeds"] == artifact["panel"]["distinct_seeds"] == 3
    assert reference["seasons"] == artifact["seasons"] == 1
    assert reference["per_seed"] == []
    text = json.dumps(reference)
    assert '"seed"' not in text and '"seeds"' not in text and "cache" not in text
    assert str(tmp_path) not in json.dumps(artifact) and "/Users/" not in json.dumps(artifact)
    report = validate_agentic_artifact(artifact)
    assert report["ok"], report
    assert validate_agentic_artifact(artifact, raw_run=run_dir)["ok"]


def test_smoke_redaction_never_computes_a_reference(tmp_path: Path, public_panel: dict, monkeypatch) -> None:
    from gm_bench.agentic import publication

    def refuse(*args, **kwargs):
        raise AssertionError("a smoke redaction must not run the reference baselines")

    monkeypatch.setattr(publication, "run_many_cached_baselines", refuse)
    run_dir = _write_run(tmp_path, PUBLIC_SEEDS, isolation="container")
    for kwargs in ({"isolation": "same-user"}, {"isolation": "container", "public_seeds": True}):
        artifact = compact_agentic_run(run_dir, **kwargs)
        assert artifact["grade"] == "smoke"
        assert "reference" not in artifact
        assert validate_agentic_artifact(artifact, raw_run=run_dir)["ok"]


def test_reference_matches_1_0_on_the_same_public_seeds(tmp_path: Path, public_panel: dict) -> None:
    """pick-trader through the 1.0 evaluate path and through the 2.0 redaction give the same numbers.

    The 2.0 episodes here only end phases; a 1.0 agent that returns no
    actions plays the identical episode (same league, same score), so 1.0's
    own paired block against pick-trader must equal the 2.0 reference field
    for field. The 1.0 side runs uncached; the 2.0 side runs through the
    baseline cache.
    """
    from gm_bench.agents import Agent
    from gm_bench.runner import evaluate_against_baselines

    class Idle(Agent):
        name = "idle"

        def act(self, observation):
            return []

    run_dir = _write_run(tmp_path, PUBLIC_SEEDS, idle=True, isolation="container")
    raw = json.loads((run_dir / "run.json").read_text())
    reference = compact_agentic_run(run_dir, isolation="container")["reference"]

    v1 = evaluate_against_baselines(Idle(), PUBLIC_SEEDS, 1, ["pick-trader"], use_baseline_cache=False)
    v1_scores = {episode["seed"]: episode["final_score"] for episode in v1["candidate"]["episodes"]}
    assert v1_scores == {episode["seed"]: episode["final_score"] for episode in raw["episodes"]}
    paired = v1["paired"]
    assert (
        reference["mean_score"] == paired["best_baseline"]["mean_score"] == v1["baselines"][0]["summary"]["mean_score"]
    )
    for key in (
        "num_seeds",
        "paired_lift_mean",
        "paired_lift_stddev",
        "paired_lift_ci95",
        "sign_flip_p_value",
        "significant_at_95",
        "candidate_seed_win_rate",
    ):
        assert reference[key] == paired[key], key
    assert paired["best_baseline"]["seed_win_rate"] == reference["candidate_seed_win_rate"]
    v1_random = evaluate_against_baselines(Idle(), PUBLIC_SEEDS, 1, ["random"], use_baseline_cache=False)
    assert reference["floor"]["mean_score"] == v1_random["baselines"][0]["summary"]["mean_score"]


def test_reference_never_touches_the_baseline_cache(tmp_path: Path, public_panel: dict, monkeypatch) -> None:
    """``--raw`` recomputes the reference from the simulator, so a tampered local cache cannot vouch for a forgery.

    The cache has no integrity check and its keys name the seeds, so the
    reference neither reads nor writes it; a second pass is bit-identical
    because the baselines are deterministic.
    """
    from gm_bench import runner
    from gm_bench.baseline_cache import default_cache_path, put_cached_episode
    from gm_bench.protocol import EpisodeConfig

    def no_cache(*args, **kwargs):
        raise AssertionError("the reference must not read or write the baseline cache")

    run_dir = _write_run(tmp_path, PUBLIC_SEEDS, isolation="container")
    with monkeypatch.context() as patch:
        patch.setattr(runner, "load_cache", no_cache)
        patch.setattr(runner, "save_cache", no_cache)
        artifact = compact_agentic_run(run_dir, isolation="container")
        assert validate_agentic_artifact(artifact, raw_run=run_dir)["ok"]
    assert not default_cache_path().exists(), "no private seed may be written into a cache key"

    # A cache poisoned with pick-trader 300 points lower, which a cached run
    # would read, changes nothing.
    fresh = json.loads(json.dumps(artifact))
    cache: dict = {}
    fingerprint = EpisodeConfig().baseline_cache_fingerprint()
    for seed in PUBLIC_SEEDS:
        episode = runner.run_episode(runner.AGENTS[REFERENCE_AGENT](), seed=seed, seasons=1).__dict__
        poisoned = dict(episode, final_score=episode["final_score"] - 300)
        put_cached_episode(REFERENCE_AGENT, seed, 1, poisoned, config_fingerprint=fingerprint, cache=cache)
    runner.save_cache(cache, default_cache_path())
    cached, hits = runner.run_many_cached_baselines(REFERENCE_AGENT, PUBLIC_SEEDS, 1)
    cached_mean = sum(episode["final_score"] for episode in cached["episodes"]) / len(PUBLIC_SEEDS)
    assert hits == len(PUBLIC_SEEDS) and abs(cached_mean - (fresh["reference"]["mean_score"] - 300)) < 1e-2
    assert compact_agentic_run(run_dir, isolation="container")["reference"] == fresh["reference"]
    assert validate_agentic_artifact(fresh, raw_run=run_dir)["ok"]

    forged = json.loads(json.dumps(artifact))
    forged["reference"]["floor"]["mean_score"] += 1.0  # internally coherent, so only --raw can catch it
    assert validate_agentic_artifact(forged)["ok"]
    report = validate_agentic_artifact(forged, raw_run=run_dir)
    assert any("fresh redaction" in error and "reference" in error for error in report["errors"])


def test_validation_rejects_an_impossible_reference(tmp_path: Path, public_panel: dict) -> None:
    panel = compact_agentic_run(_write_run(tmp_path, PUBLIC_SEEDS, isolation="container"), isolation="container")
    assert validate_agentic_artifact(panel)["ok"]
    lift = panel["reference"]["paired_lift_mean"]

    def errors_after(**changes) -> list[str]:
        edited = json.loads(json.dumps(panel))
        edited["reference"].update(changes)
        return validate_agentic_artifact(edited)["errors"]

    assert any("does not contain" in e for e in errors_after(paired_lift_ci95=[lift + 5.0, lift + 6.0]))
    assert any("wider than" in e for e in errors_after(paired_lift_stddev=0.0, paired_lift_ci95=[lift - 9, lift + 9]))
    assert any("must not be negative" in e for e in errors_after(paired_lift_stddev=-1.0))
    win_all = 1.0 if lift < 0 else 0.0
    assert any("candidate_seed_win_rate is" in e for e in errors_after(candidate_seed_win_rate=win_all))
    # The reviewer's forgery: an interval excluding its own mean, zero spread,
    # a win rate that contradicts the sign, p near 1 and "significant".
    forged = errors_after(
        paired_lift_ci95=[5.0, 6.0],
        paired_lift_stddev=0.0,
        candidate_seed_win_rate=win_all,
        sign_flip_p_value=0.99,
        significant_at_95=True,
    )
    assert forged and any("does not contain" in e for e in forged)
    # p and the interval may honestly disagree, so p alone is never an error.
    assert validate_agentic_artifact(dict(panel, reference=dict(panel["reference"], sign_flip_p_value=0.99)))["ok"]


def test_recorded_reference_scores_pin_every_panel_row(tmp_path: Path, public_panel: dict) -> None:
    """A pick-trader mean shifted together with its lift is coherent; only the recorded constants catch it without --raw."""
    panel = compact_agentic_run(_write_run(tmp_path, PUBLIC_SEEDS, isolation="container"), isolation="container")
    reference = panel["reference"]
    shifted = json.loads(json.dumps(panel))
    shifted["reference"]["mean_score"] = round(reference["mean_score"] - 200, 3)
    shifted["reference"]["paired_lift_mean"] = round(reference["paired_lift_mean"] + 200, 3)
    shifted["reference"]["paired_lift_ci95"] = [round(bound + 200, 3) for bound in reference["paired_lift_ci95"]]
    shifted["reference"]["significant_at_95"] = shifted["reference"]["paired_lift_ci95"][0] > 0
    shifted["reference"]["candidate_seed_win_rate"] = 1.0

    unpinned = validate_agentic_artifact(shifted)
    assert unpinned["ok"] and any("reference_scores" in w for w in unpinned["warnings"])

    means = {REFERENCE_AGENT: reference["mean_score"], REFERENCE_FLOOR_AGENT: reference["floor"]["mean_score"]}
    pinned_lane = dict(public_panel, reference_scores={"seasons": 1, "mean_scores": means})
    honest = validate_agentic_artifact(panel, lane=pinned_lane)
    assert honest["ok"] and not any("reference_scores" in w for w in honest["warnings"])
    errors = validate_agentic_artifact(shifted, lane=pinned_lane)["errors"]
    assert any("pick-trader mean" in e and "frozen panel" in e for e in errors)

    floor_shift = json.loads(json.dumps(panel))
    floor_shift["reference"]["floor"]["mean_score"] += 1.0
    assert any("random mean" in e for e in validate_agentic_artifact(floor_shift, lane=pinned_lane)["errors"])

    other_seasons = dict(pinned_lane, reference_scores={"seasons": 5, "mean_scores": means})
    report = validate_agentic_artifact(shifted, lane=other_seasons)
    assert report["ok"] and any("not pinned" in w for w in report["warnings"])


def test_committed_lane_records_the_reference_means_for_the_full_row() -> None:
    """The frozen panel's pick-trader and random means, computed uncached on the escrowed seeds on 2026-09-23."""
    lane = load_lane_config()
    assert lane is not None
    pins = lane["reference_scores"]
    assert pins["seasons"] == lane["panel_design"]["full_row"]["seasons"]
    assert pins["mean_scores"] == {REFERENCE_AGENT: 249.18, REFERENCE_FLOOR_AGENT: 90.367}


def test_validation_rejects_a_misplaced_or_malformed_reference(tmp_path: Path, public_panel: dict) -> None:
    run_dir = _write_run(tmp_path, PUBLIC_SEEDS, isolation="container")
    panel = compact_agentic_run(run_dir, isolation="container")
    smoke = compact_agentic_run(run_dir, isolation="same-user")

    with_reference = dict(smoke, reference=panel["reference"])
    assert any("smoke row carries no reference" in e for e in validate_agentic_artifact(with_reference)["errors"])

    missing = {key: value for key, value in panel.items() if key != "reference"}
    assert any("needs the reference block" in e for e in validate_agentic_artifact(missing)["errors"])

    off_panel = json.loads(json.dumps(panel))
    off_panel["reference"]["num_seeds"] = 2
    assert any("reference.num_seeds is 2" in e for e in validate_agentic_artifact(off_panel)["errors"])

    per_seed = json.loads(json.dumps(panel))
    per_seed["reference"]["per_seed"] = [{"lift": 1.0}]
    assert any("per_seed must be empty" in e for e in validate_agentic_artifact(per_seed)["errors"])

    other_agent = json.loads(json.dumps(panel))
    other_agent["reference"]["agent"] = "value"
    assert any("reference.agent must be 'pick-trader'" in e for e in validate_agentic_artifact(other_agent)["errors"])

    leaky = json.loads(json.dumps(panel))
    leaky["reference"]["baseline_cache"] = {"path": "/Users/someone/data/baseline_cache.json"}
    errors = validate_agentic_artifact(leaky)["errors"]
    assert any("unexpected keys ['baseline_cache']" in e for e in errors)
    assert any("local filesystem path" in e for e in errors)

    incoherent = json.loads(json.dumps(panel))
    incoherent["reference"]["paired_lift_mean"] += 5.0
    assert any("is not the row mean" in e for e in validate_agentic_artifact(incoherent)["errors"])

    contradicted = json.loads(json.dumps(panel))
    contradicted["reference"]["significant_at_95"] = not contradicted["reference"]["significant_at_95"]
    assert any("contradicts" in e for e in validate_agentic_artifact(contradicted)["errors"])

    moved_lane = dict(PUBLIC_LANE, panel_design={"reference_agent": "value"})
    assert any("reference_agent is 'value'" in e for e in validate_agentic_artifact(panel, lane=moved_lane)["errors"])


def test_cli_redacts_and_revalidates_a_panel_reference(tmp_path: Path, public_panel: dict, capsys) -> None:
    from gm_bench.cli import main

    run_dir = _write_run(tmp_path, PUBLIC_SEEDS, isolation="container")
    out = tmp_path / "results" / "agentic" / "row.json"
    main(["agentic-redact", str(run_dir), "--output", str(out), "--isolation", "container"])
    assert "panel grade, 3 seeds" in capsys.readouterr().out
    written = json.loads(out.read_text())
    assert written["reference"]["per_seed"] == [] and written["reference"]["num_seeds"] == 3
    main(["agentic-validate", str(out), "--raw", str(run_dir)])
    assert "(panel artifact), OK" in capsys.readouterr().out


def test_isolation_claim_cannot_exceed_what_the_driver_recorded(tmp_path: Path) -> None:
    """The driver records how it launched the harness; the operator may understate it, never overstate it."""
    legacy = _write_run(tmp_path / "legacy", [11])  # written before the driver recorded isolation
    same_user = _write_run(tmp_path / "same", [11], isolation="same-user")
    container = _write_run(tmp_path / "container", [11], isolation="container")
    for run_dir in (legacy, same_user):
        for claim in ("separate-user", "container"):
            with pytest.raises(ValueError, match="refusing to publish"):
                compact_agentic_run(run_dir, isolation=claim)
        assert compact_agentic_run(run_dir, isolation="same-user")["isolation"] == "same-user"
    assert compact_agentic_run(container, isolation="container")["isolation"] == "container"
    assert compact_agentic_run(container, isolation="same-user")["isolation"] == "same-user"
    with pytest.raises(ValueError, match="refusing to publish"):
        compact_agentic_run(container, isolation="separate-user")

    # An episode that disagrees with the run-level record drops the run to same-user.
    raw = json.loads((container / "run.json").read_text())
    raw["episodes"][0]["harness_run"]["isolation"] = "same-user"
    (container / "run.json").write_text(json.dumps(raw, sort_keys=True))
    with pytest.raises(ValueError, match="records isolation 'same-user'"):
        compact_agentic_run(container, isolation="container")

    # An artifact edited to claim container is caught against its raw run.
    artifact = compact_agentic_run(same_user, isolation="same-user")
    forged = json.loads(json.dumps(artifact))
    forged["isolation"] = "container"
    report = validate_agentic_artifact(forged, raw_run=same_user)
    assert any("refusing to publish it as 'container'" in error for error in report["errors"])
