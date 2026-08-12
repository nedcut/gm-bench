"""Integrity checks for the zero-spend sota-v3 public route-catalog freeze."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.run_publication_matrix as publication_runner
from gm_bench.publication import canonical_sha256, publication_execution_issues, v3_route_acceptance_issues

CONFIG = Path("config")


def _read(name: str) -> dict:
    payload = json.loads((CONFIG / name).read_text())
    assert isinstance(payload, dict)
    return payload


def test_v3_catalog_freezes_exact_balanced_cohort_without_unlocking_execution() -> None:
    registry = _read("sota_v3_models.json")

    models = registry["models"]
    assert len(models) == 8
    assert len({model["id"] for model in models}) == 8
    assert len({(model["model"], model["endpoint_tag"]) for model in models}) == 8
    assert {model["cohort"] for model in models} == {"frontier-proprietary", "open-weight"}
    # Amendment-3 withdrew Gemini 3.6 Flash and Grok 4.5, the only mandatory-
    # reasoning routes and both frontier-proprietary, so the cohort is no longer
    # balanced 4/6. Reasoning uniformity was chosen over cohort balance; this
    # pins the resulting 2/6 split so a future lineup edit cannot drift it
    # further without a deliberate decision.
    assert sum(model["cohort"] == "frontier-proprietary" for model in models) == 2
    assert sum(model["cohort"] == "open-weight" for model in models) == 6

    identities = {model["model"] for model in models}
    assert "openai/gpt-5.6-luna" in identities
    assert "openai/gpt-5.6-luna-pro" not in identities
    assert "deepseek/deepseek-v4-flash-0731" in identities
    assert "tencent/hy3" in identities
    # Evaluated for the tenth slot, ineligible at the frozen snapshot: no
    # healthy route advertises response_format under require-parameters.
    assert "thinkingmachines/inkling-small" not in identities
    # Withdrawn by amendment-3 as the two mandatory-reasoning routes. They are
    # asserted absent rather than simply dropped so that silently re-adding
    # either one -- and with it the cross-model reasoning inconsistency that
    # already excluded both from the frozen sota-v2 panel -- fails here.
    assert "google/gemini-3.6-flash" not in identities
    assert "google/gemini-3.5-flash" not in identities
    assert "x-ai/grok-4.5" not in identities
    assert "mistralai/mistral-medium-3-5" in identities
    assert "meta/muse-spark-1.1" not in identities

    assert registry["catalog_snapshot_status"] == "frozen-public-metadata-only"
    assert registry["selection_status"] == "frozen"
    assert registry["selection_frozen_at_utc"]
    assert registry["selection_revision"] == "2026-08-11-cloudflare-route-tag-refresh-v5"
    policy = registry["selection_policy"]
    assert "Qwen 3.8 Max" in policy
    assert "deepinfra/fp8" in policy and "Cloudflare" in policy
    assert "now frozen" in policy
    assert registry["catalog_checked_at_utc"]
    assert set(registry["required_smokes"]) == {model["id"] for model in models}
    assert registry["output_token_cap"] == 4_096
    assert registry["output_budget_status"] == "frozen-native-reasoning-cap"
    acceptance = registry["exact_route_acceptance"]
    assert acceptance["status"] == "accepted"
    assert acceptance["privacy_standard"]["provider_data_collection"] == "deny"
    assert acceptance["privacy_standard"]["provider_training_use_allowed"] is False
    assert acceptance["privacy_standard"]["zero_data_retention_required"] is False
    assert set(acceptance["entries"]) == {model["id"] for model in models}
    for entry in acceptance["entries"].values():
        assert entry["authenticated"] is True
        assert len(entry["route_identity_sha256"]) == 64
        privacy = entry["privacy_acceptance"]
        assert privacy["status"] == "accepted"
        assert privacy["zero_data_retention_requirement_satisfied"] is True
        assert isinstance(privacy["zero_data_retention_endpoint"], bool)
    assert registry["spend_authorized"] is True
    assert registry["route_preflight_authorized"] is True
    assert registry["panel_execution_authorized"] is False
    assert registry["publication_authorized"] is False


def test_v3_catalog_pins_routes_parameters_reasoning_and_exact_route_prices() -> None:
    registry = _read("sota_v3_models.json")
    pricing = _read("sota_v3_pricing_snapshot.json")
    rates = pricing["models"]

    for model in registry["models"]:
        assert model["upstream_provider_slug"] == model["endpoint_tag"]
        assert model["endpoint_name"].endswith(model["canonical_slug"])
        assert model["catalog_route_status"] == 0
        assert model["catalog_uptime_last_30m"] > 0
        assert {"reasoning", "max_tokens", "response_format"} <= set(model["catalog_supported_parameters"])
        assert model["reasoning_policy"] in {
            "disabled",
            "mandatory-minimum",
        }

        route_rate = rates[model["model"]]
        assert route_rate["provider_slug"] == model["endpoint_tag"]
        assert route_rate["endpoint_name"] == model["endpoint_name"]
        assert route_rate["prompt"] >= 0
        assert route_rate["completion"] >= 0

        reasoning = model["catalog_reasoning"]
        if reasoning.get("mandatory"):
            assert model["reasoning_policy"] == "mandatory-minimum"
            assert model["fixed_options"]["OPENROUTER_REASONING_ENABLED"] == "true"
            assert model["reasoning_effort"] == reasoning["supported_efforts"][-1]
        else:
            assert model["reasoning_policy"] == "disabled"
            assert model["fixed_options"]["OPENROUTER_REASONING_ENABLED"] == "false"
            assert "OPENROUTER_REASONING_EFFORT" in model["absent_options"]

    # The whole point of amendment-3: every registered route runs reasoning
    # disabled, so no model may carry a mandatory-reasoning catalog entry or a
    # reasoning-enabled fixed option. The loop above still checks the mandatory
    # branch for any future route; this asserts the branch is currently empty.
    assert [m["id"] for m in registry["models"] if m["catalog_reasoning"].get("mandatory")] == []
    assert [m["id"] for m in registry["models"] if m["reasoning_policy"] != "disabled"] == []
    assert pricing["status"] == "frozen"
    assert pricing["checked_at_utc"] == registry["catalog_checked_at_utc"]
    assert pricing["spend_authorized"] is True
    assert pricing["route_preflight_authorized"] is True
    assert pricing["smoke_execution_authorized"] is True
    assert pricing["panel_execution_authorized"] is False
    assert pricing["publication_authorized"] is False
    assert pricing["runtime_observations"]["source"] is None
    assumptions = pricing["planning_assumptions"]
    assert assumptions["input_tokens_per_decision"] == 8_000
    assert assumptions["expected_output_tokens_per_decision"] == 4_096
    assert assumptions["expected_internal_reasoning_tokens_per_decision"] == 4_096
    assert assumptions["cost_contingency_multiplier"] == 1.2
    assert assumptions["runtime_contingency_multiplier"] == 1.2
    assert "pre-smoke" in assumptions["basis"]


def test_selected_catalog_models_match_runner_exact_route_shape() -> None:
    registry = _read("sota_v3_models.json")

    # Exercise the runner's executable enum and exact-route schema directly,
    # without weakening or bypassing the separate authorization gates.
    publication_runner._validate_models(
        registry["models"],
        expected_provider=registry["provider"],
    )


def test_v3_route_acceptance_is_bound_to_public_zero_completion_evidence() -> None:
    registry = _read("sota_v3_models.json")
    acceptance = registry["exact_route_acceptance"]
    evidence = json.loads(Path(acceptance["evidence_artifact"]).read_text())

    assert evidence["format"] == "gm-bench-route-acceptance-evidence-v1"
    assert evidence["completion_calls"] == 0
    assert evidence["account_authentication"]["sensitive_values_included"] is False
    assert set(evidence["routes"]) == set(acceptance["entries"])
    # 4, not 5: the withdrawn Grok 4.5 route was pinned to xai/zdr.
    assert sum(route["zero_data_retention_endpoint"] for route in evidence["routes"].values()) == 4
    for model_id, route in evidence["routes"].items():
        entry = acceptance["entries"][model_id]
        assert entry["route_evidence_sha256"] == canonical_sha256(route)
        privacy_evidence = {
            "route_identity_sha256": route["route_identity_sha256"],
            "privacy_standard": evidence["privacy_standard"],
            "zero_data_retention_endpoint": route["zero_data_retention_endpoint"],
            "provider_policy": route["provider_policy"],
            "official_policy_sources": evidence["official_policy_sources"],
        }
        assert entry["privacy_acceptance"]["evidence_sha256"] == canonical_sha256(privacy_evidence)

    assert v3_route_acceptance_issues(registry) == []
    first_entry = registry["exact_route_acceptance"]["entries"][next(iter(evidence["routes"]))]
    route_sha = first_entry["route_evidence_sha256"]
    first_entry["route_evidence_sha256"] = "0" * 64
    assert any("route evidence digest does not match" in issue for issue in v3_route_acceptance_issues(registry))
    first_entry["route_evidence_sha256"] = route_sha
    first_entry["privacy_acceptance"]["evidence_sha256"] = "0" * 64
    assert any("privacy evidence digest does not match" in issue for issue in v3_route_acceptance_issues(registry))


def test_v3_route_acceptance_resolves_relative_evidence_from_repo_root(tmp_path: Path, monkeypatch) -> None:
    """Acceptance must not depend on which directory the caller ran from.

    The registry records a repo-relative evidence path; resolving it against
    the CWD only worked because pytest and the runner both happen to start at
    the repo root.
    """
    registry = _read("sota_v3_models.json")
    monkeypatch.chdir(tmp_path)
    assert v3_route_acceptance_issues(registry) == []


def test_smoke_authorization_still_cannot_unlock_panel_or_publication() -> None:
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")
    protocol = _read("sota_v3_publication_protocol.json")
    pricing = _read("sota_v3_pricing_snapshot.json")
    manifest = _read("sota_v3_smoke_manifest.json")

    assert lane["route_preflight_authorized"] is True
    assert lane["spend_authorized"] is True
    assert lane["smoke_execution_authorized"] is True
    assert lane["panel_execution_authorized"] is False
    assert lane["publication_authorized"] is False
    assert protocol["budget_policy"]["spend_authorized"] is True
    assert protocol["publication_authorized"] is False
    assert manifest["accepted_for_panel"] is False
    assert pricing["route_preflight_authorized"] is True

    assert (
        publication_execution_issues(
            lane,
            registry,
            manifest,
            phase="smoke",
            protocol=protocol,
            pricing=pricing,
        )
        == []
    )

    assert (
        publication_execution_issues(
            lane,
            registry,
            manifest,
            phase="route-preflight",
            protocol=protocol,
            pricing=pricing,
        )
        == []
    )
    assert registry["selection_status"] == "frozen"
    assert registry["selection_frozen_at_utc"]

    panel_issues = publication_execution_issues(
        lane,
        registry,
        manifest,
        phase="panel",
        protocol=protocol,
        pricing=pricing,
    )
    assert "panel execution is locked by the model registry" in panel_issues
    assert "sota-v3 smoke manifest is not accepted for panel execution" in panel_issues
