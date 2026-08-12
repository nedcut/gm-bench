from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.run_sota_v3_smoke_from_keychain as launcher
from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, seed_panel_hash
from scripts.seed_panel_commitment import commitment


def _install_v4_keychain_fixture(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    seeds = [(1 << 50) + index * 104729 for index in range(16)]
    seeds_text = ",".join(str(seed) for seed in seeds)
    salt = "cd" * 32
    config = tmp_path / "config"
    config.mkdir()
    (config / "sota_v4_lane.json").write_text(
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
    record = {"format": "gm-bench-private-seed-secret-v1", "seeds": seeds_text, "salt": salt}
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(record).encode().hex() + "\n"),
    )
    return seeds_text


def test_v4_launcher_verifies_the_carried_forward_private_panel(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _install_v4_keychain_fixture(tmp_path, monkeypatch)

    assert launcher._verified_seed_text("sota-v4") == expected
    assert launcher.ROUTE_ACCEPTANCE_CHECKS["sota-v4"] is launcher.v4_route_acceptance_issues


def test_v4_launcher_selects_only_the_v4_runner_lane(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _install_v4_keychain_fixture(tmp_path, monkeypatch)
    observed: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(
        launcher,
        "publication_main",
        lambda argv: observed.append((argv, launcher.os.environ.get(PRIVATE_SEEDS_ENV))) or 0,
    )

    assert launcher.main(["--contract", "sota-v4", "--max-spend-usd", "100", "--dry-run"]) == 0

    assert observed[0][0][:3] == ["smoke", "--contract", "sota-v4"]
    assert observed[0][1] == expected
    assert PRIVATE_SEEDS_ENV not in launcher.os.environ
    run_dir_index = observed[0][0].index("--run-dir") + 1
    assert observed[0][0][run_dir_index].endswith("data/publication/sota-v4-smokes")
