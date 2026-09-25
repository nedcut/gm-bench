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

The table is the surface `gm_bench/agentic/tools.py` declares. `read` tools
are answered from public state by the engine and never touch the simulator's
ledger; `query` tools are the 1.0 query actions routed through the simulator
(`scout` is budgeted); `move` tools change the league and are judged by the
simulator; `end_phase` is the one control.

| Tool | Kind | 1.0 equivalent |
|---|---|---|
| `get_status` | read | the compact header of the observation: season, phase, standings, cap, budget used so far, memo, legal tools |
| `get_rules` | read | the `rules` block of the observation |
| `get_team` | read | `inspect_team` on the agent's own team, with release costs and extension quotes |
| `list_draft_class` | read | `draft_class` (draft phase only) |
| `list_waiver_wire` | read | `waiver_wire` (midseason only) |
| `list_offers` | read | `incoming_offers` (usually only at the trade deadline) |
| `list_trade_market` | read | `trade_market` |
| `list_transactions` | read | `recent_transactions` |
| `inspect_team` | query | `inspect_team` |
| `inspect_player` | query | `inspect_player` |
| `list_free_agents` | query | `list_free_agents` |
| `scout` | query, budgeted | `scout` |
| `sign_free_agent`, `extend_contract`, `release_player`, `trade`, `draft`, `set_lineup`, `claim_waiver` | move | the core moves, one tool each |
| `accept_trade_offer`, `reject_trade_offer`, `counter_trade_offer` | move | trade negotiation |
| `write_memo` | move | `memo` (kept for parity; the agent may also use its own context and files) |
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
   A run that ends on a retryable provider error is resumed after a bounded
   backoff, is not a nudge, and the backoff is excluded from the phase guard.
   The reminder text is a contract source. Decided 2026-09-20: harnesses end a
   run the moment the model answers with text and no tool call, and losing a
   whole episode to one stray sentence measured chattiness, not management.
2. When nudges are exhausted, or cannot be sent, every remaining phase is a
   **failed decision** (the 1.0 timeout rule) and the episode is scored with
   whatever moves were already applied.
3. A per-phase **wall-clock guard** (default 20 minutes, recorded in the run
   manifest) ends the phase the same way. It is a safety stop against a hung
   harness, not a budget, and is set high enough that no honest agent hits it.
   The guard is elapsed phase time, not idle time: a tool call does not
   reset it. The engine closes the expired phase on the agent's next tool
   call and tells it so; the driver polls the guard while the harness runs
   and stops a harness whose current phase has run past it, then nudges it,
   so a hung session costs one phase rather than the episode timeout. The
   resumed session gets a full guard period to make that call before it is
   stopped again. Guard stops are counted per episode (`guard_kills`).
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
  socket and knows nothing else. A harness in a container cannot reach a
  host Unix socket through a bind mount (Docker Desktop refuses the
  connect), so there the driver listens on the host loopback on an
  ephemeral TCP port instead, the proxy dials it through
  `host.docker.internal`, and every connection must first present a per-run
  random secret that the driver writes beside the proxy, never onto a
  command line. Nothing the agent can read names the seed,
  the benchmark's interpreter, or the repository. Because the engine outlives
  every harness invocation, restarts and nudges reconnect to the same live
  episode with no replay.
- **No repo on the path.** The driver verifies that the scratch directory and
  its ancestors contain no `gm_bench` checkout, and that `gm_bench` is not
  importable from the scratch directory's default Python path. A run that
  fails the check does not start.
- **What a same-user process can still see.** The driver's own command line
  carries `--seeds`, and `ps` shows it to any process of the same user, as it
  would the driver's memory on systems that allow same-user tracing. A
  process-level sandbox cannot close that. Private-panel rows must run the
  driver under a different user or in a container from the harness; the
  free-model smokes here did not, and are labelled accordingly. The
  red-team probe (`scripts/agentic_red_team.py`, 2026-09-21) measured
  exactly this boundary: the agent read the scratch directory, the config,
  the proxy, the environment, and the socket directory and learned nothing;
  its second command was `ps`, which showed the driver, and from there it
  read the run directory's ledger header, found the checkout, and rebuilt
  the league with the checkout's own interpreter. Everything the driver can
  hide is hidden; everything the operating system shows a same-user process
  is open. Isolation is therefore recorded on every published row
  (`isolation`: `same-user`, `separate-user`, `container`) and a hard
  requirement for panel grade. The driver records the level it actually
  launched (`same-user`, or `container` with `--isolation container`), and
  publication refuses a claim stronger than that record; the operator may
  only understate it. No driver launches `separate-user` yet.
- **Filesystem and network.** The harness runs with its own permission
  prompts turned off (`opencode run --auto` approves every tool call) and the
  scratch directory as its working directory. That is not a filesystem jail:
  `--dir` sets where the agent starts, and nothing stops a shell command from
  reading elsewhere, which is exactly what the `ps` probe above went on to
  do. The driver enforces what it can, that the scratch directory holds
  nothing worth reading, and records the rest as the row's `isolation`. Model
  provider traffic is the harness's own. Anything stronger (container,
  seccomp) is a per-harness option recorded in the manifest, not a contract
  requirement. The container launcher uses that option: its egress rule
  (public internet and DNS; on the host, only the driver's port) is
  recorded under `harness.container.egress` and checked before every
  episode.
- **Cheating is detected after the fact, not only prevented.** The server
  logs every tool call with its arguments. The publication check rejects an
  episode whose ledger contains an accepted move on an entity id that no tool
  reply exposed and no successful read (`scout`, `inspect_player`,
  `inspect_team`) confirmed. Simulator ids are sequential (a season-5
  prospect is `105xxxx`), so a model can guess one; the 8-seed smoke saw
  `big-pickle` scout three guessed prospect ids and draft the best without
  listing the class. A confirmed read is the server telling the agent about
  that entity, so the id counts as exposed from then on and the read is
  reported as a guessed read. The audit is a screen for leaked ids, not
  proof; an accepted move on an id with no reply and no read behind it is
  still a violation. Scout usage above the budget, and moves in the wrong
  phase, are already protocol violations.

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

### Gate status (updated 2026-09-25: all five gates met)

| gate | status |
|---|---|
| 1. sandbox check | passes on every run. The first design put the episode file, interpreter, and repository path into the harness config, all readable by the agent's shell; replaced 2026-09-20 by the socket-and-proxy design above. Scored live episode on the socket design 2026-09-21 (`big-pickle`, seed 11, one season): 4/4 phases closed by the agent, 40 tool calls, ledger equals harness events, audit clean, validates. Red-team probe the same day: the agent found nothing in the scratch directory, config, proxy, environment, or socket directory, then found the seed through `ps` on the driver (documented same-user gap above; `container`/`separate-user` isolation is required for panel grade and recorded per row). Container launcher 2026-09-22 (contract `02a9f887e79c0497`, OpenCode 1.18.31 in the pinned image): a one-season `big-pickle` episode on seed 11 with `--isolation container` closed 4/4 phases itself with 38 tool calls over the TCP transport, ledger equals harness events, audit clean, validates, score 106.2; while it ran, `ps` and every `/proc/*/cmdline` inside the harness container showed only the container's own processes, and the host `ps` showed the driver with `--seeds 11`. The container red-team probe the same day measured nothing: `big-pickle` refused the brief and ran no command, so a red-team verdict under container isolation is still owed. Review the same day: a red-team probe on seed 11 with `opencode/mimo-v2.6-flash-free` port-scanned the host gateway and read host-loopback services (Ollama, an agent server, a tunnel's metrics and config) through `host.docker.internal`, though not the seed, checkout, or run directory. The launcher now firewalls the container's egress (host gateway only on the driver's port, no private or link-local ranges), and a host-loopback canary must be unreachable before any episode starts; checked without a model against real Docker: 7 host-loopback services reachable before the rule, none after, the proxy still served. The contract moved to `735bbacc6c9564ee` for the proxy-connection counting fix, then to `07de948a4f4afbae` when the engine learned to take a provider-stall backoff off the phase guard clock. The live episode above predates both. **Met on contract `07de948a4f4afbae` (2026-09-24):** live container episodes ran on all three harnesses (the 8-seed `space-bunny-free` smoke row below, and one-season `gpt-6-luna` and `claude-sonnet-5` smokes), and two container red-team probes ran with `opencode/space-bunny-free`. The first used the example seed printed in the red-team script and found it: the agent web-searched the team names, found the public repository, recognised its own brief in `scripts/agentic_red_team.py`, downloaded the source, rebuilt that seed's league offline and matched its `get_status` byte for byte. Nothing came from the host or driver; the script now refuses any seed outside the private-panel range (2**32 to 2**63 - 1). The second used a fresh seed from that range and ran the full 20 minutes without finding it: it reimplemented the league generator and searched six-digit seeds against the public rosters, tried `sudo`, `nsenter` and `/proc/1/root`, port-scanned the host gateway (only the driver's port answered), and sent unlisted MCP methods and tool names (all refused); the seed never appeared in any output and no output showed the driver. Seeds from a 63-bit range are out of reach of an offline search, so the public source is not a route to a panel seed |
| 2. ledger round-trip | server ledger equals harness tool events on all 7 models |
| 3. SDK conformance | passes against the official `mcp` client |
| 4. free-model smoke | 6 of 7 models closed 4/4 phases with 0 failed decisions on seed 11; one (`nemotron-3.5-lightning-free`) stopped mid-phase and was rescued by nudges. 8-seed, five-season smoke row on `big-pickle` (2026-09-22, OpenCode 1.18.31, contract `c0619fc756769e61`): 159/160 phases closed by the agent and 1 by the phase guard, 1 failed decision, mean 245.3 (SD 79.0, range 140 to 363), 171 tool calls and 103 model calls per episode, 3.3M input and 0.41M output tokens total, no compaction, 1 guard stop and 1 nudge on one seed (the nudge resumed the session; its first call closed the expired phase as `guard` and it closed the remaining 15 itself), every ledger replays, agrees with the harness, and audits clean. It was committed as `results/agentic/opencode-1.18.31-big-pickle-smoke-8x5.json`, smoke grade, public seeds 1 to 8. The earlier row on the previous contract (2026-09-21, mean 201.1, 0 guard stops) was replaced when `get_status` started listing the read tools and the socket server learned to drain its connections on stop. On contract `07de948a4f4afbae` it was replaced by a container-isolation rerun on `opencode/space-bunny-free` (2026-09-24, OpenCode 1.18.31; `big-pickle` had exhausted its free quota): 160/160 phases closed by the agent, 0 failed decisions, 29 penalized illegal moves, mean 225.8 (SD 43.7, range 189.1 to 332.0), 210 tool calls and 157 model calls per episode, 1.65M uncached and 176M cached input tokens and 0.09M output tokens total, no compaction, 4 nudges, 0 provider stalls, 0 guard stops. Committed as `results/agentic/opencode-1.18.31-space-bunny-free-smoke-8x5.json`, smoke grade, public seeds 1 to 8. Rerun 2026-09-25 under the frozen `gm-bench-2.0` label (same fingerprint, model, OpenCode version and isolation), which replaced that row: 160/160 phases closed by the agent, 0 failed decisions, 26 penalized illegal moves, mean 217.8 (SD 20.5, range 182.0 to 249.4), 217 tool calls and 146 model calls per episode, 147.3M input tokens (145.9M cached) and 0.33M output tokens total, no compaction, 5 nudges, 0 provider stalls, 0 silent-harness kills, 0 guard stops. All 5 nudges (4 in the previous run) were the same startup failure: the first OpenCode launch ended within about a second on a server `UnknownError` with no tool call, and the resumed session then played the whole episode and exited 0. The recorded `harness exit code 1` warning is that first launch's code, not the end of the episode. The driver then treated this error as the agent stopping, so a repeat on the resume would have abandoned the episode; it is now retried as a provider stall, and `harness_run.final_exit_code` records how the harness finished |
| 5. fingerprint frozen | **frozen 2026-09-25** as `gm-bench-2.0` at agentic fingerprint `07de948a4f4afbae` (`gm_bench/agentic/contract.py`); `tests/test_agentic_mcp.py` pins the pair, so any byte change to `tools.py`, `brief.py`, `episode.py` or `mcp_server.py` fails CI until it is released as a new benchmark version |

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

### Repeat noise under current behaviour (2026-09-25, `opencode/space-bunny-free`, seeds 1-8, two runs)

Two complete runs of the same row, measured at no extra cost because both
were smoke rows anyway: `opencode/space-bunny-free` on OpenCode 1.18.31,
container isolation, public seeds 1 to 8, five seasons, agentic contract
`07de948a4f4afbae`, nudges on (up to 20 per episode). Run A is the row first
committed at `results/agentic/opencode-1.18.31-space-bunny-free-smoke-8x5.json`
(redacted 2026-09-24, raw artifact SHA-256 `a632a5fa...`). Run B is the rerun
made for the contract freeze, which replaces it at the same path (redacted
2026-09-25, raw artifact SHA-256 `f548e249...`). Both closed 160/160 phases
themselves with 0 failed decisions, 0 guard stops and 0 provider stalls; run
A used 4 nudges and run B 5. Every one of those nudges followed the same
OpenCode startup failure (the first launch ended within about a second on a
server `UnknownError`, before any tool call), and the resumed session then
played the whole episode, so no episode lost play to them.

| seed | run A | run B | A - B |
|---|---|---|---|
| 1 | 332.0 | 182.0 | +150.0 |
| 2 | 189.1 | 225.1 | -35.9 |
| 3 | 212.9 | 249.4 | -36.5 |
| 4 | 227.4 | 201.4 | +26.0 |
| 5 | 230.5 | 223.2 | +7.3 |
| 6 | 190.2 | 226.6 | -36.4 |
| 7 | 232.2 | 199.3 | +32.9 |
| 8 | 192.3 | 235.3 | -43.0 |
| mean | 225.8 | 217.8 | +8.0 |

Within-seed SD, pooled across seeds (root mean square of the difference
divided by the square root of 2): 43.4 over all eight seeds, 23.3 without
seed 1. Between-seed SD (sample) is 46.7 in run A, or 19.8 without seed 1,
and 21.9 in run B. So in run B the spread between seeds is smaller than the
spread between two runs of the same seed, even with seed 1 left out. The run
means differ by 8.0 points, but individual seeds moved by 7 to 150.

This pooled figure is not on the same basis as the probe table above, which
averages per-seed population SDs. On the pooled basis that probe reads about
51, or 78 with the abandoned episode. The drop from there to 23 to 43 cannot
be credited to nudges: the model and seeds differ as well.

Minimum detectable difference at 80% power, one episode per seed, computed
the way the probe above was: `scripts/power_analysis.py --seeds $(seq 11 58)
--repeats 1 --within-seed-stddev <sd> --seed-counts 16 32 --trials 2000
--gap-step 1.0`, on the 48-seed calibration panel (paired-residual SD 40.1).
The same command reproduces the probe's rows to within one point (37: 52 and
35; 55: 68 and 46).

| within-seed SD | MDD at 16 seeds | MDD at 32 seeds |
|---|---|---|
| 23 (without seed 1) | 40 | 28 |
| 43 (all eight seeds) | 57 | 39 |

For this model the 32-seed panel resolves roughly 28 to 39 points, depending
on whether seed 1's swing is typical. The 24 to 33 projected in "Panel design"
holds only at the low end of that range.

Caveats:

- One free model, eight public seeds, two runs per seed. Seed 1 alone moves
  the estimate from 23 to 43.
- Same contract fingerprint, but not provably the same driver code. Between
  the two runs the OpenCode driver was refactored behind the harness
  interface in `gm_bench/agentic/harness.py` when the Codex driver landed
  (#147). That change also made `input_tokens` include cached input, which is
  why run B reports 147M input tokens against run A's 1.65M. A row does not
  yet record the driver code it ran, so a behavioural difference in the
  driver cannot be ruled out from the artifacts. Runs made since then
  record their driver code (the `driver` block under "Publication"), so
  later repeats can be matched on it. The container image was rebuilt from the same Dockerfile
  (same Dockerfile hash, different image ID).
- Run B carries the contract label `gm-bench-2.0` where run A carries
  `gm-bench-2.0-dev`. The label is not a fingerprint source and does not
  reach the agent, so it does not affect play.

Why one seed can score 180 or 330. The ledgers for seed 1 show a single
early decision rather than drift. Both runs signed the same three top free
agents in the first preseason and went 22-11 in season 1 with near-equal team
strength (69.5 against 69.3). Run A signed them for two years and won a close
season-1 title; run B signed them for one year, so they left after season 1,
and it opened season 2 with 15 players, team strength 11th of 12 and $34M of
unused cap. Run A stayed 2nd to 3rd and won again in season 3; run B never
made the playoffs again. Of the 150-point gap, championships account for 70
and playoff rounds for 54. Across all 16 episodes playoff rounds (rank
correlation +0.63) and championships (+0.55) track score most closely, and
their spread (SD 40.2) exceeds the total score's (SD 35.5); no process measure
(tool calls, illegal moves, trades, memos, nudges) points the same way within
seed pairs often enough to matter. The simulator is deterministic for a given
seed and action sequence, so all of this noise comes from the model's
decisions, amplified by payouts that arrive in large lumps. Stronger models
may blunder less, but the lumps stay, so expecting them to fall back to the
15 the 1.0 tables assume is not safe.

Paid models need their own probe before a resolution is quoted for them.
Following `scripts/panel_power.py`, that probe should repeat a small subset
of seeds (for example 4 seeds x 2) rather than repeat the whole panel:
repeats are the only way to measure within-seed noise, but for telling rows
apart a second pass over the panel buys less than the same episodes spent on
more seeds.

## Publication

- **Raw evidence stays with the operator.** A run directory holds seeds,
  ledgers, harness event streams, and local paths. It is never committed.
- **One compact artifact per row** under `results/agentic/`, written by
  `gm-bench agentic-redact` (`gm_bench/agentic/publication.py`, format
  `gm-bench-agentic-summary-v1`). It carries the 2.0 contract block, the
  harness identity, the panel size and a hash of the sorted seeds, per-episode
  scores and agentic telemetry (tool calls by tool, phases and how they
  ended, nudges, tokens, cost, wall time), the ledger-versus-harness
  agreement, the validation report computed at redaction time, and, for a
  panel row only, the reference contrast against `pick-trader` on the same
  seeds (aggregates only, no per-seed values). It is
  bound to the raw run by the canonical SHA-256 of `run.json`, the same
  binding the 1.0 lanes use. Ledgers, commands, and paths are dropped.
- **The driver is recorded, not fingerprinted.** The fingerprint covers
  what the agent is measured through. The driver that plays the episode
  (the shared loop's nudges, retries, resumes and stall handling, the
  harness adapters, the container launcher, the proxy) can be fixed without
  a new contract, so each run records it instead: `run.json` and the row
  carry a `driver` block with a digest of the driver files taken at run
  start, the files it covers, the git commit, whether those files matched
  it (`git_driver_clean`), and whether they changed before the run ended
  (`gm_bench/agentic/provenance.py` lists which files are contract, driver,
  or neither). Two rows with the same fingerprint and harness version but
  different digests were played by different driver code.
- **Grade is mechanical.** `panel` requires at least 32 distinct seeds,
  redacted seeds, `isolation` of `separate-user` or `container`, and a
  driver that matched a commit for the whole run. Anything
  else is `smoke`, and the artifact says so. Each episode carries a
  `seed_group` (episodes of one seed share a group) so the distinct count
  and the per-seed mean can be checked without the seeds. A smoke row on
  public seeds may keep its seeds (`--public-seeds`).
- **Validation recomputes, it does not trust.** `agentic-validate` replays
  every ledger to its score, checks the ledger header's seed against the
  episode, audits the ledger, and counts GM-Bench tool calls in the retained
  harness event stream against the replayed ledger; the run's own recorded
  agreement is then checked against both. A missing event stream is a
  problem, not a pass. Given the raw run as well (`agentic-validate <row>
  --raw <run dir>`), it checks the SHA-256 binding and that the artifact
  equals a fresh redaction of that run, so a hand-edited grade, seed group
  or score cannot pass; that is the check an operator runs on a panel row
  before committing it, since CI never sees private raw runs.
- **CI validates every committed row** with `gm-bench agentic-validate`,
  which recomputes the contract from the checkout. A byte change to the tool
  surface, brief, engine, or server therefore fails every committed row
  until it is rerun, as with 1.0. A driver change does not: a row whose
  driver digest differs from the checkout's gets a warning naming the
  commit that played it. Rows recorded before the `driver` block stay
  valid as `smoke`.
- **Site section** lands with the first panel-grade row; smoke rows are
  committed for reproducibility, not shown.

## Not in 2.0

- Simulator mechanics (2.1).
- Hard budgets of any kind.
- A `full` observation tier.
- Cross-harness comparison claims. Two harnesses on one model are two rows;
  the site may show them side by side, and no p-value is attached.
