"""Validate an agentic run directory before anyone quotes a number from it.

Every check here is mechanical and reads only what the run wrote:

- the run's contract block matches the contract this checkout computes, so
  a row cannot drift onto a different tool surface or brief unnoticed;
- every episode's ledger replays to the score the result claims, which is
  the determinism guarantee 2.0 inherits from 1.0;
- every ledger audits clean (no move on an id no tool reply exposed);
- the server ledger and the harness event stream agree on tool calls;
- failed decisions and missing telemetry are surfaced, never hidden.

Problems are reported, not fixed. ``ok`` is False if any problem is fatal;
warnings are listed separately and leave ``ok`` alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gm_bench.agentic.audit import audit_ledger
from gm_bench.agentic.contract import agentic_contract
from gm_bench.agentic.episode import AgenticEpisode

_CONTRACT_KEYS = ("base_contract_fingerprint", "agentic_fingerprint", "tool_surface", "brief", "scoring_version")


def validate_run(run_path: str | Path) -> dict[str, Any]:
    run_path = Path(run_path)
    if run_path.is_dir():
        run_path = run_path / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    warnings: list[str] = []

    current = agentic_contract()
    recorded = run.get("contract") or {}
    for key in _CONTRACT_KEYS:
        if recorded.get(key) != current.get(key):
            problems.append(f"contract.{key}: run has {recorded.get(key)!r}, checkout has {current.get(key)!r}")

    episodes = run.get("episodes") or []
    if not episodes:
        problems.append("run has no episodes")
    seeds = [episode.get("seed") for episode in episodes]
    if len(set(seeds)) != len(seeds):
        warnings.append("repeated seeds present; within-seed noise is measurable but the panel is not one-per-seed")

    per_episode = []
    for episode in episodes:
        report = _validate_episode(episode, run_path.parent)
        per_episode.append(report)
        problems.extend(f"seed {episode.get('seed')}: {item}" for item in report["problems"])
        warnings.extend(f"seed {episode.get('seed')}: {item}" for item in report["warnings"])

    return {
        "run": str(run_path),
        "agent": run.get("agent"),
        "harness": run.get("harness"),
        "episodes": len(episodes),
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "per_episode": per_episode,
    }


def _validate_episode(episode: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    problems: list[str] = []
    warnings: list[str] = []
    harness_run = episode.get("harness_run") or {}
    ledger_path = Path(harness_run.get("ledger_path") or "")
    if not ledger_path.is_absolute():
        ledger_path = run_dir / ledger_path
    replayed_score = None
    audit: dict[str, Any] | None = None
    if not ledger_path.is_file():
        problems.append(f"ledger missing at {ledger_path}")
    else:
        try:
            rebuilt = AgenticEpisode.from_ledger(ledger_path, reopen=False)
            if not rebuilt.done:
                rebuilt.abandon()
            replayed_score = rebuilt.result()["final_score"]
        except Exception as exc:  # noqa: BLE001 - a broken ledger is a finding, not a crash
            problems.append(f"ledger does not replay: {exc!r}")
        if replayed_score is not None and replayed_score != episode.get("final_score"):
            problems.append(f"replayed score {replayed_score} != recorded {episode.get('final_score')}")
        audit = audit_ledger(ledger_path)
        if not audit["auditable"]:
            problems.append("ledger is not auditable (no ids_exposed records)")
        elif audit["violations"]:
            problems.append(f"audit: {len(audit['violations'])} accepted move(s) on ids no tool reply exposed")
        elif audit["suspicious"]:
            warnings.append(f"audit: {len(audit['suspicious'])} rejected move(s) on unseen ids")

    agreement = harness_run.get("tool_call_agreement")
    if agreement is None:
        warnings.append("no tool-call agreement recorded")
    elif not agreement.get("agree"):
        problems.append(f"ledger/harness tool-call mismatch {agreement.get('ledger')}/{agreement.get('harness')}")

    failed = int(episode.get("failed_decisions", 0))
    if failed:
        warnings.append(f"{failed} of {episode.get('decisions')} phases not closed by the agent")
    if harness_run.get("timed_out"):
        warnings.append("harness hit the episode timeout")
    if int(harness_run.get("exit_code", 0) or 0) != 0:
        warnings.append(f"harness exit code {harness_run.get('exit_code')}")
    usage = episode.get("usage") or {}
    if not (usage.get("harness") or {}).get("telemetry_reported", False):
        warnings.append("harness reported no token telemetry; usage is unmeasured")

    return {
        "seed": episode.get("seed"),
        "final_score": episode.get("final_score"),
        "replayed_score": replayed_score,
        "audit": None if audit is None else {k: v for k, v in audit.items() if k not in ("violations", "suspicious")},
        "problems": problems,
        "warnings": warnings,
    }
