"""Built-in model provider registry for GM-Bench."""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gm_bench.agents import Agent, ExternalProcessAgent
from gm_bench.session import PersistentProcessAgent

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

PROVIDER_NAMES = (
    "openai",
    "anthropic",
    "gemini",
    "openrouter",
    "ollama",
    "codex",
    "claude",
    "opencode",
    "cursor",
)


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    script: str
    model_env: str
    default_model: str
    default_timeout: float
    default_profile: str | None = None
    transport: str = "coding-harness"
    credential_env: tuple[str, ...] = ()
    extra_env: dict[str, str] = field(default_factory=dict)
    provenance_env: tuple[str, ...] = ()


class ProtocolRepairAgent(Agent):
    """One bounded retry for adapter formatting failures, outside score contract."""

    def __init__(self, wrapped: Agent, attempts: int = 1) -> None:
        self.wrapped = wrapped
        self.attempts = attempts
        self.name = wrapped.name
        self.env = getattr(wrapped, "env", None)

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, _usage = self.act_with_usage(observation)
        return actions

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        actions, usage = self.wrapped.act_with_usage(observation)
        if not _model_format_failed(actions) or not usage or not usage.get("api_calls"):
            return actions, usage
        merged = dict(usage)
        for attempt in range(1, self.attempts + 1):
            retry_observation = dict(observation)
            retry_observation["protocol_repair"] = {"attempt": attempt}
            actions, retry_usage = self.wrapped.act_with_usage(retry_observation)
            merged = _merge_usage(merged, retry_usage)
            merged["protocol_repair_attempts"] = attempt
            if not _model_format_failed(actions):
                merged["protocol_repairs_succeeded"] = 1
                break
        return actions, merged


def _model_format_failed(actions: Any) -> bool:
    """True only for JSON/schema format failures worth a bounded repair retry.

    Deliberately does **not** match the generic fallback
    ``"model produced no usable actions"`` — that string contains ``action``
    but is not a format error, and treating it as one would burn an extra API
    call and inflate tokens/cost.
    """
    if not isinstance(actions, list):
        return False
    needles = ("json", "schema", "not a list", "parse", "decode")
    messages = [str(action.get("model_error", "")).lower() for action in actions if isinstance(action, dict)]
    return any(any(needle in message for needle in needles) for message in messages)


def _merge_usage(left: dict[str, Any], right: dict[str, Any] | None) -> dict[str, Any]:
    if not right:
        return left
    merged = dict(left)
    for key in (
        "api_calls",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
        "api_latency_ms",
    ):
        if key in left or key in right:
            merged[key] = round(float(left.get(key, 0)) + float(right.get(key, 0)), 6)
            if key not in {"api_latency_ms", "cost_usd"}:
                merged[key] = int(merged[key])
    for key in ("provider", "model", "upstream_provider", "generation_id"):
        if right.get(key):
            merged[key] = right[key]
    # Adapter-reported cost is authoritative only when both calls reported it.
    # Otherwise aggregate_usage can estimate from the merged token totals.
    if "cost_usd" in left and "cost_usd" in right:
        merged["cost_usd"] = round(float(left["cost_usd"]) + float(right["cost_usd"]), 6)
    else:
        merged.pop("cost_usd", None)
    upstreams = {str(value) for value in (left.get("upstream_provider"), right.get("upstream_provider")) if value}
    upstreams.update(str(value) for value in left.get("upstream_providers", []) if value)
    upstreams.update(str(value) for value in right.get("upstream_providers", []) if value)
    if upstreams:
        merged["upstream_providers"] = sorted(upstreams)
        if len(upstreams) != 1:
            merged.pop("upstream_provider", None)
    return merged


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        name="openai",
        script="openai_compatible_agent.py",
        model_env="OPENAI_MODEL",
        default_model="gpt-5.4-mini",
        default_timeout=120.0,
        default_profile="compact",
        transport="direct-api",
        credential_env=("OPENAI_API_KEY",),
        provenance_env=("OPENAI_MAX_TOKENS", "OPENAI_TEMPERATURE", "OPENAI_JSON_MODE"),
    ),
    "anthropic": ProviderSpec(
        name="anthropic",
        script="anthropic_agent.py",
        model_env="ANTHROPIC_MODEL",
        default_model="claude-sonnet-4-6",
        default_timeout=180.0,
        default_profile="compact",
        transport="direct-api",
        credential_env=("ANTHROPIC_API_KEY",),
        provenance_env=("ANTHROPIC_MAX_TOKENS", "ANTHROPIC_TEMPERATURE"),
    ),
    "gemini": ProviderSpec(
        name="gemini",
        script="gemini_agent.py",
        model_env="GEMINI_MODEL",
        default_model="gemini-3.5-flash",
        default_timeout=180.0,
        default_profile="compact",
        transport="direct-api",
        credential_env=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        provenance_env=("GEMINI_MAX_OUTPUT_TOKENS", "GEMINI_TEMPERATURE"),
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        script="openrouter_agent.py",
        model_env="OPENROUTER_MODEL",
        default_model="openai/gpt-5.4-mini",
        default_timeout=180.0,
        default_profile="compact",
        transport="gateway-api",
        credential_env=("OPENROUTER_API_KEY",),
        extra_env={
            "OPENROUTER_PROVIDER_SORT": "price",
            "OPENROUTER_ALLOW_FALLBACKS": "false",
            "OPENROUTER_REQUIRE_PARAMETERS": "false",
            "OPENROUTER_DATA_COLLECTION": "deny",
            "OPENROUTER_JSON_MODE": "false",
        },
        provenance_env=(
            "OPENROUTER_PROVIDER_ONLY",
            "OPENROUTER_EXPECTED_ENDPOINT_NAME",
            "OPENROUTER_PROVIDER_SORT",
            "OPENROUTER_ALLOW_FALLBACKS",
            "OPENROUTER_REQUIRE_PARAMETERS",
            "OPENROUTER_DATA_COLLECTION",
            "OPENROUTER_ZDR",
            "OPENROUTER_QUANTIZATIONS",
            "OPENROUTER_JSON_MODE",
            "OPENROUTER_MAX_TOKENS",
            "OPENROUTER_REASONING_EFFORT",
            "OPENROUTER_REASONING_MAX_TOKENS",
        ),
    ),
    "ollama": ProviderSpec(
        name="ollama",
        script="ollama_agent.py",
        model_env="OLLAMA_MODEL",
        default_model="gemma4:e4b",
        default_timeout=240.0,
        default_profile="tiny",
        transport="local-api",
    ),
    "codex": ProviderSpec(
        name="codex",
        script="codex_agent.py",
        model_env="CODEX_MODEL",
        default_model="gpt-5-mini",
        default_timeout=180.0,
        default_profile="tiny",
    ),
    "claude": ProviderSpec(
        name="claude",
        script="claude_agent.py",
        model_env="CLAUDE_MODEL",
        default_model="sonnet",
        default_timeout=180.0,
        default_profile="tiny",
    ),
    "opencode": ProviderSpec(
        name="opencode",
        script="opencode_agent.py",
        model_env="OPENCODE_MODEL",
        default_model="opencode/deepseek-v4-flash-free",
        default_timeout=180.0,
        default_profile="compact",
    ),
    "cursor": ProviderSpec(
        name="cursor",
        script="cursor_agent.py",
        model_env="CURSOR_MODEL",
        default_model="composer-2.5",
        default_timeout=180.0,
        default_profile="compact",
    ),
}


def resolve_provider(name: str) -> ProviderSpec:
    key = name.lower()
    if key not in PROVIDERS:
        supported = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"unknown provider {name!r}; supported providers: {supported}")
    return PROVIDERS[key]


def build_provider_agent(
    provider: str,
    *,
    model: str | None = None,
    timeout: float | None = None,
    profile: str | None = None,
    extra_env: dict[str, str] | None = None,
    session: bool = False,
) -> Agent:
    """Create an external-process agent for a built-in model provider."""
    spec = resolve_provider(provider)
    resolved_model = model or os.environ.get(spec.model_env) or spec.default_model
    resolved_timeout = timeout if timeout is not None else spec.default_timeout
    script_path = EXAMPLES / spec.script
    if not script_path.exists():
        raise FileNotFoundError(f"provider script not found: {script_path}")

    env = {
        spec.model_env: resolved_model,
        # Adapters derive their per-call backend timeout from the harness
        # decision budget unless an explicit adapter timeout env is set.
        "GM_BENCH_AGENT_TIMEOUT": str(resolved_timeout),
        # One bounded retry is enough to separate JSON-format competence from
        # strategy without creating an open-ended compute advantage.
        "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1",
    }
    if profile is not None:
        env["GM_AGENT_PROFILE"] = profile
    elif spec.default_profile and "GM_AGENT_PROFILE" not in os.environ:
        env["GM_AGENT_PROFILE"] = spec.default_profile
    # Precedence is config env > inherited shell env > provider defaults.
    # Material controls must never silently replace an operator override.
    for key, value in spec.extra_env.items():
        env[key] = os.environ.get(key, value)
    # Config-file env is the most explicit provider configuration.
    if extra_env:
        env.update(extra_env)
    # Cap repair attempts at the frozen headline lane (1). Operators may set 0
    # to disable, but cannot open an unbounded second-chance compute advantage.
    try:
        repair_attempts = int(env.get("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS", "1"))
    except (TypeError, ValueError):
        repair_attempts = 1
    env["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] = str(max(0, min(1, repair_attempts)))

    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}"
    display_name = f"{spec.name}:{resolved_model}"
    if session:
        # One live adapter process per episode: the model keeps its whole
        # trajectory in context instead of relying on the memo action. A
        # different measurement condition from fresh-spawn rows, recorded in
        # metadata and provenance so the two are never silently compared.
        agent: Agent = PersistentProcessAgent(command, timeout_seconds=resolved_timeout, env=env, name=display_name)
    else:
        base_agent = ExternalProcessAgent(command, timeout_seconds=resolved_timeout, env=env, name=display_name)
        agent = ProtocolRepairAgent(base_agent, attempts=int(env["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"]))
    # Resolve the profile exactly as the adapter subprocess will see it
    # (per-agent env overrides the inherited environment; gm_agent_common
    # defaults to "compact" when unset), so results can record what the model
    # actually observed. Scores from different profiles are not comparable.
    resolved_profile = env.get("GM_AGENT_PROFILE") or os.environ.get("GM_AGENT_PROFILE") or "compact"
    agent.metadata = {
        "provider": spec.name,
        "model": resolved_model,
        "profile": resolved_profile,
        "agent_timeout": resolved_timeout,
        "session": session,
        "transport": spec.transport,
        "protocol_repair_attempts": int(env["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"]),
    }
    provider_options = {
        key: env.get(key, os.environ.get(key))
        for key in spec.provenance_env
        if env.get(key, os.environ.get(key)) not in (None, "")
    }
    budget_cell = env.get("GM_BENCH_OUTPUT_BUDGET_CELL", os.environ.get("GM_BENCH_OUTPUT_BUDGET_CELL"))
    if budget_cell not in (None, ""):
        provider_options["GM_BENCH_OUTPUT_BUDGET_CELL"] = budget_cell
    provider_options["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] = env["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"]
    if provider_options:
        agent.metadata["provider_options"] = provider_options
    return agent


def provider_help() -> list[dict[str, Any]]:
    return [
        {
            "provider": spec.name,
            "script": str(EXAMPLES / spec.script),
            "model_env": spec.model_env,
            "default_model": spec.default_model,
            "default_timeout": spec.default_timeout,
            "default_profile": spec.default_profile,
            "transport": spec.transport,
            "credential_env": list(spec.credential_env),
            "credential_present": any(os.environ.get(name) for name in spec.credential_env)
            if spec.credential_env
            else None,
        }
        for spec in PROVIDERS.values()
    ]
