from __future__ import annotations

import json
from pathlib import Path

from gm_bench.publication import canonical_sha256
from scripts.package_publication_release import build_release, verify_archive


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _release_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    run_dir = tmp_path / "run"
    registry = {
        "contract": "sota-v2",
        "output_token_cap": 4096,
        "models": [
            {
                "id": "demo",
                "provider": "openrouter",
                "model": "demo/model",
                "upstream_provider": "Demo",
            }
        ],
    }
    raw = {
        "candidate": {
            "summary": {
                "decisions": 4,
                "mean_score": 12.5,
                "usage": {
                    "decisions_with_usage": 4,
                    "cost_decisions": 4,
                    "cost_usd": 0.01,
                },
            }
        }
    }
    analysis = {
        "models": [{"model_id": "demo"}],
        "rejected_artifacts": [],
    }
    _write_json(repo / "config/sota_v2_models.json", registry)
    for name in ("sota_v2_lane.json", "publication_protocol.json", "sota_v2_smoke_manifest.json"):
        _write_json(repo / "config" / name, {"fixture": True})
    _write_json(repo / "results/analysis/publication-panel-analysis.json", analysis)
    _write_json(
        repo / "results/leaderboard/demo.json",
        {"publication": {"raw_artifact_sha256": canonical_sha256(raw)}},
    )
    _write_json(run_dir / "raw/demo--4096.json", raw)
    _write_json(run_dir / "run-state.json", {"phase": "panel"})
    return repo, run_dir


def test_release_archive_is_deterministic_and_verifiable(tmp_path: Path) -> None:
    repo, run_dir = _release_fixture(tmp_path)
    archive = tmp_path / "release.zip"
    generated: list[bytes] = []
    for _ in range(2):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=archive,
            manifest_path=tmp_path / "manifest.json",
            checksums_path=tmp_path / "SHA256SUMS.txt",
        )
        generated.append(archive.read_bytes())

    assert generated[0] == generated[1]
    manifest = verify_archive(archive, repo_root=repo)
    assert manifest["eligible_headline_models"] == 1
    assert manifest["diagnostic_models"] == 0
    assert manifest["artifacts"][0]["compact_artifact"] == "results/leaderboard/demo.json"


def test_release_build_rejects_compact_raw_hash_mismatch(tmp_path: Path) -> None:
    repo, run_dir = _release_fixture(tmp_path)
    _write_json(repo / "results/leaderboard/demo.json", {"publication": {"raw_artifact_sha256": "0" * 64}})

    try:
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release.zip",
            manifest_path=tmp_path / "manifest.json",
            checksums_path=tmp_path / "SHA256SUMS.txt",
        )
    except ValueError as exc:
        assert "does not hash-link" in str(exc)
    else:
        raise AssertionError("expected compact/raw mismatch to fail")
