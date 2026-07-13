from __future__ import annotations

import json
import urllib.error

from examples import openrouter_agent


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return json.dumps(
            {
                "id": "gen-test",
                "model": "openai/gpt-5.4-mini",
                "provider": "OpenAI",
                "choices": [{"message": {"content": '{"actions":[{"type":"noop"}]}'}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cost": 0.00123,
                    "prompt_tokens_details": {"cached_tokens": 40},
                    "completion_tokens_details": {"reasoning_tokens": 8},
                },
            }
        ).encode()


def test_provider_preferences_are_reproducibility_safe(monkeypatch) -> None:
    for name in (
        "OPENROUTER_PROVIDER_ONLY",
        "OPENROUTER_PROVIDER_SORT",
        "OPENROUTER_ALLOW_FALLBACKS",
        "OPENROUTER_REQUIRE_PARAMETERS",
        "OPENROUTER_DATA_COLLECTION",
        "OPENROUTER_ZDR",
        "OPENROUTER_QUANTIZATIONS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert openrouter_agent.provider_preferences() == {
        "allow_fallbacks": False,
        "require_parameters": False,
        "data_collection": "deny",
        "sort": "price",
    }


def test_choose_actions_records_route_and_authoritative_cost(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, **kwargs: object) -> _Response:
        captured["payload"] = json.loads(request.data.decode())
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = kwargs["timeout"]
        return _Response()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_PROVIDER_ONLY", "openai")
    monkeypatch.setenv("OPENROUTER_QUANTIZATIONS", "fp16,fp8")
    monkeypatch.setenv("OPENROUTER_JSON_MODE", "true")
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "1024")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "medium")
    monkeypatch.setenv("OPENROUTER_REASONING_MAX_TOKENS", "256")
    monkeypatch.setattr(openrouter_agent.urllib.request, "urlopen", fake_urlopen)

    actions, usage = openrouter_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})

    assert actions == [{"type": "noop"}]
    assert captured["payload"]["provider"]["only"] == ["openai"]
    assert captured["payload"]["provider"]["quantizations"] == ["fp16", "fp8"]
    assert captured["payload"]["provider"]["allow_fallbacks"] is False
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["max_tokens"] == 1024
    assert captured["payload"]["reasoning"] == {"effort": "medium", "max_tokens": 256}
    assert usage["provider"] == "openrouter"
    assert usage["upstream_provider"] == "OpenAI"
    assert usage["generation_id"] == "gen-test"
    assert usage["cached_input_tokens"] == 40
    assert usage["reasoning_tokens"] == 8
    assert usage["cost_usd"] == 0.00123


def test_choose_actions_without_key_marks_fallback(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    actions, usage = openrouter_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})

    assert "missing OPENROUTER_API_KEY" in actions[0]["model_error"]
    assert usage is None


def test_choose_actions_network_filtered_and_config_errors_return_fallback(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        openrouter_agent.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    actions, usage = openrouter_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})
    assert "api_error" in actions[0]["model_error"]
    assert usage["api_latency_ms"] >= 0


def test_parse_failure_preserves_paid_usage(monkeypatch) -> None:
    class Malformed(_Response):
        def read(self) -> bytes:
            payload = json.loads(super().read())
            payload["choices"][0]["message"]["content"] = "not json"
            return json.dumps(payload).encode()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(openrouter_agent.urllib.request, "urlopen", lambda *args, **kwargs: Malformed())
    actions, usage = openrouter_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})

    assert "model did not return" in actions[0]["model_error"]
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 20
    assert usage["cost_usd"] == 0.00123
    assert usage["generation_id"] == "gen-test"
    assert usage["upstream_provider"] == "OpenAI"

    class EmptyChoices(_Response):
        def read(self) -> bytes:
            return b'{"choices":[],"usage":{"total_tokens":10}}'

    monkeypatch.setattr(openrouter_agent.urllib.request, "urlopen", lambda *args, **kwargs: EmptyChoices())
    actions, usage = openrouter_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})
    assert "api_error" in actions[0]["model_error"]
    assert usage["api_latency_ms"] >= 0

    monkeypatch.setenv("OPENROUTER_TEMPERATURE", "invalid")
    actions, usage = openrouter_agent.choose_actions({"phase": "preseason", "team": {"roster": []}})
    assert "api_error" in actions[0]["model_error"]
    assert usage["api_latency_ms"] >= 0
