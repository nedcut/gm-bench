"""Public evidence checks run without access to the private panel."""

import copy
import json
from pathlib import Path

import pytest

from web.scripts.validate_best_run import validate_best_run, validate_showcase

ROOT = Path(__file__).resolve().parents[1]


def test_showcase_matches_published_best_episode():
    validate_best_run()


@pytest.mark.parametrize("mutation", ["seed", "wins", "accepted", "path", "id"])
def test_showcase_rejects_leaks_and_inconsistent_counts(mutation):
    summary = json.loads((ROOT / "web/src/data/best-run-summary.json").read_text())
    data = copy.deepcopy(json.loads((ROOT / "web/src/data/astra-showcase.json").read_text()))
    if mutation == "seed":
        data["seed"] = 123
    elif mutation == "wins":
        data["seasons"][0]["wins"] += 1
    elif mutation == "accepted":
        data["seasons"][0]["moves"][0]["accepted"] = False
    elif mutation == "id":
        data["seasons"][0]["moves"][0]["player_id"] = 12
    else:
        data["seasons"][0]["moves"][0]["detail"] = "/home/operator/private/ledger.jsonl"
    with pytest.raises(AssertionError):
        validate_showcase(data, summary)
