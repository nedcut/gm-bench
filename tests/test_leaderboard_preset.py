"""Tests for the leaderboard preset and private seed panel."""

from __future__ import annotations

import pytest

from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, BenchmarkConfig


def test_leaderboard_preset_defaults():
    config = BenchmarkConfig()
    config.apply_preset("leaderboard")
    assert config.seeds == [11, 12, 13, 14, 15, 16, 17, 18]
    assert config.seasons == 5
    assert "value" in config.baselines
    assert set(config.seeds).isdisjoint({1, 2, 3, 4, 5}), "leaderboard seeds must avoid the dev panel"


def test_private_seeds_env_overrides_leaderboard(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-112")
    config = BenchmarkConfig()
    config.apply_preset("leaderboard")
    assert config.seeds == [101, 102, 110, 111, 112]


def test_private_seeds_env_does_not_touch_other_presets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101")
    config = BenchmarkConfig()
    config.apply_preset("standard")
    assert config.seeds == [1, 2, 3]
