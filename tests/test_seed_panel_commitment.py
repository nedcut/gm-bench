from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seed_panel_commitment.py"
_SPEC = importlib.util.spec_from_file_location("seed_panel_commitment", _MODULE_PATH)
assert _SPEC and _SPEC.loader
commitment_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(commitment_mod)


def test_parse_seeds_expands_ranges_sorts_and_dedupes():
    assert commitment_mod.parse_seeds("110-115,101,102,102") == [101, 102, 110, 111, 112, 113, 114, 115]


def test_parse_seeds_rejects_negative_and_descending():
    with pytest.raises(ValueError):
        commitment_mod.parse_seeds("-1")
    with pytest.raises(ValueError):
        commitment_mod.parse_seeds("115-110")


def test_commitment_is_canonical_over_order_and_formatting():
    a = commitment_mod.commitment("ab12", commitment_mod.parse_seeds("11,12,13"))
    b = commitment_mod.commitment("ab12", commitment_mod.parse_seeds("13, 11, 12, 11"))
    assert a == b
    # A different salt yields a different commitment for the same seeds.
    assert commitment_mod.commitment("ab13", [11, 12, 13]) != a


def test_commit_verify_roundtrip_via_salt_file(tmp_path, capsys):
    salt_file = tmp_path / "panel.seed-salt.json"
    rc = commitment_mod.main(["commit", "--seeds", "101,102,110-115", "--salt-file", str(salt_file)])
    assert rc == 0
    record = json.loads(salt_file.read_text())
    assert record["count"] == 8
    assert record["seeds"] == "101,102,110,111,112,113,114,115"

    rc = commitment_mod.main(["verify", "--salt-file", str(salt_file)])
    assert rc == 0

    # Explicit args reproduce the stored commitment.
    rc = commitment_mod.main(
        ["verify", "--seeds", "110-115,101,102", "--salt", record["salt"], "--commitment", record["commitment"]]
    )
    assert rc == 0


def test_verify_detects_wrong_seeds(tmp_path):
    salt_file = tmp_path / "panel.seed-salt.json"
    commitment_mod.main(["commit", "--seeds", "11,12,13", "--salt-file", str(salt_file)])
    record = json.loads(salt_file.read_text())
    rc = commitment_mod.main(
        ["verify", "--seeds", "11,12,14", "--salt", record["salt"], "--commitment", record["commitment"]]
    )
    assert rc == 1


def test_commit_refuses_to_clobber_salt_file(tmp_path):
    salt_file = tmp_path / "panel.seed-salt.json"
    assert commitment_mod.main(["commit", "--seeds", "11,12,13", "--salt-file", str(salt_file)]) == 0
    assert commitment_mod.main(["commit", "--seeds", "11,12,13", "--salt-file", str(salt_file)]) == 1
    assert commitment_mod.main(["commit", "--seeds", "11,12,13", "--salt-file", str(salt_file), "--force"]) == 0
