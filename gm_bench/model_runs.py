"""Safe orchestration for expensive model-backed benchmark panels."""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from gm_bench.agents import AGENTS, Agent
from gm_bench.baseline_cache import default_cache_path
from gm_bench.benchmark_config import validate_baseline_names
from gm_bench.contract import benchmark_contract, scaffold_fingerprint
from gm_bench.runner import (
    _episodes_payload,
    _paired_analysis,
    _precise_mean_score,
    run_episode,
    run_many,
    run_many_cached_baselines,
)
from gm_bench.session import PersistentProcessAgent
from gm_bench.telemetry import summarize_usage


class ModelRunAborted(RuntimeError):
    """Raised when consecutive adapter failures trip the model circuit breaker."""


class _FailFastState:
    """Thread-safe consecutive-failure counter shared by fail-fast wrappers.

    "Consecutive" is exact in the serial lane. With parallel workers or session
    clones, every wrapper shares one counter, so it means "N failures with no
    success in between, in the order calls happened to land" -- the failures may
    come from different episodes. That is deliberate: the breaker exists to stop
    a globally broken model (bad key, dead adapter, wrong model id) from burning
    a whole panel's quota, and a globally broken model fails everywhere at once.
    A model that merely fails intermittently keeps resetting the counter.

    Under ``--workers > 1``, abort is best-effort: ``run_many`` uses ordered
    ``executor.map`` and does not cancel in-flight futures when this raises, so
    sibling workers can still finish their current episode after the breaker
    trips. Serial and session lanes (``workers=1``) abort immediately.
    """

    def __init__(self, threshold: int) -> None:
        if threshold < 1:
            raise ValueError("fail-fast threshold must be >= 1")
        self.threshold = threshold
        self.consecutive_failures = 0
        self._lock = threading.Lock()

    def record(self, actions: Any) -> None:
        failed = not isinstance(actions, list) or any(_trips_circuit_breaker(action) for action in actions)
        with self._lock:
            if not failed:
                self.consecutive_failures = 0
                return
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.threshold:
                detail = _failure_detail(actions)
                raise ModelRunAborted(
                    f"aborting after {self.consecutive_failures} consecutive model failures: {detail}"
                )


def _trips_circuit_breaker(action: Any) -> bool:
    if not isinstance(action, dict):
        return False
    marker = action.get("error") or action.get("model_error")
    if marker is None:
        return False
    # Protocol-invalid model output is a measured benchmark outcome.
    # Infrastructure failures still trip the breaker.
    return not str(marker).startswith("protocol_error:")


class FailFastAgent(Agent):
    """Stop a panel after repeated adapter failures instead of burning quota."""

    def __init__(self, inner: Agent, threshold: int = 2) -> None:
        self.inner = inner
        self.name = inner.name
        self.metadata = getattr(inner, "metadata", {})
        # The runner's one-paid-call-per-phase rule keys on this flag. A wrapper
        # that drops it turns a paying model into a "free" agent and reopens the
        # five-round query loop the v6 rules close.
        self.pays_for_calls = getattr(inner, "pays_for_calls", False)
        self._state = _FailFastState(threshold)

    @property
    def threshold(self) -> int:
        return self._state.threshold

    @property
    def consecutive_failures(self) -> int:
        return self._state.consecutive_failures

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, _usage = self.act_with_usage(observation)
        return actions

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        actions, usage = self.inner.act_with_usage(observation)
        self._state.record(actions)
        return actions, usage


class FailFastSessionAgent(PersistentProcessAgent):
    """Fail-fast circuit breaker for session-lane (persistent process) agents.

    The frozen runner dispatches on ``isinstance(agent, PersistentProcessAgent)``
    for episode start/end, per-episode cloning, and multi-round result delivery,
    and ``runner.py`` is a contract-fingerprint source that must not change.
    Wrapping a session agent in the plain ``FailFastAgent`` would defeat those
    checks (the adapter process would never be spawned), so this proxy subclass
    keeps the type relationship while delegating everything to the inner agent.
    Clones share one failure counter so a globally failing model trips the
    breaker across episodes.
    """

    def __init__(
        self,
        inner: PersistentProcessAgent,
        threshold: int = 2,
        *,
        _state: _FailFastState | None = None,
    ) -> None:
        # Deliberately no super().__init__(): every inherited method that touches
        # process state is overridden to delegate to ``inner``.
        self.inner = inner
        self.name = inner.name
        self.metadata = getattr(inner, "metadata", {})
        self.pays_for_calls = getattr(inner, "pays_for_calls", False)
        self._state = _state or _FailFastState(threshold)

    def __getattr__(self, name: str) -> Any:
        # Backstop for the no-super().__init__() trick above. Without it, any
        # method added to PersistentProcessAgent that we forget to override here
        # would find the inherited implementation, reach for process state this
        # instance never initialized, and AttributeError mid-run -- after the
        # quota is already spent. Delegating unknown attributes to ``inner``
        # makes the failure mode "works, via the real agent" instead.
        # __getattr__ only fires for attributes normal lookup misses, so the
        # explicit overrides below still win.
        if name == "inner":
            # Never delegate the delegate: if ``inner`` itself is missing (an
            # instance built without __init__, e.g. by copy/pickle), looking it
            # up through here would recurse until the stack blows.
            raise AttributeError(name)
        return getattr(self.inner, name)

    @property
    def threshold(self) -> int:
        return self._state.threshold

    @property
    def consecutive_failures(self) -> int:
        return self._state.consecutive_failures

    def start_episode(self, seed: int, seasons: int) -> None:
        self.inner.start_episode(seed, seasons)

    def end_episode(self) -> None:
        self.inner.end_episode()

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, _usage = self.act_with_usage(observation)
        return actions

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        actions, usage = self.inner.act_with_usage(observation)
        self._state.record(actions)
        return actions, usage

    def act_on_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actions, _usage = self.act_on_results_with_usage(results)
        return actions

    def act_on_results_with_usage(
        self,
        results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        actions, usage = self.inner.act_on_results_with_usage(results)
        self._state.record(actions)
        return actions, usage

    def clone(self) -> "FailFastSessionAgent":
        return FailFastSessionAgent(self.inner.clone(), _state=self._state)


TRANSIENT_RETRY_ATTEMPTS_ENV = "GM_BENCH_TRANSIENT_RETRY_ATTEMPTS"
TRANSIENT_RETRY_BASE_SECONDS_ENV = "GM_BENCH_TRANSIENT_RETRY_BASE_SECONDS"
DEFAULT_TRANSIENT_RETRY_ATTEMPTS = 4
DEFAULT_TRANSIENT_RETRY_BASE_SECONDS = 20.0
# Gateway/provider statuses that mean "not now", never "this model misbehaved".
_TRANSIENT_HTTP_STATUSES = ("429", "502", "503", "504", "529")
_TRANSIENT_HTTP_PATTERN = re.compile(r"\bHTTP (?:" + "|".join(_TRANSIENT_HTTP_STATUSES) + r")\b")
_UNKNOWN_COST_BLOCK = "provider call did not return authoritative finite cost telemetry"


def _transient_provider_error(actions: Any, guard_state: dict[str, Any] | None) -> str | None:
    """Return the transient HTTP error behind a failed decision, or None.

    A decision counts as transient only when the adapter (or the spend guard
    that wrapped it) surfaced a rate-limit or gateway-unavailable status. A
    malformed reply, a schema failure, or any other adapter error is model
    behavior or a real fault and is left to the fail-fast breaker.
    """
    candidates: list[str] = []
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict):
                marker = action.get("model_error") or action.get("error")
                if marker:
                    candidates.append(str(marker))
    if guard_state is not None:
        telemetry_error = guard_state.get("telemetry_error")
        if isinstance(telemetry_error, str) and guard_state.get("blocked_reason") == _UNKNOWN_COST_BLOCK:
            candidates.append(telemetry_error)
    for text in candidates:
        if text.startswith("protocol_error:"):
            continue
        if _TRANSIENT_HTTP_PATTERN.search(text):
            return text[:300]
    return None


class TransientRetryAgent(Agent):
    """Retry a decision after a transient provider status before it counts as a failure.

    The frozen v6 rules give each publication cell two infrastructure attempts
    and abort a cell after two consecutive adapter failures. A pair of HTTP 429
    or 503 responses therefore consumed an attempt even though no completion
    was produced and nothing was billed. This wrapper sits between the
    fail-fast breaker and the provider agent: on a transient status it backs
    off (base * 2**n seconds with jitter), reconciles the spend guard's
    unresolved reservation the same conservative way the publication runner
    does (charged in full as spent), and re-issues the same observation. Only
    the final attempt's usage is returned, so ``api_calls`` still counts paid
    completions; the retries are recorded in the guard state and surfaced in
    the returned usage as ``transient_retries``.
    """

    def __init__(
        self,
        inner: Agent,
        *,
        attempts: int = DEFAULT_TRANSIENT_RETRY_ATTEMPTS,
        base_seconds: float = DEFAULT_TRANSIENT_RETRY_BASE_SECONDS,
        guard_state_path: Path | None = None,
        sleep=time.sleep,
        log=None,
    ) -> None:
        if attempts < 0 or base_seconds < 0:
            raise ValueError("transient retry attempts and base seconds must be non-negative")
        self.inner = inner
        self.name = inner.name
        self.metadata = getattr(inner, "metadata", {})
        self.pays_for_calls = getattr(inner, "pays_for_calls", False)
        self.attempts = attempts
        self.base_seconds = base_seconds
        self.guard_state_path = guard_state_path
        self._sleep = sleep
        self._log = log or (lambda message: print(message, file=__import__("sys").stderr))
        self.total_retries = 0

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, _usage = self.act_with_usage(observation)
        return actions

    def _guard_state(self) -> dict[str, Any] | None:
        if self.guard_state_path is None or not self.guard_state_path.exists():
            return None
        try:
            payload = json.loads(self.guard_state_path.read_text())
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _release_guard(self, state: dict[str, Any], error: str, retry: int) -> None:
        """Absorb the unresolved reservation as spent and clear the block."""
        if state.get("blocked_reason") != _UNKNOWN_COST_BLOCK:
            return
        active = float(state.get("active_call_reservation_usd") or 0.0)
        state["reported_spend_usd"] = round(float(state.get("reported_spend_usd") or 0.0) + active, 9)
        state["active_call_reservation_usd"] = 0.0
        state.pop("active_call_input_token_bound", None)
        state.pop("blocked_reason", None)
        state.pop("telemetry_error", None)
        history = state.setdefault("transient_retries", [])
        if isinstance(history, list):
            history.append(
                {
                    "retry": retry,
                    "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "error": error,
                    "absorbed_reservation_usd": active,
                    "method": "charge-full-conservative-call-reservation",
                }
            )
        assert self.guard_state_path is not None
        temporary = self.guard_state_path.with_suffix(self.guard_state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, self.guard_state_path)

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        retries = 0
        while True:
            actions, usage = self.inner.act_with_usage(observation)
            guard_state = self._guard_state()
            error = _transient_provider_error(actions, guard_state)
            if error is None or retries >= self.attempts:
                if retries and isinstance(usage, dict):
                    usage = {**usage, "transient_retries": retries}
                return actions, usage
            retries += 1
            self.total_retries += 1
            if guard_state is not None:
                self._release_guard(guard_state, error, retries)
            delay = self.base_seconds * (2 ** (retries - 1))
            delay += random.uniform(0, delay * 0.25) if delay else 0.0
            self._log(f"transient provider error ({error[:120]}); retry {retries}/{self.attempts} after {delay:.0f}s")
            self._sleep(delay)


def transient_retry_agent(agent: Agent, env: dict[str, str] | None = None) -> Agent:
    """Wrap a fresh-spawn provider agent with the transient-status retry policy.

    Session-lane agents are left alone: their process lifecycle is dispatched
    on type by the frozen runner and a retry inside one episode would need a
    different design.
    """
    if isinstance(agent, PersistentProcessAgent):
        return agent
    env = os.environ if env is None else env
    attempts_text = env.get(TRANSIENT_RETRY_ATTEMPTS_ENV)
    base_text = env.get(TRANSIENT_RETRY_BASE_SECONDS_ENV)
    attempts = int(attempts_text) if attempts_text not in (None, "") else DEFAULT_TRANSIENT_RETRY_ATTEMPTS
    base_seconds = float(base_text) if base_text not in (None, "") else DEFAULT_TRANSIENT_RETRY_BASE_SECONDS
    if attempts == 0:
        return agent
    state_path = env.get("GM_BENCH_OPENROUTER_SPEND_GUARD_STATE_PATH")
    return TransientRetryAgent(
        agent,
        attempts=attempts,
        base_seconds=base_seconds,
        guard_state_path=Path(state_path) if state_path else None,
    )


def fail_fast_agent(agent: Agent, threshold: int) -> Agent:
    """Wrap ``agent`` with the fail-fast breaker appropriate for its lane."""
    if isinstance(agent, PersistentProcessAgent):
        return FailFastSessionAgent(agent, threshold)
    return FailFastAgent(agent, threshold)


def _failure_detail(actions: Any) -> str:
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict):
                detail = action.get("model_error") or action.get("error")
                if detail:
                    return str(detail)[:300]
    return "model returned no usable actions"


def preflight_provider(provider: str, *, require_credentials: bool = False) -> None:
    """Perform zero-completion tool checks, optionally requiring API credentials."""
    provider = provider.lower()
    # Direct API adapters fail only when their first subprocess is launched;
    # check credentials here so a recorder cannot leave a partial JSONL set.
    direct_credentials = {
        "openai": ("OPENAI_API_KEY",),
        "anthropic": ("ANTHROPIC_API_KEY",),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "openrouter": ("OPENROUTER_API_KEY",),
    }
    required = direct_credentials.get(provider)
    if require_credentials and required and not any(os.environ.get(name) for name in required):
        names = " or ".join(required)
        raise ModelRunAborted(f"{provider} preflight failed: set {names}")
    if provider == "claude":
        executable = shutil.which("claude")
        if executable is None:
            raise ModelRunAborted("claude preflight failed: `claude` is not installed")
        try:
            completed = subprocess.run(
                [executable, "auth", "status"], text=True, capture_output=True, check=False, timeout=15
            )
        except subprocess.TimeoutExpired as exc:
            raise ModelRunAborted("Claude auth preflight timed out after 15 seconds") from exc
        except OSError as exc:
            raise ModelRunAborted(f"Claude auth preflight could not start: {exc}") from exc
        try:
            status = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ModelRunAborted(f"Claude auth preflight returned invalid output: {completed.stderr[-300:]}") from exc
        if completed.returncode or not status.get("loggedIn"):
            raise ModelRunAborted("Claude auth preflight failed: run `claude auth login`")
        return

    command_providers = {"codex": "codex", "opencode": "opencode", "cursor": "cursor", "ollama": "ollama"}
    executable = command_providers.get(provider)
    if executable and shutil.which(executable) is None:
        raise ModelRunAborted(f"{provider} preflight failed: `{executable}` is not installed")


def default_checkpoint_path(agent_name: str, metadata: dict[str, Any] | None = None) -> Path:
    parts = [agent_name]
    if metadata is not None:
        profile = metadata.get("profile")
        if profile:
            parts.append(str(profile))
        if metadata.get("session"):
            parts.append("session")
    safe_name = "--".join(re.sub(r"[^A-Za-z0-9_.-]+", "-", part).strip("-") for part in parts)
    return Path("data/model_checkpoints") / f"{safe_name}.json"


def run_resumable_candidate(
    agent: Agent,
    seeds: list[int],
    seasons: int,
    repeats: int,
    *,
    checkpoint_path: Path,
    resume_sources: list[Path] | None = None,
    resume_checkpoint: bool = False,
    fail_fast: int = 2,
    progress=None,
) -> dict[str, Any]:
    """Run missing seed/repeat episodes and atomically checkpoint each completion."""
    with _checkpoint_lock(checkpoint_path):
        return _run_resumable_candidate_locked(
            agent,
            seeds,
            seasons,
            repeats,
            checkpoint_path=checkpoint_path,
            resume_sources=resume_sources,
            resume_checkpoint=resume_checkpoint,
            fail_fast=fail_fast,
            progress=progress,
        )


@contextmanager
def _checkpoint_lock(path: Path):
    """Reject concurrent model runs targeting the same checkpoint."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ModelRunAborted(f"checkpoint is already in use by another model run: {path}") from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        yield
    finally:
        os.close(descriptor)


def _run_resumable_candidate_locked(
    agent: Agent,
    seeds: list[int],
    seasons: int,
    repeats: int,
    *,
    checkpoint_path: Path,
    resume_sources: list[Path] | None = None,
    resume_checkpoint: bool = False,
    fail_fast: int = 2,
    progress=None,
) -> dict[str, Any]:
    expected = {(seed, repeat) for seed in seeds for repeat in range(1, repeats + 1)}
    episodes: dict[tuple[int, int], dict[str, Any]] = {}
    metadata = dict(getattr(agent, "metadata", {}))
    provenance = _resume_provenance(metadata)
    sources = list(resume_sources or [])
    if resume_checkpoint and checkpoint_path.exists():
        sources.append(checkpoint_path)
    for source in sources:
        for episode in _load_candidate_episodes(
            source,
            agent.name,
            seasons,
            expected_metadata=metadata,
            expected_provenance=provenance,
        ):
            key = (int(episode["seed"]), int(episode.get("repeat") or 1))
            if key in expected and int(episode.get("failed_decisions", 0)) == 0:
                if key in episodes and episodes[key] != episode:
                    raise ModelRunAborted(
                        f"resume sources contain conflicting successful episodes for seed {key[0]} repeat {key[1]}"
                    )
                episodes[key] = episode

    wrapped = fail_fast_agent(transient_retry_agent(agent), fail_fast)
    _write_checkpoint(
        checkpoint_path, wrapped.name, seeds, seasons, repeats, episodes, metadata, provenance, status="running"
    )
    try:
        for seed in seeds:
            for repeat in range(1, repeats + 1):
                key = (seed, repeat)
                if key in episodes:
                    continue
                result = run_episode(wrapped, seed=seed, seasons=seasons, progress=progress)
                episode = {**result.__dict__, "repeat": repeat}
                episodes[key] = episode
                _write_checkpoint(
                    checkpoint_path,
                    wrapped.name,
                    seeds,
                    seasons,
                    repeats,
                    episodes,
                    metadata,
                    provenance,
                    status="running",
                )
    except BaseException as exc:
        _write_checkpoint(
            checkpoint_path,
            wrapped.name,
            seeds,
            seasons,
            repeats,
            episodes,
            metadata,
            provenance,
            status="aborted",
            error=str(exc),
        )
        raise

    ordered = [episodes[(seed, repeat)] for seed in seeds for repeat in range(1, repeats + 1)]
    _write_checkpoint(
        checkpoint_path, wrapped.name, seeds, seasons, repeats, episodes, metadata, provenance, status="complete"
    )
    payload = _episodes_payload(wrapped.name, seeds, seasons, ordered)
    payload["repeats"] = repeats
    return payload


def _load_candidate_episodes(
    path: Path,
    agent_name: str,
    seasons: int,
    *,
    expected_metadata: dict[str, Any],
    expected_provenance: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text())
    except OSError as exc:
        raise ModelRunAborted(f"cannot read resume source {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ModelRunAborted(f"resume source {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelRunAborted(f"resume source {path} must contain a JSON object")
    candidate = payload.get("candidate", payload)
    if not isinstance(candidate, dict):
        raise ModelRunAborted(f"resume source {path} candidate must be a JSON object")
    source_agent = candidate.get("agent") or payload.get("agent")
    source_seasons = candidate.get("seasons") or payload.get("seasons")
    if source_agent != agent_name:
        raise ModelRunAborted(f"resume source {path} is for {source_agent}, expected {agent_name}")
    try:
        parsed_seasons = int(source_seasons or 0)
    except (TypeError, ValueError) as exc:
        raise ModelRunAborted(f"resume source {path} has invalid seasons={source_seasons!r}") from exc
    if parsed_seasons != seasons:
        raise ModelRunAborted(f"resume source {path} has {source_seasons} seasons, expected {seasons}")
    source_metadata = payload.get("metadata")
    if source_metadata is None:
        source_metadata = payload.get("run_info")
    if source_metadata is None:
        source_metadata = {}
    if not isinstance(source_metadata, dict):
        raise ModelRunAborted(f"resume source {path} metadata must be a JSON object")
    for key in ("provider", "model", "profile", "session", "transport"):
        if key not in expected_metadata:
            continue
        if key not in source_metadata:
            raise ModelRunAborted(f"resume source {path} metadata is missing {key}")
        if source_metadata[key] != expected_metadata[key]:
            raise ModelRunAborted(
                f"resume source {path} has {key}={source_metadata[key]!r}, expected {expected_metadata[key]!r}"
            )
    expected_provider_options = expected_metadata.get("provider_options")
    if isinstance(expected_provider_options, dict) and expected_provider_options:
        normalized_expected = {str(key): str(value) for key, value in expected_provider_options.items()}
        source_provider_options = source_metadata.get("provider_options")
        if not isinstance(source_provider_options, dict):
            first_key = next(iter(normalized_expected))
            raise ModelRunAborted(f"resume source {path} metadata is missing provider_options key {first_key!r}")
        normalized_source = {str(key): str(value) for key, value in source_provider_options.items()}
        if normalized_source != normalized_expected:
            for key in sorted(normalized_expected.keys() | normalized_source.keys()):
                if key not in normalized_source:
                    raise ModelRunAborted(f"resume source {path} provider_options is missing key {key!r}")
                if key not in normalized_expected:
                    raise ModelRunAborted(f"resume source {path} provider_options has unexpected key {key!r}")
                if normalized_source[key] != normalized_expected[key]:
                    raise ModelRunAborted(
                        f"resume source {path} has provider_options[{key!r}]={normalized_source[key]!r}, "
                        f"expected {normalized_expected[key]!r}"
                    )
    if expected_provenance:
        source_provenance = payload.get("provenance")
        if source_provenance is None:
            source_provenance = payload.get("run_info")
        if source_provenance is None:
            source_provenance = {}
        if not isinstance(source_provenance, dict):
            raise ModelRunAborted(f"resume source {path} provenance must be a JSON object")
        if source_provenance.get("benchmark_contract") != expected_provenance["benchmark_contract"]:
            raise ModelRunAborted(f"resume source {path} does not match the current benchmark contract")
        if source_provenance.get("scaffold_fingerprint") != expected_provenance["scaffold_fingerprint"]:
            raise ModelRunAborted(f"resume source {path} does not match the current provider scaffold")
    episodes = candidate.get("episodes")
    if episodes is None:
        episodes = []
    if not isinstance(episodes, list) or any(not isinstance(episode, dict) for episode in episodes):
        raise ModelRunAborted(f"resume source {path} episodes must be a list of JSON objects")
    if any("seed" not in episode for episode in episodes):
        raise ModelRunAborted(f"resume source {path} contains an episode without a seed")
    return episodes


def _resume_provenance(metadata: dict[str, Any]) -> dict[str, Any]:
    provider = metadata.get("provider")
    if not provider:
        return {}
    return {
        "benchmark_contract": benchmark_contract(),
        "scaffold_fingerprint": scaffold_fingerprint(str(provider)),
    }


def _write_checkpoint(
    path: Path,
    agent_name: str,
    seeds: list[int],
    seasons: int,
    repeats: int,
    episodes: dict[tuple[int, int], dict[str, Any]],
    metadata: dict[str, Any],
    provenance: dict[str, Any],
    *,
    status: str,
    error: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "gm-bench-model-checkpoint-v1",
        "status": status,
        "agent": agent_name,
        "seeds": seeds,
        "seasons": seasons,
        "repeats": repeats,
        "metadata": metadata,
        "provenance": provenance,
        "episodes": [episodes[key] for key in sorted(episodes)],
        "completed": [{"seed": seed, "repeat": repeat} for seed, repeat in sorted(episodes)],
    }
    if error:
        payload["error"] = error[:1000]
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def evaluate_resumable_candidate(
    candidate: dict[str, Any],
    baseline_names: list[str],
    *,
    use_baseline_cache: bool = True,
) -> dict[str, Any]:
    """Build the normal evaluation payload after a resumable candidate completes."""
    baseline_names = validate_baseline_names(baseline_names)
    seeds = list(candidate["seeds"])
    seasons = int(candidate["seasons"])
    baselines = []
    cache_hits = 0
    cache_path = default_cache_path()
    for name in baseline_names:
        if use_baseline_cache:
            payload, hits = run_many_cached_baselines(name, seeds, seasons, cache_path=cache_path, use_cache=True)
            cache_hits += hits
        else:
            payload = run_many(AGENTS[name](), seeds=seeds, seasons=seasons, workers=None)
        baselines.append(payload)
    baseline_scores = [_precise_mean_score(result) for result in baselines]
    baseline_mean = mean(baseline_scores) if baseline_scores else 0.0
    candidate_mean = _precise_mean_score(candidate)
    summary = candidate["summary"]
    return {
        "agent": candidate["agent"],
        "seasons": seasons,
        "seeds": seeds,
        "candidate": candidate,
        "baselines": baselines,
        "baseline_cache": {
            "enabled": use_baseline_cache,
            "path": str(cache_path),
            "hits": cache_hits,
            "total": len(baseline_names) * len(seeds),
        },
        "normalized": {
            "candidate_mean_score": round(candidate_mean, 3),
            "candidate_mean_strategy_score": summary["mean_strategy_score"],
            "candidate_protocol_penalty": summary["total_protocol_penalty"],
            "baseline_panel_mean_score": round(baseline_mean, 3),
            "baseline_panel_mean_strategy_score": round(mean(b["summary"]["mean_strategy_score"] for b in baselines), 3)
            if baselines
            else 0.0,
            "baseline_panel_total_protocol_penalty": round(
                sum(b["summary"]["total_protocol_penalty"] for b in baselines), 3
            ),
            "score_lift": round(candidate_mean - baseline_mean, 3),
            "score_lift_pct": round(((candidate_mean / baseline_mean) - 1.0) * 100.0, 2) if baseline_mean else 0.0,
            "candidate_illegal_actions": summary["illegal_actions"],
            "baseline_illegal_actions": sum(b["summary"]["illegal_actions"] for b in baselines),
            "candidate_decisions": summary.get("decisions", 0),
            "candidate_failed_decisions": summary.get("failed_decisions", 0),
            "candidate_decision_failure_rate": summary.get("decision_failure_rate", 0.0),
            "candidate_memo_writes": summary.get("memo_writes", 0),
            "candidate_rejected_offers": summary.get("rejected_offers", 0),
            "candidate_failed_queries": summary.get("failed_queries", 0),
            "candidate_query_declines": summary.get("query_declines", 0),
            "candidate_mean_tokens_per_decision": (summary.get("usage") or {}).get("mean_tokens_per_decision"),
            "candidate_usage": summary.get("usage", summarize_usage([])),
        },
        "paired": _paired_analysis(seeds, candidate, baselines),
    }
