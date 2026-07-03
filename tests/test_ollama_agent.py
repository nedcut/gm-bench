from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace

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


def test_generate_http_retries_without_think_when_api_rejects_switch(monkeypatch) -> None:
    payloads: list[dict[str, object]] = []

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self) -> bytes:
            return b'{"response":"{\\"actions\\":[{\\"type\\":\\"noop\\"}]}"}'

    def fake_urlopen(request: object, **kwargs: object) -> FakeResponse:
        del kwargs
        payloads.append(json.loads(request.data.decode("utf-8")))
        if len(payloads) == 1:
            raise urllib.error.HTTPError(request.full_url, 400, "bad think switch", {}, None)
        return FakeResponse()

    monkeypatch.setattr(ollama_agent.urllib.request, "urlopen", fake_urlopen)

    content = ollama_agent.generate_http("http://127.0.0.1:11434", "gemma4:e4b", "prompt", 5, True, think=False)

    assert content == '{"actions":[{"type":"noop"}]}'
    assert payloads[0]["think"] is False
    assert "think" not in payloads[1]
