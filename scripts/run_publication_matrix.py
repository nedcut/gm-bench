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
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SWEEP_CONFIG = ROOT / "config" / "output_budget_sweep.json"
PANEL_CONFIG = ROOT / "config" / "sota_v2_models.json"
LANE_CONFIG = ROOT / "config" / "sota_v2_lane.json"
PRICING_CONFIG = ROOT / "config" / "openrouter_pricing_snapshot.json"
PROTOCOL_CONFIG = ROOT / "config" / "publication_protocol.json"
SMOKE_MANIFEST = ROOT / "config" / "sota_v2_smoke_manifest.json"
RUN_STATE_FORMAT = "gm-bench-publication-run-v1"
CALL_SPEND_GUARD_STATE = "openrouter-call-spend-guard.json"
SPEND_RECONCILIATION = "openrouter-spend-reconciliation.json"
PAID_RUN_LOCK = ".openrouter-paid-run.lock"
# Availability floors for a pinned endpoint to stay eligible.
#
# Two windows, because they detect different failures. The 24h figure is a
# chronic filter and is far too slow to see an outage: on 2026-08-04 the
# first-party DeepSeek route was deranked to status -5 while still reporting
# 99.24% over 24h. The 30m figure is what moved (78.93%), so that is the
# acute gate.
#
# Both floors sit well below the noise band. These readings drift by half a
# point between consecutive polls, so a threshold set near the observed values
# would block healthy routes at random -- a 99% 24h floor rejected two
# perfectly healthy cohort members on the day it was written while still
# passing the route that had actually failed.
MIN_UPTIME_LAST_30M_PCT = 90.0
MIN_UPTIME_LAST_1D_PCT = 95.0
CONTRACT_CONFIGS = {
    "sota-v2": (
        ROOT / "config" / "sota_v2_models.json",
        ROOT / "config" / "sota_v2_lane.json",
        ROOT / "config" / "sota_v2_smoke_manifest.json",
        ROOT / "config" / "publication_protocol.json",
        ROOT / "config" / "openrouter_pricing_snapshot.json",
    ),
    "sota-v3": (
        ROOT / "config" / "sota_v3_models.json",
        ROOT / "config" / "sota_v3_lane.json",
        ROOT / "config" / "sota_v3_smoke_manifest.json",
        ROOT / "config" / "sota_v3_publication_protocol.json",
        ROOT / "config" / "sota_v3_pricing_snapshot.json",
    ),
    "sota-v4": (
        ROOT / "config" / "sota_v4_models.json",
        ROOT / "config" / "sota_v4_lane.json",
        ROOT / "config" / "sota_v4_smoke_manifest.json",
        ROOT / "config" / "sota_v4_publication_protocol.json",
        ROOT / "config" / "sota_v4_pricing_snapshot.json",
    ),
}
# Publication contracts that share the private-panel, strict-smoke execution
# capabilities introduced in v3. Keep this explicit: contract names are
# identifiers, not versions that may safely be ordered lexicographically.
STRICT_PRIVATE_PANEL_CONTRACTS = frozenset({"sota-v3", "sota-v4"})
AUTHENTICATED_ROUTE_CONTRACTS = frozenset({"sota-v3", "sota-v4"})

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import (  # noqa: E402
    PRESETS,
    PRIVATE_SEEDS_ENV,
    seed_panel_hash,
)
from gm_bench.contract import BENCHMARK_VERSION, contract_fingerprint, scaffold_fingerprint  # noqa: E402
from gm_bench.environment import load_environment_files  # noqa: E402
from gm_bench.official import POLICIES, validate_leaderboard_payload  # noqa: E402
from gm_bench.protocol import PHASES  # noqa: E402
from gm_bench.providers import (  # noqa: E402
    OPENROUTER_CANONICAL_API_BASE,
    SPEND_GUARD_ENV_PREFIX,
)
from gm_bench.publication import (  # noqa: E402
    SMOKE_MANIFEST_FORMAT,
    is_pending_strict_smoke_cap,
    publication_execution_issues,
    smoke_manifest_issues,
)


@dataclass(frozen=True)
class Cell:
    experiment_id: str
    provider: str
    model: str
    profile: str
    preset: str
    repeats: int
    seed_count: int | None
    cap: int | None
    upstream_provider: str
    endpoint_tag: str
    endpoint_name: str
    output_cap_verification: dict[str, Any]
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


def _select_contract_config(contract: str) -> None:
    """Select one explicitly named publication lane for this CLI process."""
    global LANE_CONFIG, PANEL_CONFIG, PRICING_CONFIG, PROTOCOL_CONFIG, SMOKE_MANIFEST
    PANEL_CONFIG, LANE_CONFIG, SMOKE_MANIFEST, PROTOCOL_CONFIG, PRICING_CONFIG = CONTRACT_CONFIGS[contract]


def _require_current_publication_contract() -> None:
    registry = _read_json(PANEL_CONFIG)
    lane = _read_json(LANE_CONFIG)
    registry_contract = registry.get("contract")
    lane_contract = lane.get("contract")
    if registry_contract != BENCHMARK_VERSION or lane_contract != BENCHMARK_VERSION:
        raise ValueError(
            "the committed publication registry/lane are frozen historical evidence "
            f"({registry_contract!r}/{lane_contract!r}); current code is {BENCHMARK_VERSION!r}. "
            "Create and pre-register a new contract lane before recording smokes or running a panel."
        )
    expected_fingerprint = contract_fingerprint()
    for label, payload in (("registry", registry), ("lane", lane)):
        declared_fingerprint = payload.get("contract_fingerprint")
        if declared_fingerprint is not None and declared_fingerprint != expected_fingerprint:
            raise ValueError(
                f"the selected publication {label} targets contract fingerprint "
                f"{declared_fingerprint!r}, but current source is {expected_fingerprint!r}"
            )


def _require_execution_authorized(phase: str, registry: dict[str, Any], lane: dict[str, Any]) -> None:
    """Apply the shared authorization gate before building provider cells."""
    manifest = _read_optional_json(_smoke_manifest_path(lane))
    issues = publication_execution_issues(
        lane,
        registry,
        manifest,
        phase=phase,
        protocol=_read_optional_json(PROTOCOL_CONFIG),
        pricing=_read_optional_json(PRICING_CONFIG),
    )
    if issues:
        raise ValueError("; ".join(issues))


def _parse_private_seed_env(value: str) -> list[int]:
    seeds: list[int] = []
    for part in value.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            seeds.extend(range(int(start_text), int(end_text) + 1))
        else:
            seeds.append(int(part))
    if not seeds:
        raise ValueError(f"{PRIVATE_SEEDS_ENV} must contain at least one seed")
    return seeds


def _validate_frozen_seed_panel(lane: dict[str, Any]) -> None:
    """Bind a paid run to its frozen public/private panel before cells exist."""
    panel = lane.get("seed_panel")
    if not isinstance(panel, dict) or panel.get("status") != "frozen":
        raise ValueError("publication seed panel identity must be frozen before paid smoke or panel execution")
    name = panel.get("name")
    count = panel.get("count")
    declared_hash = panel.get("sha256")
    if (
        name not in {"public-leaderboard", "private-env"}
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 2
        or not isinstance(declared_hash, str)
        or len(declared_hash) != 64
    ):
        raise ValueError("publication seed panel must declare a valid name, count, and sha256")
    inherited = os.environ.get(PRIVATE_SEEDS_ENV)
    if name == "public-leaderboard":
        if inherited:
            raise ValueError(
                f"{PRIVATE_SEEDS_ENV} must be unset for the frozen public panel; refusing inherited seed drift"
            )
        seeds = list(PRESETS["leaderboard"]["seeds"])
    else:
        if not inherited:
            raise ValueError(f"{PRIVATE_SEEDS_ENV} is required for the frozen private panel")
        try:
            seeds = _parse_private_seed_env(inherited)
        except ValueError as exc:
            raise ValueError(f"invalid {PRIVATE_SEEDS_ENV}: {exc}") from exc
    if len(set(seeds)) != len(seeds):
        raise ValueError("publication seed panel must contain unique seeds")
    if len(seeds) != count or seed_panel_hash(seeds) != declared_hash:
        raise ValueError(
            f"{PRIVATE_SEEDS_ENV if name == 'private-env' else 'public leaderboard preset'} "
            "does not match the frozen seed panel identity"
        )


def _validate_models(
    models: list[dict[str, Any]],
    *,
    exact_routes: bool = True,
    expected_provider: str | None = None,
) -> None:
    if not models:
        raise ValueError("publication matrix contains no models")
    ids = [str(model.get("id") or "") for model in models]
    identities = [(str(model.get("provider") or ""), str(model.get("model") or "")) for model in models]
    if any(not value for value in ids) or any(not provider or not model for provider, model in identities):
        raise ValueError("every model requires non-empty id, provider, and model")
    if len(set(ids)) != len(ids) or len(set(identities)) != len(identities):
        raise ValueError("publication model ids and provider/model identities must be unique")
    if expected_provider is not None:
        if expected_provider != "openrouter":
            raise ValueError("publication runner currently supports only an explicitly OpenRouter-only lane")
        mismatched = sorted({provider for provider, _model in identities if provider != expected_provider})
        if mismatched:
            raise ValueError(
                f"publication registry is {expected_provider}-only but contains provider(s): {', '.join(mismatched)}"
            )
    for model in models:
        cap_verification = model.get("output_cap_verification")
        if cap_verification is not None:
            if not is_pending_strict_smoke_cap(cap_verification):
                raise ValueError(
                    f"publication model {model.get('id')!r} has an invalid output-cap verification exception"
                )
            if "max_tokens" not in set(model.get("catalog_supported_parameters") or []):
                raise ValueError(
                    f"publication model {model.get('id')!r} cannot defer cap verification without max_tokens support"
                )
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


def build_cells(
    phase: str,
    model_id: str | None = None,
    cap: int | None = None,
    *,
    authorization_phase: str | None = None,
) -> list[Cell]:
    authorization_phase = authorization_phase or phase
    if phase in {"route-preflight", "smoke"}:
        config = _read_json(PANEL_CONFIG)
        lane = _read_json(LANE_CONFIG)
        _require_execution_authorized(authorization_phase, config, lane)
        if phase == "smoke" and lane.get("contract") in STRICT_PRIVATE_PANEL_CONTRACTS:
            _validate_frozen_seed_panel(lane)
        models = list(config.get("models") or [])
        _validate_models(models, expected_provider=str(config.get("provider") or ""))
        frozen_cap = lane.get("output_token_cap")
        if phase == "smoke" and lane.get("output_policy_basis") not in {
            "fixed-safety-ceiling",
            "common-safety-ceiling-with-native-minimum-reasoning",
        }:
            raise ValueError("panel smoke is locked until the fixed safety ceiling is frozen")
        if phase == "smoke" and (not isinstance(frozen_cap, int) or frozen_cap < 1):
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
                seed_count=(
                    len(PRESETS["smoke"]["seeds"]) if lane.get("contract") in STRICT_PRIVATE_PANEL_CONTRACTS else None
                ),
                cap=frozen_cap,
                upstream_provider=str(model["upstream_provider"]),
                endpoint_tag=str(model["endpoint_tag"]),
                endpoint_name=str(model.get("endpoint_name") or ""),
                output_cap_verification=dict(model.get("output_cap_verification") or {}),
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
                seed_count=None,
                cap=cell_cap,
                upstream_provider=str(model["upstream_provider"]),
                endpoint_tag=str(model.get("endpoint_tag") or ""),
                endpoint_name=str(model.get("endpoint_name") or ""),
                output_cap_verification=dict(model.get("output_cap_verification") or {}),
                fixed_options={str(key): str(value) for key, value in (model.get("fixed_options") or {}).items()},
                absent_options=tuple(str(value) for value in model.get("absent_options") or []),
            )
            for model in models
            for cell_cap in caps
        ]
    else:
        config = _read_json(PANEL_CONFIG)
        lane = _read_json(LANE_CONFIG)
        _require_execution_authorized(phase, config, lane)
        if lane.get("contract") in STRICT_PRIVATE_PANEL_CONTRACTS:
            _validate_frozen_seed_panel(lane)
        models = list(config.get("models") or [])
        _validate_models(models, expected_provider=str(config.get("provider") or ""))
        frozen_cap = lane.get("output_token_cap")
        if lane.get("output_budget_status") not in {
            "frozen-saturation",
            "frozen-fixed-budget",
            "frozen-native-reasoning-cap",
        }:
            raise ValueError("full panel is locked until the selected lane freezes the output-budget policy")
        if config.get("selection_status") != "frozen":
            raise ValueError("full panel is locked until the selected model registry is frozen")
        if not isinstance(frozen_cap, int) or frozen_cap < 1:
            raise ValueError("full panel requires a positive frozen output_token_cap")
        manifest = _read_optional_json(_smoke_manifest_path(lane))
        manifest_issues = smoke_manifest_issues(manifest, config, lane, require_strict_fallback=True)
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
                seed_count=(
                    int(lane["seed_panel"]["count"]) if lane.get("contract") in STRICT_PRIVATE_PANEL_CONTRACTS else None
                ),
                cap=frozen_cap,
                upstream_provider=str(model["upstream_provider"]),
                endpoint_tag=str(model["endpoint_tag"]),
                endpoint_name=str(model.get("endpoint_name") or ""),
                output_cap_verification=dict(model.get("output_cap_verification") or {}),
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
    # Strict failure handling is the publication default. Apply it after
    # fixed_options so a stale registry env cannot quietly loosen a smoke cell
    # (smoke resolves strictness from the subprocess environment, not the CLI).
    env.update(cell.fixed_options)
    env["GM_AGENT_STRICT"] = "1"
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


def _prepare_smoke_retry_checkpoint(cell: Cell, run_dir: Path) -> Path | None:
    """Archive only an empty aborted checkpoint whose provenance is stale.

    This check runs under the paid-run lock and before reserving an infrastructure
    attempt, so a provenance-only local failure cannot consume the final retry.
    """
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    checkpoint = run_dir / "checkpoints" / f"{stem}.json"
    if not checkpoint.exists():
        return None
    payload = _read_json_if_valid(checkpoint)
    if payload is None:
        raise ValueError(f"cannot safely retry from invalid checkpoint: {checkpoint}")
    provenance = payload.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    expected_contract = contract_fingerprint()
    expected_scaffold = scaffold_fingerprint(cell.provider)
    benchmark_contract = provenance.get("benchmark_contract")
    stored_contract = (
        benchmark_contract.get("contract_fingerprint") if isinstance(benchmark_contract, dict) else benchmark_contract
    )
    if stored_contract == expected_contract and provenance.get("scaffold_fingerprint") == expected_scaffold:
        return None
    episodes = payload.get("episodes")
    completed = payload.get("completed")
    if payload.get("status") != "aborted" or episodes != [] or completed != []:
        raise ValueError("stale-provenance checkpoint is not an empty aborted attempt; refusing to reserve a retry")
    if _checkpoint_process_alive(checkpoint):
        raise ValueError("stale-provenance checkpoint is still locked by a live process")
    reservations = _read_json_if_valid(run_dir / "openrouter-reservations.json") or {}
    cell_reservation = (reservations.get("cells") or {}).get(stem)
    attempts = cell_reservation.get("attempts") if isinstance(cell_reservation, dict) else None
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise ValueError("empty stale checkpoint has no recorded infrastructure attempt to preserve")
    archive_dir = run_dir / "checkpoints" / "failed-attempts"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = archive_dir / f"{stem}--attempt-{attempts}.json"
    if archived.exists():
        raise ValueError(f"refusing to overwrite archived failed checkpoint: {archived}")
    checkpoint.replace(archived)
    return archived


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


def _enforce_operator_ceiling(max_spend_usd: float, contract: str | None) -> None:
    """Reject a `--max-spend-usd` above the contract's committed hard cap.

    `budget_policy.operator_ceiling_usd` was declared but never read, so the
    only thing standing between a typo and an unbounded run was the operator
    retyping the right number. A committed ceiling that nothing enforces is a
    comment.  A null ceiling stays permissive: contracts that have not
    committed to a number are not silently given one.  An unreadable protocol
    file is not the same as a null ceiling: it may hide a committed number, so
    it fails closed like every other malformed input to this gate.
    """
    _, _, _, protocol_path, _ = CONTRACT_CONFIGS.get(contract or "", (None,) * 5)
    if protocol_path is None:
        protocol_path = PROTOCOL_CONFIG
    try:
        budget_policy = (_read_json(protocol_path) or {}).get("budget_policy") or {}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {protocol_path.name} to enforce the operator ceiling: {exc}") from exc
    ceiling = budget_policy.get("operator_ceiling_usd")
    if ceiling is None:
        return
    if not isinstance(ceiling, (int, float)) or isinstance(ceiling, bool) or not math.isfinite(ceiling) or ceiling <= 0:
        raise ValueError(f"budget_policy.operator_ceiling_usd must be a positive finite number, got {ceiling!r}")
    if max_spend_usd > ceiling:
        raise ValueError(
            f"--max-spend-usd ${max_spend_usd:.2f} exceeds the committed operator ceiling "
            f"${float(ceiling):.2f} in {protocol_path.name}; raise the ceiling deliberately or lower the run"
        )


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
        cap_fits = cell.cap is None or (
            isinstance(maximum, int) and not isinstance(maximum, bool) and cell.cap <= maximum
        )
        if cell.cap is not None and maximum is None:
            cap_fits = is_pending_strict_smoke_cap(cell.output_cap_verification) and "max_tokens" in supported
        if required <= supported and cap_fits:
            capable.append(endpoint)
    if not capable:
        return [f"matching endpoint cannot honor required parameters {sorted(required)!r} and cap={cell.cap_label}"]
    floors = (("uptime_last_30m", MIN_UPTIME_LAST_30M_PCT, "30m"), ("uptime_last_1d", MIN_UPTIME_LAST_1D_PCT, "24h"))
    for field, floor, label in floors:
        # Fail closed. Missing or malformed health telemetry does not establish
        # that the pinned route clears the declared availability floor.
        durable = [
            endpoint
            for endpoint in capable
            if isinstance(endpoint.get(field), (int, float))
            and not isinstance(endpoint[field], bool)
            and math.isfinite(endpoint[field])
            and endpoint[field] >= floor
        ]
        if not durable:
            observed = [
                endpoint[field]
                for endpoint in capable
                if isinstance(endpoint.get(field), (int, float))
                and not isinstance(endpoint[field], bool)
                and math.isfinite(endpoint[field])
            ]
            if not observed:
                return [f"matching endpoint has no finite numeric {label} uptime telemetry"]
            return [
                f"matching endpoint is below the {floor}% {label} uptime floor "
                f"(best matching route: {max(observed):.2f}%)"
            ]
        capable = durable
    return []


def _openrouter_endpoints(model: str, env: dict[str, str]) -> dict[str, Any]:
    api_key = env.get("OPENROUTER_API_KEY")
    headers = {"User-Agent": "gm-bench-publication-runner/1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"https://openrouter.ai/api/v1/models/{model}/endpoints",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint  # nosemgrep
        return json.load(response)


def _pricing_drift_issues(cell: Cell, payload: dict[str, Any]) -> list[str]:
    """Compare the pinned route's live rates against the committed snapshot.

    The snapshot is what the reservation was computed from, so a rate that has
    risen since it was taken makes the committed budget wrong in the direction
    that costs money. That is an error. A rate that has *fallen* only means the
    run will come in under reserve, so it is reported and allowed -- the GLM
    Novita route quietly picked up a 55.1% discount that went unnoticed for two
    weeks precisely because nothing ever looked.

    Only the base rates are compared. Long-context override tiers are priced
    separately in the snapshot and are not exercised by the registered
    8,000-token decision, so a drift there cannot move this plan's cost.
    """
    try:
        rates = (_read_json(PRICING_CONFIG).get("models") or {}).get(cell.model)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"committed pricing snapshot for {cell.experiment_id} could not be read: {exc}"]
    if not isinstance(rates, dict):
        return [f"committed pricing snapshot has no rates for {cell.model}"]
    # Match the full registered route identity, exactly as `_endpoint_issues`
    # does. Comparing a price against a route we did not pin is worse than not
    # comparing at all.
    endpoint = next(
        (
            e
            for e in ((payload.get("data") or {}).get("endpoints") or [])
            if e.get("provider_name") == cell.upstream_provider
            and e.get("tag") == cell.endpoint_tag
            and e.get("name") == cell.endpoint_name
        ),
        None,
    )
    if endpoint is None:
        return [f"no endpoint matching the pinned route identity for {cell.experiment_id} to price-check"]
    issues = []
    for field in ("prompt", "completion"):
        committed = rates.get(field)
        raw = (endpoint.get("pricing") or {}).get(field)
        # Fail closed. "The price could not be verified" is not the same as
        # "the price is unchanged", and only one of them is safe to spend on.
        if (
            not isinstance(committed, (int, float))
            or isinstance(committed, bool)
            or not math.isfinite(committed)
            or committed < 0
        ):
            issues.append(f"committed {field} rate for {cell.experiment_id} is not a usable number: {committed!r}")
            continue
        try:
            live = float(raw)
        except (TypeError, ValueError):
            issues.append(f"live {field} rate for {cell.experiment_id} is unreadable: {raw!r}")
            continue
        if not math.isfinite(live) or live < 0:
            issues.append(f"live {field} rate for {cell.experiment_id} is not a usable number: {raw!r}")
            continue
        if live > committed:
            issues.append(
                f"live {field} rate {live:.10g} exceeds the committed snapshot rate {committed:.10g} "
                f"for {cell.experiment_id}; the reservation was computed from the snapshot"
            )
        elif live < committed:
            print(
                f"note: live {field} rate for {cell.experiment_id} fell from {committed:.10g} "
                f"to {live:.10g}; the run will come in under its reservation"
            )
    return issues


def _validate_openrouter_endpoint(cell: Cell, env: dict[str, str]) -> None:
    payload = _openrouter_endpoints(cell.model, env)
    issues = _endpoint_issues(cell, payload) + _pricing_drift_issues(cell, payload)
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
    guard_state = _read_json_if_valid(run_dir / CALL_SPEND_GUARD_STATE) or {}
    reported_call_spend = guard_state.get("reported_spend_usd")
    if (
        not isinstance(reported_call_spend, int | float)
        or isinstance(reported_call_spend, bool)
        or not math.isfinite(float(reported_call_spend))
        or float(reported_call_spend) < 0
    ):
        reported_call_spend = 0.0
    return max(account_delta, _artifact_spend_usd(run_dir), float(reported_call_spend))


def _reconcile_spend_guard(run_dir: Path) -> dict[str, Any]:
    """Conservatively absorb an unresolved call reservation as spent."""
    budget_path = run_dir / "openrouter-budget.json"
    state_path = run_dir / CALL_SPEND_GUARD_STATE
    if not budget_path.exists() or not state_path.exists():
        raise ValueError("spend reconciliation requires existing budget and guard state files")
    budget = _read_json(budget_path)
    state = _read_json(state_path)
    blocked_reason = state.get("blocked_reason")
    active = state.get("active_call_reservation_usd")
    reported = state.get("reported_spend_usd")
    start = budget.get("starting_total_usage_usd")
    for label, value in (("starting total", start), ("reported spend", reported), ("active reservation", active)):
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(f"spend reconciliation {label} must be finite and non-negative")
    if not isinstance(blocked_reason, str) or not blocked_reason or float(active) <= 0:
        raise ValueError("spend guard has no unresolved blocked reservation to reconcile")
    reconciled_spend = float(reported) + float(active)
    ceiling = state.get("ceiling_usd")
    if (
        not isinstance(ceiling, int | float)
        or isinstance(ceiling, bool)
        or not math.isfinite(float(ceiling))
        or float(ceiling) < 0
        or reconciled_spend > float(ceiling)
    ):
        raise ValueError("absorbing the unresolved call reservation would exceed the authorized ceiling")

    prior_evidence = state.get("reconciliation_evidence")
    prior_sha = state.get("reconciliation_sha256")
    evidence = {
        "format": "gm-bench-openrouter-spend-reconciliation-v1",
        "schema_version": 1,
        "reconciled_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "starting_total_usage_usd": float(start),
        "prior_reported_spend_usd": float(reported),
        "absorbed_unknown_call_spend_usd": float(active),
        "reconciled_reported_spend_usd": reconciled_spend,
        "prior_blocked_reason": blocked_reason,
        "prior_telemetry_error": state.get("telemetry_error"),
        "method": "charge-full-conservative-call-reservation",
        "note": "The actual provider cost was unavailable; the full pre-call upper bound is charged as spent.",
    }
    if isinstance(prior_evidence, str) and prior_evidence and isinstance(prior_sha, str) and prior_sha:
        evidence["previous_reconciliation_evidence"] = prior_evidence
        evidence["previous_reconciliation_sha256"] = prior_sha
    base = Path(SPEND_RECONCILIATION)
    evidence_path = run_dir / base
    sequence = 1
    while evidence_path.exists():
        sequence += 1
        evidence_path = run_dir / f"{base.stem}-{sequence}{base.suffix}"
    _write_json_atomic(evidence_path, evidence)
    evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    state["reported_spend_usd"] = reconciled_spend
    state["active_call_reservation_usd"] = 0.0
    evidence_name = evidence_path.name
    history = state.get("reconciliation_history")
    if not isinstance(history, list):
        history = []
    if not history and isinstance(prior_evidence, str) and isinstance(prior_sha, str):
        history.append({"evidence": prior_evidence, "sha256": prior_sha})
    history.append({"evidence": evidence_name, "sha256": evidence_sha})
    state["reconciliation_history"] = history
    state["reconciliation_evidence"] = evidence_name
    state["reconciliation_sha256"] = evidence_sha
    state.pop("active_call_input_token_bound", None)
    state.pop("blocked_reason", None)
    state.pop("telemetry_error", None)
    _write_json_atomic(state_path, state)
    return evidence


def _call_spend_guard_environment(
    cell: Cell,
    run_dir: Path,
    *,
    ceiling_usd: float,
    measured_spend_floor_usd: float,
) -> dict[str, str]:
    """Freeze the rates and allowance checked before every OpenRouter call."""
    if not isinstance(cell.cap, int) or cell.cap < 1:
        raise ValueError("paid publication calls require a positive bounded output cap")
    pricing = _read_json(PRICING_CONFIG)
    rates = (pricing.get("models") or {}).get(cell.model)
    if not isinstance(rates, dict):
        raise ValueError(f"missing committed pricing for {cell.model}")
    assumptions = pricing["planning_assumptions"]
    reasoning_enabled = cell.fixed_options.get("OPENROUTER_REASONING_ENABLED") == "true"
    reasoning_tokens = int(assumptions.get("expected_internal_reasoning_tokens_per_decision") or 0)
    reasoning_rate = rates.get("internal_reasoning")
    if reasoning_enabled and reasoning_tokens <= 0:
        raise ValueError(
            "reasoning-enabled paid publication cells require a positive committed "
            "expected_internal_reasoning_tokens_per_decision"
        )
    if reasoning_enabled and reasoning_rate is None:
        reasoning_rate = rates["completion"]
    if not reasoning_enabled:
        reasoning_tokens = 0
        reasoning_rate = 0
    prefix = SPEND_GUARD_ENV_PREFIX
    guard = {
        "OPENROUTER_API_BASE": OPENROUTER_CANONICAL_API_BASE,
        f"{prefix}STATE_PATH": str(run_dir / CALL_SPEND_GUARD_STATE),
        f"{prefix}CEILING_USD": str(ceiling_usd),
        f"{prefix}MEASURED_SPEND_FLOOR_USD": str(measured_spend_floor_usd),
        f"{prefix}PROMPT_RATE_USD": str(rates["prompt"]),
        f"{prefix}COMPLETION_RATE_USD": str(rates["completion"]),
        f"{prefix}OUTPUT_TOKEN_CAP": str(cell.cap),
        f"{prefix}REASONING_RATE_USD": str(reasoning_rate or 0),
        f"{prefix}REASONING_TOKEN_CAP": str(reasoning_tokens),
        f"{prefix}CONTINGENCY_MULTIPLIER": str(assumptions["cost_contingency_multiplier"]),
    }
    long_context = rates.get("long_context_override")
    if isinstance(long_context, dict):
        guard.update(
            {
                f"{prefix}LONG_CONTEXT_THRESHOLD": str(long_context["min_prompt_tokens"]),
                f"{prefix}LONG_CONTEXT_PROMPT_RATE_USD": str(long_context["prompt"]),
                f"{prefix}LONG_CONTEXT_COMPLETION_RATE_USD": str(long_context["completion"]),
            }
        )
    return guard


def _cell_reservation_usd(cell: Cell) -> float:
    if not isinstance(cell.cap, int) or cell.cap < 1:
        raise ValueError("paid publication cells require a positive bounded output cap")
    pricing = _read_json(PRICING_CONFIG)
    rates = (pricing.get("models") or {}).get(cell.model)
    if not isinstance(rates, dict):
        raise ValueError(f"missing committed pricing for {cell.model}")
    assumptions = pricing["planning_assumptions"]
    preset = PRESETS[cell.preset]
    seed_count = cell.seed_count if cell.seed_count is not None else len(preset["seeds"])
    if not isinstance(seed_count, int) or isinstance(seed_count, bool) or seed_count < 1:
        raise ValueError("publication reservation seed count must be a positive integer")
    decisions = seed_count * int(preset["seasons"]) * len(PHASES) * cell.repeats
    input_tokens = int(assumptions["input_tokens_per_decision"])
    reasoning_tokens = int(assumptions.get("expected_internal_reasoning_tokens_per_decision") or 0)
    repair_attempts = int(cell.fixed_options.get("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS", "0"))
    contingency = float(assumptions["cost_contingency_multiplier"])
    if input_tokens < 1 or reasoning_tokens < 0 or repair_attempts < 0 or contingency < 1:
        raise ValueError("publication reservation assumptions must be positive and conservative")
    applied_rates = rates
    long_context_override = rates.get("long_context_override")
    if isinstance(long_context_override, dict) and input_tokens >= int(long_context_override["min_prompt_tokens"]):
        applied_rates = long_context_override
    prompt = decisions * input_tokens * float(applied_rates["prompt"])
    completion = decisions * cell.cap * float(applied_rates["completion"])
    internal_reasoning = decisions * reasoning_tokens * float(rates.get("internal_reasoning") or 0)
    # This is a planning reservation, not the hard safety boundary: it assumes
    # one interaction round and reserves every decision's configured repair.
    # The in-child ProviderSpendGuardAgent separately checks every actual
    # interaction/repair call against the operator ceiling before launch.
    return round((prompt + completion + internal_reasoning) * (1 + repair_attempts) * contingency, 6)


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
        "cell_outcomes": existing.get("cell_outcomes") or {},
    }
    _write_json_atomic(path, payload)


def _record_run_cell_outcome(run_dir: Path, cell: Cell, status: str, error: str | None = None) -> None:
    path = run_dir / "run-state.json"
    payload = _read_json_if_valid(path)
    if payload is None:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    outcome = {"status": status, "updated_at_utc": now}
    if error:
        outcome["error"] = error
    payload.setdefault("cell_outcomes", {})[cell.experiment_id] = outcome
    payload["updated_at_utc"] = now
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


@contextmanager
def _exclusive_paid_run(run_dir: Path):
    """Lock one run directory for the complete paid invocation.

    The spend ceiling and account-delta baseline are scoped to ``run_dir``.
    A different run directory is therefore a separate authorization and budget,
    not a way to share this invocation's ceiling.
    """
    import fcntl

    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / PAID_RUN_LOCK
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit(
                f"another paid publication invocation holds {lock_path}; "
                "wait for it to finish or use a different run directory with a separately authorized budget"
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
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
    raw_cap = run_state.get("output_token_cap")
    if raw_cap is None:
        raw_cap = registry.get("output_token_cap")
    cap = int(raw_cap) if isinstance(raw_cap, int) and not isinstance(raw_cap, bool) else None
    cap_label = str(cap) if cap is not None else "pending"
    manifest = _read_json_if_valid(manifest_path) or {}
    manifest_entries = manifest.get("entries") if isinstance(manifest.get("entries"), dict) else {}
    reservations_payload = _read_json_if_valid(run_dir / "openrouter-reservations.json") or {}
    reservations = reservations_payload.get("cells")
    reservations = reservations if isinstance(reservations, dict) else {}
    cell_outcomes = run_state.get("cell_outcomes")
    cell_outcomes = cell_outcomes if isinstance(cell_outcomes, dict) else {}

    rows = []
    for model in registry.get("models") or []:
        model_id = str(model["id"])
        stem = f"{model_id}--{cap_label}"
        checkpoint_path = run_dir / "checkpoints" / f"{stem}.json"
        raw_path = run_dir / "raw" / f"{stem}.json"
        checkpoint = _read_json_if_valid(checkpoint_path)
        raw = _read_json_if_valid(raw_path)
        manifest_entry = manifest_entries.get(model_id)
        reservation = reservations.get(stem)
        outcome = cell_outcomes.get(model_id)
        outcome = outcome if isinstance(outcome, dict) else {}
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
        if outcome.get("status") in {"aborted", "excluded", "ineligible"}:
            state = str(outcome["status"])
        # A manifest acceptance only upgrades *this run's own* completed cell to
        # "accepted"; it never substitutes for the current run/cap's raw
        # artifact, so a stale or wrong-cap manifest entry cannot mask a cell
        # that this run directory has not actually produced.
        if (
            run_state.get("phase") == "smoke"
            and state == "complete"
            and smoke_accepted
            and cap is not None
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
                "error": outcome.get("error") or (checkpoint.get("error") if isinstance(checkpoint, dict) else None),
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
        "output_token_cap": cap,
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
    if run_info.get("strict_fallback") is not True:
        issues.append("artifact was not produced under strict failure handling")

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


_MODEL_BEHAVIOR_SMOKE_ISSUES = {
    "artifact candidate episode contains failed decisions",
    "artifact candidate summary failed_decisions must be zero",
    "artifact decision_failure_rate must be zero",
}


def _completed_smoke_model_behavior_issues(cell: Cell, run_dir: Path) -> list[str]:
    """Identify a complete, fully telemetered smoke rejected only for model behavior."""
    path = run_dir / "raw" / f"{cell.experiment_id}--{cell.cap_label}.json"
    if not path.exists():
        return []
    try:
        artifact = _read_json(path)
        registry = _read_json(PANEL_CONFIG)
        lane = _read_json(LANE_CONFIG)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    issues, _entry = _record_smoke_issues(artifact, cell.experiment_id, registry, lane)
    return issues if issues and set(issues) <= _MODEL_BEHAVIOR_SMOKE_ISSUES else []


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
        "strict_fallback": bool(run_info.get("strict_fallback")),
        "contract_fingerprint": run_info["benchmark_contract"]["contract_fingerprint"],
        "scaffold_fingerprint": run_info["scaffold_fingerprint"],
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "artifact_path": str(artifact_path),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "accepted": True,
    }
    required = {str(value) for value in registry.get("required_smokes") or []}
    recorded = set(manifest["entries"])
    complete = (
        bool(required)
        and recorded == required
        and all(isinstance(value, dict) and value.get("accepted") is True for value in manifest["entries"].values())
    )
    manifest["status"] = "accepted" if complete else "in-progress"
    manifest["accepted_for_panel"] = complete
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


def _panel_artifact_issues(cell: Cell, artifact: dict[str, Any]) -> list[str]:
    """Return blocking publication and registered-route issues for one panel artifact."""
    issues = list(validate_leaderboard_payload(artifact, policy=POLICIES[BENCHMARK_VERSION]).errors)
    run_info = artifact.get("run_info")
    run_info = run_info if isinstance(run_info, dict) else {}
    for key, expected in (
        ("provider", cell.provider),
        ("model", cell.model),
        ("profile", cell.profile),
        ("preset", cell.preset),
    ):
        if run_info.get(key) != expected:
            issues.append(f"artifact {key} does not match the registered cell")

    provider_options = run_info.get("provider_options")
    provider_options = provider_options if isinstance(provider_options, dict) else {}
    expected_options = {**cell.fixed_options, "GM_BENCH_OUTPUT_BUDGET_CELL": cell.cap_label}
    for key, expected in expected_options.items():
        if str(provider_options.get(key, "")) != str(expected):
            issues.append(f"artifact provider option {key} does not match the registered value")
    for key in cell.absent_options:
        if provider_options.get(key) not in (None, ""):
            issues.append(f"artifact provider option {key} must be absent")

    candidate = artifact.get("candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    summary = candidate.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    decisions = summary.get("decisions")
    usage = summary.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    if not isinstance(decisions, int) or usage.get("cost_decisions") != decisions:
        issues.append("candidate cost telemetry must cover every decision point")
    observed_upstreams = sorted({str(value) for value in usage.get("upstream_providers") or [] if value})
    if [value.casefold() for value in observed_upstreams] != [cell.upstream_provider.casefold()]:
        issues.append("observed upstream provider does not match the registered route")
    return list(dict.fromkeys(issues))


def _existing_panel_artifact(cell: Cell, run_dir: Path) -> tuple[Path | None, list[str]]:
    path = run_dir / "raw" / f"{cell.experiment_id}--{cell.cap_label}.json"
    if not path.exists():
        return None, []
    try:
        artifact = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return path, [f"cannot read existing panel artifact: {exc}"]
    return path, _panel_artifact_issues(cell, artifact)


def _maximum_infrastructure_attempts() -> int:
    protocol = _read_json(PROTOCOL_CONFIG)
    attempts = int((protocol.get("rerun_policy") or {}).get("maximum_infrastructure_attempts_per_cell") or 0)
    if attempts < 1:
        raise ValueError("publication protocol must allow at least one infrastructure attempt per cell")
    return attempts


def _checkpoint_failure_detail(run_dir: Path, cell: Cell) -> str | None:
    path = run_dir / "checkpoints" / f"{cell.experiment_id}--{cell.cap_label}.json"
    payload = _read_json_if_valid(path)
    error = payload.get("error") if payload else None
    return str(error) if error else None


def _append_legacy_attempt_history(
    stored: dict[str, Any], run_dir: Path, cell: Cell, measured_spend: float
) -> list[dict[str, Any]]:
    history = stored.setdefault("attempt_history", [])
    attempts = int(stored.get("attempts") or 0)
    if history or attempts < 1:
        return history
    checkpoint = run_dir / "checkpoints" / f"{cell.experiment_id}--{cell.cap_label}.json"
    finished = None
    try:
        finished = datetime.fromtimestamp(checkpoint.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        pass
    history.append(
        {
            "attempt": attempts,
            "status": "failed",
            "legacy_record": True,
            "finished_at_utc": finished,
            "measured_run_spend_usd": measured_spend,
            "error": _checkpoint_failure_detail(run_dir, cell) or "prior attempt failed before outcome logging",
        }
    )
    return history


def _reserve_cell(run_dir: Path, cell: Cell, measured_spend: float, ceiling: float) -> float:
    path = run_dir / "openrouter-reservations.json"
    payload = _read_json(path) if path.exists() else {"schema_version": 1, "cells": {}}
    reservations = payload.setdefault("cells", {})
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    # Only unsettled attempts remain a conservative liability. Successful
    # cells are replaced by their measured account/artifact spend so historical
    # worst-case reservations cannot prematurely stop a healthy serial panel.
    reserved_total = sum(
        float(value["reserved_usd"])
        for value in reservations.values()
        if value.get("status") not in {"settled", "excluded"}
    )
    reservation = _cell_reservation_usd(cell)
    if stem in reservations:
        stored = reservations[stem]
        prior_attempts = int(stored.get("attempts") or 0)
        maximum_attempts = _maximum_infrastructure_attempts()
        if stored.get("status") != "settled" and prior_attempts >= maximum_attempts:
            raise SystemExit(f"infrastructure attempt limit reached for {stem}: {prior_attempts}/{maximum_attempts}")
        committed = measured_spend + reserved_total
        if committed + reservation > ceiling:
            raise SystemExit(
                f"retry reservation would exceed spend ceiling: ${committed:.4f} + ${reservation:.4f} > ${ceiling:.4f}"
            )
        history = _append_legacy_attempt_history(stored, run_dir, cell, measured_spend)
        stored["reserved_usd"] = (
            float(stored.get("reserved_usd") or 0) + reservation
            if stored.get("status") not in {"settled", "excluded"}
            else reservation
        )
        stored["total_reserved_usd"] = float(stored.get("total_reserved_usd") or 0) + reservation
        stored["attempts"] = prior_attempts + 1
        stored["status"] = "active"
        history.append(
            {
                "attempt": stored["attempts"],
                "status": "active",
                "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "reserved_usd": reservation,
                "measured_run_spend_before_usd": measured_spend,
            }
        )
        stored["protocol_repair_attempts_reserved_per_decision"] = int(
            cell.fixed_options.get("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS", "0")
        )
        stored["cost_contingency_multiplier"] = float(
            _read_json(PRICING_CONFIG)["planning_assumptions"]["cost_contingency_multiplier"]
        )
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
        "protocol_repair_attempts_reserved_per_decision": int(
            cell.fixed_options.get("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS", "0")
        ),
        "cost_contingency_multiplier": float(
            _read_json(PRICING_CONFIG)["planning_assumptions"]["cost_contingency_multiplier"]
        ),
        "attempt_history": [
            {
                "attempt": 1,
                "status": "active",
                "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "reserved_usd": reservation,
                "measured_run_spend_before_usd": measured_spend,
            }
        ],
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
    history = stored.get("attempt_history") or []
    if history and history[-1].get("status") == "active":
        history[-1].update(
            {
                "status": "succeeded",
                "finished_at_utc": stored["settled_at_utc"],
                "measured_run_spend_usd": measured_spend,
            }
        )
    _write_json_atomic(path, payload)


def _record_failed_cell_reservation(
    run_dir: Path,
    cell: Cell,
    measured_spend: float,
    error: str,
) -> None:
    """Record a failed attempt and release liability after the frozen retry limit."""
    path = run_dir / "openrouter-reservations.json"
    if not path.exists():
        return
    payload = _read_json(path)
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    stored = (payload.get("cells") or {}).get(stem)
    if not isinstance(stored, dict):
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    history = stored.get("attempt_history") or []
    if history and history[-1].get("status") == "active":
        history[-1].update(
            {
                "status": "failed",
                "finished_at_utc": now,
                "measured_run_spend_usd": measured_spend,
                "error": error,
            }
        )
    stored["last_failure_at_utc"] = now
    stored["last_failure"] = error
    stored["measured_run_spend_usd"] = measured_spend
    if int(stored.get("attempts") or 0) >= _maximum_infrastructure_attempts():
        stored["reserved_usd"] = 0.0
        stored["status"] = "excluded"
        stored["excluded_at_utc"] = now
        stored["exclusion_reason"] = "infrastructure attempt limit reached"
    else:
        stored["status"] = "active"
    _write_json_atomic(path, payload)


def _record_ineligible_cell_reservation(
    run_dir: Path,
    cell: Cell,
    measured_spend: float,
    error: str,
) -> None:
    """Release a completed cell reservation while retaining its rejected artifact."""
    path = run_dir / "openrouter-reservations.json"
    if not path.exists():
        return
    payload = _read_json(path)
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    stored = (payload.get("cells") or {}).get(stem)
    if not isinstance(stored, dict):
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    history = stored.get("attempt_history") or []
    if history and history[-1].get("status") == "active":
        history[-1].update(
            {
                "status": "ineligible",
                "finished_at_utc": now,
                "measured_run_spend_usd": measured_spend,
                "error": error,
            }
        )
    stored["reserved_usd"] = 0.0
    stored["status"] = "ineligible"
    stored["ineligible_at_utc"] = now
    stored["ineligibility_reason"] = error
    stored["measured_run_spend_usd"] = measured_spend
    _write_json_atomic(path, payload)


def _print_command(cell: Cell, command: list[str]) -> None:
    options = {**cell.fixed_options, "GM_BENCH_OUTPUT_BUDGET_CELL": cell.cap_label, "GM_BENCH_WORKERS": "1"}
    if cell.provider == "openrouter" and cell.cap is not None:
        options["OPENROUTER_MAX_TOKENS"] = str(cell.cap)
    print(json.dumps({"cell": cell.experiment_id, "cap": cell.cap_label, "env": options, "command": command}))


def main(argv: list[str] | None = None, *, _paid_run_lock_held: bool = False) -> int:
    # The child CLI loads these files too, but the parent needs the provider key
    # to query account usage and enforce the operator's spend ceiling before it
    # launches any model process.
    load_environment_files(ROOT)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=["route-preflight", "smoke", "sweep", "panel", "record-smoke", "status", "reconcile-spend"],
    )
    parser.add_argument(
        "--contract",
        choices=sorted(CONTRACT_CONFIGS),
        help="explicit publication contract lane (required except for the retired sweep)",
    )
    parser.add_argument("--model-id")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--cap", type=int)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path("data/publication-runs"),
        help="budget/accounting scope; separate directories require separately authorized spend ceilings",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--max-spend-usd", type=float)
    parser.add_argument("--watch", action="store_true", help="refresh publication status until interrupted")
    parser.add_argument("--interval", type=float, default=2.0, help="watch refresh interval in seconds")
    parser.add_argument("--json", action="store_true", help="emit status as JSON")
    args = parser.parse_args(argv)
    if args.phase != "sweep" and not args.contract:
        parser.error(f"{args.phase} requires an explicit --contract")
    if args.contract:
        _select_contract_config(args.contract)
    manifest_path = args.manifest or SMOKE_MANIFEST
    if args.phase == "status":
        if args.interval <= 0:
            parser.error("--interval must be positive")
        return _status_command(args.run_dir, manifest_path, watch=args.watch, interval=args.interval, as_json=args.json)
    if args.phase == "reconcile-spend":
        run_dir = args.run_dir.resolve()
        try:
            with _exclusive_paid_run(run_dir):
                evidence = _reconcile_spend_guard(run_dir)
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            parser.error(str(exc))
        print(json.dumps(evidence, sort_keys=True))
        return 0
    if args.phase == "record-smoke":
        if not args.model_id:
            parser.error("record-smoke requires --model-id")
        if args.artifact is None:
            parser.error("record-smoke requires --artifact")
        try:
            _require_current_publication_contract()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        return _record_smoke(args.model_id, args.artifact, manifest_path)
    if args.max_spend_usd is not None and not math.isfinite(args.max_spend_usd):
        # NaN defeats every downstream guard silently: `nan <= 0`,
        # `nan > ceiling`, and `spent >= nan` are all false, so a NaN limit
        # satisfies "the operator passed a ceiling" while bounding nothing.
        # Infinity is the same hole whenever no ceiling is configured.
        parser.error("--max-spend-usd must be a finite number")
    if args.max_spend_usd is not None and args.max_spend_usd <= 0:
        parser.error("--max-spend-usd must be positive")
    if args.phase in {"route-preflight", "smoke", "panel"}:
        try:
            _require_current_publication_contract()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
    try:
        authorization_phase = "route-preflight" if args.dry_run or args.preflight_only else args.phase
        cells = build_cells(
            args.phase,
            args.model_id,
            args.cap,
            authorization_phase=authorization_phase,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.phase == "sweep" and not args.dry_run and not args.preflight_only:
        sweep_status = str(_read_json(SWEEP_CONFIG).get("status") or "")
        if sweep_status != "awaiting-runs":
            parser.error(f"paid sweep is locked while config/output_budget_sweep.json status is {sweep_status!r}")
    if (
        not args.dry_run
        and not args.preflight_only
        and args.phase != "route-preflight"
        and any(cell.provider == "openrouter" for cell in cells)
        and args.max_spend_usd is None
    ):
        parser.error("paid OpenRouter runs require an explicit --max-spend-usd ceiling")
    if args.max_spend_usd is not None:
        try:
            _enforce_operator_ceiling(args.max_spend_usd, args.contract)
        except ValueError as exc:
            parser.error(str(exc))
    run_dir = args.run_dir.resolve()
    paid_invocation = (
        not args.dry_run
        and not args.preflight_only
        and args.phase != "route-preflight"
        and any(cell.provider == "openrouter" for cell in cells)
    )
    if paid_invocation and not _paid_run_lock_held:
        with _exclusive_paid_run(run_dir):
            return main(argv, _paid_run_lock_held=True)
    for directory in (run_dir / "raw", run_dir / "checkpoints"):
        if not args.dry_run and not args.preflight_only and args.phase != "route-preflight":
            directory.mkdir(parents=True, exist_ok=True)
    if not args.dry_run and not args.preflight_only and args.phase != "route-preflight":
        _write_run_state(run_dir, args.phase, cells, args.max_spend_usd)
    budget_start: float | None = None
    preflight_failures: list[str] = []
    for cell in cells:
        env = cell_environment(cell)
        if args.phase == "smoke" and not args.preflight_only and not args.dry_run:
            reservations = _read_json_if_valid(run_dir / "openrouter-reservations.json") or {}
            stored = (reservations.get("cells") or {}).get(f"{cell.experiment_id}--{cell.cap_label}") or {}
            if stored.get("status") in {"excluded", "ineligible"}:
                print(f"preserving terminal smoke without rerun: {cell.experiment_id} ({stored['status']})")
                continue
            behavior_issues = _completed_smoke_model_behavior_issues(cell, run_dir)
            if behavior_issues:
                measured = float(stored.get("measured_run_spend_usd") or _artifact_spend_usd(run_dir))
                failure = "completed smoke failed only model-behavior gates: " + "; ".join(behavior_issues)
                _record_ineligible_cell_reservation(run_dir, cell, measured, failure)
                _record_run_cell_outcome(run_dir, cell, "ineligible", failure)
                print(f"preserving completed ineligible smoke without rerun: {cell.experiment_id}")
                continue
        archived_checkpoint = None
        if args.phase == "smoke" and not args.preflight_only and not args.dry_run:
            try:
                archived_checkpoint = _prepare_smoke_retry_checkpoint(cell, run_dir)
            except ValueError as exc:
                raise SystemExit(f"smoke retry checkpoint is unsafe for {cell.experiment_id}: {exc}") from exc
        if archived_checkpoint is not None:
            print(f"archived empty stale failed checkpoint before retry: {archived_checkpoint}")
        command = cell_command(
            cell,
            run_dir,
            preflight=args.preflight_only or args.phase == "route-preflight",
        )
        _print_command(cell, command)
        if args.dry_run:
            continue
        if args.phase == "smoke" and not args.preflight_only:
            reusable = _reusable_smoke_artifact(cell, run_dir)
            if reusable is not None:
                print(f"reusing clean completed smoke without another reservation or provider call: {reusable}")
                continue
        if args.phase == "panel" and not args.preflight_only:
            existing, existing_issues = _existing_panel_artifact(cell, run_dir)
            if existing is not None:
                if existing_issues:
                    failure = "existing panel artifact failed the publication gate: " + "; ".join(existing_issues)
                    measured = _artifact_spend_usd(run_dir)
                    _record_ineligible_cell_reservation(run_dir, cell, measured, failure)
                    _record_run_cell_outcome(run_dir, cell, "ineligible", failure)
                    raise SystemExit(
                        f"existing panel artifact failed the publication gate for {cell.experiment_id}: "
                        + "; ".join(existing_issues)
                    )
                print(
                    f"reusing eligible completed panel artifact without another reservation or provider call: {existing}"
                )
                _settle_cell_reservation(run_dir, cell, _artifact_spend_usd(run_dir))
                _record_run_cell_outcome(run_dir, cell, "complete")
                continue
        if cell.provider == "openrouter":
            if (
                args.phase == "route-preflight"
                and args.contract in AUTHENTICATED_ROUTE_CONTRACTS
                and not env.get("OPENROUTER_API_KEY")
            ):
                raise SystemExit(
                    f"authenticated {args.contract} route preflight requires OPENROUTER_API_KEY; "
                    "no endpoint request or model call was made"
                )
            try:
                _validate_openrouter_endpoint(cell, env)
            except (
                RuntimeError,
                urllib.error.URLError,
                TimeoutError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
            ) as exc:
                failure = f"OpenRouter endpoint preflight failed for {cell.experiment_id}: {exc}"
                # A phase that spends money must stop at the first bad route.
                # The zero-call phase must not: exiting early leaves every
                # later route unchecked, which reads as "one route is broken"
                # when the truth may be four. Collect and report them all.
                if args.phase != "route-preflight":
                    raise SystemExit(failure) from exc
                preflight_failures.append(failure)
                print(failure, file=sys.stderr)
                continue
        if args.phase == "route-preflight":
            print(f"zero-completion-call route preflight passed: {cell.experiment_id}")
            continue
        if not args.preflight_only and args.max_spend_usd is not None and cell.provider == "openrouter":
            budget_start = budget_start if budget_start is not None else _budget_start(run_dir, env)
            spent = _measured_spend_usd(run_dir, env, budget_start)
            if spent >= args.max_spend_usd:
                raise SystemExit(f"spend ceiling reached: ${spent:.4f} >= ${args.max_spend_usd:.4f}")
            _reserve_cell(run_dir, cell, spent, args.max_spend_usd)
            env.update(
                _call_spend_guard_environment(
                    cell,
                    run_dir,
                    ceiling_usd=args.max_spend_usd,
                    measured_spend_floor_usd=spent,
                )
            )
        cell_succeeded = False
        cell_error: str | None = None
        cell_ineligible = False
        try:
            try:
                subprocess.run(command, cwd=ROOT, env=env, check=True)
            except subprocess.CalledProcessError as exc:
                behavior_issues = _completed_smoke_model_behavior_issues(cell, run_dir) if args.phase == "smoke" else []
                if behavior_issues:
                    cell_error = "completed smoke failed only model-behavior gates: " + "; ".join(behavior_issues)
                    cell_ineligible = True
                else:
                    cell_error = _checkpoint_failure_detail(run_dir, cell) or f"child process exited {exc.returncode}"
                raise SystemExit(
                    f"publication cell failed: {cell.experiment_id} cap={cell.cap_label} exit={exc.returncode}"
                ) from exc
            if args.phase == "panel" and not args.preflight_only:
                artifact_path = run_dir / "raw" / f"{cell.experiment_id}--{cell.cap_label}.json"
                try:
                    artifact = _read_json(artifact_path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    cell_error = f"completed panel cell did not produce a readable raw artifact: {exc}"
                    raise SystemExit(cell_error) from exc
                issues = _panel_artifact_issues(cell, artifact)
                if issues:
                    cell_error = "completed panel artifact failed the publication gate: " + "; ".join(issues)
                    cell_ineligible = True
                    raise SystemExit(cell_error)
            cell_succeeded = True
        finally:
            # Provider failures are exactly when spend visibility matters most.
            # Report the post-cell delta even when the child exits nonzero.
            if not args.preflight_only and args.max_spend_usd is not None and cell.provider == "openrouter":
                spent = _measured_spend_usd(run_dir, env, float(budget_start))
                if cell_succeeded:
                    _settle_cell_reservation(run_dir, cell, spent)
                    _record_run_cell_outcome(run_dir, cell, "complete")
                else:
                    failure = cell_error or _checkpoint_failure_detail(run_dir, cell) or "publication cell failed"
                    if cell_ineligible:
                        _record_ineligible_cell_reservation(run_dir, cell, spent, failure)
                        state = "ineligible"
                    else:
                        _record_failed_cell_reservation(run_dir, cell, spent, failure)
                        reservation = _read_json_if_valid(run_dir / "openrouter-reservations.json") or {}
                        stored = (reservation.get("cells") or {}).get(f"{cell.experiment_id}--{cell.cap_label}") or {}
                        state = "excluded" if stored.get("status") == "excluded" else "aborted"
                    _record_run_cell_outcome(run_dir, cell, state, failure)
                print(f"measured OpenRouter spend for this run directory: ${spent:.4f}")
                if spent > args.max_spend_usd:
                    raise SystemExit(f"spend ceiling exceeded after attempted cell: ${spent:.4f}")
    if preflight_failures:
        raise SystemExit(
            f"zero-completion-call route preflight failed for "
            f"{len(preflight_failures)} of {len(cells)} routes:\n  " + "\n  ".join(preflight_failures)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
