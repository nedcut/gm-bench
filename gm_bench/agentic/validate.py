"""Validate an agentic run directory before anyone quotes a number from it.

Every check here is mechanical and reads only what the run wrote:

- the run's contract block matches the contract this checkout computes, so
  a row cannot drift onto a different tool surface or brief unnoticed;
- the run's seed list matches the episodes, and every ledger's header seed
  matches the episode that claims it;
- every episode's ledger replays to the score the result claims, which is
  the determinism guarantee 2.0 inherits from 1.0;
- every ledger audits clean (no move on an id no tool reply exposed);
- the server ledger and the harness event stream agree on tool calls, per
  tool and in total, and that agreement is recomputed here from the retained
  ledger and event stream, never taken from the run's own claim;
- no episode was ended by the provider (``ended_by_provider``): a harness
  whose provider stayed down past the stall budget left phases that were
  never played, and a run with one is not publishable;
- failed decisions and missing telemetry are surfaced, never hidden.

Replay skips one kind of ledger entry the engine logs lossily: a call whose
arguments were not a JSON object is logged with ``arguments: {}`` and was
rejected live (``invalid arguments: arguments must be an object``), but
replaying ``{}`` could execute it (an ``end_phase`` would close the phase).
Such an entry is counted and not executed, as the engine does for a call it
refused (:func:`replayable_ledger`).

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
import tempfile
from pathlib import Path
from typing import Any

from gm_bench.agentic import claude, codex, cursor, opencode
from gm_bench.agentic.audit import audit_ledger
from gm_bench.agentic.contract import agentic_contract
from gm_bench.agentic.episode import AgenticEpisode
from gm_bench.agentic.opencode import harness_tool_calls

# The engine's reply to a call whose arguments were not a JSON object (``tools.validate_arguments``
# via ``episode._execute``); the ledger then records ``arguments: {}``.
NON_OBJECT_ARGUMENTS_MESSAGE = "invalid arguments: arguments must be an object"
REDACTED_SEED = "<redacted>"

_CONTRACT_KEYS = ("base_contract_fingerprint", "agentic_fingerprint", "tool_surface", "brief", "scoring_version")
# How to read each harness's retained event stream when recounting its GM-Bench tool calls.
EVENT_PARSERS = {
    opencode.HARNESS_NAME: opencode.parse_opencode_events,
    codex.HARNESS_NAME: codex.parse_codex_events,
    claude.HARNESS_NAME: claude.parse_claude_events,
    cursor.HARNESS_NAME: cursor.parse_cursor_events,
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

    if run.get("stopped_for_provider"):
        run_problems.append(
            f"the panel stopped after episode {run['stopped_for_provider'].get('after_episode')}: the provider "
            f"ended it ({run['stopped_for_provider'].get('reason')}); rerun the panel"
        )

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


def redact_seeds(report: dict[str, Any]) -> dict[str, Any]:
    """A copy of a :func:`validate_run` report with no seed in it (for printing a private-panel run).

    ``per_episode[].seed`` becomes :data:`REDACTED_SEED`, and the top-level
    ``problems`` and ``warnings`` are rebuilt from the per-episode lists with
    episodes named by index only.
    """
    redacted = dict(report)
    redacted["per_episode"] = [{**episode, "seed": REDACTED_SEED} for episode in report["per_episode"]]
    for key in ("problems", "warnings"):
        entries = list(report[f"run_{key}"])
        for index, episode in enumerate(report["per_episode"]):
            entries.extend(f"episode {index}: {item}" for item in episode[key])
        redacted[key] = entries
    return redacted


def provider_ended(episode: dict[str, Any]) -> dict[str, Any] | None:
    """Why the provider, not the agent, ended this episode; ``None`` when it did not.

    The driver records ``harness_run.ended_by_provider``. A run recorded before
    it did is read from what it left: its last invocation was a provider stall
    (the last relaunch's ``provider_stall``, or the first launch's when there
    was no relaunch) and phases were still open (``harness_exit``), with no
    quota stop or timeout to explain them.
    """
    harness_run = episode.get("harness_run") or {}
    if "ended_by_provider" in harness_run:
        return harness_run["ended_by_provider"] or None
    nudges = harness_run.get("nudges") or []
    last_stalled = (
        bool(nudges[-1].get("provider_stall")) if nudges else int(harness_run.get("provider_stalls") or 0) > 0
    )
    unplayed = int(((episode.get("agentic") or {}).get("phases_ended_by") or {}).get("harness_exit", 0) or 0)
    if not (last_stalled and unplayed) or harness_run.get("ended_by_quota") or harness_run.get("timed_out"):
        return None
    return {
        "reason": "inferred: the last invocation was a provider stall and phases were left open",
        "provider_stalls": harness_run.get("provider_stalls"),
        "provider_stall_wait_seconds": harness_run.get("provider_stall_wait_seconds"),
    }


def replayable_ledger(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """The ledger with non-object-argument calls marked not executed, and how many were.

    Only an exact match is touched: an executed ``tool_call`` that failed with
    :data:`NON_OBJECT_ARGUMENTS_MESSAGE` and was logged with empty arguments.
    It never reached the simulator, so not replaying it is what happened live.
    """
    marked = 0
    out = []
    for record in records:
        if (
            record.get("event") == "tool_call"
            and record.get("executed", True)
            and not record.get("ok")
            and record.get("arguments") == {}
            and record.get("message") == NON_OBJECT_ARGUMENTS_MESSAGE
        ):
            record = {**record, "executed": False}
            marked += 1
        out.append(record)
    return out, marked


def _replay(ledger_path: Path) -> tuple[AgenticEpisode, int]:
    """Replay a ledger through :func:`replayable_ledger` (read-only: the ledger itself is never written)."""
    records = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records, marked = replayable_ledger(records)
    if not marked:
        return AgenticEpisode.from_ledger(ledger_path, reopen=False), 0
    with tempfile.TemporaryDirectory(prefix="gmb-replay-") as directory:
        copy = Path(directory) / "ledger.jsonl"
        copy.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records), encoding="utf-8")
        return AgenticEpisode.from_ledger(copy, reopen=False), marked


# A phase is empty when the agent neither looked at anything beyond the status nor acted in it.
EMPTY_PHASE_TOOLS = frozenset({"get_status", "end_phase"})
EMPTY_PHASE_DEFINITION = (
    "a closed phase whose every ledger tool call (if any) was get_status or end_phase: "
    "the agent read nothing beyond the status and made no move"
)


def empty_phases(ledger_path: str | Path) -> int:
    """How many of the ledger's closed phases were empty (:data:`EMPTY_PHASE_DEFINITION`).

    Calls are attributed to the ``season`` and ``phase`` the ledger recorded
    for them; a phase is one ``phase_end`` record, however it ended.
    """
    calls: dict[tuple[Any, Any], set[str]] = {}
    closed: list[tuple[Any, Any]] = []
    for line in Path(ledger_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        key = (record.get("season"), record.get("phase"))
        if record.get("event") == "tool_call":
            calls.setdefault(key, set()).add(str(record.get("tool")))
        elif record.get("event") == "phase_end":
            closed.append(key)
    return sum(1 for key in closed if calls.get(key, set()) <= EMPTY_PHASE_TOOLS)


def _harness_calls_by_tool(telemetry: dict[str, Any]) -> dict[str, int]:
    """The harness's GM-Bench tool calls per tool, named as the ledger names them (``gm-bench_draft`` -> ``draft``)."""
    prefix = "gm-bench_"
    return {
        name[len(prefix) :]: int(count)
        for name, count in (telemetry.get("harness_tool_events") or {}).items()
        if name.startswith(prefix) and count
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
    replayed_by_tool: dict[str, int] | None = None
    empty: int | None = None
    audit: dict[str, Any] | None = None
    if ledger_path is None or not ledger_path.is_file():
        problems.append(f"ledger missing at {ledger_path}")
    else:
        try:
            rebuilt, skipped = _replay(ledger_path)
            if skipped:
                warnings.append(
                    f"{skipped} ledger call(s) with non-object arguments were rejected live and are not replayed"
                )
            if rebuilt.seed != episode.get("seed"):
                problems.append("ledger header seed does not match the episode's recorded seed")
            if not rebuilt.done:
                rebuilt.abandon()
            replayed_score = rebuilt.result()["final_score"]
            replayed_calls = sum(rebuilt.tool_counts.values())
            replayed_by_tool = {tool: int(count) for tool, count in rebuilt.tool_counts.items() if count}
        except Exception as exc:  # noqa: BLE001 - a broken ledger is a finding, not a crash
            problems.append(f"ledger does not replay: {exc!r}")
        if replayed_score is not None and replayed_score != episode.get("final_score"):
            problems.append(f"replayed score {replayed_score} != recorded {episode.get('final_score')}")
        try:
            empty = empty_phases(ledger_path)
        except (OSError, ValueError) as exc:
            problems.append(f"ledger phases cannot be read: {exc!r}")
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
            if audit.get("guessed_draft_picks"):
                warnings.append(
                    f"audit: {len(audit['guessed_draft_picks'])} draft pick(s) on guessed prospect ids "
                    "(blind picks: prospect ids carry no hidden information)"
                )

    # Gate 2 of the spec, recomputed from the evidence: the replayed ledger's
    # tool-call count against the harness's own event stream. The recorded
    # agreement is then checked against both, so a stale or edited claim is
    # caught along with a truncated event file. The recount is what decides:
    # a recorded mismatch that the recount resolves (the driver's event parser
    # has since been fixed) is a warning, and redaction publishes the recount.
    # A recorded agreement the recount contradicts stays a problem.
    agreement = harness_run.get("tool_call_agreement")
    harness_calls: int | None = None
    harness_by_tool: dict[str, int] | None = None
    if events_path is None or not events_path.is_file():
        problems.append("harness event stream missing; tool-call agreement cannot be recomputed")
    elif harness_name not in EVENT_PARSERS:
        problems.append(f"cannot recompute tool-call agreement for harness {harness_name!r}")
    else:
        telemetry = EVENT_PARSERS[harness_name](events_path.read_text(encoding="utf-8").splitlines())
        harness_calls = harness_tool_calls(telemetry)
        harness_by_tool = _harness_calls_by_tool(telemetry)
    # Per tool, not only in total: two offsetting differences must not pass.
    per_tool_agrees = replayed_by_tool is not None and replayed_by_tool == harness_by_tool
    recounted = replayed_calls is not None and replayed_calls == harness_calls and per_tool_agrees
    recorded = f"{agreement.get('ledger')}/{agreement.get('harness')}" if agreement is not None else None
    if agreement is None:
        warnings.append("no tool-call agreement recorded")
    elif not agreement.get("agree"):
        if recounted:
            warnings.append(
                f"recorded ledger/harness tool-call mismatch {recorded} superseded by the recount "
                f"{replayed_calls}/{harness_calls}"
            )
        else:
            problems.append(f"ledger/harness tool-call mismatch {recorded}")
    if replayed_calls is not None and harness_calls is not None:
        if replayed_calls != harness_calls:
            problems.append(f"replayed ledger has {replayed_calls} tool calls, harness stream has {harness_calls}")
        elif not per_tool_agrees:
            differing = sorted(
                tool
                for tool in set(replayed_by_tool or {}) | set(harness_by_tool or {})
                if (replayed_by_tool or {}).get(tool, 0) != (harness_by_tool or {}).get(tool, 0)
            )
            problems.append(
                f"replayed ledger and harness stream both have {replayed_calls} tool calls but disagree per tool "
                f"({', '.join(differing)})"
            )
        elif (
            agreement is not None
            and agreement.get("agree")
            and (agreement.get("ledger") != replayed_calls or agreement.get("harness") != harness_calls)
        ):
            problems.append(
                f"recorded tool-call agreement {recorded} does not match the recomputed {replayed_calls}/{harness_calls}"
            )

    ended = provider_ended(episode)
    if ended is not None:
        unplayed = ((episode.get("agentic") or {}).get("phases_ended_by") or {}).get("harness_exit", 0)
        problems.append(
            f"ended by the provider ({ended.get('reason')}) with {unplayed} phase(s) never played; "
            "the score is not the model's, so the run cannot be published: rerun it"
        )

    failed = int(episode.get("failed_decisions", 0))
    if failed:
        warnings.append(f"{failed} of {episode.get('decisions')} phases not closed by the agent")
    if harness_run.get("timed_out"):
        warnings.append("harness hit the episode timeout")
    if int(harness_run.get("guard_kills", 0) or 0):
        warnings.append(f"harness stopped {harness_run.get('guard_kills')} time(s) by the phase guard")
    # How the harness finished: the last invocation's exit code. Runs recorded
    # before ``final_exit_code`` only have the first launch's, and are read as
    # they always were.
    final_exit = harness_run.get("final_exit_code", harness_run.get("exit_code"))
    if int(final_exit or 0) != 0:
        warnings.append(f"harness exit code {final_exit}")
    if harness_run.get("server_drained") is False:
        warnings.append("a proxy connection was still open when the socket server stopped")
    problems.extend(cursor.prompt_audit_problems(harness_name, harness_run))
    usage = episode.get("usage") or {}
    if not (usage.get("harness") or {}).get("telemetry_reported", False):
        warnings.append("harness reported no token telemetry; usage is unmeasured")

    return {
        "seed": episode.get("seed"),
        "final_score": episode.get("final_score"),
        "replayed_score": replayed_score,
        "replayed_tool_calls": replayed_calls,
        "harness_tool_calls": harness_calls,
        "tool_calls_recounted": recounted,
        # Phases where the agent only read the status and ended the phase (EMPTY_PHASE_DEFINITION).
        "empty_phases": empty,
        "audit": None
        if audit is None
        else {
            k: v
            for k, v in audit.items()
            if k not in ("violations", "suspicious", "guessed_reads", "guessed_draft_picks")
        },
        "problems": problems,
        "warnings": warnings,
    }
