from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gm_bench.official import REDACTED_SEEDS_SENTINEL, SOTA_V5_POLICY, validate_leaderboard_payload
from web.scripts.build_leaderboard import OUTPUT_PATH as V2_OUTPUT_PATH
from web.scripts.build_study import V5_OUTPUT_PATH, build_study

SITE_DATASET = Path("web/src/data/leaderboard.json")


def test_v5_site_builder_writes_only_where_asked(tmp_path: Path) -> None:
    """The builder reads the contract-scoped headline artifacts and the committed
    analysis, but writes only to the path it is given; the checked-in site
    dataset is untouched by a build directed elsewhere."""
    before = hashlib.sha256(SITE_DATASET.read_bytes()).hexdigest()

    dataset = build_study(output_path=tmp_path / "leaderboard-sota-v5.json")

    assert dataset["publication"]["publishable_results"] is True
    assert len(dataset["models"]) == 11
    assert dataset["preset"]["seeds"] == REDACTED_SEEDS_SENTINEL
    assert dataset["preset"]["seed_count"] == 29
    assert dataset["headroom"]["pick_trader"] == 247.109
    assert (tmp_path / "leaderboard-sota-v5.json").is_file()
    assert hashlib.sha256(SITE_DATASET.read_bytes()).hexdigest() == before


def test_checked_in_site_dataset_is_the_sota_v5_study() -> None:
    """The site publishes sota-v5 (owner decision 2026-09-04); the checked-in
    dataset must match a fresh build of the frozen artifacts."""
    assert V5_OUTPUT_PATH == SITE_DATASET.resolve()
    committed = json.loads(SITE_DATASET.read_text())
    assert committed["contract"]["benchmark_version"] == "sota-v5"
    assert committed["preset"]["seeds"] == REDACTED_SEEDS_SENTINEL
    assert committed["preset"]["seed_count"] == 29
    assert len(committed["models"]) == 11


def test_archived_v2_site_dataset_is_preserved_beside_v5() -> None:
    """The archived phase-one dataset stays reproducible under its own path."""
    assert V2_OUTPUT_PATH == Path("web/src/data/leaderboard-sota-v2.json").resolve()
    archived = json.loads(V2_OUTPUT_PATH.read_text())
    assert archived["contract"]["benchmark_version"] == "sota-v2"
    assert len(archived["models"]) == 8


DECISION_LANE_ARTIFACT = Path("results/leaderboard/decision-lane/typesafe-jev-1.13-openrouter.json")


def test_decision_lane_is_published_beside_the_headline(tmp_path: Path) -> None:
    """The decision-model lane rides the same contract and private panel but is
    its own bucket: never a headline row, never counted, never sharing an id."""
    dataset = build_study(output_path=tmp_path / "leaderboard.json")

    assert len(dataset["models"]) == 11
    rows = dataset["decision_lane_models"]
    assert [row["id"] for row in rows] == ["typesafe:typesafe/jev-1.13"]
    row = rows[0]
    assert row["lane"] == "decision-api"
    assert row["seed_panel"] == "private-env"
    assert row["seed_count"] == 29
    assert row["seeds"] is None
    assert row.get("per_seed_scores") is None
    assert row["scaffold_fingerprint"] == "e1fc1e298283f465"
    assert row["provider_options"]["JEV_ROUTE"] == "openrouter"
    assert row["artifact_path"] == str(DECISION_LANE_ARTIFACT)
    assert "OpenRouter" in row["route"]
    assert row["id"] not in {model["id"] for model in dataset["models"]}
    assert dataset["publication"]["eligible_headline_models"] == 11
    assert dataset["headroom"]["best_model"] == max(model["mean_score"] for model in dataset["models"])

    committed = json.loads(SITE_DATASET.read_text())
    assert committed["decision_lane_models"] == rows


def test_decision_lane_refuses_a_chat_lane_artifact(tmp_path: Path) -> None:
    """A headline-shaped artifact dropped into the decision-lane directory must
    fail the build rather than quietly becoming a decision-lane row."""
    lane_dir = tmp_path / "decision-lane"
    lane_dir.mkdir()
    source = next(Path("results/leaderboard/sota-v5").glob("*.json"))
    (lane_dir / source.name).write_text(source.read_text())

    with pytest.raises(ValueError, match="decision-api"):
        build_study(output_path=tmp_path / "leaderboard.json", decision_lane_dir=lane_dir)


def test_decision_lane_artifact_is_redacted_and_validates() -> None:
    """The committed decision-lane artifact is a redacted private-panel row that
    passes the sota-v5 policy on its own scaffold fingerprint."""
    payload = json.loads(DECISION_LANE_ARTIFACT.read_text())
    assert payload["seeds"] == REDACTED_SEEDS_SENTINEL
    assert payload["candidate"]["episodes"] == []
    assert payload["paired"]["per_seed"] == []
    assert payload["redaction"]["applied"] is True
    assert payload["run_info"]["transport"] == "decision-api"
    assert payload["run_info"]["scaffold_fingerprint"] == SOTA_V5_POLICY.expected_scaffold_fingerprints["typesafe"]
    report = validate_leaderboard_payload(payload, policy=SOTA_V5_POLICY)
    assert report.ok, report.errors


def test_decision_lane_refuses_a_duplicate_id(tmp_path: Path) -> None:
    """Two artifacts claiming the same decision-lane id would render as two
    rows with one identity; the builder must refuse the second."""
    lane_dir = tmp_path / "decision-lane"
    lane_dir.mkdir()
    (lane_dir / "a.json").write_text(DECISION_LANE_ARTIFACT.read_text())
    (lane_dir / "b.json").write_text(DECISION_LANE_ARTIFACT.read_text())

    with pytest.raises(ValueError, match="repeats decision-lane id"):
        build_study(output_path=tmp_path / "leaderboard.json", decision_lane_dir=lane_dir)


def test_decision_lane_artifact_carries_no_local_path() -> None:
    payload = json.loads(DECISION_LANE_ARTIFACT.read_text())
    assert "path" not in payload["baseline_cache"]
    assert "baseline_cache.path" in payload["redaction"]["removed"]
