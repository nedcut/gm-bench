import importlib.util
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("rescore_agentic_v2", _SCRIPTS / "rescore_agentic_v2.py")
rescore = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rescore)


def test_the_rescore_uses_score_v2_weight_for_weight() -> None:
    rescore._check_weights()  # raises if the deep dive's candidate E drifts from gm_bench/v21/scoring.py


def test_every_published_panel_row_has_a_bound_rescore() -> None:
    from gm_bench.v21 import scoring

    lane = json.loads((rescore.OUTPUT / "lane.json").read_text())
    assert lane["scoring_scale_fingerprint"] == scoring.scale_fingerprint()
    for raw_sha, artifact in rescore._artifacts_by_raw_sha().items():
        payload = json.loads((rescore.OUTPUT / artifact.name).read_text())
        assert payload["raw_artifact_sha256"] == raw_sha
        assert payload["scoring_version"] == "score-v2"
        # Aggregates and seed groups only: no seed values, no per-seed lifts.
        assert not {"seed", "seeds"} & set(payload) and payload["reference"]["per_seed"] == []
        assert all(
            set(episode) == {"index", "seed_group", "final_score", "strategy_score", "protocol_penalty"}
            for episode in payload["episodes"]
        )
