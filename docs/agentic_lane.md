# Running the agentic lane (GM-Bench 2.0)

The frozen decisions are in `docs/bench_v2_spec.md`. This page is the
operator's view: what a run does, what it writes, and how to read it.

## What happens in a run

```bash
python -m gm_bench agentic --harness opencode --model opencode/big-pickle \
  --seeds 11 12 --seasons 5 --output /tmp/agentic-big-pickle
```

For each seed, serially:

1. The driver writes `seed-<n>/episode.json` (seed, seasons, ledger path)
   under `--output`, readable by the owner only. The agent never sees this
   directory.
2. It creates an empty scratch directory and drops an `opencode.json` there
   that declares the `gm-bench` MCP server: this repository's Python running
   `gm_bench.agentic.mcp_server`, with the episode file passed through the
   server's own environment block and code mode off so each model tool call
   is one ledger entry.
3. It checks the sandbox and refuses to start if the scratch directory sits
   under a GM-Bench checkout or if `python3` on the harness's `PATH` can
   `import gm_bench`. The harness environment is the operator's minus every
   `GM_BENCH_*` variable, Python path overrides, and the virtualenv.
4. It runs `opencode run --format json --pure --auto --dir <scratch>` with the
   task brief from `gm_bench/agentic/brief.py` as the message and captures
   the event stream to `seed-<n>/opencode-events.jsonl`.
5. When the harness exits, the driver rebuilds the episode from
   `seed-<n>/ledger.jsonl`, closes any phase the agent left open as a failed
   decision, joins the harness's token and cost telemetry, scores, and writes
   `seed-<n>/result.json`. The run-level `run.json` carries every episode,
   the usual `summary` block, and an `agentic_summary`.

The MCP server is a plain stdio JSON-RPC process. If the harness restarts it
mid-episode, it replays the ledger and carries on; it never scores on its own.

## Reading the result

Per episode, `result.json` has the 1.0 fields (`final_score`,
`strategy_score`, `protocol_penalty`, `illegal_actions`, `failed_decisions`,
season summaries, transactions) plus:

- `agentic.tool_calls`, `agentic.tool_calls_by_tool`, `agentic.moves_accepted`,
  `agentic.moves_rejected`, `agentic.scout_points_used`
- `agentic.phases`: one row per phase with how it ended (`agent`, `guard`,
  `harness_exit`), tool calls, and wall-clock seconds
- `usage`: model calls, input/output/reasoning/cached tokens, cost when the
  harness reports it (`null` when it does not), and a `harness` block with
  compactions and the harness's own tool-event counts
- `harness_run`: the command (brief elided), exit code, timeout flag, wall
  time, and where the raw event stream lives

`failed_decisions` counts phases the agent did not close itself. A harness
that finishes without ever calling `end_phase` scores a no-op episode with
every phase failed, exactly like a 1.0 adapter that never produced output.

## Auditing a ledger

```python
from gm_bench.agentic.audit import audit_ledger
audit_ledger("/tmp/agentic-big-pickle/seed-11/ledger.jsonl")
```

Every tool reply's entity ids are recorded, so the audit can list moves that
named a player, prospect, team, or offer no earlier reply exposed. Accepted
moves on unseen ids are `violations`; rejected ones are `suspicious`. The
audit reports, it does not decide; publication does.

## Development harness and models

OpenCode is the development harness. `opencode models` lists the free
`opencode/*` models; they cost nothing and are fine for smoke runs and for
rows flagged as unpinned. Never parallelize seeds against a
subscription-metered harness; the driver is serial on purpose.

`--phase-guard-seconds` (default 1200) is a hang stop, not a budget. There
are no budgets in 2.0; tool calls, tokens, and dollars are reported beside
the score.

## Tests

- `tests/test_agentic_episode.py`: calendar, moves, ledger replay, guard,
  audit, and equivalence with a 1.0 no-op episode on the same seed
- `tests/test_agentic_mcp.py`: the stdio server driven by a minimal JSON-RPC
  client, server restart, sandbox checks, event parsing
- `tests/test_agentic_conformance.py`: the server driven by the official
  `mcp` SDK client (dev extra; skipped when not installed)
