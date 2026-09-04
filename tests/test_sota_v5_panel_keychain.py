from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_sota_v5_panel_from_keychain as launcher
from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, seed_panel_hash
from scripts.seed_panel_commitment import commitment

SERVICE = "gm-bench-sota-v5-v6-private-panel"


def _install_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: object
) -> tuple[str, list[list[str]]]:
    seeds = [(1 << 50) + index * 104729 for index in range(29)]
    seeds_text = ",".join(str(seed) for seed in seeds)
    salt = "ab" * 32
    config = tmp_path / "config"
    config.mkdir()
    panel = {
        "status": "frozen",
        "name": "private-env",
        "count": len(seeds),
        "sha256": seed_panel_hash(seeds),
        "hiding_commitment_sha256": commitment(salt, seeds),
        "secret_escrow": f"macos-keychain:{SERVICE}",
        "owner_attestation_required": True,
        "owner_attestation_status": "attested-before-seed-access",
    }
    panel.update(overrides)
    (config / "sota_v5_lane.json").write_text(json.dumps({"seed_panel": panel}))
    record = {"format": "gm-bench-private-seed-secret-v1", "seeds": seeds_text, "salt": salt}
    commands: list[list[str]] = []

    def fake_run(args, **_kwargs):
        commands.append(list(args))
        return SimpleNamespace(stdout=json.dumps(record).encode().hex() + "\n")

    monkeypatch.delenv(PRIVATE_SEEDS_ENV, raising=False)
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "DEFAULT_RUN_DIR", tmp_path / "data" / "publication" / "sota-v5-panel")
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    return seeds_text, commands


def test_panel_launcher_reads_the_escrow_named_by_the_lane_and_verifies_both_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected, commands = _install_fixture(tmp_path, monkeypatch)

    assert launcher.verified_seed_text(launcher._lane()) == expected
    assert commands[0][commands[0].index("-s") + 1] == SERVICE
    assert commands[0][commands[0].index("-a") + 1] == launcher.KEYCHAIN_ACCOUNT


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"hiding_commitment_sha256": "0" * 64}, "hiding commitment"),
        ({"sha256": "0" * 64}, "execution hash"),
        ({"count": 28}, "execution hash"),
        ({"owner_attestation_status": "pending"}, "owner attestation"),
        ({"secret_escrow": "file:/tmp/seeds.json"}, "Keychain escrow"),
    ],
)
def test_panel_launcher_refuses_seeds_that_do_not_match_the_commitment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: dict[str, object], message: str
) -> None:
    _install_fixture(tmp_path, monkeypatch, **override)

    with pytest.raises(ValueError, match=message):
        launcher.verified_seed_text(launcher._lane())


def test_panel_launcher_hands_verified_seeds_to_the_panel_phase_only_for_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected, _commands = _install_fixture(tmp_path, monkeypatch)
    observed: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(
        launcher,
        "publication_main",
        lambda argv: observed.append((argv, launcher.os.environ.get(PRIVATE_SEEDS_ENV))) or 0,
    )

    assert launcher.main(["--max-spend-usd", "100", "--dry-run"]) == 0

    argv, seeds_during_run = observed[0]
    assert argv[:3] == ["panel", "--contract", "sota-v5"]
    assert argv[argv.index("--run-dir") + 1].endswith("data/publication/sota-v5-panel")
    assert argv[argv.index("--max-spend-usd") + 1] == "100.0"
    assert argv[-1] == "--dry-run"
    assert seeds_during_run == expected
    assert PRIVATE_SEEDS_ENV not in launcher.os.environ


def test_panel_launcher_refuses_inherited_private_seeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _expected, commands = _install_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "must-not-be-used")
    monkeypatch.setattr(launcher, "publication_main", lambda argv: pytest.fail("runner must not start"))

    with pytest.raises(ValueError, match="must be unset"):
        launcher.main(["--max-spend-usd", "100", "--dry-run"])

    assert commands == []
    assert launcher.os.environ[PRIVATE_SEEDS_ENV] == "must-not-be-used"


def test_panel_launcher_refuses_a_run_directory_holding_smoke_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fixture(tmp_path, monkeypatch)
    run_dir = tmp_path / "data" / "publication" / "sota-v5-smokes-v2"
    run_dir.mkdir(parents=True)
    (run_dir / "run-state.json").write_text(json.dumps({"phase": "smoke"}))
    monkeypatch.setattr(launcher, "publication_main", lambda argv: pytest.fail("runner must not start"))

    with pytest.raises(ValueError, match="own run directory"):
        launcher.main(["--max-spend-usd", "100", "--dry-run", "--run-dir", str(run_dir)])

    (run_dir / "run-state.json").write_text(json.dumps({"phase": "panel"}))
    monkeypatch.setattr(launcher, "publication_main", lambda argv: 0)
    assert launcher.main(["--max-spend-usd", "100", "--dry-run", "--run-dir", str(run_dir)]) == 0


def test_committed_lane_names_the_v6_escrow_not_the_retired_v3_one() -> None:
    lane = json.loads(Path("config/sota_v5_lane.json").read_text())

    assert launcher.keychain_service(lane) == SERVICE
    assert lane["seed_panel"]["retired_commitment"]["secret_escrow"] != lane["seed_panel"]["secret_escrow"]
