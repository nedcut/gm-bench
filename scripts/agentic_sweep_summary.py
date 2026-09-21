#!/usr/bin/env python3
"""Tabulate several agentic run directories side by side.

Diagnostic only, not part of the contract. Point it at one or more run
directories written by ``gm-bench agentic`` (each holding a ``run.json``) and
it prints one row per run: score, reliability, tool usage, tokens, cost, and
the ledger audit verdict. Use it to compare free models on a smoke seed
before deciding which are worth a full panel.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# isort: split
from gm_bench.agentic.audit import audit_ledger

COLUMNS = (
    "model",
    "seeds",
    "score",
    "illegal",
    "failed",
    "ended_by",
    "calls/ep",
    "moves ok/rej",
    "model calls",
    "tokens in/out",
    "cost",
    "wall s",
    "agree",
    "audit",
)


def summarize(run_dir: Path) -> dict[str, str] | None:
    run_file = run_dir / "run.json"
    if not run_file.is_file():
        return None
    run = json.loads(run_file.read_text(encoding="utf-8"))
    episodes = run.get("episodes", [])
    summary = run.get("summary", {})
    usage = summary.get("usage", {})
    agentic = run.get("agentic_summary", {})
    audits = []
    agreements = []
    moves_ok = moves_rej = 0
    for episode in episodes:
        ledger = Path(episode.get("harness_run", {}).get("ledger_path", ""))
        if not ledger.is_absolute():
            ledger = run_dir / ledger
        if ledger.is_file():
            report = audit_ledger(ledger)
            audits.append(
                "clean"
                if report["clean"]
                else ("n/a" if not report["auditable"] else f"{len(report['violations'])} viol")
            )
        agreement = episode.get("harness_run", {}).get("tool_call_agreement")
        if agreement:
            agreements.append("yes" if agreement["agree"] else f"{agreement['ledger']}/{agreement['harness']}")
        moves_ok += episode.get("agentic", {}).get("moves_accepted", 0)
        moves_rej += episode.get("agentic", {}).get("moves_rejected", 0)
    cost = usage.get("cost_usd")
    return {
        "model": str(run.get("harness", {}).get("model", run.get("agent", run_dir.name))),
        "seeds": str(len(run.get("seeds", []))),
        "score": f"{summary.get('mean_score', 0):.1f}",
        "illegal": str(summary.get("illegal_actions", 0)),
        "failed": f"{summary.get('failed_decisions', 0)}/{summary.get('decisions', 0)}",
        "ended_by": ",".join(f"{k}={v}" for k, v in sorted(agentic.get("phases_ended_by", {}).items())),
        "calls/ep": str(agentic.get("mean_tool_calls_per_episode", "")),
        "moves ok/rej": f"{moves_ok}/{moves_rej}",
        "model calls": str(usage.get("api_calls", "")),
        "tokens in/out": f"{usage.get('input_tokens', 0) / 1000:.0f}k/{usage.get('output_tokens', 0) / 1000:.0f}k",
        "cost": "n/a" if cost is None else f"${cost:.4f}",
        "wall s": str(agentic.get("mean_wall_seconds", "")),
        "agree": ",".join(agreements) or "n/a",
        "audit": ",".join(audits) or "n/a",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", nargs="+", type=Path, help="run directories, or a parent holding several")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = []
    for path in args.run_dirs:
        candidates = [path] if (path / "run.json").is_file() else sorted(p for p in path.iterdir() if p.is_dir())
        for candidate in candidates:
            row = summarize(candidate)
            if row:
                rows.append(row)
    if not rows:
        print("no runs found (no run.json under " + ", ".join(str(p) for p in args.run_dirs) + ")", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    widths = {column: max(len(column), *(len(row[column]) for row in rows)) for column in COLUMNS}
    print("  ".join(column.ljust(widths[column]) for column in COLUMNS))
    for row in rows:
        print("  ".join(row[column].ljust(widths[column]) for column in COLUMNS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
