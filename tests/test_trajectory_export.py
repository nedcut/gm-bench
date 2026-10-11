"""Keep the experimental public demo separate, faithful, and reproducible."""

import hashlib
import json

import pytest

from gm_bench.recorder import validate_replay_fixture
from scripts import build_trajectory_demo as export


def test_public_demo_replays_and_preserves_original():
    original_bytes = export.ORIGINAL.read_bytes()
    original = json.loads(original_bytes)
    payload = json.loads(export.DESTINATION.read_bytes())
    assert payload["original_replay_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert payload["tool_trace"] is None
    assert payload["seed_scope"] == "public-dev"
    assert payload["source_package_sha256"] == export.source_package_digest()
    for episode in payload["episodes"]:
        fixture = episode["fixture"]
        assert episode["kind"] == "scripted-demo"
        assert fixture["seed"] == 1
        assert len(fixture["decisions"]) == 20
        assert validate_replay_fixture(fixture)["valid"]
        if fixture["agent"] == "conservative":
            assert fixture["expected"] == original["expected"]
            for new, old in zip(fixture["decisions"], original["decisions"], strict=True):
                assert [r["actions"] for r in new["interaction_rounds"]] == [
                    r["actions"] for r in old["interaction_rounds"]
                ]
    left, right = payload["episodes"]
    assert (
        left["fixture"]["decisions"][0]["interaction_rounds"][0]["observation"]
        == right["fixture"]["decisions"][0]["interaction_rounds"][0]["observation"]
    )


def test_export_refuses_misattributed_source(monkeypatch):
    monkeypatch.setattr(export, "SOURCE_PACKAGE_SHA256", "changed")
    with pytest.raises(ValueError, match="source changed"):
        export.build_demo()
