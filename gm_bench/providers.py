"""Built-in model provider registry for GM-Bench."""

from __future__ import annotations

import json
import math
import os
import shlex
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gm_bench.agents import Agent, ExternalProcessAgent, model_adapter_observation
from gm_bench.contract import _repository_checkout_root
from gm_bench.protocol import V6_OUTPUT_TOKEN_CEILING
from gm_bench.session import PersistentProcessAgent

_PACKAGE_ROOT = Path(__file__).resolve().parent


def _examples_path() -> Path:
    checkout_root = _repository_checkout_root()
    if checkout_root is not None:
        return checkout_root / "examples"
    return _PACKAGE_ROOT / "_resources" / "examples"


EXAMPLES = _examples_path()

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


SPEND_GUARD_ENV_PREFIX = "GM_BENCH_OPENROUTER_SPEND_GUARD_"
_SPEND_GUARD_PREFIX = SPEND_GUARD_ENV_PREFIX
OPENROUTER_CANONICAL_API_BASE = "https://openrouter.ai/api/v1"
# The OpenRouter adapter adds a fixed system message, the compact scaffold,
# action examples, and chat framing around the observation.  A UTF-8 byte is a
# conservative upper bound for a tokenizer token in the user-controlled text;
# 32 KiB covers the adapter's current fixed material and provider framing with
# ample headroom.  The bound is deliberately recomputed from every observation
# rather than pretending that one average prompt describes every interaction.
_SPEND_GUARD_INPUT_OVERHEAD_TOKENS = 32_768


class ProviderSpendGuardAgent(Agent):
    """Fail-closed OpenRouter spend guard checked before every provider call.

    The publication process is serial, but one decision can make several model
    calls (interaction rounds plus a protocol repair).  Wrapping the base
    ``ExternalProcessAgent`` *inside* ``ProtocolRepairAgent`` makes this guard
    run for every primary and repair call.  State is persisted atomically so a
    later cell cannot forget cost already reported by an earlier child.
    """

    def __init__(
        self,
        wrapped: Agent,
        *,
        state_path: Path,
        ceiling_usd: float,
        measured_spend_floor_usd: float,
        prompt_rate_usd: float,
        completion_rate_usd: float,
        output_token_cap: int,
        contingency_multiplier: float,
        reasoning_rate_usd: float = 0.0,
        reasoning_token_cap: int = 0,
        long_context_threshold: int | None = None,
        long_context_prompt_rate_usd: float | None = None,
        long_context_completion_rate_usd: float | None = None,
    ) -> None:
        self.wrapped = wrapped
        self.name = wrapped.name
        self.env = getattr(wrapped, "env", None)
        self.state_path = state_path
        self.ceiling_usd = ceiling_usd
        self.measured_spend_floor_usd = measured_spend_floor_usd
        self.prompt_rate_usd = prompt_rate_usd
        self.completion_rate_usd = completion_rate_usd
        self.output_token_cap = output_token_cap
        self.contingency_multiplier = contingency_multiplier
        self.reasoning_rate_usd = reasoning_rate_usd
        self.reasoning_token_cap = reasoning_token_cap
        self.long_context_threshold = long_context_threshold
        self.long_context_prompt_rate_usd = long_context_prompt_rate_usd
        self.long_context_completion_rate_usd = long_context_completion_rate_usd

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, _usage = self.act_with_usage(observation)
        return actions

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "schema_version": 1,
                "ceiling_usd": self.ceiling_usd,
                "reported_spend_usd": self.measured_spend_floor_usd,
                "active_call_reservation_usd": 0.0,
            }
        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read spend-guard state: {exc}") from exc
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            raise ValueError("invalid spend-guard state")
        stored_ceiling = state.get("ceiling_usd")
        if not isinstance(stored_ceiling, int | float) or not math.isclose(
            float(stored_ceiling), self.ceiling_usd, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ValueError("spend-guard state ceiling differs from the authorized ceiling")
        for field_name in ("reported_spend_usd", "active_call_reservation_usd"):
            value = state.get(field_name)
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"spend-guard state {field_name} must be finite and non-negative")
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.state_path.parent,
            prefix=f".{self.state_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.state_path)

    @contextmanager
    def _exclusive_call(self):
        """Hold a crash-visible inter-process lock through reserve and settle."""
        lock_path = self.state_path.with_name(f".{self.state_path.name}.lock")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ValueError(
                f"another publication process holds {lock_path.name}; "
                "if it crashed, reconcile provider spend before removing the lock"
            ) from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(f"pid={os.getpid()}\n")
                handle.flush()
                os.fsync(handle.fileno())
            yield
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def _maximum_call_cost_usd(self, observation: dict[str, Any]) -> tuple[float, int]:
        adapter_payload = json.dumps(
            model_adapter_observation(observation),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        input_token_bound = len(adapter_payload) + _SPEND_GUARD_INPUT_OVERHEAD_TOKENS
        prompt_rate = self.prompt_rate_usd
        completion_rate = self.completion_rate_usd
        if self.long_context_threshold is not None and input_token_bound >= self.long_context_threshold:
            # The byte-derived input bound may cross a tier even when the
            # actual tokenized prompt does not. Use the more expensive side of
            # each tier so that uncertainty cannot select a discounted rate.
            prompt_rate = max(prompt_rate, self.long_context_prompt_rate_usd or 0.0)
            completion_rate = max(completion_rate, self.long_context_completion_rate_usd or 0.0)
        maximum = (
            input_token_bound * prompt_rate
            + self.output_token_cap * completion_rate
            + self.reasoning_token_cap * self.reasoning_rate_usd
        ) * self.contingency_multiplier
        return maximum, input_token_bound

    @staticmethod
    def _blocked(reason: str) -> tuple[list[dict[str, Any]], None]:
        return [{"type": "noop", "error": f"spend_guard: {reason}"}], None

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            with self._exclusive_call():
                return self._act_with_usage_locked(observation)
        except ValueError as exc:
            return self._blocked(str(exc))

    def _act_with_usage_locked(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        state = self._read_state()
        prior_block = state.get("blocked_reason")
        if isinstance(prior_block, str) and prior_block:
            return self._blocked(prior_block)
        active = float(state.get("active_call_reservation_usd") or 0.0)
        if active > 0:
            reason = "an earlier provider call has unresolved cost; reconcile it before resuming"
            state["blocked_reason"] = reason
            self._write_state(state)
            return self._blocked(reason)

        reported = max(float(state.get("reported_spend_usd") or 0.0), self.measured_spend_floor_usd)
        maximum_call_cost, input_token_bound = self._maximum_call_cost_usd(observation)
        if reported + maximum_call_cost > self.ceiling_usd:
            reason = (
                f"next-call bound ${maximum_call_cost:.6f} would exceed ceiling "
                f"(${reported:.6f} reported of ${self.ceiling_usd:.6f})"
            )
            state.update({"reported_spend_usd": reported, "blocked_reason": reason})
            self._write_state(state)
            return self._blocked(reason)

        state.update(
            {
                "reported_spend_usd": reported,
                "active_call_reservation_usd": maximum_call_cost,
                "active_call_input_token_bound": input_token_bound,
            }
        )
        self._write_state(state)
        actions, usage = self.wrapped.act_with_usage(observation)
        cost = usage.get("cost_usd") if isinstance(usage, dict) else None
        if (
            not isinstance(cost, int | float)
            or isinstance(cost, bool)
            or not math.isfinite(float(cost))
            or float(cost) < 0
        ):
            reason = "provider call did not return authoritative finite cost telemetry"
            state["blocked_reason"] = reason
            if isinstance(usage, dict) and isinstance(usage.get("telemetry_error"), str):
                state["telemetry_error"] = usage["telemetry_error"][:500]
            else:
                adapter_error = next(
                    (
                        action.get("error") or action.get("model_error")
                        for action in actions
                        if isinstance(action, dict) and (action.get("error") or action.get("model_error"))
                    ),
                    None,
                )
                if adapter_error is not None:
                    state["telemetry_error"] = str(adapter_error)[:500]
            # Keep the active reservation: the call may have been billed even
            # though the adapter could not report its cost.
            self._write_state(state)
            return self._blocked(reason)
        actual_cost = float(cost)
        state["reported_spend_usd"] = reported + actual_cost
        state["active_call_reservation_usd"] = 0.0
        state.pop("active_call_input_token_bound", None)
        if actual_cost > maximum_call_cost:
            reason = (
                f"reported call cost ${actual_cost:.6f} exceeded its conservative ${maximum_call_cost:.6f} reservation"
            )
            state["blocked_reason"] = reason
            self._write_state(state)
            return self._blocked(reason)
        self._write_state(state)
        return actions, usage


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
    messages = [
        str(action.get("model_error") or action.get("error") or "").lower()
        for action in actions
        if isinstance(action, dict)
    ]
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
    truncation_reasons = {"length", "max_tokens", "max_output_tokens"}

    def finish_reason_count(usage: dict[str, Any]) -> int:
        if "calls_with_finish_reason" in usage:
            return int(usage["calls_with_finish_reason"])
        return int(bool(usage.get("finish_reason")))

    def truncated_call_count(usage: dict[str, Any]) -> int:
        if "truncated_calls" in usage:
            return int(usage["truncated_calls"])
        reasons = (usage.get("finish_reason"), usage.get("native_finish_reason"))
        return int(any(str(reason or "").lower() in truncation_reasons for reason in reasons))

    def max_output_tokens_per_call(usage: dict[str, Any]) -> int:
        if "max_output_tokens_per_call" in usage:
            return int(usage["max_output_tokens_per_call"])
        return int(usage.get("output_tokens") or 0)

    # A protocol repair folds multiple provider calls into one decision-level
    # record. Preserve the per-call audit fields instead of treating the summed
    # token count and first finish reason as if they described one call.
    merged["calls_with_finish_reason"] = finish_reason_count(left) + finish_reason_count(right)
    merged["truncated_calls"] = truncated_call_count(left) + truncated_call_count(right)
    merged["max_output_tokens_per_call"] = max(
        max_output_tokens_per_call(left),
        max_output_tokens_per_call(right),
    )
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
        extra_env={"OPENAI_MAX_TOKENS": str(V6_OUTPUT_TOKEN_CEILING)},
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
        extra_env={"ANTHROPIC_MAX_TOKENS": str(V6_OUTPUT_TOKEN_CEILING)},
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
        extra_env={"GEMINI_MAX_OUTPUT_TOKENS": str(V6_OUTPUT_TOKEN_CEILING)},
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
            "OPENROUTER_MAX_TOKENS": str(V6_OUTPUT_TOKEN_CEILING),
            # v6 disables reasoning where the route allows it. Models that
            # cannot turn it off run at their minimum effort, set per model in
            # the panel config, and their reasoning tokens are recorded.
            "OPENROUTER_REASONING_ENABLED": "false",
        },
        provenance_env=(
            "OPENROUTER_API_BASE",
            "OPENROUTER_PROVIDER_ONLY",
            "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER",
            "OPENROUTER_EXPECTED_ENDPOINT_NAME",
            "OPENROUTER_PROVIDER_SORT",
            "OPENROUTER_ALLOW_FALLBACKS",
            "OPENROUTER_REQUIRE_PARAMETERS",
            "OPENROUTER_DATA_COLLECTION",
            "OPENROUTER_ZDR",
            "OPENROUTER_QUANTIZATIONS",
            "OPENROUTER_JSON_MODE",
            "OPENROUTER_MAX_TOKENS",
            "OPENROUTER_REASONING_ENABLED",
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


def _strict_env_value(value: Any) -> str:
    """Normalise a strictness setting to the adapter wire format ("1"/"0")."""
    if isinstance(value, str):
        return "1" if value.strip() == "1" else "0"
    return "1" if value else "0"


def _spend_guard_agent(wrapped: Agent, env: dict[str, str]) -> ProviderSpendGuardAgent | None:
    """Build the publication-only OpenRouter guard from runner-owned env."""
    state_path = env.get(f"{_SPEND_GUARD_PREFIX}STATE_PATH")
    if not state_path:
        return None

    def required_float(suffix: str) -> float:
        key = f"{_SPEND_GUARD_PREFIX}{suffix}"
        try:
            value = float(env[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a finite non-negative number") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite non-negative number")
        return value

    def required_int(suffix: str) -> int:
        key = f"{_SPEND_GUARD_PREFIX}{suffix}"
        try:
            value = int(env[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a non-negative integer") from exc
        if value < 0:
            raise ValueError(f"{key} must be a non-negative integer")
        return value

    ceiling = required_float("CEILING_USD")
    contingency = required_float("CONTINGENCY_MULTIPLIER")
    output_cap = required_int("OUTPUT_TOKEN_CAP")
    if ceiling <= 0 or contingency < 1 or output_cap < 1:
        raise ValueError("publication spend guard requires a positive ceiling/output cap and contingency >= 1")

    threshold_text = env.get(f"{_SPEND_GUARD_PREFIX}LONG_CONTEXT_THRESHOLD")
    threshold = int(threshold_text) if threshold_text else None
    if threshold is not None and threshold < 1:
        raise ValueError(f"{_SPEND_GUARD_PREFIX}LONG_CONTEXT_THRESHOLD must be a positive integer")
    long_prompt = required_float("LONG_CONTEXT_PROMPT_RATE_USD") if threshold is not None else None
    long_completion = required_float("LONG_CONTEXT_COMPLETION_RATE_USD") if threshold is not None else None
    return ProviderSpendGuardAgent(
        wrapped,
        state_path=Path(state_path),
        ceiling_usd=ceiling,
        measured_spend_floor_usd=required_float("MEASURED_SPEND_FLOOR_USD"),
        prompt_rate_usd=required_float("PROMPT_RATE_USD"),
        completion_rate_usd=required_float("COMPLETION_RATE_USD"),
        output_token_cap=output_cap,
        contingency_multiplier=contingency,
        reasoning_rate_usd=required_float("REASONING_RATE_USD"),
        reasoning_token_cap=required_int("REASONING_TOKEN_CAP"),
        long_context_threshold=threshold,
        long_context_prompt_rate_usd=long_prompt,
        long_context_completion_rate_usd=long_completion,
    )


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
    strict_fallback: bool | None = None,
) -> Agent:
    """Create an external-process agent for a built-in model provider.

    `strict_fallback` is the harness-resolved failure-handling policy. With it
    set, a failed decision becomes a bare noop instead of a host-supplied draft
    and lineup, so nothing the model did not produce moves roster state. The
    harness resolves it rather than trusting the operator's shell, because a
    stale ambient `GM_AGENT_STRICT` would otherwise silently decide how a
    publication row was measured.
    """
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
        # v6 buys no retries: a malformed reply is repaired locally under the
        # published rules in gm_bench/repair.py or recorded as a structured
        # no-op. Operators can set 1 to replay the pre-v6 paid-retry lane.
        "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "0",
        # Failure handling is a measurement condition, so it is always pinned
        # and always recorded. A harness-resolved policy wins over an ambient
        # value; without one the inherited environment still decides.
        "GM_AGENT_STRICT": (
            _strict_env_value(strict_fallback)
            if strict_fallback is not None
            else os.environ.get("GM_AGENT_STRICT", "0")
        ),
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
    guard_env = {**os.environ, **env}
    spend_guard_enabled = spec.name == "openrouter" and bool(guard_env.get(f"{_SPEND_GUARD_PREFIX}STATE_PATH"))
    if spend_guard_enabled:
        configured_base = guard_env.get("OPENROUTER_API_BASE", OPENROUTER_CANONICAL_API_BASE).rstrip("/")
        if configured_base != OPENROUTER_CANONICAL_API_BASE:
            raise ValueError(
                "publication OpenRouter runs require canonical API base "
                f"{OPENROUTER_CANONICAL_API_BASE!r}; got {configured_base!r}"
            )
        env["OPENROUTER_API_BASE"] = OPENROUTER_CANONICAL_API_BASE
        if session:
            raise ValueError("publication OpenRouter spend guard does not support persistent session mode")
    # v6 defaults to no paid retry. Operators replaying the older lane may set
    # 1, but cannot open an unbounded second-chance compute advantage.
    try:
        repair_attempts = int(env.get("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS", "0"))
    except (TypeError, ValueError):
        repair_attempts = 0
    env["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] = str(max(0, min(1, repair_attempts)))
    # A harness-resolved policy is reapplied after config env: failure handling
    # decides whether a row is publishable, so a stale config `env` entry must
    # not quietly override the lane default or an explicit operator flag.
    if strict_fallback is not None:
        env["GM_AGENT_STRICT"] = _strict_env_value(strict_fallback)
    env["GM_AGENT_STRICT"] = _strict_env_value(env["GM_AGENT_STRICT"])

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
        guarded_agent: Agent = base_agent
        if spec.name == "openrouter":
            guarded_agent = _spend_guard_agent(base_agent, guard_env) or base_agent
        agent = ProtocolRepairAgent(guarded_agent, attempts=int(env["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"]))
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
        "strict_fallback": env["GM_AGENT_STRICT"] == "1",
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
    # Recorded for every provider, including the CLI harnesses with an empty
    # provenance_env: a published row must say which failure-handling policy
    # produced it, not leave a reader guessing.
    provider_options["GM_AGENT_STRICT"] = env["GM_AGENT_STRICT"]
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
