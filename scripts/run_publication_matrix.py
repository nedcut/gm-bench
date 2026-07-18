#!/usr/bin/env python3
"""Run the pre-registered GM-Bench publication matrix one serial cell at a time.

The driver is intentionally conservative: it never fans out model calls, writes
one atomic artifact and checkpoint per cell, validates configuration provenance,
and can stop against a cumulative OpenRouter spend ceiling. Use ``--dry-run`` to
inspect every command and environment value without contacting a provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SWEEP_CONFIG = ROOT / "config" / "output_budget_sweep.json"
PANEL_CONFIG = ROOT / "config" / "sota_v2_models.json"
LANE_CONFIG = ROOT / "config" / "sota_v2_lane.json"
PRICING_CONFIG = ROOT / "config" / "openrouter_pricing_snapshot.json"
SMOKE_MANIFEST = ROOT / "config" / "sota_v2_smoke_manifest.json"
RUN_STATE_FORMAT = "gm-bench-publication-run-v1"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRESETS  # noqa: E402
from gm_bench.contract import contract_fingerprint, scaffold_fingerprint  # noqa: E402
from gm_bench.environment import load_environment_files  # noqa: E402
from gm_bench.protocol import PHASES  # noqa: E402
from gm_bench.publication import SMOKE_MANIFEST_FORMAT, smoke_manifest_issues  # noqa: E402


@dataclass(frozen=True)
class Cell:
    experiment_id: str
    provider: str
    model: str
    profile: str
    preset: str
    repeats: int
    cap: int | None
    upstream_provider: str
    endpoint_tag: str
    endpoint_name: str
    fixed_options: dict[str, str]
    absent_options: tuple[str, ...]

    @property
    def cap_label(self) -> str:
        return "uncapped" if self.cap is None else str(self.cap)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _validate_models(models: list[dict[str, Any]], *, exact_routes: bool = True) -> None:
    if not models:
        raise ValueError("publication matrix contains no models")
    ids = [str(model.get("id") or "") for model in models]
    identities = [(str(model.get("provider") or ""), str(model.get("model") or "")) for model in models]
    if any(not value for value in ids) or any(not provider or not model for provider, model in identities):
        raise ValueError("every model requires non-empty id, provider, and model")
    if len(set(ids)) != len(ids) or len(set(identities)) != len(identities):
        raise ValueError("publication model ids and provider/model identities must be unique")
    if not exact_routes:
        return
    for model in models:
        required = ("upstream_provider", "upstream_provider_slug", "endpoint_tag", "endpoint_name")
        if any(not str(model.get(key) or "").strip() for key in required):
            raise ValueError(f"publication model {model.get('id')!r} is missing exact endpoint identity")
        policy = model.get("reasoning_policy")
        options = model.get("fixed_options") or {}
        if policy == "disabled":
            if (
                options.get("OPENROUTER_REASONING_ENABLED") != "false"
                or options.get("OPENROUTER_REASONING_EFFORT") is not None
                or model.get("reasoning_effort") is not None
            ):
                raise ValueError(f"publication model {model.get('id')!r} has an invalid disabled reasoning policy")
        elif policy == "mandatory-minimum":
            effort = model.get("reasoning_effort")
            if (
                not effort
                or options.get("OPENROUTER_REASONING_ENABLED") != "true"
                or options.get("OPENROUTER_REASONING_EFFORT") != effort
            ):
                raise ValueError(f"publication model {model.get('id')!r} has an invalid mandatory reasoning policy")
        else:
            raise ValueError(f"publication model {model.get('id')!r} has an unknown reasoning policy")


def _smoke_manifest_path(lane: dict[str, Any]) -> Path:
    configured = lane.get("smoke_manifest")
    return ROOT / str(configured) if configured else SMOKE_MANIFEST


def _registered_fixed_options(config: dict[str, Any], model: dict[str, Any]) -> dict[str, str]:
    return {
        **{str(key): str(value) for key, value in (config.get("shared_fixed_options") or {}).items()},
        **{str(key): str(value) for key, value in (model.get("fixed_options") or {}).items()},
        "OPENROUTER_PROVIDER_ONLY": str(model["upstream_provider_slug"]),
        "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER": str(model["upstream_provider"]),
        "OPENROUTER_EXPECTED_ENDPOINT_NAME": str(model["endpoint_name"]),
    }


def _registered_absent_options(config: dict[str, Any], model: dict[str, Any]) -> tuple[str, ...]:
    fixed = _registered_fixed_options(config, model)
    values = [*(config.get("shared_absent_options") or []), *(model.get("absent_options") or [])]
    return tuple(dict.fromkeys(str(value) for value in values if str(value) not in fixed))


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    try:
        return _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def build_cells(phase: str, model_id: str | None = None, cap: int | None = None) -> list[Cell]:
    if phase == "smoke":
        config = _read_json(PANEL_CONFIG)
        lane = _read_json(LANE_CONFIG)
        models = list(config.get("models") or [])
        _validate_models(models)
        frozen_cap = lane.get("output_token_cap")
        if lane.get("output_policy_basis") not in {
            "fixed-safety-ceiling",
            "common-safety-ceiling-with-native-minimum-reasoning",
        }:
            raise ValueError("panel smoke is locked until the fixed safety ceiling is frozen")
        if not isinstance(frozen_cap, int) or frozen_cap < 1:
            raise ValueError("panel smoke requires a positive frozen output_token_cap")
        if cap is not None and cap != frozen_cap:
            raise ValueError(f"requested cap {cap} differs from frozen panel smoke cap {frozen_cap}")
        cells = [
            Cell(
                experiment_id=str(model["id"]),
                provider=str(model["provider"]),
                model=str(model["model"]),
                profile=str(config["profile"]),
                preset="smoke",
                repeats=1,
                cap=frozen_cap,
                upstream_provider=str(model["upstream_provider"]),
                endpoint_tag=str(model["endpoint_tag"]),
                endpoint_name=str(model.get("endpoint_name") or ""),
                fixed_options=_registered_fixed_options(config, model),
                absent_options=_registered_absent_options(config, model),
            )
            for model in models
        ]
    elif phase == "sweep":
        config = _read_json(SWEEP_CONFIG)
        models = list(config.get("models") or [])
        _validate_models(models, exact_routes=False)
        configured_caps = list(config["output_token_caps"])
        if cap is not None and cap not in configured_caps:
            raise ValueError(f"requested cap {cap} is not in the pre-registered sweep {configured_caps}")
        caps = [cap] if cap is not None else configured_caps
        preset = str(config["preset"])
        repeats = int(config["repeats"])
        cells = [
            Cell(
                experiment_id=str(model["id"]),
                provider=str(model["provider"]),
                model=str(model["model"]),
                profile=str(config["profile"]),
                preset=preset,
                repeats=repeats,
                cap=cell_cap,
                upstream_provider=str(model["upstream_provider"]),
                endpoint_tag=str(model.get("endpoint_tag") or ""),
                endpoint_name=str(model.get("endpoint_name") or ""),
                fixed_options={str(key): str(value) for key, value in (model.get("fixed_options") or {}).items()},
                absent_options=tuple(str(value) for value in model.get("absent_options") or []),
            )
            for model in models
            for cell_cap in caps
        ]
    else:
        config = _read_json(PANEL_CONFIG)
        lane = _read_json(LANE_CONFIG)
        models = list(config.get("models") or [])
        _validate_models(models)
        frozen_cap = lane.get("output_token_cap")
        if lane.get("output_budget_status") not in {
            "frozen-saturation",
            "frozen-fixed-budget",
            "frozen-native-reasoning-cap",
        }:
            raise ValueError("full panel is locked until config/sota_v2_lane.json freezes the output-budget policy")
        if config.get("selection_status") != "frozen":
            raise ValueError("full panel is locked until config/sota_v2_models.json freezes the model registry")
        if not isinstance(frozen_cap, int) or frozen_cap < 1:
            raise ValueError("full panel requires a positive frozen output_token_cap")
        manifest = _read_optional_json(_smoke_manifest_path(lane))
        manifest_issues = smoke_manifest_issues(manifest, config, lane)
        if manifest_issues:
            raise ValueError(
                "full panel is locked until every registered smoke is recorded and accepted: "
                + "; ".join(manifest_issues)
            )
        if cap is not None and cap != frozen_cap:
            raise ValueError(f"requested cap {cap} differs from frozen panel cap {frozen_cap}")
        cells = [
            Cell(
                experiment_id=str(model["id"]),
                provider=str(model["provider"]),
                model=str(model["model"]),
                profile=str(config["profile"]),
                preset=str(config["preset"]),
                repeats=int(config["repeats"]),
                cap=frozen_cap,
                upstream_provider=str(model["upstream_provider"]),
                endpoint_tag=str(model["endpoint_tag"]),
                endpoint_name=str(model.get("endpoint_name") or ""),
                fixed_options=_registered_fixed_options(config, model),
                absent_options=_registered_absent_options(config, model),
            )
            for model in models
        ]
    if model_id:
        cells = [cell for cell in cells if cell.experiment_id == model_id]
        if not cells:
            raise ValueError(f"unknown model id: {model_id}")
    return cells


def cell_environment(cell: Cell) -> dict[str, str]:
    env = dict(os.environ)
    for key in cell.absent_options:
        env.pop(key, None)
    env.update(cell.fixed_options)
    env["GM_BENCH_OUTPUT_BUDGET_CELL"] = cell.cap_label
    if cell.provider == "openrouter":
        if cell.cap is None:
            env.pop("OPENROUTER_MAX_TOKENS", None)
        else:
            env["OPENROUTER_MAX_TOKENS"] = str(cell.cap)
    env["GM_BENCH_WORKERS"] = "1"
    return env


def cell_command(cell: Cell, run_dir: Path, *, preflight: bool = False) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "gm_bench",
        "model",
        "--provider",
        cell.provider,
        "--model",
        cell.model,
        "--preset",
        cell.preset,
        "--profile",
        cell.profile,
        "--repeats",
        str(cell.repeats),
        "--workers",
        "1",
        "--no-log",
    ]
    if preflight:
        return [*command, "--preflight-only"]
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    command.extend(
        [
            "--checkpoint",
            str(run_dir / "checkpoints" / f"{stem}.json"),
            "--fail-fast",
            "2",
            "--output",
            str(run_dir / "raw" / f"{stem}.json"),
        ]
    )
    if cell.preset == "smoke":
        command.append("--require-clean")
    if (run_dir / "checkpoints" / f"{stem}.json").exists():
        command.append("--resume")
    return command


def _openrouter_usage_usd(env: dict[str, str]) -> float:
    key = env.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is required to enforce --max-spend-usd")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "gm-bench-publication-runner/1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint  # nosemgrep
        payload = json.load(response)
    return float(payload["data"]["total_usage"])


def _endpoint_issues(cell: Cell, payload: dict[str, Any]) -> list[str]:
    endpoints = (payload.get("data") or {}).get("endpoints") or []
    expected_provider = cell.upstream_provider
    matches = [
        endpoint
        for endpoint in endpoints
        if endpoint.get("provider_name") == expected_provider
        and endpoint.get("tag") == cell.endpoint_tag
        and endpoint.get("name") == cell.endpoint_name
        and endpoint.get("status") == 0
    ]
    if not cell.endpoint_name:
        return ["pre-registered OpenRouter endpoint_name is empty"]
    if not matches:
        return [
            "no healthy OpenRouter endpoint matches "
            f"provider={expected_provider!r} tag={cell.endpoint_tag!r} name={cell.endpoint_name!r}"
        ]
    required = {"max_tokens", "reasoning"}
    if cell.fixed_options.get("OPENROUTER_JSON_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}:
        required.add("response_format")
    capable = []
    for endpoint in matches:
        supported = set(endpoint.get("supported_parameters") or [])
        maximum = endpoint.get("max_completion_tokens")
        cap_fits = cell.cap is None or maximum is None or (isinstance(maximum, int) and cell.cap <= maximum)
        if required <= supported and cap_fits:
            capable.append(endpoint)
    if not capable:
        return [f"matching endpoint cannot honor required parameters {sorted(required)!r} and cap={cell.cap_label}"]
    return []


@lru_cache(maxsize=32)
def _openrouter_endpoints(model: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://openrouter.ai/api/v1/models/{model}/endpoints",
        headers={"User-Agent": "gm-bench-publication-runner/1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint  # nosemgrep
        return json.load(response)


def _validate_openrouter_endpoint(cell: Cell) -> None:
    issues = _endpoint_issues(cell, _openrouter_endpoints(cell.model))
    if issues:
        raise RuntimeError("; ".join(issues))


def _budget_start(run_dir: Path, env: dict[str, str]) -> float:
    path = run_dir / "openrouter-budget.json"
    if path.exists():
        return float(_read_json(path)["starting_total_usage_usd"])
    usage = _openrouter_usage_usd(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(path, {"starting_total_usage_usd": usage})
    return usage


def _artifact_spend_usd(run_dir: Path) -> float:
    total = 0.0
    for path in (run_dir / "raw").glob("*.json"):
        try:
            payload = _read_json(path)
            usage = ((payload.get("candidate") or {}).get("summary") or {}).get("usage") or {}
            cost = usage.get("cost_usd")
            if cost is not None:
                total += float(cost)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return total


def _measured_spend_usd(run_dir: Path, env: dict[str, str], budget_start: float) -> float:
    # Account totals may update asynchronously; completed artifact telemetry is
    # immediate. Use the larger measurement so a lagging credits endpoint never
    # weakens the guard.
    account_delta = max(0.0, _openrouter_usage_usd(env) - budget_start)
    return max(account_delta, _artifact_spend_usd(run_dir))


def _cell_reservation_usd(cell: Cell) -> float:
    if not isinstance(cell.cap, int) or cell.cap < 1:
        raise ValueError("paid publication cells require a positive bounded output cap")
    pricing = _read_json(PRICING_CONFIG)
    rates = (pricing.get("models") or {}).get(cell.model)
    if not isinstance(rates, dict):
        raise ValueError(f"missing committed pricing for {cell.model}")
    assumptions = pricing["planning_assumptions"]
    preset = PRESETS[cell.preset]
    decisions = len(preset["seeds"]) * int(preset["seasons"]) * len(PHASES) * cell.repeats
    input_tokens = int(assumptions["input_tokens_per_decision"])
    prompt = decisions * input_tokens * float(rates["prompt"])
    completion = decisions * cell.cap * float(rates["completion"])
    return round(prompt + completion, 6)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _read_json_if_valid(path: Path) -> dict[str, Any] | None:
    try:
        return _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _write_run_state(run_dir: Path, phase: str, cells: list[Cell], spend_ceiling_usd: float | None) -> None:
    path = run_dir / "run-state.json"
    existing = _read_json_if_valid(path) or {}
    launched = {str(value) for value in existing.get("launched_model_ids") or [] if isinstance(value, str) and value}
    launched.update(cell.experiment_id for cell in cells)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "format": RUN_STATE_FORMAT,
        "schema_version": 1,
        "phase": phase,
        "output_token_cap": cells[0].cap if cells else None,
        "started_at_utc": existing.get("started_at_utc") or now,
        "updated_at_utc": now,
        "launched_model_ids": sorted(launched),
        "spend_ceiling_usd": spend_ceiling_usd,
    }
    _write_json_atomic(path, payload)


def _checkpoint_process_alive(path: Path) -> bool:
    import fcntl

    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        descriptor = os.open(lock_path, os.O_RDONLY)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def _payload_cost_usd(payload: dict[str, Any] | None) -> float | None:
    if not payload:
        return None
    candidate = payload.get("candidate")
    if isinstance(candidate, dict):
        summary = candidate.get("summary")
        usage = summary.get("usage") if isinstance(summary, dict) else None
        if isinstance(usage, dict) and usage.get("cost_usd") is not None:
            try:
                return float(usage["cost_usd"])
            except (TypeError, ValueError):
                return None
    costs = []
    for episode in payload.get("episodes") or []:
        usage = episode.get("usage") if isinstance(episode, dict) else None
        if isinstance(usage, dict) and usage.get("cost_usd") is not None:
            try:
                costs.append(float(usage["cost_usd"]))
            except (TypeError, ValueError):
                continue
    return sum(costs) if costs else None


def _expected_progress(
    run_state: dict[str, Any], checkpoint: dict[str, Any] | None, raw: dict[str, Any] | None
) -> tuple[int, int | None, int, int | None]:
    source = checkpoint or raw or {}
    completed = source.get("completed")
    if isinstance(completed, list):
        completed_episodes = len(completed)
    else:
        candidate = raw.get("candidate") if raw else None
        episodes = candidate.get("episodes") if isinstance(candidate, dict) else None
        completed_episodes = len(episodes) if isinstance(episodes, list) else 0

    seeds = source.get("seeds")
    repeats = source.get("repeats")
    seasons = source.get("seasons")
    if raw and isinstance(raw.get("candidate"), dict):
        repeats = repeats or raw["candidate"].get("repeats")
        seasons = seasons or raw["candidate"].get("seasons")
    total_episodes = None
    if isinstance(seeds, list) and isinstance(repeats, int):
        total_episodes = len(seeds) * repeats
    elif run_state.get("phase") == "smoke":
        total_episodes = 1
        seasons = seasons or 1
    elif run_state.get("phase") == "panel":
        registry = _read_json_if_valid(PANEL_CONFIG) or {}
        preset = PRESETS.get(str(registry.get("preset") or "leaderboard"), {})
        total_episodes = len(preset.get("seeds") or []) * int(registry.get("repeats") or 0)
        seasons = seasons or int(preset.get("seasons") or 0)

    decisions_per_episode = int(seasons or 0) * len(PHASES)
    completed_decisions = completed_episodes * decisions_per_episode
    total_decisions = total_episodes * decisions_per_episode if total_episodes is not None else None
    return completed_episodes, total_episodes, completed_decisions, total_decisions


def publication_run_status(run_dir: Path, manifest_path: Path = SMOKE_MANIFEST) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    registry = _read_json(PANEL_CONFIG)
    run_state = _read_json_if_valid(run_dir / "run-state.json") or {}
    cap = int(run_state.get("output_token_cap") or registry["output_token_cap"])
    manifest = _read_json_if_valid(manifest_path) or {}
    manifest_entries = manifest.get("entries") if isinstance(manifest.get("entries"), dict) else {}
    reservations_payload = _read_json_if_valid(run_dir / "openrouter-reservations.json") or {}
    reservations = reservations_payload.get("cells")
    reservations = reservations if isinstance(reservations, dict) else {}

    rows = []
    for model in registry.get("models") or []:
        model_id = str(model["id"])
        stem = f"{model_id}--{cap}"
        checkpoint_path = run_dir / "checkpoints" / f"{stem}.json"
        raw_path = run_dir / "raw" / f"{stem}.json"
        checkpoint = _read_json_if_valid(checkpoint_path)
        raw = _read_json_if_valid(raw_path)
        manifest_entry = manifest_entries.get(model_id)
        reservation = reservations.get(stem)
        smoke_accepted = isinstance(manifest_entry, dict) and manifest_entry.get("accepted") is True

        if raw_path.exists() and raw is None:
            state = "invalid-raw"
        elif raw is not None:
            state = "complete"
        elif checkpoint_path.exists() and checkpoint is None:
            state = "invalid-checkpoint"
        elif checkpoint is not None:
            checkpoint_state = str(checkpoint.get("status") or "unknown")
            if checkpoint_state == "running":
                state = "running" if _checkpoint_process_alive(checkpoint_path) else "interrupted"
            else:
                state = checkpoint_state
        elif isinstance(reservation, dict):
            state = "reserved"
        else:
            state = "queued"
        # A manifest acceptance only upgrades *this run's own* completed cell to
        # "accepted"; it never substitutes for the current run/cap's raw
        # artifact, so a stale or wrong-cap manifest entry cannot mask a cell
        # that this run directory has not actually produced.
        if (
            run_state.get("phase") == "smoke"
            and state == "complete"
            and smoke_accepted
            and manifest_entry.get("output_token_cap") == cap
        ):
            state = "accepted"

        completed, total, completed_decisions, total_decisions = _expected_progress(run_state, checkpoint, raw)
        if state in {"complete", "accepted"} and total is not None:
            completed = total
            completed_decisions = total_decisions or completed_decisions
        mtimes = [path.stat().st_mtime for path in (checkpoint_path, raw_path) if path.exists()]
        rows.append(
            {
                "model_id": model_id,
                "model": model.get("model"),
                "state": state,
                "smoke_accepted": smoke_accepted,
                "completed_episodes": completed,
                "total_episodes": total,
                "completed_decisions": completed_decisions,
                "total_decisions": total_decisions,
                "cost_usd": _payload_cost_usd(raw or checkpoint),
                "reserved_usd": (
                    float(reservation["reserved_usd"])
                    if isinstance(reservation, dict) and reservation.get("reserved_usd") is not None
                    else None
                ),
                "updated_at_epoch": max(mtimes) if mtimes else None,
                "error": checkpoint.get("error") if isinstance(checkpoint, dict) else None,
            }
        )

    artifact_spend = _artifact_spend_usd(run_dir)
    reserved_spend = sum(
        float(value.get("reserved_usd") or 0.0) for value in reservations.values() if isinstance(value, dict)
    )
    return {
        "format": "gm-bench-publication-status-v1",
        "run_dir": str(run_dir),
        "phase": run_state.get("phase") or "unknown",
        "output_token_cap": run_state.get("output_token_cap") or cap,
        "started_at_utc": run_state.get("started_at_utc"),
        "spend_ceiling_usd": run_state.get("spend_ceiling_usd"),
        "artifact_spend_usd": round(artifact_spend, 6),
        "reserved_spend_usd": round(reserved_spend, 6),
        "total_cells": len(rows),
        "accepted_smokes": sum(row["smoke_accepted"] for row in rows),
        "active_cells": sum(row["state"] == "running" for row in rows),
        "completed_cells": sum(row["state"] in {"complete", "accepted"} for row in rows),
        "rows": rows,
    }


def _format_progress(completed: int, total: int | None) -> str:
    return f"{completed}/{total}" if total is not None else str(completed)


def _format_age(timestamp: float | None) -> str:
    if timestamp is None:
        return "-"
    seconds = max(0, int(time.time() - timestamp))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def render_publication_status(status: dict[str, Any]) -> str:
    ceiling = status.get("spend_ceiling_usd")
    ceiling_text = f"${float(ceiling):.4f}" if ceiling is not None else "not recorded"
    lines = [
        "GM-Bench publication run",
        f"dir: {status['run_dir']}",
        (
            f"phase: {status['phase']}  cap: {status['output_token_cap']}  "
            f"active: {status['active_cells']}  "
            f"complete: {status['completed_cells']}/{status['total_cells']}  "
            f"accepted smokes: {status['accepted_smokes']}/{status['total_cells']}"
        ),
        (
            f"spend: ${status['artifact_spend_usd']:.4f} in artifacts  "
            f"${status['reserved_spend_usd']:.4f} reserved  ceiling: {ceiling_text}"
        ),
        "",
        f"{'MODEL':<42} {'STATE':<18} {'EPISODES':>9} {'DECISIONS':>10} {'COST':>9} {'UPDATED':>8}",
        "-" * 102,
    ]
    for row in status["rows"]:
        cost = f"${row['cost_usd']:.4f}" if row["cost_usd"] is not None else "-"
        lines.append(
            f"{row['model_id'][:42]:<42} {row['state']:<18} "
            f"{_format_progress(row['completed_episodes'], row['total_episodes']):>9} "
            f"{_format_progress(row['completed_decisions'], row['total_decisions']):>10} "
            f"{cost:>9} {_format_age(row['updated_at_epoch']):>8}"
        )
        if row.get("error"):
            lines.append(f"  error: {str(row['error']).splitlines()[0][:92]}")
    return "\n".join(lines)


def _status_command(run_dir: Path, manifest_path: Path, *, watch: bool, interval: float, as_json: bool) -> int:
    try:
        while True:
            status = publication_run_status(run_dir, manifest_path)
            rendered = json.dumps(status, sort_keys=True) if as_json else render_publication_status(status)
            if watch and sys.stdout.isatty() and not as_json:
                print("\033[2J\033[H", end="")
            print(rendered, flush=True)
            if not watch:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
        return 0


def _record_smoke_issues(
    artifact: dict[str, Any],
    model_id: str,
    registry: dict[str, Any],
    lane: dict[str, Any],
) -> tuple[list[str], dict[str, Any] | None]:
    models = [model for model in registry.get("models") or [] if isinstance(model, dict)]
    entry = next((model for model in models if model.get("id") == model_id), None)
    if entry is None:
        return [f"unknown model id: {model_id}"], None

    issues: list[str] = []
    run_info = artifact.get("run_info")
    run_info = run_info if isinstance(run_info, dict) else {}
    if run_info.get("provider") != entry.get("provider"):
        issues.append("artifact provider does not match the registered provider")
    if run_info.get("model") != entry.get("model"):
        issues.append("artifact model does not match the registered model")
    if run_info.get("preset") != "smoke":
        issues.append("artifact preset must be 'smoke'")
    if run_info.get("profile") != registry.get("profile"):
        issues.append("artifact profile does not match the registered profile")

    smoke = PRESETS["smoke"]
    expected_seeds = list(smoke["seeds"])
    expected_seasons = int(smoke["seasons"])
    expected_decisions = len(expected_seeds) * expected_seasons * len(PHASES)
    if artifact.get("publication") is not None:
        issues.append("artifact must be the original raw smoke result, not a compact publication artifact")
    if artifact.get("seeds") != expected_seeds:
        issues.append(f"artifact seeds must match the smoke preset: {expected_seeds}")
    if artifact.get("seasons") != expected_seasons:
        issues.append(f"artifact seasons must match the smoke preset: {expected_seasons}")

    provider_options = run_info.get("provider_options")
    provider_options = provider_options if isinstance(provider_options, dict) else {}
    expected_options = {
        **_registered_fixed_options(registry, entry),
    }
    for key, value in expected_options.items():
        if provider_options.get(key) != value:
            issues.append(f"artifact provider option {key} does not match the registered value")
    for key in _registered_absent_options(registry, entry):
        if provider_options.get(key) not in (None, ""):
            issues.append(f"artifact provider option {key} must be absent")

    frozen_cap = lane.get("output_token_cap")
    if provider_options.get("GM_BENCH_OUTPUT_BUDGET_CELL") != str(frozen_cap):
        issues.append("artifact output-budget cell does not match the frozen cap")
    benchmark_contract = run_info.get("benchmark_contract")
    benchmark_contract = benchmark_contract if isinstance(benchmark_contract, dict) else {}
    current_contract = contract_fingerprint()
    current_scaffold = scaffold_fingerprint(str(entry.get("provider") or ""))
    if benchmark_contract.get("contract_fingerprint") != current_contract:
        issues.append("artifact was recorded under a different benchmark contract")
    if run_info.get("scaffold_fingerprint") != current_scaffold:
        issues.append("artifact was recorded under a different prompt scaffold")

    candidate = artifact.get("candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    if candidate.get("repeats") != 1:
        issues.append("artifact candidate repeats must be one for the smoke preset")
    if candidate.get("seasons") != expected_seasons:
        issues.append(f"artifact candidate seasons must be {expected_seasons}")
    episodes = candidate.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != len(expected_seeds):
        issues.append(f"artifact candidate must contain {len(expected_seeds)} complete smoke episode(s)")
    else:
        expected_pairs = {(seed, 1) for seed in expected_seeds}
        observed_pairs = {
            (episode.get("seed"), episode.get("repeat", 1)) for episode in episodes if isinstance(episode, dict)
        }
        if observed_pairs != expected_pairs:
            issues.append("artifact candidate episodes do not match the smoke seed/repeat panel")
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            if episode.get("seasons") != expected_seasons:
                issues.append("artifact candidate episode has the wrong season count")
            if episode.get("decisions") != expected_seasons * len(PHASES):
                issues.append("artifact candidate episode does not contain every smoke decision point")
            if episode.get("failed_decisions") != 0:
                issues.append("artifact candidate episode contains failed decisions")
    summary = candidate.get("summary") or {}
    summary = summary if isinstance(summary, dict) else {}
    if summary.get("decisions") != expected_decisions:
        issues.append(f"artifact candidate summary decisions must be {expected_decisions}")
    if summary.get("failed_decisions") != 0:
        issues.append("artifact candidate summary failed_decisions must be zero")
    if summary.get("decision_failure_rate") != 0:
        issues.append("artifact decision_failure_rate must be zero")
    usage = summary.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    if usage.get("decisions_with_usage") != expected_decisions:
        issues.append(f"artifact usage must cover all {expected_decisions} smoke decision points")
    if usage.get("cost_decisions") != expected_decisions:
        issues.append(f"artifact cost telemetry must cover all {expected_decisions} smoke decision points")
    for key in ("provider", "model"):
        if usage.get(key) != entry.get(key):
            issues.append(f"artifact usage {key} does not match the registered route")
    repair_attempts = usage.get("protocol_repair_attempts", 0)
    repair_successes = usage.get("protocol_repairs_succeeded", 0)
    if not isinstance(repair_attempts, int) or isinstance(repair_attempts, bool) or repair_attempts < 0:
        issues.append("artifact protocol_repair_attempts must be a non-negative integer")
        repair_attempts = 0
    if repair_successes != repair_attempts:
        issues.append("artifact successful protocol repairs must match repair attempts")
    api_calls = usage.get("api_calls")
    minimum_api_calls = expected_decisions + repair_attempts
    if not isinstance(api_calls, int) or isinstance(api_calls, bool) or api_calls < minimum_api_calls:
        issues.append(f"artifact must record at least {minimum_api_calls} API calls for its decisions and repairs")
    calls_with_finish_reason = usage.get("calls_with_finish_reason")
    if calls_with_finish_reason != api_calls:
        issues.append("artifact finish-reason telemetry must cover every API call")
    truncated_calls = usage.get("truncated_calls")
    if truncated_calls != 0:
        issues.append("artifact shows cap-induced truncation")
    reasoning_tokens = usage.get("reasoning_tokens")
    if entry.get("reasoning_policy") == "disabled" and reasoning_tokens not in (None, 0):
        issues.append("artifact recorded reasoning tokens for a reasoning-disabled model")
    if entry.get("reasoning_policy") == "mandatory-minimum" and (
        not isinstance(reasoning_tokens, int) or isinstance(reasoning_tokens, bool) or reasoning_tokens < 0
    ):
        issues.append("artifact is missing reasoning-token telemetry for a mandatory-reasoning model")
    max_output = usage.get("max_output_tokens_per_call")
    threshold = lane.get("cap_pressure_threshold_tokens")
    if not isinstance(max_output, int) or isinstance(max_output, bool):
        issues.append("artifact is missing max_output_tokens_per_call")
    elif isinstance(threshold, int) and max_output >= threshold:
        issues.append(
            f"artifact peaked at {max_output} output tokens, at or above the {threshold}-token cap-pressure threshold"
        )
    observed_upstreams = usage.get("upstream_providers")
    expected_upstream = str(entry.get("upstream_provider") or "").casefold()
    if (
        not isinstance(observed_upstreams, list)
        or len(observed_upstreams) != 1
        or not isinstance(observed_upstreams[0], str)
        or observed_upstreams[0].casefold() != expected_upstream
    ):
        issues.append("artifact upstream provider does not match the registered route")
    return issues, entry


def _record_smoke(model_id: str, artifact_path: Path, manifest_path: Path) -> int:
    try:
        artifact_bytes = artifact_path.read_bytes()
        artifact = json.loads(artifact_bytes)
        if not isinstance(artifact, dict):
            raise ValueError("artifact must contain a JSON object")
        registry = _read_json(PANEL_CONFIG)
        lane = _read_json(LANE_CONFIG)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"record-smoke: {exc}", file=sys.stderr)
        return 1

    issues, entry = _record_smoke_issues(artifact, model_id, registry, lane)
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    assert entry is not None

    if manifest_path.exists():
        try:
            manifest = _read_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"record-smoke: cannot update existing manifest: {exc}", file=sys.stderr)
            return 1
        if manifest.get("format") != SMOKE_MANIFEST_FORMAT or not isinstance(manifest.get("entries"), dict):
            print("record-smoke: existing manifest has an unsupported format", file=sys.stderr)
            return 1
    else:
        manifest = {"format": SMOKE_MANIFEST_FORMAT, "schema_version": 1, "entries": {}}

    usage = artifact["candidate"]["summary"]["usage"]
    run_info = artifact["run_info"]
    manifest["entries"][model_id] = {
        "provider": entry["provider"],
        "model": entry["model"],
        "upstream_provider": entry["upstream_provider"],
        "upstream_provider_slug": entry["upstream_provider_slug"],
        "endpoint_tag": entry["endpoint_tag"],
        "endpoint_name": entry["endpoint_name"],
        "output_token_cap": int(lane["output_token_cap"]),
        "api_calls": usage["api_calls"],
        "calls_with_finish_reason": usage["calls_with_finish_reason"],
        "decisions_with_usage": usage["decisions_with_usage"],
        "cost_decisions": usage["cost_decisions"],
        "protocol_repair_attempts": usage.get("protocol_repair_attempts", 0),
        "protocol_repairs_succeeded": usage.get("protocol_repairs_succeeded", 0),
        "truncated_calls": usage["truncated_calls"],
        "max_output_tokens_per_call": usage["max_output_tokens_per_call"],
        "reasoning_tokens": usage.get("reasoning_tokens") or 0,
        "reasoning_policy": entry["reasoning_policy"],
        "reasoning_effort": entry.get("reasoning_effort"),
        "decision_failure_rate": artifact["candidate"]["summary"]["decision_failure_rate"],
        "contract_fingerprint": run_info["benchmark_contract"]["contract_fingerprint"],
        "scaffold_fingerprint": run_info["scaffold_fingerprint"],
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "artifact_path": str(artifact_path),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "accepted": True,
    }
    _write_json_atomic(manifest_path, manifest)
    print(f"recorded accepted smoke for {model_id} in {manifest_path}")
    return 0


def _reusable_smoke_artifact(cell: Cell, run_dir: Path) -> Path | None:
    """Return an existing raw smoke only when it still passes the current gate."""
    artifact_path = run_dir / "raw" / f"{cell.experiment_id}--{cell.cap_label}.json"
    try:
        artifact = _read_json(artifact_path)
        registry = _read_json(PANEL_CONFIG)
        lane = _read_json(LANE_CONFIG)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    issues, _entry = _record_smoke_issues(artifact, cell.experiment_id, registry, lane)
    return artifact_path if not issues else None


def _reserve_cell(run_dir: Path, cell: Cell, measured_spend: float, ceiling: float) -> float:
    path = run_dir / "openrouter-reservations.json"
    payload = _read_json(path) if path.exists() else {"schema_version": 1, "cells": {}}
    reservations = payload.setdefault("cells", {})
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    # Only unsettled attempts remain a conservative liability. Successful
    # cells are replaced by their measured account/artifact spend so historical
    # worst-case reservations cannot prematurely stop a healthy serial panel.
    reserved_total = sum(
        float(value["reserved_usd"]) for value in reservations.values() if value.get("status") != "settled"
    )
    reservation = _cell_reservation_usd(cell)
    if stem in reservations:
        committed = measured_spend + reserved_total
        if committed + reservation > ceiling:
            raise SystemExit(
                f"retry reservation would exceed spend ceiling: ${committed:.4f} + ${reservation:.4f} > ${ceiling:.4f}"
            )
        stored = reservations[stem]
        stored["reserved_usd"] = (
            float(stored.get("reserved_usd") or 0) + reservation if stored.get("status") != "settled" else reservation
        )
        stored["total_reserved_usd"] = float(stored.get("total_reserved_usd") or 0) + reservation
        stored["attempts"] = int(stored.get("attempts") or 1) + 1
        stored["status"] = "active"
        stored.pop("settled_at_utc", None)
        stored.pop("measured_run_spend_usd", None)
        _write_json_atomic(path, payload)
        print(
            f"reserved retry ${reservation:.4f} for {stem}; "
            f"cumulative conservative commitment ${committed + reservation:.4f}"
        )
        return committed + reservation
    committed = measured_spend + reserved_total
    if committed + reservation > ceiling:
        raise SystemExit(
            f"cell reservation would exceed spend ceiling: ${committed:.4f} + ${reservation:.4f} > ${ceiling:.4f}"
        )
    reservations[stem] = {
        "experiment_id": cell.experiment_id,
        "model": cell.model,
        "output_token_cap": cell.cap,
        "reserved_usd": reservation,
        "total_reserved_usd": reservation,
        "attempts": 1,
        "status": "active",
    }
    _write_json_atomic(path, payload)
    print(f"reserved ${reservation:.4f} for {stem}; cumulative conservative commitment ${committed + reservation:.4f}")
    return committed + reservation


def _settle_cell_reservation(run_dir: Path, cell: Cell, measured_spend: float) -> None:
    """Release a successful cell's worst-case reservation in favor of measured spend."""
    path = run_dir / "openrouter-reservations.json"
    if not path.exists():
        return
    payload = _read_json(path)
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    stored = (payload.get("cells") or {}).get(stem)
    if not isinstance(stored, dict):
        return
    stored["reserved_usd"] = 0.0
    stored["status"] = "settled"
    stored["settled_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stored["measured_run_spend_usd"] = measured_spend
    _write_json_atomic(path, payload)


def _print_command(cell: Cell, command: list[str]) -> None:
    options = {**cell.fixed_options, "GM_BENCH_OUTPUT_BUDGET_CELL": cell.cap_label, "GM_BENCH_WORKERS": "1"}
    if cell.provider == "openrouter" and cell.cap is not None:
        options["OPENROUTER_MAX_TOKENS"] = str(cell.cap)
    print(json.dumps({"cell": cell.experiment_id, "cap": cell.cap_label, "env": options, "command": command}))


def main(argv: list[str] | None = None) -> int:
    # The child CLI loads these files too, but the parent needs the provider key
    # to query account usage and enforce the operator's spend ceiling before it
    # launches any model process.
    load_environment_files(ROOT)
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["smoke", "sweep", "panel", "record-smoke", "status"])
    parser.add_argument("--model-id")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--manifest", type=Path, default=SMOKE_MANIFEST)
    parser.add_argument("--cap", type=int)
    parser.add_argument("--run-dir", type=Path, default=Path("data/publication-runs"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--max-spend-usd", type=float)
    parser.add_argument("--watch", action="store_true", help="refresh publication status until interrupted")
    parser.add_argument("--interval", type=float, default=2.0, help="watch refresh interval in seconds")
    parser.add_argument("--json", action="store_true", help="emit status as JSON")
    args = parser.parse_args(argv)
    if args.phase == "status":
        if args.interval <= 0:
            parser.error("--interval must be positive")
        return _status_command(args.run_dir, args.manifest, watch=args.watch, interval=args.interval, as_json=args.json)
    if args.phase == "record-smoke":
        if not args.model_id:
            parser.error("record-smoke requires --model-id")
        if args.artifact is None:
            parser.error("record-smoke requires --artifact")
        return _record_smoke(args.model_id, args.artifact, args.manifest)
    if args.max_spend_usd is not None and args.max_spend_usd <= 0:
        parser.error("--max-spend-usd must be positive")
    try:
        cells = build_cells(args.phase, args.model_id, args.cap)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.phase == "sweep" and not args.dry_run and not args.preflight_only:
        sweep_status = str(_read_json(SWEEP_CONFIG).get("status") or "")
        if sweep_status != "awaiting-runs":
            parser.error(f"paid sweep is locked while config/output_budget_sweep.json status is {sweep_status!r}")
    if (
        not args.dry_run
        and not args.preflight_only
        and any(cell.provider == "openrouter" for cell in cells)
        and args.max_spend_usd is None
    ):
        parser.error("paid OpenRouter runs require an explicit --max-spend-usd ceiling")
    run_dir = args.run_dir.resolve()
    for directory in (run_dir / "raw", run_dir / "checkpoints"):
        if not args.dry_run:
            directory.mkdir(parents=True, exist_ok=True)
    if not args.dry_run and not args.preflight_only:
        _write_run_state(run_dir, args.phase, cells, args.max_spend_usd)
    budget_start: float | None = None
    for cell in cells:
        env = cell_environment(cell)
        command = cell_command(cell, run_dir, preflight=args.preflight_only)
        _print_command(cell, command)
        if args.dry_run:
            continue
        if args.phase == "smoke" and not args.preflight_only:
            reusable = _reusable_smoke_artifact(cell, run_dir)
            if reusable is not None:
                print(f"reusing clean completed smoke without another reservation or provider call: {reusable}")
                continue
        if cell.provider == "openrouter":
            try:
                _validate_openrouter_endpoint(cell)
            except (
                RuntimeError,
                urllib.error.URLError,
                TimeoutError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
            ) as exc:
                raise SystemExit(f"OpenRouter endpoint preflight failed for {cell.experiment_id}: {exc}") from exc
        if args.max_spend_usd is not None and cell.provider == "openrouter":
            budget_start = budget_start if budget_start is not None else _budget_start(run_dir, env)
            spent = _measured_spend_usd(run_dir, env, budget_start)
            if spent >= args.max_spend_usd:
                raise SystemExit(f"spend ceiling reached: ${spent:.4f} >= ${args.max_spend_usd:.4f}")
            _reserve_cell(run_dir, cell, spent, args.max_spend_usd)
        cell_succeeded = False
        try:
            try:
                subprocess.run(command, cwd=ROOT, env=env, check=True)
                cell_succeeded = True
            except subprocess.CalledProcessError as exc:
                raise SystemExit(
                    f"publication cell failed: {cell.experiment_id} cap={cell.cap_label} exit={exc.returncode}"
                ) from exc
        finally:
            # Provider failures are exactly when spend visibility matters most.
            # Report the post-cell delta even when the child exits nonzero.
            if args.max_spend_usd is not None and cell.provider == "openrouter":
                spent = _measured_spend_usd(run_dir, env, float(budget_start))
                if cell_succeeded:
                    _settle_cell_reservation(run_dir, cell, spent)
                print(f"measured OpenRouter spend for this run directory: ${spent:.4f}")
                if spent > args.max_spend_usd:
                    raise SystemExit(f"spend ceiling exceeded after attempted cell: ${spent:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
