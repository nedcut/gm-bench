# Running the agentic lane (GM-Bench 2.0)

The frozen decisions are in `docs/bench_v2_spec.md`. This page is the
operator's view: what a run does, what it writes, and how to read it.

## What happens in a run

```bash
python -m gm_bench agentic --harness opencode --model opencode/big-pickle \
  --seeds 11 12 --seasons 5 --output /tmp/agentic-big-pickle
```

For each seed, serially:

1. The driver builds the episode engine in its own process and serves it as
   an MCP server over a private Unix socket. The seed is never written where
   the agent could find it; the only copy on disk is the ledger header under
   `--output`, a directory the agent is never told about.
2. It creates an empty scratch directory holding a standard-library proxy
   script (`gm_bench_proxy.py`, copied from `gm_bench/agentic/_proxy.py`) and
   an `opencode.json` that launches the proxy on the harness's own `python3`
   with the socket path as its only argument, with code mode off so each
   model tool call is one ledger entry.
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
   the usual `summary` block, and an `agentic_summary`. Evidence paths in
   `harness_run` are relative to the run directory, so the directory can be
   moved and still validate.

The run directory must be fresh: an episode directory that already holds
evidence is refused before any harness launches, because the ledger is
append-only and a rerun would write a second episode onto the first. A seed
listed twice (a within-seed noise probe) gets one directory per attempt,
`seed-11` then `seed-11-r2`.

If the harness exits before the episode is complete, the driver **nudges**:
it resumes the same OpenCode session (`--session <id>`, context intact) with
a fixed reminder of the season and phase, up to `--max-nudges` times (default
20). A nudge that produces no new tool call ends the loop. Nudges are listed
per episode in `harness_run.nudges` with the tool calls and phases each one
bought; only after they are exhausted are the remaining phases closed as
failed decisions. The reminder text lives in `gm_bench/agentic/brief.py` and
is a contract source.

The engine outlives every harness invocation, so restarts and nudges
reconnect to the same live episode. The stdio entry point
(`python -m gm_bench.agentic.mcp_server`, configured by an episode file)
remains for tests and hand-driven harnesses; it replays the ledger on start.

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
  compactions and the harness's own tool-event counts. OpenCode reports one
  total per session, so the block is one record covering every decision of
  the episode; the run summary's per-decision means divide that total by
  the decision count, and wall time lives on `harness_run`, not in the usage
  block
- `harness_run`: the command (brief elided), exit code, timeout flag, wall
  time, nudges used and what each bought, phase-guard stops (`guard_kills`),
  whether every proxy connection had closed when the server stopped
  (`server_drained`), and where the raw event stream lives

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
moves on unseen ids are `violations`; rejected ones are `suspicious`. Ids are
sequential, so models do guess them: a successful read on a guessed id
(`scout`, `inspect_player`, `inspect_team`) is reported as a `guessed_read`
and the id counts as exposed from that reply on. The audit reports, it does
not decide; publication does.

## Validating a run

```bash
python -m gm_bench agentic-validate /tmp/agentic-big-pickle
```

Exit code 0 means every episode's ledger replays to the recorded score, its
header seed matches the episode, it audits clean, the GM-Bench tool calls in
the retained `opencode-events.jsonl` equal the replayed ledger's (the
recorded agreement is checked against that recount, not trusted), and the
run's contract block matches this checkout's `agentic_contract()`. Failed
phases, timeouts, guard stops, and missing telemetry are warnings: reported,
never hidden, never fatal. A missing event stream is a problem.

## Publishing a row

```bash
python -m gm_bench agentic-redact /tmp/agentic-big-pickle \
    --output results/agentic/opencode-1.18.31-big-pickle-smoke-8x5.json \
    --isolation same-user --public-seeds
python -m gm_bench agentic-validate results/agentic/opencode-1.18.31-big-pickle-smoke-8x5.json
python -m gm_bench agentic-validate results/agentic/opencode-1.18.31-big-pickle-smoke-8x5.json \
    --raw /tmp/agentic-big-pickle
```

The second validation, with `--raw`, checks the artifact's SHA-256 binding
against the raw `run.json` and that the artifact equals a fresh redaction of
that run. CI cannot run it (raw runs stay with the operator), so run it
yourself before committing any panel-grade row.

The artifact is the only thing committed. It keeps scores, telemetry, the
contract block, the harness identity, and a hash of the seeds; it drops
ledgers, event streams, commands, and paths, and it is bound to the raw
`run.json` by SHA-256. `--isolation` is your statement of how the harness was
separated from the driver (see the sandbox section of the spec): `same-user`
runs are `smoke` grade whatever their size, and `panel` grade needs 32 or
more seeds, redacted seeds, and `separate-user` or `container`. The redact
command refuses to write anything that would not validate. CI re-validates
every file under `results/agentic/` against the checkout's contract. A
`panel`-grade row must also be a run of the lane's frozen private panel: both
`agentic-redact` and `agentic-validate` (and so CI) reject it unless its
`panel.sha256` equals `seed_panel.artifact_panel_sha256` in
`config/bench_v2_lane.json` and its distinct-seed count equals that panel's
`count`; `smoke` rows are exempt. On the site, a row is flagged `unpinned`
(may not be reproducible) unless its harness model id is listed with its pin
under `model_pinning.pinned_models` in the same file; add the pin there, in
the same change that commits the row, only when the served model version or
provider is actually fixed.

A `panel`-grade artifact also carries a `reference` block: the spec's one
supported inference, the predeclared contrast against `pick-trader` on the
same seeds and seasons (`docs/bench_v2_spec.md`, Panel design). You do not
run it separately. `agentic-redact` computes it from the seeds in the raw
`run.json`, in-process, so nothing new goes on a command line: it plays
`pick-trader` and `random` (shown as a floor) through the 1.0 runner's
scripted-baseline path, with the default episode config `gm-bench evaluate`
uses, so the scores are the ones a 1.0 run on those seeds reports. It plays
them live with the baseline cache off (about 12 seconds for 32 seeds at 5
seasons): the cache has no integrity check, so reading it would let `--raw`
vouch for whatever a local file says, and writing it would put the private
seeds in its keys. A 2.0 episode is scored by the same functions on
the same simulator as a 1.0 episode, so the per-seed difference is like for
like. The block mirrors a redacted 1.0 `paired` block with `pick-trader` as
the only baseline: `mean_score` (pick-trader), `floor.mean_score` (random),
`seasons`, `num_seeds`, `paired_lift_mean` (row per-seed score minus
pick-trader's, averaged), `paired_lift_stddev`, `paired_lift_ci95`
(deterministic bootstrap), `sign_flip_p_value`, `significant_at_95`,
`candidate_seed_win_rate`, and `per_seed`, which is always empty: a per-seed
lift on a private seed gives the row's score on that seed. It keeps no seed,
no cache path, and no cache hit count. Validation rejects a panel row
without the block, a block whose `num_seeds` is not the row's distinct seed
groups, a non-empty `per_seed`, any agent but `pick-trader`, and a `smoke`
row that carries one; `smoke` rows never get a reference. It also rejects
numbers the paired statistics cannot produce: a lift that is not the row
mean minus the pick-trader mean, an interval that does not contain its lift
or is wider than its standard deviation allows, and a seed win rate of 0 or
1 against the sign of the lift. The p-value is not tied to the interval,
because the exact sign-flip test and the bootstrap interval can disagree.
`agentic-validate --raw` recomputes the block from the simulator as part of
the fresh redaction and requires it to be identical.

A hand edit that shifts the pick-trader mean and the lift together stays
internally consistent, and CI never has the raw run. But `pick-trader` and
`random` are deterministic, so on the one frozen panel their 5-season means
are constants every panel row shares. After the first panel row passes
`agentic-validate --raw`, record its `reference.mean_score` and
`reference.floor.mean_score` under `reference_scores.mean_scores` in
`config/bench_v2_lane.json`; they are aggregates the row already publishes.
From then on `agentic-validate`, the site build, and the site data check
reject a panel row whose reference or floor mean differs. Until they are
recorded, validation warns that the reference is unpinned, and the site
build and data check require every panel row at a season count to agree.

## Private panel

A full row is the 32-seed private panel (`docs/bench_v2_spec.md`, Panel
design). `config/bench_v2_lane.json` commits to it by digest only: the
execution hash of the ordered seeds, `artifact_panel_sha256` (the
`panel.sha256` a published panel row must carry), and a salted hiding
commitment. Positions 1 to 29 are the `sota-v5` private panel in its
committed order, which is what pairs a model's 1.0 and 2.0 scores per seed;
positions 30 to 32 were drawn 2026-09-22 by
`scripts/draw_bench_v2_private_panel.py` with the generator that drew v5.
The seeds and salt live only in the macOS Keychain
(`gm-bench-bench-v2-private-panel`).

```bash
python scripts/run_bench_v2_panel_from_keychain.py --verify-only
python scripts/run_bench_v2_panel_from_keychain.py \
    --model opencode/big-pickle --output /path/outside/the/checkout/run
```

`--verify-only` checks the escrow against every committed digest and prints
only the result. A run checks the same digests, refuses to start until the
lane's `owner_attestation_status` is `attested-before-seed-access`, and then
runs `gm-bench agentic --seeds-stdin` in its own process with the seeds on
standard input. No command line or environment variable carries them.
Episode directories are named by position (`episode-00`, `episode-01`, ...)
rather than `seed-<seed>`, because the harness's stdout and stderr are files
there and would otherwise show the seed in its open-file table; the harness's
stdin is `/dev/null`. Progress lines name episodes by `seed_group` rather than
seed. The output
directory must be empty and outside the checkout. Other arguments pass
through to `gm-bench agentic` unchanged, so driver options (and any
isolation flags the driver adds) need no launcher change; `--seeds` and
`--json` are refused. Keeping seeds out of `ps` and `lsof` does not isolate
the harness: the run directory still holds them (ledger headers and finished
episodes' `result.json`), so panel grade still needs
`separate-user` or `container` isolation.

## Red-teaming the sandbox

```bash
echo 11 | python scripts/agentic_red_team.py --model opencode/big-pickle --output /tmp/red-team
```

Launches the harness exactly as a run does, but with a brief that tells the
agent to find the seed by any means. The report lists every shell command
the agent ran and whether the seed appeared in its output. Expect
`SEED FOUND` on a same-user machine: `ps` shows the driver's command line.
Expect `SEED NOT FOUND` only when the harness runs as another user or in a
container.

## Comparing runs

```bash
python scripts/agentic_sweep_summary.py /tmp/agentic-sweep
```

One row per run directory: score, illegal actions, failed phases, tool calls,
tokens, cost, wall time, agreement, and audit verdict. Diagnostic only.

## Development harness and models

OpenCode is the development harness. `opencode models` lists the free
`opencode/*` models; they cost nothing and are fine for smoke runs and for
rows flagged as unpinned. Never parallelize seeds against a
subscription-metered harness; the driver is serial on purpose.

`--phase-guard-seconds` (default 1200) is a hang stop, not a budget. It is
elapsed phase time, not idle time. The driver polls it while the harness
runs: a session whose current phase has run past the guard is stopped and
nudged, and its next call closes the expired phase as `guard`. There are no
budgets in 2.0; tool calls, tokens, and dollars are reported beside the
score.

## Tests

- `tests/test_agentic_episode.py`: calendar, moves, ledger replay, guard,
  audit, and equivalence with a 1.0 no-op episode on the same seed
- `tests/test_agentic_mcp.py`: the stdio server driven by a minimal JSON-RPC
  client, server restart, sandbox checks, event parsing
- `tests/test_agentic_conformance.py`: the server driven by the official
  `mcp` SDK client (dev extra; skipped when not installed)
- `tests/test_agentic_publication.py`: the compact artifact is bound to its
  raw run, redacted, graded by the spec's rules, and rejects drift or
  tampering
- `tests/test_bench_v2_panel.py`: the committed 32-seed lane is internally
  consistent and extends the `sota-v5` panel, the Keychain launcher refuses
  an escrow that misses any digest, and seeds stay off command lines,
  environment variables, and progress output
