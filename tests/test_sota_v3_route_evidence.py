from __future__ import annotations

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
