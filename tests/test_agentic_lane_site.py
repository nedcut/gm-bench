"""The site's GM-Bench 2.0 section: panel-grade rows only, kept apart from every 1.0 table.

The panel rows here are fixtures built in memory from the committed smoke row (grade, isolation, and seed groups edited,
plus a synthetic reference block coherent with the row) and written to a
temporary directory, never under ``results/agentic/``.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from gm_bench.agentic.publication import PANEL_MIN_SEEDS, REDACTED_SEEDS
from tests.test_agentic_publication import clean_driver, fixture_reference
from web.scripts.build_study import build_study

SITE_DATASET = Path("web/src/data/leaderboard.json")
SMOKE_ROW = Path("results/agentic/opencode-1.18.31-space-bunny-free-smoke-8x5.json")
LANE_PANEL = json.loads(Path("config/bench_v2_lane.json").read_text())["seed_panel"]


def _smoke() -> dict:
    return json.loads(SMOKE_ROW.read_text())


def _panel_fixture(*, isolation: str = "separate-user", model: str | None = None) -> dict:
    """The smoke row reshaped into a 32-group panel row on the lane's frozen panel digest."""
    row = _smoke()
    smoke_episodes = row["episodes"]
    episodes = []
    for index in range(LANE_PANEL["count"]):
        episode = copy.deepcopy(smoke_episodes[index % len(smoke_episodes)])
        episode.pop("seed", None)
        episode.update(index=index, seed_group=index)
        episodes.append(episode)
    row["episodes"] = episodes
    row["grade"] = "panel"
    row["isolation"] = isolation
    row["panel"] = {
        "seed_count": len(episodes),
        "distinct_seeds": len(episodes),
        "seeds": REDACTED_SEEDS,
        "sha256": LANE_PANEL["artifact_panel_sha256"],
    }
    row["summary"]["mean_score"] = round(sum(e["final_score"] for e in episodes) / len(episodes), 3)
    row["reference"] = fixture_reference(row)
    row["driver"] = clean_driver()
    if model is not None:
        row["harness"]["model"] = model
    return row


def _build(
    tmp_path: Path,
    *rows: tuple[str, dict],
    pinned_models: dict | None = None,
    reference_scores: dict | None = None,
) -> dict:
    agentic_dir = tmp_path / "agentic"
    agentic_dir.mkdir()
    for name, payload in rows:
        (agentic_dir / name).write_text(json.dumps(payload))
    if pinned_models is None and reference_scores is None:
        return build_study(output_path=tmp_path / "leaderboard.json", agentic_dir=agentic_dir)
    root = tmp_path / "root"
    shutil.copytree(Path("config"), root / "config")
    (root / "results").mkdir()
    for name in ("analysis", "leaderboard"):
        (root / "results" / name).symlink_to(Path("results", name).resolve(), target_is_directory=True)
    lane_path = root / "config" / "bench_v2_lane.json"
    lane = json.loads(lane_path.read_text())
    if pinned_models is not None:
        lane["model_pinning"]["pinned_models"] = pinned_models
    if reference_scores is not None:
        lane["reference_scores"]["mean_scores"] = reference_scores
    lane_path.write_text(json.dumps(lane))
    return build_study(root=root, output_path=tmp_path / "leaderboard.json", agentic_dir=agentic_dir)


def test_current_results_publish_only_the_committed_panel_rows(tmp_path: Path) -> None:
    """The site's 2.0 section shows the committed panel rows and none of the smoke rows."""
    assert _smoke()["grade"] == "smoke"
    dataset = build_study(output_path=tmp_path / "leaderboard.json")
    assert [row["id"] for row in dataset["agentic_lane"]] == ["agentic:codex-0.156.1:gpt-6-luna"]
    assert all(row["grade"] == "panel" for row in dataset["agentic_lane"])
    assert json.loads(SITE_DATASET.read_text()) == dataset


def test_panel_row_is_published_beside_every_1_0_table(tmp_path: Path) -> None:
    panel = _panel_fixture()
    dataset = _build(tmp_path, ("smoke.json", _smoke()), ("panel.json", panel))

    assert len(dataset["models"]) == 11
    assert [row["id"] for row in dataset["decision_lane_models"]] == ["typesafe:typesafe/jev-1.13"]
    assert dataset["publication"]["eligible_headline_models"] == 11
    rows = dataset["agentic_lane"]
    assert len(rows) == 1, "the smoke row must not be published"
    row = rows[0]
    assert row["id"] == "agentic:opencode-1.18.31:opencode/space-bunny-free"
    assert row["lane"] == "agentic" and row["grade"] == "panel"
    assert row["harness"] == {
        "name": "opencode",
        "version": "1.18.31",
        "model": "opencode/space-bunny-free",
        "variant": None,
    }
    assert row["unpinned"] is True and row["pin"] is None
    assert row["isolation"] == "separate-user"
    assert row["panel"] == {
        "distinct_seeds": PANEL_MIN_SEEDS,
        "episodes": PANEL_MIN_SEEDS,
        "sha256": LANE_PANEL["artifact_panel_sha256"],
    }
    smoke_scores = [e["final_score"] for e in _smoke()["episodes"]]
    assert row["mean_score"] == pytest.approx(sum(smoke_scores) / len(smoke_scores), abs=1e-3)
    assert row["score_stddev"] == pytest.approx(_smoke()["summary"]["score_stddev"], abs=1e-3)
    assert row["seed_mean_min"] == min(smoke_scores) and row["seed_mean_max"] == max(smoke_scores)
    assert row["contract"]["agentic_fingerprint"] == panel["contract"]["agentic_fingerprint"]
    assert row["contract"]["tool_surface"] == "gm-bench-agentic-v1"
    assert row["contract"]["brief"] == "gm-bench-agentic-brief-v1"

    telemetry = row["telemetry"]
    repeats = PANEL_MIN_SEEDS // len(smoke_scores)
    smoke_calls = sum(e["agentic"]["tool_calls"] for e in _smoke()["episodes"])
    assert telemetry["tool_calls"] == repeats * smoke_calls
    assert sum(telemetry["tool_calls_by_tool"].values()) == telemetry["tool_calls"]
    assert telemetry["phases_ended_by"] == {"agent": repeats * 160}
    assert telemetry["nudges_used"] == repeats * _smoke()["agentic_summary"]["nudges_used"]
    assert telemetry["nudges_per_episode"] == pytest.approx(telemetry["nudges_used"] / PANEL_MIN_SEEDS, abs=0.01)
    assert telemetry["telemetry_episodes"] == PANEL_MIN_SEEDS
    assert telemetry["input_tokens"] == repeats * sum(e["usage"]["input_tokens"] for e in _smoke()["episodes"])
    assert telemetry["cost_usd"] == 0.0
    assert row["agreement"] == {
        "episodes": PANEL_MIN_SEEDS,
        "episodes_agreeing": PANEL_MIN_SEEDS,
        "ledger_tool_calls": repeats * smoke_calls,
        "harness_tool_calls": repeats * smoke_calls,
    }
    # The one inference the spec supports: pick-trader on this row's own seeds.
    reference = panel["reference"]
    assert row["reference"] == {key: value for key, value in reference.items() if key != "per_seed"}
    assert row["reference"]["agent"] == "pick-trader"
    assert row["reference"]["num_seeds"] == row["panel"]["distinct_seeds"] == LANE_PANEL["count"]
    assert row["v1_row_id"] is None
    assert row["artifact_path"] == "panel.json"
    text = json.dumps(row)
    assert "seeds" not in row and '"seed"' not in text and "per_seed" not in text
    outside_reference = json.dumps({key: value for key, value in row.items() if key != "reference"})
    assert "p_value" not in outside_reference, "no p-value between rows, harnesses, or models"
    one_zero_ids = {m["id"] for m in dataset["models"] + dataset["decision_lane_models"]}
    assert row["id"] not in one_zero_ids


def test_smoke_rows_are_never_published(tmp_path: Path) -> None:
    demoted = _panel_fixture()
    demoted["grade"] = "smoke"
    dataset = _build(tmp_path, ("smoke.json", _smoke()), ("demoted.json", demoted))
    assert dataset["agentic_lane"] == []


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda row: row["panel"].update(sha256="0" * 64), "not the lane's frozen private panel"),
        (lambda row: row.update(isolation="same-user"), "isolated from the driver"),
        (lambda row: row["panel"].update(distinct_seeds=31), "distinct"),
        (lambda row: row.pop("reference"), "needs the reference block"),
        (lambda row: row["reference"].update(num_seeds=29), "reference.num_seeds is 29"),
        (lambda row: row["reference"].update(per_seed=[{"lift": 1.0}]), "per_seed must be empty"),
        (lambda row: row["reference"].update(agent="value"), "reference.agent must be 'pick-trader'"),
    ],
)
def test_a_panel_row_that_does_not_validate_fails_the_build(tmp_path: Path, edit, message: str) -> None:
    bad = _panel_fixture()
    edit(bad)
    with pytest.raises(ValueError, match=message):
        _build(tmp_path, ("bad.json", bad))


def test_only_agentic_artifacts_belong_in_the_agentic_directory(tmp_path: Path) -> None:
    stray = json.loads(Path("results/leaderboard/decision-lane/typesafe-jev-1.13-openrouter.json").read_text())
    with pytest.raises(ValueError, match="gm-bench-agentic-summary-v1"):
        _build(tmp_path, ("stray.json", stray))


def test_duplicate_row_identity_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repeats agentic row"):
        _build(tmp_path, ("a.json", _panel_fixture()), ("b.json", _panel_fixture()))


def test_two_harness_variants_on_one_model_are_two_rows(tmp_path: Path) -> None:
    other = _panel_fixture()
    other["harness"]["variant"] = "high"
    dataset = _build(tmp_path, ("a.json", _panel_fixture()), ("b.json", other))
    assert sorted(row["id"] for row in dataset["agentic_lane"]) == [
        "agentic:opencode-1.18.31:opencode/space-bunny-free",
        "agentic:opencode-1.18.31:opencode/space-bunny-free:high",
    ]


@pytest.mark.parametrize("model", ["x-ai/grok-4.3", "openrouter/x-ai/grok-4.3"])
def test_a_1_0_row_on_the_same_model_is_linked_by_id_only(tmp_path: Path, model: str) -> None:
    dataset = _build(tmp_path, ("panel.json", _panel_fixture(model=model)))
    (row,) = dataset["agentic_lane"]
    assert row["v1_row_id"] == "openrouter:x-ai/grok-4.3"
    assert not any(key.startswith(("paired", "lift", "primary")) for key in row)
    assert row["reference"]["agent"] == "pick-trader", "the only contrast is pick-trader, never the 1.0 row"


def test_unreported_telemetry_is_unmeasured_not_zero(tmp_path: Path) -> None:
    quiet = _panel_fixture()
    for episode in quiet["episodes"]:
        episode["usage"]["harness"]["telemetry_reported"] = False
    (row,) = _build(tmp_path, ("quiet.json", quiet))["agentic_lane"]
    telemetry = row["telemetry"]
    assert telemetry["telemetry_episodes"] == 0
    assert telemetry["input_tokens"] is None and telemetry["cost_usd"] is None
    assert telemetry["tool_calls"] > 0


def test_tokens_reported_without_cost_leave_cost_unmeasured(tmp_path: Path) -> None:
    """A harness that reports tokens but not cost publishes no cost, not $0."""
    partial = _panel_fixture()
    for episode in partial["episodes"]:
        episode["usage"]["cost_usd"] = None
    partial["episodes"][0]["usage"]["cost_usd"] = 0.5
    (row,) = _build(tmp_path, ("partial.json", partial))["agentic_lane"]
    telemetry = row["telemetry"]
    assert telemetry["input_tokens"] is not None
    assert telemetry["cost_usd"] == 0.5 and telemetry["cost_per_episode_usd"] == 0.5
    for episode in partial["episodes"]:
        episode["usage"]["cost_usd"] = None
    (tmp_path / "none").mkdir()
    (row,) = _build(tmp_path / "none", ("partial.json", partial))["agentic_lane"]
    assert row["telemetry"]["cost_usd"] is None and row["telemetry"]["cost_per_episode_usd"] is None


def test_rows_are_ordered_by_pinning_and_identity_never_by_score(tmp_path: Path) -> None:
    low = _panel_fixture(model="zz/low-scorer")
    high = _panel_fixture(model="aa/high-scorer")
    for row, shift in ((high, 100.0), (low, -100.0)):
        for episode in row["episodes"]:
            episode["final_score"] += shift
        row["summary"]["mean_score"] = round(row["summary"]["mean_score"] + shift, 3)
        row["reference"] = fixture_reference(row)
    pinned = _panel_fixture(model="mm/pinned")
    dataset = _build(
        tmp_path,
        ("high.json", high),
        ("low.json", low),
        ("pinned.json", pinned),
        pinned_models={"mm/pinned": "mm/pinned@2026-09-01 via mm"},
    )
    rows = dataset["agentic_lane"]
    assert [row["model"] for row in rows] == ["mm/pinned", "aa/high-scorer", "zz/low-scorer"]
    assert [(row["unpinned"], row["pin"]) for row in rows] == [
        (False, "mm/pinned@2026-09-01 via mm"),
        (True, None),
        (True, None),
    ]


def test_committed_lane_pins_no_model_yet() -> None:
    """A pin is a claim that the row is reproducible; none has been made."""
    lane = json.loads(Path("config/bench_v2_lane.json").read_text())
    assert lane["model_pinning"]["pinned_models"] == {}


def test_a_malformed_pin_fails_the_build(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pinned_models"):
        _build(tmp_path, ("panel.json", _panel_fixture()), pinned_models={"opencode/space-bunny-free": ""})


def test_rows_on_one_panel_must_share_the_reference_means(tmp_path: Path) -> None:
    """pick-trader and random are deterministic, so a shifted reference on one row fails the build even unpinned."""
    shifted = _panel_fixture(model="aa/shifted")
    shifted["reference"] = fixture_reference(shifted, reference_mean=150.0)  # internally coherent
    with pytest.raises(ValueError, match="is not the frozen panel's 249.18|every row's reference must agree"):
        _build(tmp_path, ("a.json", _panel_fixture()), ("b.json", shifted))


def test_recorded_reference_scores_fail_a_row_off_them(tmp_path: Path) -> None:
    honest = {"pick-trader": 249.18, "random": 90.367}
    (tmp_path / "ok").mkdir()
    (tmp_path / "off").mkdir()
    (row,) = _build(tmp_path / "ok", ("panel.json", _panel_fixture()), reference_scores=honest)["agentic_lane"]
    assert row["reference"]["mean_score"] == 249.18
    with pytest.raises(ValueError, match="frozen panel"):
        _build(tmp_path / "off", ("panel.json", _panel_fixture()), reference_scores=dict(honest, random=91.0))
