"""The GM-Bench 2.0 private panel commitment and its Keychain launcher."""

from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_bench_v2_panel_from_keychain as launcher
from gm_bench import cli
from gm_bench.agentic import opencode as opencode_driver
from gm_bench.agentic.publication import PANEL_MIN_SEEDS, seed_panel_sha256
from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, seed_panel_hash
from scripts.seed_panel_commitment import commitment

REPO = Path(__file__).resolve().parents[1]
SERVICE = "gm-bench-bench-v2-private-panel"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _committed(name: str) -> dict:
    return json.loads((REPO / "config" / name).read_text())


# -- the committed lane -------------------------------------------------------


def test_committed_lane_freezes_a_32_seed_private_panel_that_extends_sota_v5() -> None:
    lane = _committed("bench_v2_lane.json")
    v5 = _committed("sota_v5_lane.json")["seed_panel"]
    panel = lane["seed_panel"]
    lineage = panel["lineage"]

    assert panel["status"] == "frozen" and panel["name"] == "private-env"
    assert panel["count"] == 32 == lane["panel_design"]["full_row"]["seeds"] == PANEL_MIN_SEEDS
    assert lane["panel_design"]["full_row"]["seasons"] == launcher.PANEL_SEASONS
    for key in ("sha256", "artifact_panel_sha256", "hiding_commitment_sha256"):
        assert _HEX64.match(panel[key]), key
    assert len({panel["sha256"], panel["artifact_panel_sha256"], panel["hiding_commitment_sha256"]}) == 3
    assert panel["generation_method"] == v5["generation_method"]
    assert launcher.keychain_service(lane) == SERVICE
    assert panel["secret_escrow"] not in {v5["secret_escrow"], v5["retired_commitment"]["secret_escrow"]}
    assert lineage["shared_prefix_count"] == v5["count"] == 29
    assert lineage["shared_prefix_sha256"] == v5["sha256"]
    assert lineage["shared_prefix_escrow"] == v5["secret_escrow"]
    assert lineage["shared_prefix_count"] + lineage["new_seed_count"] == panel["count"]
    assert panel["seed_values_included"] is False
    assert panel["owner_attestation_required"] is True


def test_committed_lane_carries_no_private_seed_sized_integer() -> None:
    text = (REPO / "config" / "bench_v2_lane.json").read_text()
    assert not [token for token in re.findall(r"(?<![0-9a-f])\d{10,}(?![0-9a-f])", text)]


# -- the launcher -------------------------------------------------------------


def _seeds() -> list[int]:
    return [(1 << 50) + index * 104729 for index in range(32)]


def _install_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, v5_sha: str | None = None, **overrides):
    seeds = _seeds()
    seeds_text = ",".join(str(seed) for seed in seeds)
    salt = "cd" * 32
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    panel = {
        "status": "frozen",
        "name": "private-env",
        "count": 32,
        "sha256": seed_panel_hash(seeds),
        "artifact_panel_sha256": seed_panel_sha256(seeds),
        "hiding_commitment_sha256": commitment(salt, seeds),
        "secret_escrow": f"macos-keychain:{SERVICE}",
        "lineage": {"shared_prefix_count": 29, "shared_prefix_sha256": seed_panel_hash(seeds[:29])},
        "owner_attestation_required": True,
        "owner_attestation_status": "attested-before-seed-access",
    }
    panel.update(overrides)
    (root / "config" / "bench_v2_lane.json").write_text(json.dumps({"seed_panel": panel}))
    v5_panel = {"count": 29, "sha256": v5_sha or seed_panel_hash(seeds[:29])}
    (root / "config" / "sota_v5_lane.json").write_text(json.dumps({"seed_panel": v5_panel}))
    record = {"format": "gm-bench-private-seed-secret-v1", "seeds": seeds_text, "salt": salt}
    commands: list[list[str]] = []

    def fake_run(args, **_kwargs):
        commands.append(list(args))
        return SimpleNamespace(stdout=json.dumps(record, indent=2).encode().hex() + "\n")

    monkeypatch.delenv(PRIVATE_SEEDS_ENV, raising=False)
    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    return seeds_text, commands


def test_launcher_reads_the_named_escrow_and_verifies_every_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected, commands = _install_fixture(tmp_path, monkeypatch)

    assert launcher.verified_seed_text(launcher._lane(), launcher._shared_lane()) == expected
    assert commands == [["security", "find-generic-password", "-s", SERVICE, "-a", launcher.KEYCHAIN_ACCOUNT, "-w"]]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"hiding_commitment_sha256": "0" * 64}, "hiding commitment"),
        ({"sha256": "0" * 64}, "execution hash"),
        ({"count": 31}, "execution hash"),
        ({"artifact_panel_sha256": "0" * 64}, "artifact panel hash"),
        ({"lineage": {"shared_prefix_count": 28, "shared_prefix_sha256": "0" * 64}}, "sota-v5 panel"),
        ({"owner_attestation_status": "pending-owner-attestation"}, "owner attestation"),
        ({"secret_escrow": "file:/tmp/seeds.json"}, "Keychain escrow"),
        ({"status": "pending"}, "frozen private panel"),
    ],
)
def test_launcher_refuses_an_escrow_that_does_not_match_the_commitment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: dict, message: str
) -> None:
    _install_fixture(tmp_path, monkeypatch, **override)

    with pytest.raises(ValueError, match=message):
        launcher.verified_seed_text(launcher._lane(), launcher._shared_lane())


def test_launcher_refuses_a_prefix_that_is_not_the_committed_sota_v5_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fixture(tmp_path, monkeypatch, v5_sha="1" * 64)

    with pytest.raises(ValueError, match="sota-v5 panel"):
        launcher.verified_seed_text(launcher._lane(), launcher._shared_lane())


def _capture_cli(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_main(argv):
        calls.append({"argv": list(argv), "stdin": sys.stdin.read(), "env": dict(os.environ)})

    monkeypatch.setattr(cli, "main", fake_main)
    return calls


def test_launcher_runs_the_agentic_cli_with_seeds_on_stdin_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeds_text, commands = _install_fixture(tmp_path, monkeypatch)
    calls = _capture_cli(monkeypatch)
    stdin_before = sys.stdin
    output = tmp_path / "run"

    assert (
        launcher.main(["--model", "opencode/big-pickle", "--output", str(output), "--variant", "low", "--isolation-x"])
        == 0
    )

    (call,) = calls
    assert call["stdin"] == seeds_text
    assert call["argv"] == [
        "agentic",
        "--seeds-stdin",
        "--model",
        "opencode/big-pickle",
        "--output",
        str(output),
        "--seasons",
        "5",
        "--variant",
        "low",
        "--isolation-x",
    ]
    seeds = seeds_text.split(",")
    for argv in [call["argv"], sys.argv, *commands]:
        assert not any(seed in arg for seed in seeds for arg in argv)
    assert not any(seed in value for seed in seeds for value in call["env"].values())
    assert sys.stdin is stdin_before


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--seeds", "1"], "not allowed"),
        (["--seeds=1"], "not allowed"),
        (["--json"], "not allowed"),
    ],
)
def test_launcher_refuses_passthrough_that_would_expose_seeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str], message: str
) -> None:
    _install_fixture(tmp_path, monkeypatch)
    calls = _capture_cli(monkeypatch)

    with pytest.raises(ValueError, match=message):
        launcher.main(["--model", "m", "--output", str(tmp_path / "run"), *extra])
    assert calls == []


def test_launcher_refuses_before_running_when_the_escrow_does_not_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fixture(tmp_path, monkeypatch, hiding_commitment_sha256="0" * 64)
    calls = _capture_cli(monkeypatch)

    with pytest.raises(ValueError, match="hiding commitment"):
        launcher.main(["--model", "m", "--output", str(tmp_path / "run")])
    assert calls == []


def test_launcher_refuses_inherited_seed_env_bad_output_and_other_season_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fixture(tmp_path, monkeypatch)
    calls = _capture_cli(monkeypatch)
    used = tmp_path / "used"
    used.mkdir()
    (used / "run.json").write_text("{}")

    with pytest.raises(ValueError, match="empty directory"):
        launcher.main(["--model", "m", "--output", str(used)])
    with pytest.raises(ValueError, match="inside the checkout"):
        launcher.main(["--model", "m", "--output", str(launcher.ROOT / "data" / "run")])
    with pytest.raises(SystemExit):
        launcher.main(["--model", "m", "--output", str(tmp_path / "run"), "--seasons", "3"])
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "1,2,3")
    with pytest.raises(ValueError, match="must be unset"):
        launcher.main(["--model", "m", "--output", str(tmp_path / "run")])
    assert calls == []


def test_verify_only_prints_no_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seeds_text, _ = _install_fixture(tmp_path, monkeypatch, owner_attestation_status="pending-owner-attestation")

    assert launcher.main(["--verify-only"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["status"] == "escrow-matches-commitment"
    assert not any(seed in out for seed in seeds_text.split(","))


# -- gm-bench agentic --seeds-stdin ------------------------------------------


def test_agentic_cli_reads_seeds_from_stdin_and_keeps_them_out_of_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    private = [(1 << 40) + 7, (1 << 40) + 11]
    seen: dict = {}

    def fake_run_panel(seeds, *, progress, run_dir, **kwargs):
        seen["seeds"] = list(seeds)
        seen["by_position"] = kwargs["name_episodes_by_position"]
        for seed in seeds:
            progress({"seed": seed, "stage": "done", "final_score": 1.0})
        return {
            "agent": "opencode:m",
            "harness": {"name": "opencode", "version": "x"},
            "seeds": list(seeds),
            "summary": {"mean_score": 1.0, "illegal_actions": 0, "failed_decisions": 0, "decisions": 1, "usage": {}},
            "agentic_summary": {},
        }

    monkeypatch.setattr(opencode_driver, "run_panel", fake_run_panel)
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{private[0]},\n{private[1]}\n"))

    cli.main(["agentic", "--seeds-stdin", "--model", "m", "--output", str(tmp_path / "run")])

    assert seen["seeds"] == private
    assert seen["by_position"] is True
    captured = capsys.readouterr()
    assert not any(str(seed) in captured.out + captured.err for seed in private)
    assert [json.loads(line)["seed_group"] for line in captured.err.splitlines()] == [0, 1]


def test_agentic_cli_refuses_json_or_both_seed_sources_with_stdin_seeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(opencode_driver, "run_panel", lambda *a, **k: pytest.fail("must not run"))
    monkeypatch.setattr(sys, "stdin", io.StringIO("4294967297"))
    base = ["agentic", "--model", "m", "--output", str(tmp_path / "run")]

    with pytest.raises(SystemExit, match="--json"):
        cli.main([*base, "--seeds-stdin", "--json"])
    with pytest.raises(SystemExit):
        cli.main([*base, "--seeds-stdin", "--seeds", "11"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("  \n"))
    with pytest.raises(SystemExit, match="no seeds"):
        cli.main([*base, "--seeds-stdin"])


def test_agentic_cli_keeps_seed_named_episode_directories_for_public_seeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def fake_run_panel(seeds, **kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(opencode_driver, "run_panel", fake_run_panel)
    with pytest.raises(SystemExit):
        cli.main(["agentic", "--seeds", "11", "--model", "m", "--output", str(tmp_path / "run")])
    assert seen["name_episodes_by_position"] is False


def test_run_panel_names_episode_directories_by_position_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs: list[str] = []

    def fake_run_episode(seed, *, run_dir, episode_dir, **kwargs):
        dirs.append(str(episode_dir.relative_to(run_dir)))
        return {"seed": seed}

    monkeypatch.setattr(opencode_driver, "run_episode", fake_run_episode)
    monkeypatch.setattr(opencode_driver, "opencode_version", lambda binary: "x")
    monkeypatch.setattr(opencode_driver, "summarize_episodes", lambda episodes: {})
    monkeypatch.setattr(opencode_driver, "_agentic_summary", lambda episodes: {})
    private = [(1 << 40) + 7, (1 << 40) + 11, (1 << 40) + 7]

    opencode_driver.run_panel(private, model="m", run_dir=tmp_path / "a", name_episodes_by_position=True)
    assert dirs == ["episode-00", "episode-01", "episode-02"]

    dirs.clear()
    opencode_driver.run_panel([11, 12, 11], model="m", run_dir=tmp_path / "b")
    assert dirs == ["seed-11", "seed-12", "seed-11-r2"]
