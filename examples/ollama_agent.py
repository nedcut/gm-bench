"""Ollama-backed external agent for GM-Bench.

Usage:
    OLLAMA_MODEL=gemma4:e4b python -m gm_bench run \
      --agent-cmd "python examples/ollama_agent.py" --agent-timeout 120 \
      --seeds 1 --seasons 1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    from gm_agent_common import (
        build_prompt,
        emit,
        fallback_actions,
        make_usage,
        parse_actions,
        resolve_call_timeout,
        run_session_loop,
        strip_terminal_codes,
    )
except ModuleNotFoundError:
    from examples.gm_agent_common import (
        build_prompt,
        emit,
        fallback_actions,
        make_usage,
        parse_actions,
        resolve_call_timeout,
        run_session_loop,
        strip_terminal_codes,
    )

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "gm_actions.schema.json"

# One entry per completed backend call; merged into a single usage block at
# emit time so repair retries count as extra api_calls, not lost telemetry.
CALLS: list[dict[str, Any]] = []


def load_action_schema() -> dict[str, Any] | None:
    """The real JSON schema Ollama constrains generation to, or None if missing.

    Ollama's /api/generate accepts a full JSON-schema object as `format` (not
    just the string "json"), which pins the model to the exact action shape and
    stops it from hallucinating verbs like buy/sell/analyze.
    """
    try:
        return json.loads(SCHEMA_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def choose_actions(
    observation: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if observation.get("phase") == "action_results":
        return [{"type": "end_turn"}], None
    CALLS.clear()
    model = os.environ.get("OLLAMA_MODEL", "gemma4:e4b")
    os.environ.setdefault("GM_AGENT_PROFILE", "tiny")
    think = resolve_think_mode(model)
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    timeout = resolve_call_timeout("OLLAMA_TIMEOUT", 120.0)
    schema = load_action_schema()
    prompt = build_prompt(observation)
    try:
        content = generate(host, model, prompt, timeout, schema, think=think)
        try:
            return parse_actions(content), merged_usage(model)
        except ValueError as exc:
            repair_prompt = (
                f"{prompt}\n\nYour previous answer was invalid: {str(content)[:300]!r}. "
                "Return exactly one JSON object with an actions array and no other text."
            )
            # Retry unconstrained: the schema-pinned first attempt already failed
            # to parse, so pinning the same schema again just reproduces it. Drop
            # the format constraint (schema=None) so a weak model can emit
            # *something* parseable, guided by the textual instruction above.
            repaired = generate(host, model, repair_prompt, timeout, None, think=think)
            try:
                return parse_actions(repaired), merged_usage(model)
            except ValueError:
                snippet = str(repaired or content).replace("\n", " ")[:220]
                return (
                    fallback_actions(observation, f"ollama_parse_error: {exc}; content={snippet!r}"),
                    merged_usage(model),
                )
    except (
        subprocess.TimeoutExpired,
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        return fallback_actions(observation, f"ollama_error: {exc}"), merged_usage(model)


def merged_usage(model: str) -> dict[str, Any] | None:
    if not CALLS:
        return None
    input_tokens = [call["input_tokens"] for call in CALLS if "input_tokens" in call]
    output_tokens = [call["output_tokens"] for call in CALLS if "output_tokens" in call]
    return make_usage(
        provider="ollama",
        model=model,
        api_calls=len(CALLS),
        input_tokens=sum(input_tokens) if input_tokens else None,
        output_tokens=sum(output_tokens) if output_tokens else None,
        api_latency_ms=round(sum(call["api_latency_ms"] for call in CALLS), 1),
    )


def resolve_think_mode(model: str) -> bool | None:
    """Decide whether to force the Ollama think switch on, off, or leave unset.

    Without the real `think` control, some thinking models spend the whole
    generation on reasoning prose and never emit JSON, so every decision falls
    back. Thinking defaults to off for every model; the CLI/HTTP callers retry
    without the switch when a model or an older Ollama rejects it.
    `OLLAMA_THINK=1` opts a model back in.
    """
    del model
    setting = os.environ.get("OLLAMA_THINK")
    if setting is None:
        return False
    return setting.strip().lower() not in {"0", "false", "no", "off"}


def generate(
    host: str, model: str, prompt: str, timeout: float, schema: dict[str, Any] | None, think: bool | None = None
) -> str:
    """Prefer schema-constrained HTTP generation; fall back to unconstrained CLI.

    The HTTP path pins the model to the real action schema when one is supplied.
    Only if that schema-constrained call errors — e.g. an older Ollama that
    rejects a full JSON-schema `format` object — do we drop to the unconstrained
    `ollama run` CLI.
    """
    if os.environ.get("OLLAMA_TRANSPORT", "http") != "http":
        return generate_cli(model, prompt, timeout, think=think)
    try:
        return generate_http(host, model, prompt, timeout, format_schema=schema, think=think)
    except urllib.error.HTTPError as exc:
        # Any 400 from a schema-constrained call means this Ollama build won't
        # accept the JSON-schema `format` object; some builds reject it with an
        # opaque body the substring heuristic misses, so key on "we sent a
        # schema" too rather than degrading straight to a fallback decision.
        if _is_schema_format_rejection(exc) or (schema is not None and exc.code == 400):
            return generate_cli(model, prompt, timeout, think=think)
        raise


def generate_cli(model: str, prompt: str, timeout: float, think: bool | None = None) -> str:
    command = ["ollama", "run", model]
    if think is not None:
        command.append(f"--think={'true' if think else 'false'}")
    command.append(prompt)
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        # Older CLIs reject --think, and non-thinking models reject the switch
        # itself; either way the un-flagged invocation is the right retry.
        if think is not None and "think" in completed.stderr.lower():
            return generate_cli(model, prompt, timeout, think=None)
        raise ValueError(completed.stderr[-500:])
    # The CLI reports no token counts; latency is the only telemetry here.
    CALLS.append({"api_latency_ms": (time.perf_counter() - started) * 1000.0})
    return strip_terminal_codes(completed.stdout)


def generate_http(
    host: str,
    model: str,
    prompt: str,
    timeout: float,
    format_schema: dict[str, Any] | None,
    think: bool | None = None,
) -> str:
    payload: dict[str, object] = {
        "model": model,
        "stream": False,
        "prompt": prompt,
        "options": {
            "temperature": float(os.environ.get("OLLAMA_TEMPERATURE", "0.2")),
            "num_predict": int(os.environ.get("OLLAMA_NUM_PREDICT", "512")),
        },
    }
    if think is not None:
        payload["think"] = think
    if format_schema is not None:
        # A full JSON-schema object (not the generic "json" string) constrains
        # decoding to the exact action shape.
        payload["format"] = format_schema
    request = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        # Fixed local/provider HTTP endpoint from operator config, not attacker-controlled input.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosemgrep
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if think is not None and _is_think_rejection(exc):
            return generate_http(host, model, prompt, timeout, format_schema, think=None)
        raise
    call: dict[str, Any] = {"api_latency_ms": (time.perf_counter() - started) * 1000.0}
    if isinstance(data.get("prompt_eval_count"), int):
        call["input_tokens"] = data["prompt_eval_count"]
    if isinstance(data.get("eval_count"), int):
        call["output_tokens"] = data["eval_count"]
    CALLS.append(call)
    return extract_ollama_content(data)


def _is_schema_format_rejection(exc: urllib.error.HTTPError) -> bool:
    if exc.code != 400:
        return False
    text = _http_error_text(exc).lower()
    mentions_schema_format = "format" in text or "schema" in text
    rejected_as_unsupported = any(marker in text for marker in ("unsupported", "not support", "invalid", "unmarshal"))
    return mentions_schema_format and rejected_as_unsupported


def _is_think_rejection(exc: urllib.error.HTTPError) -> bool:
    return exc.code == 400 and "think" in _http_error_text(exc).lower()


def _http_error_text(exc: urllib.error.HTTPError) -> str:
    cached = getattr(exc, "_gm_bench_error_text", None)
    if cached is None:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except (OSError, AttributeError, UnicodeDecodeError):
            body = ""
        cached = " ".join(part for part in (str(exc.reason), str(exc), body) if part)
        setattr(exc, "_gm_bench_error_text", cached)
    return str(cached)


def extract_ollama_content(data: dict[str, object]) -> str:
    message = data.get("message")
    candidates: list[object] = []
    if isinstance(message, dict):
        candidates.extend([message.get("content"), message.get("response")])
    candidates.extend([data.get("response"), data.get("content")])
    if isinstance(message, dict):
        candidates.extend([message.get("thinking"), message.get("reasoning")])
    candidates.append(data.get("thinking"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return json.dumps(data)[:1000]


def main() -> None:
    # One-shot keeps json.load + emit on this module so existing adapter tests
    # can monkeypatch them; session mode uses the shared line-delimited loop.
    if os.environ.get("GM_BENCH_SESSION") == "1":
        run_session_loop(choose_actions)
        return
    observation = json.load(sys.stdin)
    actions, usage = choose_actions(observation)
    emit(actions, usage)


if __name__ == "__main__":
    main()
