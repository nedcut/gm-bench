#!/usr/bin/env python3
"""Run the pre-registered GM-Bench publication matrix one serial cell at a time.

The driver is intentionally conservative: it never fans out model calls, writes
one atomic artifact and checkpoint per cell, validates configuration provenance,
and can stop against a cumulative OpenRouter spend ceiling. Use ``--dry-run`` to
inspect every command and environment value without contacting a provider.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SWEEP_CONFIG = ROOT / "config" / "output_budget_sweep.json"
PANEL_CONFIG = ROOT / "config" / "sota_v2_models.json"
LANE_CONFIG = ROOT / "config" / "sota_v2_lane.json"
PRICING_CONFIG = ROOT / "config" / "openrouter_pricing_snapshot.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRESETS  # noqa: E402
from gm_bench.protocol import PHASES  # noqa: E402


@dataclass(frozen=True)
class Cell:
    experiment_id: str
    provider: str
    model: str
    profile: str
    preset: str
    repeats: int
    cap: int | None
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


def _validate_models(models: list[dict[str, Any]]) -> None:
    if not models:
        raise ValueError("publication matrix contains no models")
    ids = [str(model.get("id") or "") for model in models]
    identities = [(str(model.get("provider") or ""), str(model.get("model") or "")) for model in models]
    if any(not value for value in ids) or any(not provider or not model for provider, model in identities):
        raise ValueError("every model requires non-empty id, provider, and model")
    if len(set(ids)) != len(ids) or len(set(identities)) != len(identities):
        raise ValueError("publication model ids and provider/model identities must be unique")


def build_cells(phase: str, model_id: str | None = None, cap: int | None = None) -> list[Cell]:
    if phase == "smoke":
        config = _read_json(PANEL_CONFIG)
        lane = _read_json(LANE_CONFIG)
        models = list(config.get("models") or [])
        _validate_models(models)
        frozen_cap = lane.get("output_token_cap")
        if lane.get("output_policy_basis") != "fixed-safety-ceiling":
            raise ValueError("panel smoke is locked until the fixed safety ceiling is frozen")
        if not isinstance(frozen_cap, int) or frozen_cap < 1:
            raise ValueError("panel smoke requires a positive frozen output_token_cap")
        if cap is not None and cap != frozen_cap:
            raise ValueError(f"requested cap {cap} differs from frozen panel smoke cap {frozen_cap}")
        shared = {str(key): str(value) for key, value in (config.get("shared_fixed_options") or {}).items()}
        cells = [
            Cell(
                experiment_id=str(model["id"]),
                provider=str(model["provider"]),
                model=str(model["model"]),
                profile=str(config["profile"]),
                preset="smoke",
                repeats=1,
                cap=frozen_cap,
                endpoint_name=str(model.get("endpoint_name") or ""),
                fixed_options={
                    **shared,
                    "OPENROUTER_PROVIDER_ONLY": str(model["upstream_provider"]),
                    "OPENROUTER_EXPECTED_ENDPOINT_NAME": str(model["endpoint_name"]),
                },
                absent_options=tuple(str(value) for value in config.get("shared_absent_options") or []),
            )
            for model in models
        ]
    elif phase == "sweep":
        config = _read_json(SWEEP_CONFIG)
        models = list(config.get("models") or [])
        _validate_models(models)
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
        if lane.get("output_budget_status") not in {"frozen-saturation", "frozen-fixed-budget"}:
            raise ValueError("full panel is locked until config/sota_v2_lane.json freezes the output-budget policy")
        if config.get("selection_status") != "frozen":
            raise ValueError("full panel is locked until config/sota_v2_models.json freezes the model registry")
        if not isinstance(frozen_cap, int) or frozen_cap < 1:
            raise ValueError("full panel requires a positive frozen output_token_cap")
        if cap is not None and cap != frozen_cap:
            raise ValueError(f"requested cap {cap} differs from frozen panel cap {frozen_cap}")
        shared = {str(key): str(value) for key, value in (config.get("shared_fixed_options") or {}).items()}
        cells = [
            Cell(
                experiment_id=str(model["id"]),
                provider=str(model["provider"]),
                model=str(model["model"]),
                profile=str(config["profile"]),
                preset=str(config["preset"]),
                repeats=int(config["repeats"]),
                cap=frozen_cap,
                endpoint_name=str(model.get("endpoint_name") or ""),
                fixed_options={
                    **shared,
                    "OPENROUTER_PROVIDER_ONLY": str(model["upstream_provider"]),
                    "OPENROUTER_EXPECTED_ENDPOINT_NAME": str(model["endpoint_name"]),
                },
                absent_options=tuple(str(value) for value in config.get("shared_absent_options") or []),
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
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint
        payload = json.load(response)
    return float(payload["data"]["total_usage"])


def _endpoint_issues(cell: Cell, payload: dict[str, Any]) -> list[str]:
    endpoints = (payload.get("data") or {}).get("endpoints") or []
    expected_provider = cell.fixed_options.get("OPENROUTER_PROVIDER_ONLY", "")
    matches = [
        endpoint
        for endpoint in endpoints
        if endpoint.get("provider_name") == expected_provider
        and endpoint.get("name") == cell.endpoint_name
        and endpoint.get("status") == 0
    ]
    if not cell.endpoint_name:
        return ["pre-registered OpenRouter endpoint_name is empty"]
    if not matches:
        return [f"no healthy OpenRouter endpoint matches provider={expected_provider!r} name={cell.endpoint_name!r}"]
    required = {"max_tokens", "response_format", "reasoning"}
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
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint
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


def _reserve_cell(run_dir: Path, cell: Cell, measured_spend: float, ceiling: float) -> float:
    path = run_dir / "openrouter-reservations.json"
    payload = _read_json(path) if path.exists() else {"schema_version": 1, "cells": {}}
    reservations = payload.setdefault("cells", {})
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    reserved_total = sum(float(value["reserved_usd"]) for value in reservations.values())
    if stem in reservations:
        committed = max(measured_spend, reserved_total)
        if committed > ceiling:
            raise SystemExit(f"spend ceiling exceeded by existing reservations: ${committed:.4f}")
        return committed
    reservation = _cell_reservation_usd(cell)
    committed = max(measured_spend, reserved_total)
    if committed + reservation > ceiling:
        raise SystemExit(
            f"cell reservation would exceed spend ceiling: ${committed:.4f} + ${reservation:.4f} > ${ceiling:.4f}"
        )
    reservations[stem] = {
        "experiment_id": cell.experiment_id,
        "model": cell.model,
        "output_token_cap": cell.cap,
        "reserved_usd": reservation,
    }
    _write_json_atomic(path, payload)
    print(f"reserved ${reservation:.4f} for {stem}; cumulative conservative commitment ${committed + reservation:.4f}")
    return committed + reservation


def _print_command(cell: Cell, command: list[str]) -> None:
    options = {**cell.fixed_options, "GM_BENCH_OUTPUT_BUDGET_CELL": cell.cap_label, "GM_BENCH_WORKERS": "1"}
    if cell.provider == "openrouter" and cell.cap is not None:
        options["OPENROUTER_MAX_TOKENS"] = str(cell.cap)
    print(json.dumps({"cell": cell.experiment_id, "cap": cell.cap_label, "env": options, "command": command}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["smoke", "sweep", "panel"])
    parser.add_argument("--model-id")
    parser.add_argument("--cap", type=int)
    parser.add_argument("--run-dir", type=Path, default=Path("data/publication-runs"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--max-spend-usd", type=float)
    args = parser.parse_args(argv)
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
    budget_start: float | None = None
    for cell in cells:
        env = cell_environment(cell)
        command = cell_command(cell, run_dir, preflight=args.preflight_only)
        _print_command(cell, command)
        if args.dry_run:
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
        try:
            try:
                subprocess.run(command, cwd=ROOT, env=env, check=True)
            except subprocess.CalledProcessError as exc:
                raise SystemExit(
                    f"publication cell failed: {cell.experiment_id} cap={cell.cap_label} exit={exc.returncode}"
                ) from exc
        finally:
            # Provider failures are exactly when spend visibility matters most.
            # Report the post-cell delta even when the child exits nonzero.
            if args.max_spend_usd is not None and cell.provider == "openrouter":
                spent = _measured_spend_usd(run_dir, env, float(budget_start))
                print(f"measured OpenRouter spend for this run directory: ${spent:.4f}")
                if spent > args.max_spend_usd:
                    raise SystemExit(f"spend ceiling exceeded after attempted cell: ${spent:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
