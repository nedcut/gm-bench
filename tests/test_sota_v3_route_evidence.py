from __future__ import annotations

import pytest

import scripts.collect_sota_v3_route_evidence as collector


def test_route_evidence_http_client_rejects_non_openrouter_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    accessed: list[str] = []
    monkeypatch.setattr(
        collector.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: accessed.append("called"),
    )

    for url in (
        "file:///etc/passwd",
        "https://example.com/api/v1/providers",
        "http://openrouter.ai/api/v1/providers",
        "https://openrouter.ai/not-api/providers",
    ):
        with pytest.raises(ValueError, match="refusing non-OpenRouter metadata URL"):
            collector._get_json(url, {})
    assert accessed == []
