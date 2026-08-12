from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import gm_bench.contract as contract_module
import gm_bench.publication as publication
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
    (config / "sota_v3_publication_protocol.json").write_text(
        json.dumps({"budget_policy": {"operator_ceiling_usd": 100.0}})
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

    assert launcher.main(["--max-spend-usd", "100", "--dry-run"]) == 0
    assert observed[0][1] == expected
    assert PRIVATE_SEEDS_ENV not in launcher.os.environ
    assert observed[0][0][:3] == ["smoke", "--contract", "sota-v3"]


@pytest.mark.parametrize("modes", [("--dry-run", "--preflight-only"), ("--preflight-only", "--dry-run")])
def test_keychain_launcher_records_final_fingerprint_readiness(
    tmp_path, monkeypatch: pytest.MonkeyPatch, modes: tuple[str, str]
) -> None:
    _install_keychain_fixture(tmp_path, monkeypatch)
    fingerprint = "final-fingerprint"
    lane_path = tmp_path / "config" / "sota_v3_lane.json"
    lane = json.loads(lane_path.read_text())
    lane["contract_fingerprint"] = fingerprint
    lane_path.write_text(json.dumps(lane))
    route_path = tmp_path / "results" / "analysis" / "route.json"
    route_path.parent.mkdir(parents=True)
    route = {
        "format": "gm-bench-route-acceptance-evidence-v1",
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "completion_calls": 0,
        "generated_at_utc": "2026-08-11T12:00:00+00:00",
    }
    route_path.write_text(json.dumps(route))
    (tmp_path / "config" / "sota_v3_models.json").write_text(
        json.dumps(
            {
                "contract_fingerprint": fingerprint,
                "models": [{"id": "model-a"}, {"id": "model-b"}],
                "exact_route_acceptance": {
                    "evidence_artifact": "results/analysis/route.json",
                    "accepted_at_utc": route["generated_at_utc"],
                },
            }
        )
    )
    monkeypatch.setattr(launcher, "contract_fingerprint", lambda: fingerprint)
    monkeypatch.setitem(launcher.ROUTE_ACCEPTANCE_CHECKS, "sota-v3", lambda _registry: [])
    monkeypatch.setattr(launcher, "publication_main", lambda _argv: 0)

    for mode in modes:
        assert (
            launcher.main(
                [
                    "--max-spend-usd",
                    "100",
                    mode,
                    "--record-readiness",
                    "results/analysis/final-preflight.json",
                ]
            )
            == 0
        )

    evidence = json.loads((tmp_path / "results" / "analysis" / "final-preflight.json").read_text())
    updated_lane = json.loads(lane_path.read_text())
    assert evidence["contract_fingerprint"] == fingerprint
    assert evidence["openrouter_scaffold_fingerprint"] == launcher.scaffold_fingerprint("openrouter")
    assert evidence["completion_calls"] == 0
    assert evidence["keychain_dry_run"]["model_ids"] == ["model-a", "model-b"]
    assert evidence["keychain_dry_run"]["private_seed_values_included"] is False
    assert evidence["keychain_dry_run"]["operator_ceiling_usd"] == 100
    assert evidence["authenticated_route_and_price_preflight"]["pricing_checked"] is True
    assert updated_lane["final_preflight_evidence"]["status"] == "accepted"
    assert updated_lane["final_preflight_evidence"]["contract_fingerprint"] == fingerprint
    assert updated_lane["final_preflight_evidence"]["operator_ceiling_usd"] == 100
    registry = json.loads((tmp_path / "config" / "sota_v3_models.json").read_text())
    protocol = json.loads((tmp_path / "config" / "sota_v3_publication_protocol.json").read_text())
    monkeypatch.setattr(publication, "_REPO_ROOT", tmp_path)
    assert publication.v3_final_preflight_issues(updated_lane, registry, protocol) == []
    monkeypatch.setattr(contract_module, "scaffold_fingerprint", lambda _provider: "future-scaffold")
    assert publication.v3_final_preflight_issues(updated_lane, registry, protocol) == []

    evidence["authenticated_route_and_price_preflight"]["pricing_checked"] = False
    (tmp_path / "results" / "analysis" / "final-preflight.json").write_text(json.dumps(evidence))
    updated_lane["final_preflight_evidence"]["sha256"] = publication.canonical_sha256(evidence)
    assert "live route pricing" in " ".join(publication.v3_final_preflight_issues(updated_lane, registry, protocol))

    evidence["authenticated_route_and_price_preflight"]["pricing_checked"] = True
    (tmp_path / "results" / "analysis" / "final-preflight.json").write_text(json.dumps(evidence))
    updated_lane["final_preflight_evidence"]["sha256"] = publication.canonical_sha256(evidence)
    protocol["budget_policy"]["operator_ceiling_usd"] = 90.0
    assert "protocol operator ceiling" in " ".join(
        publication.v3_final_preflight_issues(updated_lane, registry, protocol)
    )
