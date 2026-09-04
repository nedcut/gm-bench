from __future__ import annotations

import hashlib
from pathlib import Path

from gm_bench.official import REDACTED_SEEDS_SENTINEL
from web.scripts.build_study import V5_OUTPUT_PATH, build_study


def test_v5_site_builder_builds_the_authorized_study_only_where_asked(tmp_path: Path) -> None:
    """Publication was authorized on 2026-09-03; the site release is a separate decision.

    The builder reads the contract-scoped headline artifacts and the committed
    analysis, but writes only to the path it is given. The checked-in v2 site
    dataset and the absent v5 dataset are untouched.
    """
    site = Path("web/src/data/leaderboard.json")
    before = hashlib.sha256(site.read_bytes()).hexdigest()

    dataset = build_study(output_path=tmp_path / "leaderboard-sota-v5.json")

    assert dataset["publication"]["publishable_results"] is True
    assert len(dataset["models"]) == 11
    assert dataset["preset"]["seeds"] == REDACTED_SEEDS_SENTINEL
    assert dataset["preset"]["seed_count"] == 29
    assert dataset["headroom"]["pick_trader"] == 247.109
    assert (tmp_path / "leaderboard-sota-v5.json").is_file()
    assert not V5_OUTPUT_PATH.exists()
    assert hashlib.sha256(site.read_bytes()).hexdigest() == before


def test_v2_checked_in_dataset_is_not_replaced_by_v5_builder() -> None:
    assert Path("web/src/data/leaderboard.json").is_file()
    assert not Path("web/src/data/leaderboard-sota-v5.json").exists()
