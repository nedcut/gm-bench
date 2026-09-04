from __future__ import annotations

import hashlib
import json
from pathlib import Path

from gm_bench.official import REDACTED_SEEDS_SENTINEL
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
