from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.run_sota_v3_smoke_from_keychain as launcher
from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, seed_panel_hash
from scripts.seed_panel_commitment import commitment


def _install_keychain_fixture(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    seeds = [(1 << 50) + index * 104729 for index in range(16)]
    seeds_text = ",".join(str(seed) for seed in seeds)
    salt = "ab" * 32
    record = {
        "format": "gm-bench-private-seed-secret-v1",
        "seeds": seeds_text,
        "salt": salt,
    }
    config = tmp_path / "config"
    config.mkdir()
    (config / "sota_v3_lane.json").write_text(
        json.dumps(
            {
                "seed_panel": {
                    "status": "frozen",
                    "name": "private-env",
                    "count": len(seeds),
                    "sha256": seed_panel_hash(seeds),
                    "hiding_commitment_sha256": commitment(salt, seeds),
                }
            }
        )
    )
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(record).encode().hex() + "\n"),
    )
    return seeds_text


def test_keychain_launcher_verifies_hex_encoded_private_panel(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _install_keychain_fixture(tmp_path, monkeypatch)
    assert launcher._verified_seed_text() == expected


def test_keychain_launcher_sets_seed_env_only_for_runner(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _install_keychain_fixture(tmp_path, monkeypatch)
    observed: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(
        launcher,
        "publication_main",
        lambda argv: observed.append((argv, launcher.os.environ.get(PRIVATE_SEEDS_ENV))) or 0,
    )

    assert launcher.main(["--max-spend-usd", "150", "--dry-run"]) == 0
    assert observed[0][1] == expected
    assert PRIVATE_SEEDS_ENV not in launcher.os.environ
    assert observed[0][0][:3] == ["smoke", "--contract", "sota-v3"]
