from __future__ import annotations

import json
import urllib.error

from examples import anthropic_agent


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return json.dumps(
            {
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": '{"actions":[{"type":"noop"}]}'}],
                "usage": {
                    "input_tokens": 100,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 30,
                    "output_tokens": 10,
                },
            }
        ).encode()


def test_choose_actions_calls_native_messages_api(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, **kwargs: object) -> _Response:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = kwargs["timeout"]
        return _Response()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic_agent.urllib.request, "urlopen", fake_urlopen)

    actions, usage = anthropic_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})

    assert actions == [{"type": "noop"}]
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["X-api-key"] == "test-key"
    assert captured["payload"]["model"] == "claude-sonnet-4-6"
    assert usage["provider"] == "anthropic"
    assert usage["input_tokens"] == 100
    assert usage["cached_input_tokens"] == 50
    assert usage["output_tokens"] == 10
    assert usage["total_tokens"] == 160


def test_choose_actions_without_key_marks_fallback(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    actions, usage = anthropic_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})

    assert "missing ANTHROPIC_API_KEY" in actions[0]["model_error"]
    assert usage is None


def test_choose_actions_network_and_config_errors_return_measured_fallback(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        anthropic_agent.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    actions, usage = anthropic_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})
    assert "api_error" in actions[0]["model_error"]
    assert usage["api_latency_ms"] >= 0

    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "invalid")
    actions, usage = anthropic_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})
    assert "api_error" in actions[0]["model_error"]
    assert usage["api_latency_ms"] >= 0
