"""Safe orchestration for expensive model-backed benchmark panels."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from statistics import mean
from typing import Any

from gm_bench.agents import AGENTS, Agent
from gm_bench.baseline_cache import default_cache_path
from gm_bench.runner import (
    _episodes_payload,
    _paired_analysis,
    _precise_mean_score,
    run_episode,
    run_many,
    run_many_cached_baselines,
)
from gm_bench.telemetry import summarize_usage


class ModelRunAborted(RuntimeError):
    """Raised when consecutive adapter failures trip the model circuit breaker."""


class FailFastAgent(Agent):
    """Stop a panel after repeated adapter failures instead of burning quota."""

    def __init__(self, inner: Agent, threshold: int = 2) -> None:
        if threshold < 1:
            raise ValueError("fail-fast threshold must be >= 1")
        self.inner = inner
        self.name = inner.name
        self.metadata = getattr(inner, "metadata", {})
        self.threshold = threshold
        self.consecutive_failures = 0

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, _usage = self.act_with_usage(observation)
        return actions

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        actions, usage = self.inner.act_with_usage(observation)
        failed = not isinstance(actions, list) or any(
            isinstance(action, dict) and ("error" in action or "model_error" in action) for action in actions
        )
        if not failed:
            self.consecutive_failures = 0
            return actions, usage

        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            detail = _failure_detail(actions)
            raise ModelRunAborted(f"aborting after {self.consecutive_failures} consecutive model failures: {detail}")
        return actions, usage


def _failure_detail(actions: Any) -> str:
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict):
                detail = action.get("model_error") or action.get("error")
                if detail:
                    return str(detail)[:300]
    return "model returned no usable actions"


def preflight_provider(provider: str) -> None:
    """Perform credential/tool checks without making a billed model request."""
    if provider == "claude":
        completed = subprocess.run(
            ["claude", "auth", "status"], text=True, capture_output=True, check=False, timeout=15
        )
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


def default_checkpoint_path(agent_name: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", agent_name).strip("-")
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
    expected = {(seed, repeat) for seed in seeds for repeat in range(1, repeats + 1)}
    episodes: dict[tuple[int, int], dict[str, Any]] = {}
    sources = list(resume_sources or [])
    if resume_checkpoint and checkpoint_path.exists():
        sources.append(checkpoint_path)
    for source in sources:
        for episode in _load_candidate_episodes(
            source,
            agent.name,
            seasons,
            expected_metadata=getattr(agent, "metadata", {}),
        ):
            key = (int(episode["seed"]), int(episode.get("repeat") or 1))
            if key in expected and int(episode.get("failed_decisions", 0)) == 0:
                episodes[key] = episode

    wrapped = FailFastAgent(agent, threshold=fail_fast)
    metadata = dict(getattr(agent, "metadata", {}))
    _write_checkpoint(checkpoint_path, wrapped.name, seeds, seasons, repeats, episodes, metadata, status="running")
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
                    checkpoint_path, wrapped.name, seeds, seasons, repeats, episodes, metadata, status="running"
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
            status="aborted",
            error=str(exc),
        )
        raise

    ordered = [episodes[(seed, repeat)] for seed in seeds for repeat in range(1, repeats + 1)]
    _write_checkpoint(checkpoint_path, wrapped.name, seeds, seasons, repeats, episodes, metadata, status="complete")
    payload = _episodes_payload(wrapped.name, seeds, seasons, ordered)
    payload["repeats"] = repeats
    return payload


def _load_candidate_episodes(
    path: Path,
    agent_name: str,
    seasons: int,
    *,
    expected_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    candidate = payload.get("candidate", payload)
    source_agent = candidate.get("agent") or payload.get("agent")
    source_seasons = candidate.get("seasons") or payload.get("seasons")
    if source_agent != agent_name:
        raise ModelRunAborted(f"resume source {path} is for {source_agent}, expected {agent_name}")
    if int(source_seasons or 0) != seasons:
        raise ModelRunAborted(f"resume source {path} has {source_seasons} seasons, expected {seasons}")
    source_metadata = payload.get("metadata") or payload.get("run_info") or {}
    for key in ("provider", "model", "profile", "session"):
        if key in source_metadata and key in expected_metadata and source_metadata[key] != expected_metadata[key]:
            raise ModelRunAborted(
                f"resume source {path} has {key}={source_metadata[key]!r}, expected {expected_metadata[key]!r}"
            )
    return list(candidate.get("episodes") or [])


def _write_checkpoint(
    path: Path,
    agent_name: str,
    seeds: list[int],
    seasons: int,
    repeats: int,
    episodes: dict[tuple[int, int], dict[str, Any]],
    metadata: dict[str, Any],
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
            payload = run_many(AGENTS[name](), seeds=seeds, seasons=seasons, workers=1)
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
            "candidate_usage": summary.get("usage", summarize_usage([])),
        },
        "paired": _paired_analysis(seeds, candidate, baselines),
    }
