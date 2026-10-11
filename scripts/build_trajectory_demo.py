#!/usr/bin/env python3
"""Export public seed 1 only for the experimental website trajectory explorer.

No external artifacts, seeds, credentials, provider or model inputs are accepted.
The existing conservative replay remains the authority and is never rewritten.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gm_bench.agents import AGENTS, Agent  # noqa: E402
from gm_bench.protocol import EpisodeConfig  # noqa: E402
from gm_bench.recorder import (  # noqa: E402
    DecisionRecorder,
    canonical_state_digest,
    record_episode,
    validate_replay_fixture,
)
from gm_bench.scoring import score_breakdown, score_components  # noqa: E402
from gm_bench.simulator import League  # noqa: E402

DESTINATION = ROOT / "web/public/replay/trajectory-demo.json"
ORIGINAL = ROOT / "web/public/replay/replay_fixture.json"
# Identifies the engine checkout used for these demonstrations. Later site-only
# edits do not pretend to have regenerated scientific evidence on a new engine.
SOURCE_COMMIT = "4f87f40a73269a32ab1e3789569dd48d2d1084ec"
SOURCE_PACKAGE_SHA256 = "70e044bca5ed8875835953d3a147757c05f3274380894233ccdc94c51c336e15"


# Pin the original source surface, not every module in a future checkout.
# Adding an independent experiment must not rewrite public-demo provenance.
# A new dependency of this demo requires changing a pinned importer, which the
# digest still rejects until the source commit/manifest/hash are reviewed.
SOURCE_MODULES = (
    "__init__.py",
    "__main__.py",
    "action_validation.py",
    "agent_utils.py",
    "agents.py",
    "baseline_cache.py",
    "benchmark_config.py",
    "calibration.py",
    "cli.py",
    "contract.py",
    "decision_providers.py",
    "environment.py",
    "generator.py",
    "gui.py",
    "model_runs.py",
    "models.py",
    "official.py",
    "oracle.py",
    "protocol.py",
    "providers.py",
    "publication.py",
    "recorder.py",
    "repair.py",
    "runner.py",
    "scaffold_view.py",
    "scoring.py",
    "session.py",
    "simulator.py",
    "storage.py",
    "telemetry.py",
    "validity.py",
)


class CaptureAgent(Agent):
    """Retain the full observation actually passed to the scripted policy."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.wrapped = AGENTS[name]()
        self.observations: list[dict] = []

    def act(self, observation: dict) -> list[dict]:
        self.observations.append(copy.deepcopy(observation))
        return self.wrapped.act(observation)


def source_package_digest() -> str:
    """Hash the pinned source manifest, independent of unrelated module additions."""
    digest = hashlib.sha256()
    for name in SOURCE_MODULES:
        path = ROOT / "gm_bench" / name
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def build_demo() -> dict:
    if source_package_digest() != SOURCE_PACKAGE_SHA256:
        raise ValueError("engine/recorder source changed: review and pin new source provenance before exporting")
    original_bytes = ORIGINAL.read_bytes()
    original = json.loads(original_bytes)
    episodes = []
    with tempfile.TemporaryDirectory(prefix="gm-trajectory-") as temporary:
        for name in ("conservative", "pick-trader"):
            agent = CaptureAgent(name)
            path = Path(temporary) / f"{name}.jsonl"
            with DecisionRecorder(path, agent_name=name, ghost_agents=()) as recorder:
                recorder.provenance["git_head"] = SOURCE_COMMIT
                league = record_episode(agent, seed=1, recorder=recorder, seasons=5, config=EpisodeConfig())
                fixture_path = recorder.export_replay_fixture(
                    Path(temporary) / f"{name}.json", league, config=EpisodeConfig()
                )
            fixture = json.loads(fixture_path.read_text())
            validate_replay_fixture(fixture)
            if name == "conservative":
                if fixture["expected"]["state_digest"] != original["expected"]["state_digest"]:
                    raise ValueError("conservative demo no longer matches the original replay")
                if fixture["decisions"] != original["decisions"]:
                    raise ValueError("conservative decisions no longer match the original replay")
            records = [json.loads(line) for line in path.read_text().splitlines()]
            cursor = 0
            for decision, record in zip(fixture["decisions"], records, strict=True):
                for round_record in decision["interaction_rounds"]:
                    round_record["observation"] = agent.observations[cursor]
                    cursor += 1
                decision["results"] = record["results"]
                decision["delta"] = record["delta"]
            assert cursor == len(agent.observations)
            episodes.append(
                {
                    "kind": "scripted-demo",
                    "fixture": fixture,
                    "components": score_components(league, 0),
                    "score": score_breakdown(league, 0),
                }
            )
    return {
        "schema": "gm-bench-public-trajectories-v1",
        "track": "experimental-public-demo",
        "seed_scope": "public-dev",
        "source_commit": SOURCE_COMMIT,
        "source_package_sha256": SOURCE_PACKAGE_SHA256,
        "starting_state_digest": canonical_state_digest(League.new(seed=1, user_team_id=0)),
        "original_replay_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "tool_trace": None,
        "episodes": episodes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="regenerate offline and compare without writing")
    args = parser.parse_args()
    output = json.dumps(build_demo(), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text() != output:
            raise SystemExit("public trajectory export is stale; run scripts/build_trajectory_demo.py")
        print("Public trajectory export reproduced; both five-season replay digests verified.")
    else:
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        DESTINATION.write_text(output)
        print(f"Wrote {DESTINATION} ({len(output):,} bytes)")


if __name__ == "__main__":
    main()
