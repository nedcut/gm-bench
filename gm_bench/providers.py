"""Built-in model provider registry for GM-Bench."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gm_bench.agents import Agent, ExternalProcessAgent

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

PROVIDER_NAMES = ("openai", "ollama", "codex", "claude", "opencode")


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    script: str
    model_env: str
    default_model: str
    default_timeout: float
    default_profile: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        name="openai",
        script="openai_compatible_agent.py",
        model_env="LLM_MODEL",
        default_model="gpt-4.1-mini",
        default_timeout=120.0,
        default_profile="compact",
    ),
    "ollama": ProviderSpec(
        name="ollama",
        script="ollama_agent.py",
        model_env="OLLAMA_MODEL",
        default_model="gemma4:e4b",
        default_timeout=240.0,
        default_profile="tiny",
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
) -> Agent:
    """Create an external-process agent for a built-in model provider."""
    spec = resolve_provider(provider)
    resolved_model = model or os.environ.get(spec.model_env) or spec.default_model
    resolved_timeout = timeout if timeout is not None else spec.default_timeout
    script_path = EXAMPLES / spec.script
    if not script_path.exists():
        raise FileNotFoundError(f"provider script not found: {script_path}")

    env = {spec.model_env: resolved_model}
    if profile is not None:
        env["GM_AGENT_PROFILE"] = profile
    elif spec.default_profile and "GM_AGENT_PROFILE" not in os.environ:
        env["GM_AGENT_PROFILE"] = spec.default_profile
    if extra_env:
        env.update(extra_env)
    env.update(spec.extra_env)

    command = f"{sys.executable} {script_path}"
    display_name = f"{spec.name}:{resolved_model}"
    return ExternalProcessAgent(command, timeout_seconds=resolved_timeout, env=env, name=display_name)


def provider_help() -> list[dict[str, Any]]:
    return [
        {
            "provider": spec.name,
            "script": str(EXAMPLES / spec.script),
            "model_env": spec.model_env,
            "default_model": spec.default_model,
            "default_timeout": spec.default_timeout,
            "default_profile": spec.default_profile,
        }
        for spec in PROVIDERS.values()
    ]
