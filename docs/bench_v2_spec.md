# GM-Bench 2.0 specification

Frozen decisions for the 2.0 benchmark. Settled 2026-09-20 from the design
discussion that followed the `sota-v5` publication. Changes to this file after
the 2.0 contract freeze create a new benchmark version.

## Naming

- **GM-Bench 1.0** is the frozen `sota-v5` contract as published on
  2026-09-03, together with its decision-model lane. Nothing in 1.0 is
  renamed, rerun, or rewritten; the label is declared in `CHANGELOG.md` and
  on the site.
- **GM-Bench 2.0** is the agentic contract described here. It gets its own
  contract fingerprint, results directory, publication policy, and site
  section. 2.0 rows never enter a 1.0 table and vice versa.
- **2.1 and later** are reserved for simulator mechanics (the v6 mechanic
  list: draft lottery, willingness, lineup construction, re-sign pressure).
  2.0 deliberately ships none of them.

## What 2.0 measures

Five-season hockey franchise management by an **agent**: a language model
running inside its own harness (OpenCode, Claude Code, Codex CLI, or another
tool-using loop), driving the simulator through a tool interface for one
continuous session per episode.

1.0 measured a model answering one bounded prompt per decision phase. 2.0
measures whether an agent can assess an unfamiliar environment, gather the
information it needs through tools, act, keep its own memory across five
seasons, and do so without spending more than the result is worth.

Headline claim: dated **model + harness + harness version** performance under
these conditions. The harness is part of the row identity because it supplies
the system prompt, tool-calling loop, compaction, and permission model the
model plays through. A model row on two harnesses is two rows.

Secondary claim, available for free because the simulator and seeds are
unchanged: the same model's 1.0 one-shot score against its 2.0 agentic score,
paired per seed. Whether agency helps is a result, not an assumption.

## Interface

GM-Bench 2.0 is a **Model Context Protocol (MCP) server** over the existing
simulator, spoken over the stdio transport. A thin command-line wrapper
exposes the same verbs for harnesses without MCP support. Both paths share
one code path and produce identical ledgers.

### Tool surface

The tool set mirrors the 1.0 action protocol. Names are frozen at the
contract freeze; descriptions and input schemas are contract sources.

| Tool | Kind | 1.0 equivalent |
|---|---|---|
| `get_status` | read | the compact header of the observation: season, phase, standings, cap, budget used so far |
| `get_team` | read | `inspect_team` on the agent's own team |
| `inspect_team` | query | `inspect_team` |
| `inspect_player` | query | `inspect_player` |
| `list_free_agents` | query | `list_free_agents` |
| `list_draft_class` | query | `draft_class` (draft phase only) |
| `list_waiver_wire` | query | `waiver_wire` (midseason only) |
| `list_offers` | query | `incoming_offers` (trade deadline only) |
| `list_transactions` | query | `recent_transactions` |
| `scout` | query, budgeted | `scout` |
| `sign_free_agent`, `trade`, `draft`, `set_lineup`, `claim_waiver`, `extend_contract` | move | the core moves, one tool each |
| `accept_trade_offer`, `reject_trade_offer`, `counter_trade_offer` | move | trade negotiation |
| `write_memo` | memory | `memo` (kept for parity; the agent may also use its own context and files) |
| `end_phase` | control | `end_turn` |

Every move returns the same result object the 1.0 runner echoed as
`action_results`: accepted or rejected, the reason, and the legality class
(protocol violation versus rejected offer). The 1.0 distinction is kept: only
protocol violations are penalized.

### Observation exposure

Most of the observation sits behind tools. The initial task brief carries
only the rules of the league, the scoring priorities, the tool list, and the
agent's team identity. Rosters, market, draft class, and offers are fetched
on demand. This is the capability under measurement: find out what matters,
without calling everything.

The 1.0 `full` observation tier is not offered in 2.0.

### Phase control

The agent ends a phase by calling `end_phase`. Precautions, in order:

1. A harness that exits with the episode unfinished is **nudged**: the driver
   resumes the same session (context intact) with a fixed reminder of the
   season and phase and the instruction to continue. Nudges are capped per
   episode (default 20, recorded in the manifest), stop early when a nudge
   produces no new tool call, and are reported per episode beside the score.
   The reminder text is a contract source. Decided 2026-09-20: harnesses end a
   run the moment the model answers with text and no tool call, and losing a
   whole episode to one stray sentence measured chattiness, not management.
2. When nudges are exhausted, or cannot be sent, every remaining phase is a
   **failed decision** (the 1.0 timeout rule) and the episode is scored with
   whatever moves were already applied.
3. A per-phase **wall-clock guard** (default 20 minutes, recorded in the run
   manifest) ends the phase the same way. It is a safety stop against a hung
   harness, not a budget, and is set high enough that no honest agent hits it.
4. The server refuses moves that belong to a different phase with a
   protocol-violation result, exactly as 1.0 does.

## Budget policy

**Report, do not cap.** Every row publishes, per episode and per run:

- tool calls (total and by tool), and the number of `scout` points spent
- harness turns (assistant messages) and compaction events, where the
  harness reports them
- input, output, cached, and reasoning tokens, where the harness reports them
- wall-clock per phase and per episode
- cost in dollars from the harness's own accounting, falling back to
  `gm_bench/pricing.json` at the model's list price when the harness reports
  tokens but not cost

Spending is controlled by choosing which models to run, not by the contract.
Cost sits beside the score on the site, never inside it.

The server-side tool-call ledger is **authoritative**. Harness telemetry is
best-effort: a row whose harness reports no tokens publishes them as
unmeasured, not zero, following the 1.0 convention for within-seed noise.

## Sandbox

The agent may run code. The sandbox exists so that it cannot reach hidden
state, cannot damage the host, and cannot carry information between episodes.

- **Scratch directory per episode.** The harness is launched with an empty
  temporary directory as its working directory. The GM-Bench checkout, the
  results tree, and the run database are not under it.
- **Hidden state stays in the driver process.** True potential, reservation
  prices, partner valuation noise, and the seed live only in the memory of the
  driver, which serves the MCP protocol over a private Unix socket (mode
  0600, in its own temporary directory). What the harness launches as the
  "MCP server" is a standard-library proxy script copied into the scratch
  directory and run on the harness's own `python3`; it forwards stdio to the
  socket and knows nothing else. Nothing the agent can read names the seed,
  the benchmark's interpreter, or the repository. Because the engine outlives
  every harness invocation, restarts and nudges reconnect to the same live
  episode with no replay.
- **No repo on the path.** The driver verifies that the scratch directory and
  its ancestors contain no `gm_bench` checkout, and that `gm_bench` is not
  importable from the scratch directory's default Python path. A run that
  fails the check does not start.
- **Filesystem and network.** The harness is run with its own permission
  system set to auto-approve inside the scratch directory only. Model
  provider traffic is the harness's own. Anything stronger (container, seccomp)
  is a per-harness option recorded in the manifest, not a contract requirement.
- **Cheating is detected after the fact, not only prevented.** The server
  logs every tool call with its arguments. The publication check rejects an
  episode whose ledger contains a move referencing an entity the agent never
  fetched through a tool, since the only other way to know that ID is a leak.
  Scout usage above the budget, and moves in the wrong phase, are already
  protocol violations.

## Row identity and eligibility

A row is `model + harness + harness version` (for example
`opencode/1.18.30 · anthropic/claude-haiku-4.5`). The model string is what
the harness resolves it to; the driver records the harness's own model
identifier and, where available, the served model version.

Eligibility is looser than 1.0 on purpose:

- **No structured-output requirement.** Tool calls replace the JSON action
  batch, so the 1.0 route rule about `response_format` does not apply.
- **No route pinning requirement.** Where the harness chooses the provider,
  the row records what the harness reported and nothing more.
- **Free and preview models are publishable.** A row whose model version or
  provider is not pinnable is published with an `unpinned` flag and a plain
  sentence saying the row may not be reproducible. It is an extra data point,
  not a headline.
- What stays: strict failure handling (a failed decision is a pure no-op,
  never a harness-chosen move), the same scoring scale, the same private
  seeds, and serial execution for subscription-metered harnesses.

## Panel design

The 2.0 panel is **32 private seeds, one episode per seed**: the 29-seed 1.0
private panel plus three new seeds drawn the same way and kept in the same
keychain. The 29 shared seeds carry the 1.0-versus-2.0 per-model pairing; the
three new ones round the panel to an even 32.

The design was checked against the alternatives on 2026-09-20 with
`scripts/power_analysis.py` on the 48-seed calibration panel (paired-residual
SD 40.1). Minimum detectable difference at 80% power, in score points:

| episodes | design | model repeat SD 15 | SD 25 | SD 35 |
|---|---|---|---|---|
| 10 | 10 seeds × 1 | 49 | 57 | 66 |
| 20 | 10 seeds × 2 | 47 | 51 | 56 |
| 16 | 16 seeds × 1 | 35 | 42 | 50 |
| 32 | 16 seeds × 2 | 33 | 38 | 41 |
| 24 | 24 seeds × 1 | 29 | 33 | 40 |
| 29 | 29 seeds × 1 | 25 | 30 | 35 |
| 32 | 32 seeds × 1 | ~24 | ~29 | ~33 |

Repeating seeds buys almost nothing: the seed-to-seed spread dominates the
model's own noise, so a second run of the same seed averages the smaller term.
For the same number of episodes, more seeds beats more repeats every time
(32 episodes as 16 × 2 resolves 38 points; as 32 × 1 about 29).

Decisions:

- **Full row:** 32 seeds × 1. Expected MDD 24 to 33 points depending on the
  model's repeat noise, which for agentic runs is expected toward the high end.
- **Smoke row:** 8 seeds × 1 from the same panel, for development and for
  free-model rows where a full run is not worth the wall-clock. Published
  only with the `smoke` flag and no reference contrast.
- **Repeat-noise probe:** within-seed repeat SD is not measured per row. It is
  measured once per harness on one cheap model (5 seeds × 3), published in
  the calibration doc, and used as the assumed noise for that harness's rows,
  the same way 1.0 assumed 15.
- The only supported inference remains the predeclared reference contrast
  against `pick-trader` on the same seeds. No ranking or tiering.

## Implementation: standard library only, verified against the official SDK

The `gm_bench` package stays dependency-free. The MCP server is hand-written
over the stdio transport in the standard library: newline-delimited JSON-RPC
2.0 with `initialize`, `notifications/initialized`, `ping`, `tools/list`, and
`tools/call`. That is the whole surface a tool server needs.

Reasons, in priority order:

1. **The server's wire output is a contract source.** Tool names,
   descriptions, and input schemas are fingerprinted byte-exactly. Serializing
   them through a third-party SDK would put the fingerprint under that SDK's
   release cadence; a routine upgrade could invalidate every published row.
2. **The surface is small.** Five methods and a version negotiation. A
   client that speaks a newer protocol version is expected to accept the
   server's older one or disconnect; the server answers with the latest
   version it implements.
3. **Installation stays one command with no resolver.** `pip install
   gm-bench` remains zero-dependency, which is what lets the published
   reproduction instructions stay short.

The official `mcp` Python SDK joins the **dev** extras only, as a client in a
conformance test: it must complete the handshake, list the tools, and call
each one against the hand-written server. That test is the guard against the
protocol drifting under us. OpenCode's `codemode` wrapper is disabled in the
generated harness config so that one model tool call is one ledger entry.

## First harness: OpenCode

OpenCode is the development harness: open source, provider-agnostic, free
models available for smoke runs, and a headless mode that reports usage.

The driver, per episode:

1. Creates the scratch directory and writes an `opencode.json` declaring the
   GM-Bench server as a local MCP server with `codemode` off.
2. Starts `opencode run --format json --pure --dir <scratch> --model <m>` with
   the task brief as the message and, where the model supports it, the lowest
   reasoning variant.
3. Parses the newline-delimited JSON events for turns, tool calls, tokens,
   cost, and compaction, and joins them to the server ledger by timestamp.
4. Records the OpenCode version, the resolved model string, and the full
   generated config in the run manifest.

Claude Code and Codex CLI drivers follow the same shape once the OpenCode
driver has passed the smoke gate. The AGENTS.md rule about serial execution
for subscription-metered harnesses applies to all of them.

## Gates before any paid run

1. Sandbox check passes on the driver, including the "no repo on the path"
   verification and a red-team episode that tries to read the seed.
2. Ledger round-trip: the server's tool-call count and the harness's reported
   tool-call count agree on a scripted client.
3. Conformance test against the official SDK client passes.
4. A free-model smoke row (8 seeds) completes with a failed-decision rate
   under 10%.
5. Contract fingerprint frozen: tool schemas, task brief, server, scoring.

### Gate status (2026-09-20, all on OpenCode 1.18.30, free models, seed 11, one season)

| gate | status |
|---|---|
| 1. sandbox check | passes on every run. The first design put the episode file, interpreter, and repository path into the harness config, all readable by the agent's shell; replaced 2026-09-20 by the socket-and-proxy design above. Red-team probe result recorded below |
| 2. ledger round-trip | server ledger equals harness tool events on all 7 models |
| 3. SDK conformance | passes against the official `mcp` client |
| 4. free-model smoke | 6 of 7 models closed 4/4 phases with 0 failed decisions; one (`nemotron-3.5-lightning-free`) stopped mid-phase and scored 4/4 failed, which is the intended harness-exit path. 8-seed smoke not yet run |
| 5. fingerprint frozen | `agentic_fingerprint` exists and is recorded in every run; still `gm-bench-2.0-dev`, and it moves whenever `episode.py` moves |

Observed shapes on one season: 31 to 47 tool calls, 13 to 47 model calls,
64k to 352k input tokens, 1.5 to 17 minutes wall. A five-season `big-pickle`
episode used 143 tool calls and 104 model calls with no compaction, context
peaking near 84k tokens. Every ledger audited clean.

### Repeat-noise probe (2026-09-20, `opencode/big-pickle`, seeds 11-13, five seasons, 2 to 3 runs each)

| seed | scores | within-seed SD |
|---|---|---|
| 11 | 272, 192, 166 | 45 |
| 12 | 270, 87 (harness exit after two seasons) | 91 |
| 13 | 209, 267 | 29 |

Mean within-seed SD 55 with the abandoned episode, about 37 without it. Both
are far above the 15 the 1.0 tables assume and above the 25 caveat threshold.
Re-running the power script at these levels, one episode per seed:

| within-seed SD | MDD at 16 seeds | MDD at 32 seeds |
|---|---|---|
| 37 | 51 | 35 |
| 55 | 67 | 46 |

So for a model this noisy the 32-seed panel resolves roughly 35 to 46
points, not the 24 to 33 projected above. This is one free model on three
seeds; the number is a warning, not a measurement. Stronger models are
expected to be steadier, and the per-harness probe in the panel design
stays the rule: measure it before quoting a resolution. Every probe ledger
audited clean and agreed with the harness tool-event count once refused
post-completion calls were counted on replay.

The harness-stop behaviour seen above (a model answering with text, or a
malformed tool call rendered as text, ends the OpenCode run) is now handled
by the nudge rule in "Phase control". The sweep and probe numbers above were
measured before nudges existed and are kept as the no-nudge baseline.

Nudge check (2026-09-20, `nemotron-3.5-lightning-free`, seed 11, one season,
the model that scored 4/4 failed without nudges): two nudges, the first
bought 22 tool calls and three phases, the second finished the season. The
episode completed with 36 tool calls and one phase closed by the 600 s guard
used for the check. Ledger and harness agreed on 36 calls across all three
harness invocations of one session.

## Not in 2.0

- Simulator mechanics (2.1).
- Hard budgets of any kind.
- A `full` observation tier.
- Cross-harness comparison claims. Two harnesses on one model are two rows;
  the site may show them side by side, and no p-value is attached.
