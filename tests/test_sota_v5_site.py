from __future__ import annotations

from pathlib import Path

import pytest

from web.scripts.build_study import build_study


def test_v5_site_builder_is_locked_before_reading_unpublished_results() -> None:
    with pytest.raises(ValueError, match="sota-v5 site publication is locked"):
        build_study()


def test_v2_checked_in_dataset_is_not_replaced_by_v5_builder() -> None:
    assert Path("web/src/data/leaderboard.json").is_file()
    assert not Path("web/src/data/leaderboard-sota-v5.json").exists()
