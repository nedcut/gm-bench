"""Keep the experimental public demo separate, faithful, and reproducible."""

import hashlib
import json
import math
import shutil

import pytest

from gm_bench.recorder import validate_replay_fixture
from scripts import build_trajectory_demo as export


def assert_export_matches(actual, expected, path=()):
    """Preserve JSON semantics; allow two ULPs only in four asset rollups.

    Python 3.12 changed float summation. The 3.11 export differs by one ULP
    in these derived components, never in recorded actions or replay state.
    Object key order is immaterial; array order and scalar types are exact.
    """
    assert type(actual) is type(expected), path
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), path
        for key in expected:
            assert_export_matches(actual[key], expected[key], (*path, key))
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            assert_export_matches(left, right, (*path, index))
    elif isinstance(expected, float):
        assert math.isfinite(actual) and math.isfinite(expected), path
        tolerant = (
            len(path) == 4
            and path[0] == "episodes"
            and path[1] in (0, 1)
            and path[2] == "components"
            and path[3]
            in (
                "future_pick_assets",
                "future_pick_assets_contribution",
                "total_assets",
                "total_assets_contribution",
            )
        )
        assert abs(actual - expected) <= (2 * math.ulp(expected) if tolerant else 0), path
    else:
        assert actual == expected, path


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


@pytest.fixture
def source_copy(tmp_path, monkeypatch):
    """A byte-identical pinned source tree that tests can safely change."""
    package = tmp_path / "gm_bench"
    package.mkdir()
    for name in export.SOURCE_MODULES:
        shutil.copyfile(export.ROOT / "gm_bench" / name, package / name)
    monkeypatch.setattr(export, "ROOT", tmp_path)
    return package


def test_unrelated_modules_preserve_digest_and_export(source_copy):
    assert export.source_package_digest() == export.SOURCE_PACKAGE_SHA256

    # Compare within this interpreter: Python 3.11 and 3.12+ sum floats
    # differently, so byte equality with a fixture generated elsewhere is not
    # the invariant under test. Digest equality also avoids a multi-MB diff.
    def output_digest():
        serialized = json.dumps(export.build_demo(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(serialized.encode()).hexdigest()

    original_digest = output_digest()
    # Keep cross-runtime fixture coverage as well as exact same-runtime
    # determinism. Normalize JSON object keys (e.g. integer draft years).
    actual = json.loads(json.dumps(export.build_demo()))
    assert_export_matches(actual, json.loads(export.DESTINATION.read_text()))
    (source_copy / "independent_experiment.py").write_text("raise AssertionError('must not be imported')\n")
    (source_copy / "future_experiments").mkdir()
    (source_copy / "future_experiments" / "__init__.py").write_text("# unrelated package\n")
    assert export.source_package_digest() == export.SOURCE_PACKAGE_SHA256
    assert output_digest() == original_digest


@pytest.mark.parametrize(
    ("actual", "expected", "path"),
    [
        ({"a": 1}, {"a": 1, "b": 2}, ()),
        ([1, 2], [2, 1], ()),
        ([1], [1, 2], ()),
        (True, 1, ()),
        (1.0, 1, ()),
        (2, 1, ()),
        ("changed", "original", ()),
        (math.nextafter(1.0, 2.0), 1.0, ("episodes", 0, "fixture", "score")),
        (1.0 + 3 * math.ulp(1.0), 1.0, ("episodes", 0, "components", "total_assets")),
        (float("inf"), 1.0, ("episodes", 0, "components", "total_assets")),
        (float("nan"), 1.0, ("episodes", 0, "components", "total_assets")),
    ],
)
def test_export_comparison_rejects_semantic_changes(actual, expected, path):
    with pytest.raises(AssertionError):
        assert_export_matches(actual, expected, path)


def test_export_comparison_allows_only_bounded_asset_roundoff():
    assert_export_matches(1.0 + 2 * math.ulp(1.0), 1.0, ("episodes", 0, "components", "total_assets"))


@pytest.mark.parametrize("name", export.SOURCE_MODULES)
def test_pinned_source_mutations_are_rejected(source_copy, name):
    path = source_copy / name
    path.write_bytes(path.read_bytes() + b"\n# changed pinned source\n")
    assert export.source_package_digest() != export.SOURCE_PACKAGE_SHA256
    with pytest.raises(ValueError, match="source changed"):
        export.build_demo()


def test_missing_pinned_source_is_rejected(source_copy):
    (source_copy / "recorder.py").unlink()
    with pytest.raises(FileNotFoundError):
        export.build_demo()
