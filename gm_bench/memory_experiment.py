"""Preregister and run a separate, public-seed-only paired journal experiment.

Run ``python -m gm_bench.memory_experiment --help``. No frozen entrypoint imports
this module. The experimental wrapper, limits and observations are not GM-Bench 2.0.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Callable

from gm_bench.agentic.brief import task_brief
from gm_bench.agentic.contract import agentic_contract
from gm_bench.agentic.episode import AgenticEpisode
from gm_bench.agentic.tools import TOOLS
from gm_bench.memory_experiment_provider import openai_chat, scripted

VERSION = "gm-bench-memory-experiment-v1"
CONDITIONS = ["no_persistent_journal", "structured_decision_journal"]
SOURCES = ["memory_experiment.py", "memory_experiment_provider.py"]
ANALYSIS = {
    "primary": "final_score",
    "direction": "structured_decision_journal minus no_persistent_journal",
    "pair": "public simulator seed x repeat index; fresh episode and provider request state per condition",
    "repeats": "average paired differences within seed first; seeds are the analysis units",
    "uncertainty": "descriptive seed-level standard error; null for fewer than two seeds; no significance test",
    "failures": "retain all completed runner records including failures; abandon remaining phases and score them",
    "missing": "no complete-panel estimate unless every preregistered cell exists exactly once",
    "retry": "none; interrupted panels are incomplete; rerun the whole panel in a new directory, retain both",
    "secondary": ["completed", "illegal_actions", "tool_calls", "rejected_tool_calls", "model_calls"],
}
CONTROLS = {
    "max_calls_per_phase": 12,
    "max_request_chars": 120000,
    "max_journal_chars": 4000,
    "max_output_tokens": 2048,
    "socket_timeout_seconds": 60,
}
PROTOCOL = {
    "context": "reset history at every phase; journal generated in both arms, retained across phases only in treatment",
    "tools": "frozen 2.0 tool semantics except write_memo unavailable in BOTH conditions",
    "observations": "only current phase coordinates, current-phase call/reply history, journal, tool schemas and brief",
    "clock": "engine phase guard disabled in BOTH arms; bounded calls and socket inactivity timeout, not wall deadline",
    "request_budget": "max_request_chars bounds canonical JSON request characters, not wire bytes or tokens",
    "overflow": "stop entire episode on budget, malformed response, provider or identity error; no truncation or retries",
    "order": "alternate condition order by seed index plus repeat index; serial execution",
    "sampling": "temperature 0; sampling seed unsupported by this adapter, not sent; provider nondeterminism remains",
    "seed_visibility": "public demonstration seeds only; numeric simulator seed never included in model request",
}
LIMITATIONS = [
    "Offline scripted fixtures test machinery, not whether memory improves LLM performance.",
    "Historical facts remain retrievable through tools: this may measure retrieval efficiency, not memory dependence.",
    "Both arms plan and write journals; only cross-phase retention differs. This does not isolate planning benefit.",
    "Journal input tokens and resulting actions can differ; equal resource ceilings do not mean equal realized compute.",
    "Public seeds, fixed order counterbalancing, one model/harness and small panels limit generalization.",
    "A model snapshot ID is not deterministic inference; backend fingerprints and sampling support are recorded.",
    "Existing four 2.0 rows are unpinned exploratory evidence; no causal 1.0 versus 2.0 comparison is supported.",
]


def encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def source_digest() -> str:
    return digest({name: (Path(__file__).parent / name).read_text() for name in SOURCES})


def provenance() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    try:
        top = (
            subprocess.check_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
        if Path(top).resolve() != root:
            raise ValueError("installed package is not the checkout root")
        head = (
            subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
        dirty = bool(subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"]).strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        head, dirty = None, None
    return {
        "git_head": head,
        "working_tree_dirty": dirty,
        "source_sha256": source_digest(),
        "python": platform.python_version(),
    }


def write_json(path: Path, value: Any) -> None:
    # Exclusive creation protects preregistration and prevents accidental selective reruns.
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, indent=2, sort_keys=True, allow_nan=False)
        file.write("\n")


def register(
    seeds: list[int],
    repeats: int = 2,
    seasons: int = 1,
    *,
    provider: str = "scripted",
    model: str = "scripted-rules-v1",
    pin: str = "pinned",
    controls: dict[str, int] | None = None,
    pricing: dict[str, float] | None = None,
) -> dict[str, Any]:
    manifest = {
        "version": VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seed_scope": "public",
        "seeds": seeds,
        "repeats": repeats,
        "seasons": seasons,
        "conditions": CONDITIONS,
        "protocol": PROTOCOL,
        "analysis": ANALYSIS,
        "controls": CONTROLS | (controls or {}),
        "model": {
            "provider": provider,
            "requested": model,
            "pin_status": pin,
            "expected_response_model": model if pin == "pinned" else None,
            "sampling_seed": "unsupported",
            "harness": "stateless-json-one-tool-v1",
        },
        "pricing_usd_per_million": pricing,
        "base_contract": agentic_contract(),
        "provenance": provenance(),
    }
    manifest["manifest_sha256"] = digest(manifest)
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> None:
    unsigned = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if manifest.get("manifest_sha256") != digest(unsigned):
        raise ValueError("manifest hash mismatch")
    for key, expected in (
        ("version", VERSION),
        ("seed_scope", "public"),
        ("conditions", CONDITIONS),
        ("protocol", PROTOCOL),
        ("analysis", ANALYSIS),
        ("base_contract", agentic_contract()),
    ):
        if manifest.get(key) != expected:
            raise ValueError(f"unsupported or changed {key}")
    if manifest["provenance"]["source_sha256"] != source_digest():
        raise ValueError("experimental source changed since preregistration; register a new panel")
    seeds = manifest["seeds"]
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(type(s) is not int or s < 0 for s in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("seeds must be unique nonnegative public integers")
    for name in ("repeats", "seasons"):
        if type(manifest[name]) is not int or manifest[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    controls = manifest["controls"]
    if set(controls) != set(CONTROLS) or any(type(v) is not int or v < 1 for v in controls.values()):
        raise ValueError("controls must contain exactly the positive integer limits")
    model = manifest["model"]
    if model["provider"] not in ("scripted", "openai-chat") or model["pin_status"] not in (
        "pinned",
        "unpinned",
        "unsupported",
    ):
        raise ValueError("unsupported provider or pin status")
    if not isinstance(model["requested"], str) or not model["requested"].strip():
        raise ValueError("model ID is required")
    if model["sampling_seed"] != "unsupported" or model["harness"] != "stateless-json-one-tool-v1":
        raise ValueError("unsupported sampling or harness configuration")
    if model["provider"] == "scripted" and (
        model["requested"] != "scripted-rules-v1" or model["pin_status"] != "pinned"
    ):
        raise ValueError("scripted fixture identity must be pinned to scripted-rules-v1")
    if model["pin_status"] == "pinned":
        if model["expected_response_model"] != model["requested"]:
            raise ValueError("pin must match requested model")
        if model["provider"] == "openai-chat" and not re.search(r"-\d{4}-\d{2}-\d{2}$", model["requested"]):
            raise ValueError("pinned OpenAI runs require a dated snapshot ID, not an alias")
    elif model["expected_response_model"] is not None:
        raise ValueError("unpinned/unsupported models cannot assert a response pin")
    pricing = manifest["pricing_usd_per_million"]
    if pricing is not None and (
        set(pricing) != {"input", "output"}
        or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in pricing.values())
    ):
        raise ValueError("pricing must contain finite nonnegative input/output rates or be null")


def cells(manifest: dict[str, Any]):
    for index, seed in enumerate(manifest["seeds"]):
        for repeat in range(manifest["repeats"]):
            order = CONDITIONS if (index + repeat) % 2 == 0 else list(reversed(CONDITIONS))
            for condition in order:
                yield seed, repeat, condition


def empty_journal() -> dict[str, list[str]]:
    return {"facts": [], "plan": [], "decisions": []}


def reject_constant(value: str) -> None:
    raise ValueError(f"nonstandard JSON constant: {value}")


def parse_action(content: str, limit: int) -> dict[str, Any]:
    action = json.loads(content, parse_constant=reject_constant)
    # Also reject overflowed numbers (e.g. 1e999), before executing any tool.
    encoded(action)
    if not isinstance(action, dict) or set(action) != {"tool", "arguments", "journal"}:
        raise ValueError("response must contain exactly tool, arguments, journal")
    journal = action["journal"]
    if (
        not isinstance(journal, dict)
        or set(journal) != set(empty_journal())
        or any(not isinstance(v, list) or any(not isinstance(s, str) for s in v) for v in journal.values())
        or len(encoded(journal)) > limit
    ):
        raise ValueError("invalid or oversized structured journal")
    if not isinstance(action["tool"], str) or not isinstance(action["arguments"], dict):
        raise ValueError("tool must be a string and arguments an object")
    return action


def measurement(value: float | int | None, status: str, basis: str) -> dict[str, Any]:
    return {"value": value, "status": status, "basis": basis}


def usage_totals(events: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    totals = {}
    for key in ("prompt_tokens", "completion_tokens"):
        values = [(event.get("usage") or {}).get(key) for event in events]
        known = all(type(v) is int and v >= 0 for v in values)
        totals[key] = measurement(
            sum(values) if known else None,
            "measured" if known else "unavailable",
            "provider reported; scripted calls use zero tokens; null if any call lacks usage",
        )
    pricing = manifest["pricing_usd_per_million"]
    if manifest["model"]["provider"] == "scripted":
        cost = measurement(0, "measured", "offline fixture; no provider calls")
    elif pricing and all(t["value"] is not None for t in totals.values()):
        cost = measurement(
            (
                totals["prompt_tokens"]["value"] * pricing["input"]
                + totals["completion_tokens"]["value"] * pricing["output"]
            )
            / 1e6,
            "estimated",
            "preregistered rates times reported tokens; ignores cache discounts and billing adjustments",
        )
    else:
        cost = measurement(None, "unavailable", "missing pricing or usage; never substitute zero")
    return {
        **totals,
        "cost_usd": cost,
        "billed_cost_usd": measurement(None, "unavailable", "billing not queried"),
        "provider_latency_seconds": measurement(
            sum(e["latency_seconds"] for e in events), "measured", "client wall clock"
        ),
    }


def play(
    manifest: dict[str, Any], seed: int, repeat: int, condition: str, directory: Path, provider: Callable = scripted
) -> dict[str, Any]:
    controls, model = manifest["controls"], manifest["model"]
    episode = AgenticEpisode(seed, manifest["seasons"], ledger_path=directory / "ledger.jsonl", phase_guard_seconds=0)
    journal, history, events = empty_journal(), [], []
    phase_calls, rejected = 0, 0
    termination = "completed"
    tools = [tool for tool in TOOLS if tool["name"] != "write_memo"]
    instruction = task_brief(manifest["seasons"], episode.league.user_team.name, 0) + (
        "\nEXPERIMENTAL HARNESS OVERRIDES: No file access or write_memo. Only the supplied tools exist. "
        "Conversation history resets each phase. A structured journal is supplied; do not assume its retention. "
        "Reply with only JSON containing tool (one tool name), arguments (object), journal (object with exactly "
        "facts, plan, decisions, each an array of strings). Update the journal based only on observations; "
        "it is scratch planning, not an additional tool call. Never include hidden guesses as facts. "
        f"Limits: {encoded(controls)}. End each phase within the call limit."
    )
    started = time.monotonic()
    try:
        with (directory / "trace.jsonl").open("x", encoding="utf-8") as trace:
            while not episode.done:
                phase = (episode.season, episode.phase)
                request = {
                    "instructions": instruction,
                    "tools": tools,
                    "season": episode.season,
                    "phase": episode.phase,
                    "history": history,
                    "journal": journal,
                }
                if phase_calls >= controls["max_calls_per_phase"]:
                    termination = "call_budget"
                    break
                if len(encoded(request)) > controls["max_request_chars"]:
                    termination = "prompt_budget"
                    break
                event = {"season": phase[0], "phase": phase[1], "request": copy.deepcopy(request)}
                began = time.monotonic()
                phase_calls += 1
                try:
                    response = provider(copy.deepcopy(request), model, controls)
                    event.update(response)
                except Exception as error:
                    # Do not serialize exception text: provider errors may echo credentials or headers.
                    event["error_type"] = type(error).__name__
                    termination = "provider_error"
                event["latency_seconds"] = time.monotonic() - began
                events.append(event)
                if termination == "completed":
                    if model["pin_status"] == "pinned" and event.get("model") != model["expected_response_model"]:
                        termination = "identity_mismatch"
                    else:
                        try:
                            action = parse_action(event["content"], controls["max_journal_chars"])
                        except (ValueError, TypeError, KeyError):
                            termination = "malformed_response"
                        else:
                            journal = action["journal"]
                            if action["tool"] == "write_memo":
                                result = {
                                    "ok": False,
                                    "message": "write_memo is unavailable in both experimental conditions",
                                }
                            else:
                                result = episode.call_tool(action["tool"], action["arguments"])
                                if action["tool"] == "get_status" and result.get("ok"):
                                    # Keep the advertised tool set consistent with the wrapper's allowed tools.
                                    result["data"]["legal_tools"] = [
                                        name for name in result["data"]["legal_tools"] if name != "write_memo"
                                    ]
                            rejected += not result.get("ok", False)
                            event["action"], event["result"] = action, result
                            history.append({"action": action, "result": result})
                            if (episode.season, episode.phase) != phase:
                                history, phase_calls = [], 0
                                if condition == CONDITIONS[0]:
                                    journal = empty_journal()
                event["termination"] = None if termination == "completed" else termination
                trace.write(encoded(event) + "\n")
                trace.flush()
                if termination != "completed":
                    break
        if not episode.done:
            episode.abandon()
        result = episode.result("experimental-" + condition)
    finally:
        episode.close()
    metrics = {
        key: result[key]
        for key in ("final_score", "strategy_score", "protocol_penalty", "illegal_actions", "failed_decisions")
    }
    metrics.update(
        completed=int(termination == "completed"),
        tool_calls=sum("action" in event for event in events),
        rejected_tool_calls=rejected,
        model_calls=len(events),
    )
    return {
        "manifest_sha256": manifest["manifest_sha256"],
        "seed": seed,
        "repeat": repeat,
        "condition": condition,
        "termination": termination,
        "metrics": metrics,
        "tool_calls_by_tool": dict(Counter(e["action"]["tool"] for e in events if "action" in e)),
        "phases_ended_by": result["agentic"]["phases_ended_by"],
        "usage": usage_totals(events, manifest),
        "elapsed_seconds": measurement(
            time.monotonic() - started, "measured", "episode client wall clock including finalization"
        ),
        "observed_models": sorted({str(e.get("model")) for e in events}),
        "backend_fingerprints": sorted({str(e.get("system_fingerprint")) for e in events}),
        "identity_verified": model["pin_status"] == "pinned"
        and bool(events)
        and all(e.get("model") == model["expected_response_model"] for e in events),
    }


def analyze(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = set(cells(manifest))
    indexed = {}
    for row in rows:
        key = (row["seed"], row["repeat"], row["condition"])
        if key in indexed or key not in expected or row["manifest_sha256"] != manifest["manifest_sha256"]:
            raise ValueError("duplicate, unexpected or mismatched cell")
        indexed[key] = row
    missing = sorted(expected - indexed.keys())
    report = {
        "version": VERSION,
        "manifest_sha256": manifest["manifest_sha256"],
        "analysis": ANALYSIS,
        "limitations": LIMITATIONS,
        "complete_panel": not missing,
        "missing_cells": missing,
        "cells_recorded": len(rows),
        "cells_expected": len(expected),
        "all_episodes_completed": not missing and all(row["metrics"]["completed"] for row in rows),
        "all_identities_verified": not missing and all(row["identity_verified"] for row in rows),
        "evidence": "offline fixture" if manifest["model"]["provider"] == "scripted" else "experimental model run",
        "model": manifest["model"],
        "paired_metrics": {},
        "pairs": [],
    }
    for seed in manifest["seeds"]:
        for repeat in range(manifest["repeats"]):
            pair = [indexed.get((seed, repeat, condition)) for condition in CONDITIONS]
            if all(pair):
                report["pairs"].append(
                    {
                        "seed": seed,
                        "repeat": repeat,
                        "deltas": {
                            metric: pair[1]["metrics"][metric] - pair[0]["metrics"][metric]
                            for metric in [ANALYSIS["primary"], *ANALYSIS["secondary"]]
                        },
                    }
                )
    if not missing:
        for metric in [ANALYSIS["primary"], *ANALYSIS["secondary"]]:
            deltas = [
                mean(p["deltas"][metric] for p in report["pairs"] if p["seed"] == seed) for seed in manifest["seeds"]
            ]
            report["paired_metrics"][metric] = {
                "mean_difference": mean(deltas),
                "seed_standard_error": stdev(deltas) / math.sqrt(len(deltas)) if len(deltas) > 1 else None,
                "seed_count": len(deltas),
                "pair_count": len(report["pairs"]),
                "seed_mean_differences": deltas,
            }
    return report


def markdown_report(report: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Experimental decision journal report",
        "",
        f"Evidence: **{report['evidence']}**. Separate from frozen 1.0/2.0 panels.",
        "",
        f"Manifest SHA-256: `{report['manifest_sha256']}`.",
        "",
        f"Model: `{report['model']['requested']}`; pin status: **{report['model']['pin_status']}**; "
        f"sampling seed: {report['model']['sampling_seed']}.",
        f"Source unchanged during run: {report.get('source_unchanged', 'unavailable')}.",
        "",
        f"Cells: {report['cells_recorded']}/{report['cells_expected']}; complete panel: {report['complete_panel']}; "
        f"all episodes completed: {report['all_episodes_completed']}; all identity pins verified: {report['all_identities_verified']}.",
        "",
        "Differences are journal minus no persistent journal, averaged within seed over repeats first. "
        "Standard errors are descriptive; no hypothesis test or memory-benefit claim.",
        "",
        "| Metric | Mean paired difference | Seed SE | Seeds | Pairs |",
        "|---|---:|---:|---:|---:|",
    ]
    for metric, result in report["paired_metrics"].items():
        se = result["seed_standard_error"]
        lines.append(
            f"| {metric} | {result['mean_difference']:.6g} | {se if se is not None else 'unavailable'} | "
            f"{result['seed_count']} | {result['pair_count']} |"
        )
    if not report["complete_panel"]:
        lines.extend(["", "Incomplete panel: pooled estimates withheld. Missing cells are listed in analysis.json."])
    lines.extend(
        [
            "",
            "| Seed/repeat | Condition | Completion | Illegal | Score | Tools | Input/output tokens | Provider seconds | USD |",
            "|---|---|---|---:|---:|---:|---|---|---|",
        ]
    )
    for row in rows:
        m, u = row["metrics"], row["usage"]

        def show(item):
            value = item["value"]
            return f"{value:.6g} ({item['status']})" if value is not None else "unavailable"

        lines.append(
            f"| {row['seed']}/{row['repeat']} | {row['condition']} | {row['termination']} | {m['illegal_actions']} | "
            f"{m['final_score']} | {m['tool_calls']} | {show(u['prompt_tokens'])} / {show(u['completion_tokens'])} | "
            f"{show(u['provider_latency_seconds'])} | {show(u['cost_usd'])} |"
        )
    lines.extend(
        [
            "",
            "Billed cost is unavailable. Provider time is measured locally; token counts are provider-reported "
            "(zero for fixtures). Missing usage is unavailable, never zero-filled. See each cell.json for bases, "
            "rejections, termination, model identity and tool counts.",
            "",
            *[f"- {text}" for text in LIMITATIONS],
            "",
        ]
    )
    return "\n".join(lines)


def run(
    manifest_path: Path, output: Path, *, allow_paid: bool = False, provider: Callable | None = None
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    validate_manifest(manifest)
    if manifest["model"]["provider"] != "scripted" and not allow_paid:
        raise ValueError("real provider disabled; a separately authorized run requires --allow-paid")
    if provider is None:
        provider = scripted if manifest["model"]["provider"] == "scripted" else openai_chat
        if provider == openai_chat and not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is absent")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "manifest.json", manifest)  # written before the first outcome
    before = provenance()
    write_json(output / "run-start.json", before)
    rows = []
    for index, (seed, repeat, condition) in enumerate(cells(manifest)):
        directory = output / f"cell-{index:04d}"
        directory.mkdir()
        row = play(manifest, seed, repeat, condition, directory, provider)
        rows.append(row)
        write_json(directory / "cell.json", row)
    after = provenance()
    artifact_hashes = {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.glob("cell-*/*"))
        if path.is_file()
    }
    write_json(
        output / "run-end.json", {**after, "changed_during_run": before != after, "artifact_sha256": artifact_hashes}
    )
    return report_directory(output)


def report_directory(output: Path) -> dict[str, Any]:
    manifest = json.loads((output / "manifest.json").read_text())
    validate_manifest(manifest)
    rows = [json.loads(path.read_text()) for path in sorted(output.glob("cell-*/cell.json"))]
    report = analyze(manifest, rows)
    end = output / "run-end.json"
    report["source_unchanged"] = end.exists() and not json.loads(end.read_text())["changed_during_run"]
    if end.exists():
        recorded = json.loads(end.read_text())["artifact_sha256"]
        actual = {
            str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.glob("cell-*/*"))
            if path.is_file()
        }
        if recorded != actual:
            raise ValueError("cell evidence differs from run-end hashes")
    # Derived reports may be regenerated; manifests, traces and outcomes are exclusive writes.
    (output / "analysis.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (output / "report.md").write_text(markdown_report(report, rows))
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("register", help="freeze conditions and analysis before any outcomes")
    pre.add_argument("--out", type=Path, required=True)
    pre.add_argument("--public-seeds", type=int, nargs="+", required=True)
    pre.add_argument("--repeats", type=int, default=2)
    pre.add_argument("--seasons", type=int, default=1)
    pre.add_argument("--provider", choices=["scripted", "openai-chat"], default="scripted")
    pre.add_argument("--model", default="scripted-rules-v1")
    pre.add_argument("--pin-status", choices=["pinned", "unpinned", "unsupported"], default="pinned")
    for key, default in CONTROLS.items():
        pre.add_argument("--" + key.replace("_", "-"), type=int, default=default)
    pre.add_argument("--input-usd-per-million", type=float)
    pre.add_argument("--output-usd-per-million", type=float)
    execute = commands.add_parser("run", help="execute each preregistered cell once, serially")
    execute.add_argument("manifest", type=Path)
    execute.add_argument("--out", type=Path, required=True)
    execute.add_argument("--allow-paid", action="store_true")
    report = commands.add_parser("report", help="regenerate analysis, including interrupted panels")
    report.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "register":
            rates = [args.input_usd_per_million, args.output_usd_per_million]
            if (rates[0] is None) != (rates[1] is None):
                raise ValueError("provide both pricing rates or neither")
            manifest = register(
                args.public_seeds,
                args.repeats,
                args.seasons,
                provider=args.provider,
                model=args.model,
                pin=args.pin_status,
                controls={key: getattr(args, key) for key in CONTROLS},
                pricing=None if rates[0] is None else dict(zip(("input", "output"), rates)),
            )
            write_json(args.out, manifest)
            print(manifest["manifest_sha256"])
        elif args.command == "run":
            run(args.manifest, args.out, allow_paid=args.allow_paid)
            print(args.out / "report.md")
        else:
            report_directory(args.directory)
            print(args.directory / "report.md")
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"experiment error: {error}\n")


if __name__ == "__main__":
    main()
