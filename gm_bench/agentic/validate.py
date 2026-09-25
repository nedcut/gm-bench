"""Validate an agentic run directory before anyone quotes a number from it.

Every check here is mechanical and reads only what the run wrote:

- the run's contract block matches the contract this checkout computes, so
  a row cannot drift onto a different tool surface or brief unnoticed;
- the run's seed list matches the episodes, and every ledger's header seed
  matches the episode that claims it;
- every episode's ledger replays to the score the result claims, which is
  the determinism guarantee 2.0 inherits from 1.0;
- every ledger audits clean (no move on an id no tool reply exposed);
- the server ledger and the harness event stream agree on tool calls, and
  that agreement is recomputed here from the retained ledger and event
  stream, never taken from the run's own claim;
- failed decisions and missing telemetry are surfaced, never hidden.

Problems are reported, not fixed. ``ok`` is False if any problem is fatal;
warnings are listed separately and leave ``ok`` alone.

The top-level ``problems`` and ``warnings`` name episodes by index and seed
for the operator. ``run_problems`` and ``run_warnings`` hold only the
run-level entries, and ``per_episode`` holds each episode's own lists, so a
publication step can rebuild the report by episode index without copying a
seed into a redacted artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gm_bench.agentic import codex, opencode
from gm_bench.agentic.audit import audit_ledger
from gm_bench.agentic.contract import agentic_contract
from gm_bench.agentic.episode import AgenticEpisode
from gm_bench.agentic.opencode import harness_tool_calls

_CONTRACT_KEYS = ("base_contract_fingerprint", "agentic_fingerprint", "tool_surface", "brief", "scoring_version")
# How to read each harness's retained event stream when recounting its GM-Bench tool calls.
EVENT_PARSERS = {
    opencode.HARNESS_NAME: opencode.parse_opencode_events,
    codex.HARNESS_NAME: codex.parse_codex_events,
}


def validate_run(run_path: str | Path) -> dict[str, Any]:
    run_path = Path(run_path)
    if run_path.is_dir():
        run_path = run_path / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run_problems: list[str] = []
    run_warnings: list[str] = []

    current = agentic_contract()
    recorded = run.get("contract") or {}
    for key in _CONTRACT_KEYS:
        if recorded.get(key) != current.get(key):
            run_problems.append(f"contract.{key}: run has {recorded.get(key)!r}, checkout has {current.get(key)!r}")

    episodes = run.get("episodes") or []
    if not episodes:
        run_problems.append("run has no episodes")
    seeds = [episode.get("seed") for episode in episodes]
    if list(run.get("seeds") or []) != seeds:
        run_problems.append("run.seeds does not match the episodes' seeds (count or order)")
    if len(set(seeds)) != len(seeds):
        run_warnings.append("repeated seeds present; within-seed noise is measurable but the panel is not one-per-seed")

    harness_name = (run.get("harness") or {}).get("name")
    per_episode = []
    problems = list(run_problems)
    warnings = list(run_warnings)
    for index, episode in enumerate(episodes):
        report = _validate_episode(episode, run_path.parent, harness_name)
        per_episode.append(report)
        label = f"episode {index} (seed {episode.get('seed')})"
        problems.extend(f"{label}: {item}" for item in report["problems"])
        warnings.extend(f"{label}: {item}" for item in report["warnings"])

    return {
        "run": str(run_path),
        "agent": run.get("agent"),
        "harness": run.get("harness"),
        "episodes": len(episodes),
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "run_problems": run_problems,
        "run_warnings": run_warnings,
        "per_episode": per_episode,
    }


def _evidence_path(recorded: Any, run_dir: Path) -> Path | None:
    """A path the driver recorded, relative to the run directory unless absolute."""
    if not recorded:
        return None
    path = Path(str(recorded))
    return path if path.is_absolute() else run_dir / path


def _validate_episode(episode: dict[str, Any], run_dir: Path, harness_name: str | None) -> dict[str, Any]:
    problems: list[str] = []
    warnings: list[str] = []
    harness_run = episode.get("harness_run") or {}
    ledger_path = _evidence_path(harness_run.get("ledger_path"), run_dir)
    events_path = _evidence_path(harness_run.get("events_path"), run_dir)
    replayed_score = None
    replayed_calls: int | None = None
    audit: dict[str, Any] | None = None
    if ledger_path is None or not ledger_path.is_file():
        problems.append(f"ledger missing at {ledger_path}")
    else:
        try:
            rebuilt = AgenticEpisode.from_ledger(ledger_path, reopen=False)
            if rebuilt.seed != episode.get("seed"):
                problems.append("ledger header seed does not match the episode's recorded seed")
            if not rebuilt.done:
                rebuilt.abandon()
            replayed_score = rebuilt.result()["final_score"]
            replayed_calls = sum(rebuilt.tool_counts.values())
        except Exception as exc:  # noqa: BLE001 - a broken ledger is a finding, not a crash
            problems.append(f"ledger does not replay: {exc!r}")
        if replayed_score is not None and replayed_score != episode.get("final_score"):
            problems.append(f"replayed score {replayed_score} != recorded {episode.get('final_score')}")
        try:
            audit = audit_ledger(ledger_path)
        except Exception as exc:  # noqa: BLE001 - same: report the unreadable ledger, keep validating
            problems.append(f"ledger does not audit: {exc!r}")
        if audit is not None:
            if not audit["auditable"]:
                problems.append("ledger is not auditable (no ids_exposed records)")
            elif audit["violations"]:
                problems.append(f"audit: {len(audit['violations'])} accepted move(s) on ids no tool reply exposed")
            elif audit["suspicious"]:
                warnings.append(f"audit: {len(audit['suspicious'])} rejected move(s) on unseen ids")
            if audit.get("guessed_reads"):
                warnings.append(f"audit: {len(audit['guessed_reads'])} successful read(s) on guessed ids")

    # Gate 2 of the spec, recomputed from the evidence: the replayed ledger's
    # tool-call count against the harness's own event stream. The recorded
    # agreement is then checked against both, so a stale or edited claim is
    # caught along with a truncated event file.
    agreement = harness_run.get("tool_call_agreement")
    if agreement is None:
        warnings.append("no tool-call agreement recorded")
    elif not agreement.get("agree"):
        problems.append(f"ledger/harness tool-call mismatch {agreement.get('ledger')}/{agreement.get('harness')}")
    harness_calls: int | None = None
    if events_path is None or not events_path.is_file():
        problems.append("harness event stream missing; tool-call agreement cannot be recomputed")
    elif harness_name not in EVENT_PARSERS:
        problems.append(f"cannot recompute tool-call agreement for harness {harness_name!r}")
    else:
        telemetry = EVENT_PARSERS[harness_name](events_path.read_text(encoding="utf-8").splitlines())
        harness_calls = harness_tool_calls(telemetry)
    if replayed_calls is not None and harness_calls is not None:
        if replayed_calls != harness_calls:
            problems.append(f"replayed ledger has {replayed_calls} tool calls, harness stream has {harness_calls}")
        elif agreement is not None and (
            agreement.get("ledger") != replayed_calls or agreement.get("harness") != harness_calls
        ):
            problems.append(
                f"recorded tool-call agreement {agreement.get('ledger')}/{agreement.get('harness')} "
                f"does not match the recomputed {replayed_calls}/{harness_calls}"
            )

    failed = int(episode.get("failed_decisions", 0))
    if failed:
        warnings.append(f"{failed} of {episode.get('decisions')} phases not closed by the agent")
    if harness_run.get("timed_out"):
        warnings.append("harness hit the episode timeout")
    if int(harness_run.get("guard_kills", 0) or 0):
        warnings.append(f"harness stopped {harness_run.get('guard_kills')} time(s) by the phase guard")
    if int(harness_run.get("exit_code", 0) or 0) != 0:
        warnings.append(f"harness exit code {harness_run.get('exit_code')}")
    if harness_run.get("server_drained") is False:
        warnings.append("a proxy connection was still open when the socket server stopped")
    usage = episode.get("usage") or {}
    if not (usage.get("harness") or {}).get("telemetry_reported", False):
        warnings.append("harness reported no token telemetry; usage is unmeasured")

    return {
        "seed": episode.get("seed"),
        "final_score": episode.get("final_score"),
        "replayed_score": replayed_score,
        "replayed_tool_calls": replayed_calls,
        "harness_tool_calls": harness_calls,
        "audit": None
        if audit is None
        else {k: v for k, v in audit.items() if k not in ("violations", "suspicious", "guessed_reads")},
        "problems": problems,
        "warnings": warnings,
    }
