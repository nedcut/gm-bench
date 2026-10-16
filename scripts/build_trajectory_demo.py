#!/usr/bin/env python3
"""Export public seed 1 only for the experimental website trajectory explorer.

No external artifacts, seeds, credentials, provider or model inputs are accepted.
The existing conservative replay remains the authority and is never rewritten.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gm_bench.agentic.contract import agentic_contract  # noqa: E402
from gm_bench.agentic.episode import ENDED_BY_AGENT, AgenticEpisode  # noqa: E402
from gm_bench.agentic.tools import TOOLS_BY_NAME, validate_arguments  # noqa: E402
from gm_bench.agents import AGENTS, Agent  # noqa: E402
from gm_bench.protocol import EpisodeConfig  # noqa: E402
from gm_bench.recorder import (  # noqa: E402
    DecisionRecorder,
    canonical_state,
    canonical_state_digest,
    component_delta,
    probe_observation,
    record_episode,
    validate_replay_fixture,
)
from gm_bench.runner import _observation_tier_for_agent  # noqa: E402
from gm_bench.scoring import score_breakdown, score_components  # noqa: E402
from gm_bench.simulator import League  # noqa: E402

DESTINATION = ROOT / "web/public/replay/trajectory-demo.json"
ORIGINAL = ROOT / "web/public/replay/replay_fixture.json"
# Seed-1 ledgers from the committed public smoke rows, copied verbatim from the
# raw runs. Resolved from this file, not ROOT, so source-copy tests still find
# them and the rows they are checked against.
EVIDENCE = Path(__file__).resolve().parents[1]
LEDGERS = EVIDENCE / "docs/trajectory-explorer/ledgers"
AGENT_RUNS = (
    {
        "agent": "claude-code-sonnet-5",
        "ledger": "claude-2.1.281-claude-sonnet-5-seed-1.ledger.jsonl",
        "row": "results/agentic/claude-2.1.281-claude-sonnet-5-smoke-4x5-run-a.json",
        "harness": "claude",
        "harness_version": "2.1.281",
        "model": "claude-sonnet-5",
    },
    {
        "agent": "codex-gpt-6-luna",
        "ledger": "codex-0.156.1-gpt-6-luna-seed-1.ledger.jsonl",
        "row": "results/agentic/codex-0.156.1-gpt-6-luna-smoke-4x5-run-a.json",
        "harness": "codex",
        "harness_version": "0.156.1",
        "model": "gpt-6-luna",
    },
)
# Identifies the engine checkout used for these demonstrations. Later site-only
# edits do not pretend to have regenerated scientific evidence on a new engine.
SOURCE_COMMIT = "4f87f40a73269a32ab1e3789569dd48d2d1084ec"
SOURCE_PACKAGE_SHA256 = "bb0a475cba1416657b3c2f09a214104878f1875724b95268bfeffe0b2528a6eb"


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


def agent_episode(run: dict, tier: str, contract_fingerprint: str) -> dict:
    """Rebuild one agent's 2.0 episode from its ledger, window by window.

    Replays the ledger through the frozen engine the way ``from_ledger`` does,
    but snapshots each phase: the state at phase open (shown to the reader,
    never to the agent, which read state only through its tool calls), every
    tool call with its recorded reply, the simulator actions, and the score
    delta before the phase's closing hooks. Each replayed reply must agree with
    the recorded one, and the final score must equal the committed row's.
    """
    ledger_path = LEDGERS / run["ledger"]
    ledger_bytes = ledger_path.read_bytes()
    records = [json.loads(line) for line in ledger_bytes.decode().splitlines() if line.strip()]
    header = records[0]
    if header.get("event") != "episode" or header["seed"] != 1:
        raise ValueError(f"{ledger_path.name} is not a seed-1 agentic ledger")
    episode = AgenticEpisode(
        header["seed"], header["seasons"], header["user_team_id"], ledger_path=None, write_header=False
    )
    episode._replaying = True
    league = episode.league
    decisions: list[dict] = []
    window: dict | None = None

    def close_window(ended_by: str) -> None:
        window["delta"] = component_delta(window.pop("before"), score_components(league, header["user_team_id"]))
        window["ended_by"] = ended_by
        decisions.append(window)

    def open_window() -> None:
        nonlocal window
        window = {
            "decision_index": len(decisions),
            "season": episode.season,
            "phase": episode.phase,
            "before": score_components(league, header["user_team_id"]),
            "interaction_rounds": [
                {"round": 0, "observation": probe_observation(league, episode.phase, tier), "actions": []}
            ],
            "results": [],
            "tool_calls": [],
        }

    # The ledger logs the next phase's ``phase_open`` before the ``end_phase``
    # call that caused it, so windows follow the engine's calendar and the
    # recorded ``phase_open`` order is checked once at the end.
    open_window()
    for record in records[1:]:
        event = record["event"]
        if event == "tool_call":
            call = {
                "seq": record["seq"],
                "tool": record["tool"],
                "kind": TOOLS_BY_NAME[record["tool"]]["kind"] if record["tool"] in TOOLS_BY_NAME else "unknown",
                "arguments": record["arguments"],
                "ok": record["ok"],
                "message": record["message"],
                "executed": record["executed"],
                "penalized": record["penalized"],
                "ids_exposed": len(record["ids_exposed"]),
            }
            window["tool_calls"].append(call)
            if not record["executed"]:
                continue
            arguments = record["arguments"] or {}
            reaches_simulator = call["kind"] in ("query", "move") and not validate_arguments(call["tool"], arguments)
            if call["tool"] == "end_phase" and call["ok"]:
                close_window(ENDED_BY_AGENT)
            logged = len(league.transactions)
            reply = episode._execute(call["tool"], arguments)
            if bool(reply.get("ok")) != record["ok"] or str(reply.get("message", ""))[:300] != record["message"]:
                raise ValueError(f"{ledger_path.name}: call {record['seq']} replayed differently from the ledger")
            if reaches_simulator:
                for transaction in league.transactions[logged:]:
                    if transaction.team_id == header["user_team_id"]:
                        window["interaction_rounds"][0]["actions"].append(transaction.action)
                        window["results"].append(
                            {
                                "accepted": transaction.accepted,
                                "message": transaction.message,
                                "action": transaction.action,
                            }
                        )
            if call["tool"] == "end_phase" and call["ok"] and not episode.done:
                open_window()
        elif event == "phase_end" and record["ended_by"] != ENDED_BY_AGENT:
            close_window(record["ended_by"])
            episode._close_phase(record["ended_by"])
            if not episode.done:
                open_window()
    if not episode.done or len(decisions) != 20:
        raise ValueError(f"{ledger_path.name}: ledger does not complete five seasons")
    opened = [(r["season"], r["phase"]) for r in records if r["event"] == "phase_open"]
    if opened != [(d["season"], d["phase"]) for d in decisions]:
        raise ValueError(f"{ledger_path.name}: replay is out of step with the recorded calendar")

    score = score_breakdown(league, header["user_team_id"])
    row = json.loads((EVIDENCE / run["row"]).read_text())
    committed = next(e["final_score"] for e in row["episodes"] if e["seed"] == 1)
    if round(score["final_score"], 3) != committed:
        raise ValueError(f"{ledger_path.name}: replayed score {score['final_score']:.3f} != committed {committed}")
    return {
        "kind": "agentic-run",
        "fixture": {
            "schema": "gm-bench-decision-replay-v1",
            "seed": header["seed"],
            "config": dataclasses.asdict(EpisodeConfig()),
            "user_team_id": header["user_team_id"],
            "agent": run["agent"],
            "metadata": {
                "harness": run["harness"],
                "harness_version": run["harness_version"],
                "model": run["model"],
                "isolation": row["isolation"],
                "grade": row["grade"],
                "source_row": run["row"],
                "ledger": f"docs/trajectory-explorer/ledgers/{run['ledger']}",
                "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
            },
            "provenance": {
                "contract_fingerprint": contract_fingerprint,
                "agentic_fingerprint": row["contract"]["agentic_fingerprint"],
            },
            "decisions": decisions,
            "expected": {"state": canonical_state(league), "state_digest": canonical_state_digest(league)},
        },
        "components": score_components(league, header["user_team_id"]),
        "score": score,
    }


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
    fingerprint = agentic_contract()["agentic_fingerprint"]
    if any(
        json.loads((EVIDENCE / run["row"]).read_text())["contract"]["agentic_fingerprint"] != fingerprint
        for run in AGENT_RUNS
    ):
        raise ValueError("an agent run was played on a different agentic contract than this checkout")
    tier = _observation_tier_for_agent(AGENTS["pick-trader"](), EpisodeConfig())
    contract = episodes[0]["fixture"]["provenance"]["contract_fingerprint"]
    episodes.extend(agent_episode(run, tier, contract) for run in AGENT_RUNS)
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
        print("Public trajectory export reproduced; scripted digests and agent ledger replays verified.")
    else:
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        DESTINATION.write_text(output)
        print(f"Wrote {DESTINATION} ({len(output):,} bytes)")


if __name__ == "__main__":
    main()
