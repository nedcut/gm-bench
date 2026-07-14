from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.estimate_publication_cost import estimate


def test_committed_sweep_cost_is_bounded_and_reproducible() -> None:
    sweep = json.loads(Path("config/output_budget_sweep.json").read_text())
    pricing = json.loads(Path("config/openrouter_pricing_snapshot.json").read_text())
    result = estimate(sweep, pricing)
    assert len(result["cells"]) == 12
    assert result["assumptions"]["decisions_per_cell"] == 480
    assert result["planning_total_usd"] == pytest.approx(27.0)
    assert result["token_ceiling_total_usd"] == pytest.approx(78.76)
    assert result["token_ceiling_total_with_contingency_usd"] < 100.0
    assert result["projected_serial_api_hours"] == pytest.approx(8.96)
    assert result["projected_serial_api_hours_with_contingency"] == pytest.approx(13.44)


def test_cost_estimator_rejects_unbounded_cells() -> None:
    sweep = json.loads(Path("config/output_budget_sweep.json").read_text())
    pricing = json.loads(Path("config/openrouter_pricing_snapshot.json").read_text())
    sweep["output_token_caps"][-1] = None
    with pytest.raises(ValueError, match="positive bounded cap"):
        estimate(sweep, pricing)
