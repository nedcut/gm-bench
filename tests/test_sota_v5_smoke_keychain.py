from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.run_sota_v3_smoke_from_keychain as launcher
from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, seed_panel_hash
from scripts.seed_panel_commitment import commitment


def _install_v5_keychain_fixture(tmp_path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, list[list[str]]]:
    seeds = [(1 << 50) + index * 104729 for index in range(16)]
    seeds_text = ",".join(str(seed) for seed in seeds)
    salt = "ef" * 32
    config = tmp_path / "config"
    config.mkdir()
    (config / "sota_v5_lane.json").write_text(
        json.dumps(
            {
                "seed_panel": {
                    "status": "frozen",
                    "name": "private-env",
                    "count": len(seeds),
                    "sha256": seed_panel_hash(seeds),
                    "hiding_commitment_sha256": commitment(salt, seeds),
                    "secret_escrow": "macos-keychain:gm-bench-sota-v3-private-panel",
                    "lineage_chain": ["sota-v3", "sota-v4", "sota-v5"],
                }
            }
        )
    )
    record = {"format": "gm-bench-private-seed-secret-v1", "seeds": seeds_text, "salt": salt}
    commands: list[list[str]] = []

    def fake_run(args, **_kwargs):
        commands.append(list(args))
        return SimpleNamespace(stdout=json.dumps(record).encode().hex() + "\n")

    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    return seeds_text, commands


def test_v5_launcher_reuses_and_verifies_the_original_seed_escrow(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected, commands = _install_v5_keychain_fixture(tmp_path, monkeypatch)

    assert launcher._verified_seed_text("sota-v5") == expected
    assert commands[0][commands[0].index("-s") + 1] == launcher.KEYCHAIN_SERVICE
    assert launcher.KEYCHAIN_SERVICES["sota-v5"] == launcher.KEYCHAIN_SERVICE
    assert launcher.ROUTE_ACCEPTANCE_CHECKS["sota-v5"] is launcher.v5_route_acceptance_issues


def test_v5_launcher_selects_only_the_v5_runner_lane_without_reading_private_seeds(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _expected, commands = _install_v5_keychain_fixture(tmp_path, monkeypatch)
    observed: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(
        launcher,
        "publication_main",
        lambda argv: observed.append((argv, launcher.os.environ.get(PRIVATE_SEEDS_ENV))) or 0,
    )

    assert launcher.main(["--contract", "sota-v5", "--max-spend-usd", "10", "--dry-run"]) == 0

    assert observed[0][0][:3] == ["smoke", "--contract", "sota-v5"]
    assert observed[0][1] is None
    assert commands == []
    assert PRIVATE_SEEDS_ENV not in launcher.os.environ
    run_dir_index = observed[0][0].index("--run-dir") + 1
    assert observed[0][0][run_dir_index].endswith("data/publication/sota-v5-smokes")


def test_v5_readiness_records_seed_free_smoke_command_dry_run(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_v5_keychain_fixture(tmp_path, monkeypatch)
    config = tmp_path / "config"
    lane_path = config / "sota_v5_lane.json"
    lane = json.loads(lane_path.read_text())
    lane["contract_fingerprint"] = "v5-fingerprint"
    lane_path.write_text(json.dumps(lane))
    route_path = tmp_path / "results" / "analysis" / "sota-v5-route.json"
    route_path.parent.mkdir(parents=True)
    route_path.write_text(
        json.dumps(
            {
                "format": "gm-bench-route-acceptance-evidence-v1",
                "contract": "sota-v5",
                "generated_at_utc": "2026-08-16T00:00:00+00:00",
                "completion_calls": 0,
            }
        )
    )
    (config / "sota_v5_models.json").write_text(
        json.dumps(
            {
                "contract_fingerprint": "v5-fingerprint",
                "models": [{"id": "model-v5"}],
                "exact_route_acceptance": {"evidence_artifact": "results/analysis/sota-v5-route.json"},
            }
        )
    )
    readiness = tmp_path / "results" / "analysis" / "sota-v5-final.json"
    monkeypatch.setattr(launcher, "contract_fingerprint", lambda: "v5-fingerprint")
    monkeypatch.setitem(launcher.ROUTE_ACCEPTANCE_CHECKS, "sota-v5", lambda _registry: [])

    launcher._record_readiness(readiness, contract="sota-v5", max_spend_usd=10.0, mode="dry-run")

    evidence = json.loads(readiness.read_text())
    dry_run = evidence["smoke_command_dry_run"]
    assert "keychain_dry_run" not in evidence
    assert dry_run["private_seed_accessed"] is False
    assert dry_run["hiding_commitment_verified"] is False
    assert dry_run["private_seed_values_included"] is False
