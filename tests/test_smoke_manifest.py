from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from gm_bench.contract import contract_fingerprint, scaffold_fingerprint
from gm_bench.publication import SMOKE_MANIFEST_FORMAT, smoke_manifest_issues


def _registry_and_lane() -> tuple[dict, dict]:
    registry = json.loads(Path("config/sota_v2_models.json").read_text())
    lane = json.loads(Path("config/sota_v2_lane.json").read_text())
    return registry, lane


def _valid_manifest(registry: dict, lane: dict) -> dict:
    return {
        "format": SMOKE_MANIFEST_FORMAT,
        "schema_version": 1,
        "entries": {
            model["id"]: {
                "provider": model["provider"],
                "model": model["model"],
                "upstream_provider": model["upstream_provider"],
                "endpoint_name": model["endpoint_name"],
                "output_token_cap": lane["output_token_cap"],
                "api_calls": 2,
                "calls_with_finish_reason": 2,
                "truncated_calls": 0,
                "max_output_tokens_per_call": 100,
                "reasoning_tokens": 0,
                "decision_failure_rate": 0,
                "contract_fingerprint": contract_fingerprint(),
                "scaffold_fingerprint": scaffold_fingerprint(model["provider"]),
                "artifact_sha256": "a" * 64,
                "accepted": True,
            }
            for model in registry["models"]
        },
    }


def test_missing_smoke_manifest_is_rejected() -> None:
    registry, lane = _registry_and_lane()
    assert smoke_manifest_issues(None, registry, lane) == [
        "smoke manifest is missing; record every registered-model smoke before the panel"
    ]


def test_complete_valid_smoke_manifest_has_no_issues() -> None:
    registry, lane = _registry_and_lane()
    assert smoke_manifest_issues(_valid_manifest(registry, lane), registry, lane) == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "has no smoke manifest entry"),
        ("not-accepted", "is not accepted"),
        ("truncated", "cap-induced truncation"),
        ("wrong-cap", "not frozen"),
        ("peak", "cap-pressure threshold"),
        ("failed-decisions", "decision_failure_rate must be zero"),
        ("invalid-sha", "raw artifact sha256"),
        ("wrong-scaffold", "different prompt scaffold"),
    ],
)
def test_invalid_smoke_entry_reports_issue(mutation: str, message: str) -> None:
    registry, lane = _registry_and_lane()
    manifest = copy.deepcopy(_valid_manifest(registry, lane))
    model_id = registry["models"][0]["id"]
    entry = manifest["entries"][model_id]
    if mutation == "missing":
        del manifest["entries"][model_id]
    elif mutation == "not-accepted":
        entry["accepted"] = False
    elif mutation == "truncated":
        entry["truncated_calls"] = 1
    elif mutation == "wrong-cap":
        entry["output_token_cap"] = lane["output_token_cap"] * 2
    elif mutation == "peak":
        entry["max_output_tokens_per_call"] = lane["cap_pressure_threshold_tokens"]
    elif mutation == "failed-decisions":
        entry["decision_failure_rate"] = 0.5
    elif mutation == "invalid-sha":
        entry["artifact_sha256"] = "z" * 64
    else:
        entry["scaffold_fingerprint"] = "wrong"
    assert any(message in issue for issue in smoke_manifest_issues(manifest, registry, lane))


def test_stale_smoke_manifest_entry_is_flagged() -> None:
    registry, lane = _registry_and_lane()
    manifest = _valid_manifest(registry, lane)
    manifest["entries"]["retired-model"] = copy.deepcopy(next(iter(manifest["entries"].values())))
    assert any(
        "'retired-model' is not in the current model registry" in issue
        for issue in smoke_manifest_issues(manifest, registry, lane)
    )
