from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace

import pytest

from examples import ollama_agent


def test_resolve_think_mode_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_THINK", raising=False)
    assert ollama_agent.resolve_think_mode("gemma4:e4b") is False


def test_resolve_think_mode_accepts_explicit_opt_in_and_off_values(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_THINK", "1")
    assert ollama_agent.resolve_think_mode("gemma4:e4b") is True

    monkeypatch.setenv("OLLAMA_THINK", "off")
    assert ollama_agent.resolve_think_mode("gemma4:e4b") is False


def test_generate_cli_retries_without_think_when_cli_rejects_switch(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        calls.append(command)
        if len(calls) == 1:
            return SimpleNamespace(returncode=1, stderr="unknown flag: --think", stdout="")
        return SimpleNamespace(returncode=0, stderr="", stdout='{"actions":[{"type":"noop"}]}')

    monkeypatch.setattr(ollama_agent.subprocess, "run", fake_run)

    content = ollama_agent.generate_cli("gemma4:e4b", "prompt", 5, think=False)

    assert content == '{"actions":[{"type":"noop"}]}'
    assert calls == [
        ["ollama", "run", "gemma4:e4b", "--think=false", "prompt"],
        ["ollama", "run", "gemma4:e4b", "prompt"],
    ]


class _FakeNoopResponse:
    def __enter__(self) -> "_FakeNoopResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return b'{"response":"{\\"actions\\":[{\\"type\\":\\"noop\\"}]}"}'


_SCHEMA = {"type": "object", "required": ["actions"]}


def test_generate_http_retries_without_think_when_api_rejects_switch(monkeypatch) -> None:
    payloads: list[dict[str, object]] = []

    def fake_urlopen(request: object, **kwargs: object) -> _FakeNoopResponse:
        del kwargs
        payloads.append(json.loads(request.data.decode("utf-8")))
        if len(payloads) == 1:
            raise urllib.error.HTTPError(request.full_url, 400, "bad think switch", {}, None)
        return _FakeNoopResponse()

    monkeypatch.setattr(ollama_agent.urllib.request, "urlopen", fake_urlopen)

    content = ollama_agent.generate_http("http://127.0.0.1:11434", "gemma4:e4b", "prompt", 5, _SCHEMA, think=False)

    assert content == '{"actions":[{"type":"noop"}]}'
    assert payloads[0]["think"] is False
    assert "think" not in payloads[1]
    # The real action schema is passed as the format object on both the initial
    # call and the think-less retry, not the generic "json" string.
    assert payloads[0]["format"] == _SCHEMA
    assert payloads[1]["format"] == _SCHEMA


def test_load_action_schema_returns_the_real_action_schema() -> None:
    schema = ollama_agent.load_action_schema()
    assert schema is not None
    assert "draft" in schema["properties"]["actions"]["items"]["properties"]["type"]["enum"]


def test_generate_defaults_to_schema_constrained_http(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_TRANSPORT", raising=False)
    payloads: list[dict[str, object]] = []

    def fake_urlopen(request: object, **kwargs: object) -> _FakeNoopResponse:
        del kwargs
        payloads.append(json.loads(request.data.decode("utf-8")))
        return _FakeNoopResponse()

    monkeypatch.setattr(ollama_agent.urllib.request, "urlopen", fake_urlopen)

    content = ollama_agent.generate("http://127.0.0.1:11434", "gemma4:e4b", "prompt", 5, _SCHEMA, think=False)

    assert content == '{"actions":[{"type":"noop"}]}'
    assert len(payloads) == 1
    assert payloads[0]["format"] == _SCHEMA


def test_generate_falls_back_to_cli_when_schema_call_errors(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_TRANSPORT", raising=False)

    def fake_urlopen(request: object, **kwargs: object) -> object:
        del kwargs
        raise urllib.error.HTTPError(getattr(request, "full_url", ""), 400, "unsupported format schema", {}, None)

    cli_calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        cli_calls.append(command)
        return SimpleNamespace(returncode=0, stderr="", stdout='{"actions":[{"type":"noop"}]}')

    monkeypatch.setattr(ollama_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ollama_agent.subprocess, "run", fake_run)

    content = ollama_agent.generate("http://127.0.0.1:11434", "gemma4:e4b", "prompt", 5, _SCHEMA, think=None)

    assert content == '{"actions":[{"type":"noop"}]}'
    assert cli_calls == [["ollama", "run", "gemma4:e4b", "prompt"]]


def test_generate_does_not_fall_back_to_cli_for_non_schema_http_errors(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_TRANSPORT", raising=False)

    def fake_urlopen(request: object, **kwargs: object) -> object:
        del kwargs
        raise urllib.error.HTTPError(getattr(request, "full_url", ""), 500, "server error", {}, None)

    cli_calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        cli_calls.append(command)
        return SimpleNamespace(returncode=0, stderr="", stdout='{"actions":[{"type":"noop"}]}')

    monkeypatch.setattr(ollama_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ollama_agent.subprocess, "run", fake_run)

    with pytest.raises(urllib.error.HTTPError):
        ollama_agent.generate("http://127.0.0.1:11434", "gemma4:e4b", "prompt", 5, _SCHEMA, think=None)

    assert cli_calls == []
