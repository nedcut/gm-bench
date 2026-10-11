"""Offline checks for the isolated experimental draft diagnostic."""

import copy
import json
import random
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from gm_bench import counterfactual as cf


@pytest.fixture(scope="module")
def checkpoint():
    return cf.make_checkpoint(1)


@pytest.fixture(scope="module")
def comparison(checkpoint):
    return cf.compare(
        checkpoint, cf.enumerate_candidates(checkpoint, 2), horizons=(1, 2), rollout_seeds=(1001, 1002, 1003)
    )


def test_replay_and_json_roundtrip(checkpoint, tmp_path):
    cf.save_json(tmp_path / "checkpoint.json", checkpoint)
    rebuilt = cf.replay_checkpoint(cf.read_json(tmp_path / "checkpoint.json"))
    assert cf.state_digest(rebuilt) == checkpoint["state_sha256"]
    assert "true_potential" not in json.dumps(checkpoint)
    assert cf.make_checkpoint(1) == checkpoint
    assert cf.replay_checkpoint(cf.make_checkpoint(2, 2)).season == 2


@pytest.mark.parametrize("field", ["observation", "prefix", "state_sha256", "provenance", "checkpoint_id"])
def test_tamper_rejected(checkpoint, field):
    bad = copy.deepcopy(checkpoint)
    bad[field] = "tampered"
    with pytest.raises(ValueError, match="replay mismatch"):
        cf.replay_checkpoint(bad)


def test_candidate_validation_and_isolation(checkpoint):
    league = cf.replay_checkpoint(checkpoint)
    before = cf.state_digest(league)
    candidates = cf.enumerate_candidates(checkpoint, 3)
    assert len(candidates) == 3
    cf._validate_candidates(league, candidates)
    assert cf.state_digest(league) == before
    for bad in ([], [candidates[0]] * 2, [*candidates, {"type": "draft", "prospect_id": -1}], [{"type": "noop"}] * 2):
        with pytest.raises(ValueError):
            cf._validate_candidates(league, bad)
    a, b = cf._branch(league, 1001), cf._branch(league, 1001)
    a.players[next(iter(a.players))].overall = -100
    a.teams[0].roster.clear()
    assert cf.state_digest(b) == before == cf.state_digest(league)


def test_rng_instrumentation_preserves_draws():
    record = {"random_calls": 0, "getrandbits_calls": 0, "requested_bits": 0}
    audited, plain = cf._AuditedRandom("test", record), random.Random("test")
    for _ in range(20):
        assert audited.random() == plain.random()
        assert audited.randint(1, 13) == plain.randint(1, 13)
        assert audited.gauss(0, 1) == plain.gauss(0, 1)
    assert audited.getstate() == plain.getstate()
    assert record["random_calls"] > 20
    assert record["getrandbits_calls"] >= 20


def test_rng_branch_control_and_independent_streams(checkpoint):
    league = cf.replay_checkpoint(checkpoint)
    left, right, independent = (cf._branch(league, seed) for seed in (1001, 1001, 1002))
    assert left._rng("test").random() == right._rng("test").random()
    assert left.rng_audit == right.rng_audit
    assert cf._branch(league, 1001)._rng("test").random() != independent._rng("test").random()
    assert independent.seed == league.seed  # no changed latent state or seed-keyed reservations


def test_reproducibility_order_and_paired_uncertainty(checkpoint, comparison):
    actions = comparison["candidates"]
    duplicate = cf.compare(checkpoint, actions, horizons=(1, 2), rollout_seeds=(1001, 1002, 1003))
    assert comparison == duplicate
    reversed_result = cf.compare(checkpoint, actions[::-1], horizons=(1, 2), rollout_seeds=(1001, 1002, 1003))
    for left in comparison["rows"]:
        right = next(
            r
            for r in reversed_result["rows"]
            if r["candidate_index"] == 1 - left["candidate_index"]
            and r["horizon"] == left["horizon"]
            and r["rollout_seed"] == left["rollout_seed"]
        )
        assert left["state_sha256"] == right["state_sha256"]
    for summary in comparison["summaries"]:
        assert summary["score"]["n"] == 3  # not six correlated season rows
        if summary["candidate_index"] == 0:
            assert summary["paired_score_delta_vs_candidate_0"]["mean"] == 0
            assert summary["paired_score_delta_vs_candidate_0"]["standard_error"] == 0
    assert comparison["randomness"]["event_level_crn_guaranteed"] is False
    assert cf.uncertainty([1.0])["standard_error"] is None
    assert cf.make_checkpoint(1) == checkpoint


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rollout_seeds": (1001, 1001)},
        {"rollout_seeds": ()},
        {"rollout_seeds": (1,)},
        {"horizons": (4,)},
        {"horizons": (1, 1)},
        {"horizons": (True,)},
    ],
)
def test_runtime_bounds(checkpoint, kwargs):
    with pytest.raises(ValueError):
        cf.compare(checkpoint, **kwargs)


@pytest.mark.parametrize("seed", [0, 33, True, "1"])
def test_public_seeds_only(seed):
    with pytest.raises(ValueError):
        cf.make_checkpoint(seed)


def test_export_schemas(checkpoint, comparison):
    for name, payload in (("checkpoint", checkpoint), ("comparison", comparison)):
        schema = json.loads((Path(__file__).parents[1] / "schemas" / f"counterfactual_{name}.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(payload, schema)


def test_cli_end_to_end(tmp_path):
    checkpoint, result = tmp_path / "checkpoint.json", tmp_path / "comparison.json"
    for args in (
        ["checkpoint", "--seed", "2", "--out", str(checkpoint)],
        ["compare", str(checkpoint), "--limit", "2", "--rollouts", "1", "--horizons", "1", "--out", str(result)],
    ):
        subprocess.run(
            [sys.executable, "-m", "gm_bench.counterfactual", *args], check=True, timeout=30, capture_output=True
        )
    payload = cf.read_json(result)
    assert len(payload["rows"]) == 2
    assert payload["summaries"][0]["score"]["normal_95_interval"] is None


def test_horizon_prefix_and_downstream_win_subtraction(checkpoint, comparison):
    shorter = cf.compare(checkpoint, comparison["candidates"], horizons=(1,), rollout_seeds=(1001, 1002, 1003))
    assert shorter["rows"] == [r for r in comparison["rows"] if r["horizon"] == 1]
    league = cf.replay_checkpoint(checkpoint)
    before_wins = league.user_team.wins
    assert before_wins > 0
    branch = cf._branch(league, 1001)
    branch.apply_actions([comparison["candidates"][0]], "draft")
    cf._finish(branch, "draft")
    summary = branch.simulate_season()
    assert shorter["rows"][0]["downstream_wins"] == summary.wins - before_wins
