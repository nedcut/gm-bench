from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.collect_sota_v3_route_evidence as collector


def test_route_evidence_http_client_rejects_non_api_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    accessed: list[str] = []
    monkeypatch.setattr(
        collector.http.client,
        "HTTPSConnection",
        lambda *_args, **_kwargs: accessed.append("called"),
    )

    for path in (
        "file:///etc/passwd",
        "https://example.com/api/v1/providers",
        "//example.com/api/v1/providers",
        "/not-api/providers",
        "/api/v1/providers?unexpected=query",
    ):
        with pytest.raises(ValueError, match="refusing non-OpenRouter metadata path"):
            collector._get_json(path, {})
    assert accessed == []


@pytest.mark.parametrize("option", ["--registry", "--output"])
def test_route_evidence_cli_rejects_paths_outside_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    option: str,
) -> None:
    accessed: list[str] = []
    monkeypatch.setattr(
        collector.http.client,
        "HTTPSConnection",
        lambda *_args, **_kwargs: accessed.append("called"),
    )

    with pytest.raises(SystemExit):
        collector.main([option, str(tmp_path / "outside.json")])
    assert accessed == []


def test_v4_route_evidence_defaults_cannot_overwrite_v3(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    registry = config / "sota_v4_models.json"
    registry.write_text(json.dumps({"contract": "sota-v4", "models": []}))
    monkeypatch.setattr(collector, "ROOT", tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(
        collector,
        "collect",
        lambda payload, _headers: {
            "contract": payload["contract"],
            "generated_at_utc": "2026-08-12T00:00:00+00:00",
            "completion_calls": 0,
            "routes": {},
        },
    )

    assert collector.main(["--contract", "sota-v4"]) == 0
    assert (tmp_path / "results" / "analysis" / "sota-v4-route-acceptance-evidence.json").exists()
    assert not (tmp_path / "results" / "analysis" / "sota-v3-route-acceptance-evidence.json").exists()


def test_route_evidence_rejects_registry_contract_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    registry = config / "sota_v4_models.json"
    registry.write_text(json.dumps({"contract": "sota-v3", "models": []}))
    monkeypatch.setattr(collector, "ROOT", tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    with pytest.raises(SystemExit):
        collector.main(["--contract", "sota-v4"])
