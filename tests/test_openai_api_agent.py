from __future__ import annotations

import json
import urllib.error

from examples import openai_compatible_agent


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return json.dumps(
            {
                "model": "gpt-5.4-mini",
                "choices": [{"message": {"content": '{"actions":[{"type":"noop"}]}'}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_tokens_details": {"cached_tokens": 40},
                    "completion_tokens_details": {"reasoning_tokens": 8},
                },
            }
        ).encode()


def test_choose_actions_calls_direct_openai_api(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, **kwargs: object) -> _Response:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = kwargs["timeout"]
        return _Response()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    monkeypatch.delenv("OPENAI_TEMPERATURE", raising=False)
    monkeypatch.setattr(openai_compatible_agent.urllib.request, "urlopen", fake_urlopen)

    actions, usage = openai_compatible_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})

    assert actions == [{"type": "noop"}]
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert "temperature" not in captured["payload"]
    assert usage["provider"] == "openai"
    assert usage["cached_input_tokens"] == 40
    assert usage["reasoning_tokens"] == 8


def test_choose_actions_without_key_marks_fallback(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    actions, usage = openai_compatible_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})

    assert "missing OPENAI_API_KEY" in actions[0]["model_error"]
    assert usage is None


def test_json_mode_can_be_disabled(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, **kwargs: object) -> _Response:
        del kwargs
        captured["payload"] = json.loads(request.data.decode())
        return _Response()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_JSON_MODE", "false")
    monkeypatch.setattr(openai_compatible_agent.urllib.request, "urlopen", fake_urlopen)

    openai_compatible_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})
    assert "response_format" not in captured["payload"]


def test_choose_actions_network_and_config_errors_return_measured_fallback(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        openai_compatible_agent.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    actions, usage = openai_compatible_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})
    assert "api_error" in actions[0]["model_error"]
    assert usage["api_latency_ms"] >= 0

    monkeypatch.setenv("OPENAI_TEMPERATURE", "invalid")
    actions, usage = openai_compatible_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})
    assert "api_error" in actions[0]["model_error"]
    assert usage["api_latency_ms"] >= 0
