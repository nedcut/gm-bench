from __future__ import annotations

import importlib.util
import json
import stat
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
    original = salt_file.read_bytes()
    assert commitment_mod.main(["commit", "--seeds", "11,12,13", "--salt-file", str(salt_file)]) == 1
    assert salt_file.read_bytes() == original


def test_commit_creates_secret_file_with_owner_only_permissions(tmp_path, capsys):
    salt_file = tmp_path / "panel.seed-salt.json"
    assert commitment_mod.main(["commit", "--seeds", "11,12,13", "--salt-file", str(salt_file)]) == 0

    assert stat.S_IMODE(salt_file.stat().st_mode) == 0o600
    warning = capsys.readouterr().err
    assert "plaintext secret material" in warning
    assert "gitignore is not encryption" in warning


def test_commit_refuses_salt_file_inside_checkout():
    salt_file = commitment_mod._ROOT / "data" / "private-seed-salt-must-not-exist.json"

    assert commitment_mod.main(["commit", "--seeds", "11,12,13", "--salt-file", str(salt_file)]) == 2
    assert not salt_file.exists()


def test_execution_hash_preserves_order_and_never_prints_seeds(tmp_path, monkeypatch, capsys):
    seeds = [(1 << 50) + index * 104729 for index in range(17)]
    lane = tmp_path / "lane.json"
    lane.write_text(json.dumps({"seed_panel": {"name": "private-env", "count": 17}}))
    monkeypatch.setenv(commitment_mod.PRIVATE_SEEDS_ENV, ",".join(str(seed) for seed in seeds))

    assert commitment_mod.main(["execution-hash", "--lane", str(lane)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["count"] == 17
    assert payload["sha256"] == commitment_mod.seed_panel_hash(seeds)
    assert payload["seed_values_included"] is False
    assert all(str(seed) not in json.dumps(payload) for seed in seeds)
    assert payload["sha256"] != commitment_mod.seed_panel_hash(sorted(seeds, reverse=True))


def test_execution_hash_rejects_missing_or_low_entropy_seed_env(tmp_path, monkeypatch):
    lane = tmp_path / "lane.json"
    lane.write_text(json.dumps({"seed_panel": {"name": "private-env", "count": 17}}))
    monkeypatch.delenv(commitment_mod.PRIVATE_SEEDS_ENV, raising=False)
    assert commitment_mod.main(["execution-hash", "--lane", str(lane)]) == 2

    monkeypatch.setenv(commitment_mod.PRIVATE_SEEDS_ENV, ",".join(str(seed) for seed in range(100, 117)))
    assert commitment_mod.main(["execution-hash", "--lane", str(lane)]) == 2


def test_execution_hash_rejects_wrong_count_or_committed_preset_overlap(tmp_path, monkeypatch):
    lane = tmp_path / "lane.json"
    lane.write_text(json.dumps({"seed_panel": {"name": "private-env", "count": 17}}))

    high_entropy = [(1 << 50) + index * 104729 for index in range(17)]
    monkeypatch.setenv(commitment_mod.PRIVATE_SEEDS_ENV, ",".join(str(seed) for seed in high_entropy[:-1]))
    assert commitment_mod.main(["execution-hash", "--lane", str(lane)]) == 2

    committed_seed = next(iter(commitment_mod.PRESETS["smoke"]["seeds"]))
    overlapping = [committed_seed, *high_entropy[1:]]
    monkeypatch.setenv(commitment_mod.PRIVATE_SEEDS_ENV, ",".join(str(seed) for seed in overlapping))
    assert commitment_mod.main(["execution-hash", "--lane", str(lane)]) == 2


def test_generate_private_panel_is_uniform_ordered_and_public_output_hides_seeds(tmp_path, monkeypatch, capsys):
    lane = tmp_path / "lane.json"
    lane.write_text(
        json.dumps(
            {
                "seed_panel": {
                    "status": "pending-authorized-generation",
                    "count": 3,
                }
            }
        )
    )
    draws = iter([7, 7, 11, 13])
    monkeypatch.setattr(commitment_mod.secrets, "randbelow", lambda _span: next(draws))
    monkeypatch.setattr(commitment_mod.secrets, "token_hex", lambda _count: "ab" * 32)
    secret_file = tmp_path / "private-panel.json"

    assert (
        commitment_mod.main(
            [
                "generate",
                "--lane",
                str(lane),
                "--secret-file",
                str(secret_file),
            ]
        )
        == 0
    )

    record = json.loads(secret_file.read_text())
    expected = [
        commitment_mod._PRIVATE_SEED_MIN + 7,
        commitment_mod._PRIVATE_SEED_MIN + 11,
        commitment_mod._PRIVATE_SEED_MIN + 13,
    ]
    assert record["seeds"] == ",".join(str(seed) for seed in expected)
    assert record["generation_method"] == commitment_mod._GENERATION_METHOD
    assert record["execution_sha256"] == commitment_mod.seed_panel_hash(expected)
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600

    public = json.loads(capsys.readouterr().out)
    assert public["count"] == 3
    assert public["seed_values_included"] is False
    assert public["sha256"] == record["execution_sha256"]
    assert all(str(seed) not in json.dumps(public) for seed in expected)


def test_generate_private_panel_requires_pending_lane_and_refuses_clobber(tmp_path, monkeypatch):
    lane = tmp_path / "lane.json"
    lane.write_text(json.dumps({"seed_panel": {"status": "pending-authorized-generation", "count": 2}}))
    draws = iter([1, 2, 3, 4])
    monkeypatch.setattr(commitment_mod.secrets, "randbelow", lambda _span: next(draws))
    monkeypatch.setattr(commitment_mod.secrets, "token_hex", lambda _count: "cd" * 32)
    secret_file = tmp_path / "private-panel.json"
    args = ["generate", "--lane", str(lane), "--secret-file", str(secret_file)]

    assert commitment_mod.main(args) == 0
    original = secret_file.read_bytes()
    assert commitment_mod.main(args) == 2
    assert secret_file.read_bytes() == original

    lane.write_text(json.dumps({"seed_panel": {"status": "frozen", "count": 2}}))
    assert commitment_mod.main(["generate", "--lane", str(lane), "--secret-file", str(tmp_path / "other")]) == 2


def test_generate_private_panel_refuses_secret_path_inside_checkout(tmp_path):
    lane = tmp_path / "lane.json"
    lane.write_text(json.dumps({"seed_panel": {"status": "pending-authorized-generation", "count": 2}}))
    secret_file = commitment_mod._ROOT / "data" / "private-panel-must-not-exist.json"

    assert commitment_mod.main(["generate", "--lane", str(lane), "--secret-file", str(secret_file)]) == 2
    assert not secret_file.exists()
