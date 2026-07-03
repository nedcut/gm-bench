from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_baseline_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the baseline cache so tests never touch the repo's data/ directory.

    Also inherited by subprocess-based CLI tests via the environment.
    """
    monkeypatch.setenv("GM_BENCH_BASELINE_CACHE", str(tmp_path / "baseline_cache.json"))
