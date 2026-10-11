"""Deterministic offline specialist learning, separation and adapter checks."""

import copy
import json
import subprocess
import sys

import pytest

from gm_bench import counterfactual as cf
from gm_bench import draft_specialist as specialist


@pytest.fixture(scope="module")
def panels():
    result = []
    for seed in (1, 2, 17, 18):
        checkpoint = cf.make_checkpoint(seed)
        result.append(
            cf.compare(checkpoint, cf.enumerate_candidates(checkpoint, 3), horizons=(1, 2), rollout_seeds=(1001, 1002))
        )
    return result[:2], result[2:]


@pytest.fixture(scope="module")
def model(panels):
    return specialist.fit(panels[0])


def test_deterministic_fit_and_episode_evaluation(panels, model):
    train, test = panels
    assert model == specialist.fit(train)
    assert any(abs(w) > 0 for w in model["weights"])
    report = specialist.evaluate(model, test)
    assert set(report["training_seeds"]).isdisjoint(report["test_seeds"])
    assert report["score_delta_vs_heuristic"]["n"] == 2
    assert len(report["episodes"]) == 2
    assert model["feature_names"] == specialist.FEATURES
    assert "seed" not in model["feature_names"]


def test_leakage_rejected_at_seed_level(panels, model):
    train, test = panels
    with pytest.raises(ValueError, match="overlap"):
        specialist.evaluate(model, [train[0], test[0]])
    with pytest.raises(ValueError, match="duplicate"):
        specialist.evaluate(model, [test[0], test[0]])
    with pytest.raises(ValueError, match="duplicated"):
        specialist.fit([train[0], train[0]])
    # A different checkpoint season still belongs to the same seed episode group.
    cp = cf.make_checkpoint(1, 2)
    same_seed = cf.compare(cp, cf.enumerate_candidates(cp, 2), horizons=(2,), rollout_seeds=(1001,))
    with pytest.raises(ValueError, match="overlap"):
        specialist.evaluate(model, [same_seed, test[0]])


def test_training_is_not_affected_by_test_labels(panels, model):
    train, test = panels
    mutated = copy.deepcopy(test)
    mutated[0]["rows"][0]["score"] += 10000
    assert specialist.fit(train) == model
    with pytest.raises(ValueError, match="hash"):
        specialist.evaluate(model, mutated)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unexpected", "summary", "nonfinite"])
def test_label_semantics_checked_even_with_recomputed_hash(panels, mutation):
    payload = copy.deepcopy(panels[0][0])
    if mutation == "missing":
        payload["rows"].pop()
    elif mutation == "duplicate":
        payload["rows"].append(copy.deepcopy(payload["rows"][0]))
    elif mutation == "unexpected":
        payload["rows"][0]["candidate_index"] = 20
    elif mutation == "summary":
        payload["summaries"][0]["score"]["mean"] += 1
    else:
        payload["rows"][0]["score"] = "nan"
    payload["comparison_id"] = cf.digest({k: v for k, v in payload.items() if k != "comparison_id"})
    with pytest.raises(ValueError):
        specialist.validate_comparison(payload)


def test_adapter_only_uses_public_features_and_does_not_simulate(panels, model, monkeypatch):
    payload = panels[1][0]
    observation = copy.deepcopy(payload["checkpoint"]["observation"])
    candidates = payload["candidates"]
    before = cf.canonical(observation)
    monkeypatch.setattr(cf, "compare", lambda *args, **kwargs: pytest.fail("adapter simulated"))
    monkeypatch.setattr(cf, "replay_checkpoint", lambda *args, **kwargs: pytest.fail("adapter replayed"))
    ranked = specialist.rank_candidates(observation, candidates, model)
    assert cf.canonical(observation) == before
    observation["seed"] = 999
    observation["private_information"] = {"true_potential": 10000}
    assert specialist.rank_candidates(observation, candidates, model) == ranked
    reversed_result = specialist.rank_candidates(observation, candidates[::-1], model)
    assert [r["action"] for r in ranked] == [r["action"] for r in reversed_result]
    assert [r["preference"] for r in ranked] == sorted([r["preference"] for r in ranked], reverse=True)


def test_model_integrity_and_input_validation(panels, model):
    bad = copy.deepcopy(model)
    bad["weights"][0] += 1
    with pytest.raises(ValueError, match="integrity"):
        specialist.validate_model(bad)
    bad["scales"][0] = 0
    bad["model_id"] = cf.digest({k: v for k, v in bad.items() if k != "model_id"})
    with pytest.raises(ValueError, match="scales"):
        specialist.validate_model(bad)
    obs = panels[1][0]["checkpoint"]["observation"]
    with pytest.raises(ValueError, match="public draft"):
        specialist.rank_candidates(
            obs, [{"type": "draft", "prospect_id": -1}, {"type": "draft", "prospect_id": -2}], model
        )


def test_ridge_solver_known_solution():
    assert specialist._solve([[2.0, 1.0], [1.0, 3.0]], [3.0, 4.0]) == pytest.approx([1.0, 1.0])


def test_cli_demo_and_adapter(tmp_path):
    destination = tmp_path / "demo"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "gm_bench.draft_specialist",
            "demo",
            "--out-dir",
            str(destination),
            "--train-seeds",
            "1",
            "2",
            "--test-seeds",
            "17",
            "18",
            "--rollouts",
            "1",
            "--candidates",
            "2",
            "--horizon",
            "1",
        ],
        check=True,
        timeout=30,
        capture_output=True,
    )
    payload = cf.read_json(destination / "test-17.json")
    cf.save_json(tmp_path / "observation.json", payload["checkpoint"]["observation"])
    cf.save_json(tmp_path / "candidates.json", payload["candidates"])
    subprocess.run(
        [
            sys.executable,
            "-m",
            "gm_bench.draft_specialist",
            "rank",
            str(destination / "model.json"),
            str(tmp_path / "observation.json"),
            str(tmp_path / "candidates.json"),
            "--out",
            str(tmp_path / "ranked.json"),
        ],
        check=True,
        timeout=30,
        capture_output=True,
    )
    assert len(json.loads((tmp_path / "ranked.json").read_text())) == 2
    report = cf.read_json(destination / "evaluation.json")
    assert report["score_delta_vs_heuristic"]["n"] == 2


def test_adapter_requires_current_pick(panels, model):
    payload = panels[1][0]
    observation = copy.deepcopy(payload["checkpoint"]["observation"])
    observation["team"]["draft_picks"] = {}
    with pytest.raises(ValueError, match="no current-season"):
        specialist.rank_candidates(observation, payload["candidates"], model)


def test_specialist_schemas(panels, model):
    from pathlib import Path

    import jsonschema

    for name, payload in (("model", model), ("evaluation", specialist.evaluate(model, panels[1]))):
        schema = json.loads(
            (Path(__file__).parents[1] / "schemas" / f"draft_specialist_{name}.schema.json").read_text()
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(payload, schema)
