from __future__ import annotations

import json

from examples import gemini_agent


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return json.dumps(
            {
                "modelVersion": "gemini-3.5-flash",
                "candidates": [{"content": {"parts": [{"text": '{"actions":[{"type":"noop"}]}'}]}}],
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "candidatesTokenCount": 8,
                    "thoughtsTokenCount": 22,
                    "totalTokenCount": 150,
                },
            }
        ).encode()


def test_choose_actions_uses_native_api_and_counts_thinking_as_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, **kwargs: object) -> _Response:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = kwargs["timeout"]
        return _Response()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    monkeypatch.setattr(gemini_agent.urllib.request, "urlopen", fake_urlopen)

    actions, usage = gemini_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})

    assert actions == [{"type": "noop"}]
    assert captured["url"].endswith("/models/gemini-3.5-flash:generateContent")
    assert captured["headers"]["X-goog-api-key"] == "test-key"
    assert captured["payload"]["generationConfig"]["responseMimeType"] == "application/json"
    assert usage == {
        "provider": "gemini",
        "model": "gemini-3.5-flash",
        "api_calls": 1,
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "api_latency_ms": usage["api_latency_ms"],
    }


def test_choose_actions_without_key_returns_measured_fallback(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    actions, usage = gemini_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})

    assert actions[0]["type"] == "noop"
    assert "missing GEMINI_API_KEY" in actions[0]["model_error"]
    assert usage is None
