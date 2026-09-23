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
   an MCP server over a private Unix socket (or, with `--isolation
   container`, a loopback TCP port; see "Running the harness in a container"
   below). The seed is never written where the agent could find it; the only
   copy on disk is the ledger header under `--output`, a directory the agent
   is never told about.
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

A run that ends on a retryable provider error (the last event is an `error`
with `isRetryable`, a 408/425/429/500/502/503/504 status, or a rate-limit,
overload or try-again-later message) is a **provider stall**, not the agent
stopping: the driver waits 60 s, doubling per consecutive stall up to 600 s,
then resumes the session with the same reminder. A stall retry does not
spend a nudge, and a retry that stalls again without a tool call does not end
the loop; after 8 retries or 45 minutes of waiting in an episode a stall is
handled like any other exit. The wait is not phase-guard time: the driver
takes it off the open phase's clock (`AgenticEpisode.exclude_from_phase_clock`,
logged in the ledger as a `clock_pause` event that replay and the audit
ignore, and left out of the phase's recorded `seconds`), so only time a
harness was running counts toward the guard. Each nudge entry records
`stall_retry`, `backoff_seconds` and `provider_stall`, and `harness_run`
records `provider_stalls` and `provider_stall_wait_seconds`.

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
  provider stalls and the backoff waited for them,
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
more seeds, redacted seeds, and `separate-user` or `container`. The driver
records what it actually launched (`isolation` in `run.json` and in every
episode's `harness_run`), and redact refuses a claim stronger than that
record: a `container` run may be published as `container` or understated as
`same-user`, a same-user run (or one written before the driver recorded
isolation) only as `same-user`. No driver launches `separate-user` yet, so
that level cannot currently be claimed. The redact command refuses to write
anything that would not validate. CI re-validates every file under
`results/agentic/` against the checkout's contract. A
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
are constants every panel row shares. Those means are pinned under
`reference_scores.mean_scores` in `config/bench_v2_lane.json`: pick-trader
249.18 and random 90.367, computed on 2026-09-23 directly on the escrowed
32-seed panel at 5 seasons, uncached and in-process, with only the two
aggregates printed. `agentic-validate`, the site build, and the site data
check reject a 5-season panel row whose reference or floor mean differs.
For any other season count nothing is pinned: validation warns that the
reference is unpinned, and the site build and data check require every
panel row at that season count to agree.

## Running the harness in a container

```bash
python -m gm_bench agentic --isolation container --model opencode/big-pickle \
  --seeds 11 --seasons 1 --output /tmp/agentic-container
```

Panel grade needs the harness separated from the driver, because on a
same-user machine the agent's shell can run `ps`, read the driver's
`--seeds`, and follow it to the run directory and the checkout.
`--isolation container` runs the OpenCode harness in Docker while the engine,
the seed, and the ledger stay in the driver process on the host
(`gm_bench/agentic/container.py`).

Requirements: Docker Desktop (tested on macOS with Docker 29.3.1) with the
daemon running, and network access for the first image build and for the
model provider. No Docker Desktop setting needs changing: `/var/folders`
temp directories are shared by default, and `host.docker.internal` reaches
the host loopback out of the box.

The image. On the first run the driver builds
`gm-bench-agentic-opencode:<opencode version>-<Dockerfile hash>` from a
Dockerfile it pipes to `docker build` (no build context): a digest-pinned
`node:22-bookworm-slim` base, Debian's `python3` for the proxy, `procps`,
`iptables` for the egress rule, the `gmb-egress` entrypoint, and
`opencode-ai@1.18.31`. It refuses to run if the image reports a
different OpenCode version. `run.json` records the image tag, image id
(the content digest of what ran), base image, Dockerfile SHA-256, OpenCode
version, Docker server version, and the egress rule under
`harness.container`, and that block is carried into the published
artifact. `--binary` is ignored in container
mode.

Authentication. The free `opencode/*` models need no credentials: OpenCode
1.18.31 on the host stores none for them (`opencode auth list` shows 0
credentials) and the container lists and runs them anonymously. Nothing is
provisioned. A model that needs a provider key is not supported in container
mode yet; do not mount `~/.config/opencode` or the home directory to get
one, because that directory's `AGENTS.md`, skills and commands would change
what the harness plays with. The harness's only configuration is the staged
`opencode.json`.

What the container can see:

- its own processes only (separate process namespace; `ps` shows the harness,
  the proxy, and whatever the agent started);
- `/work`, the episode's scratch directory bind-mounted from the host,
  holding only `gm_bench_proxy.py`, `gm_bench_proxy.secret`, and
  `opencode.json`;
- its home, a per-episode Docker volume (`gmb-home-<random>`), so OpenCode's
  session store survives from the first run to each nudge's `--session`
  resume. The volume is deleted when the episode ends, so nothing carries to
  the next episode;
- the public internet (for the model provider) and DNS, and on the host
  only the driver's port through `host.docker.internal`. See "Egress"
  below.

What it cannot see: host processes (including the driver's command line),
the checkout, the run directory, the ledger, the seed, the host environment
(no `-e` is passed), host OpenCode configuration or credentials, any other
service on the host loopback, and anything on a private network. Each
invocation starts as root in the image's `gmb-egress` entrypoint with only
`NET_ADMIN`, `SETUID`, `SETGID` and `SETPCAP` (every other capability
dropped, `no-new-privileges`), installs the egress rule, then drops to the
unprivileged `node` user with an empty capability set and bounding set
before OpenCode starts, so the agent cannot change the rule.

The transport. Docker Desktop cannot pass a host Unix socket through a bind
mount (the connect fails with `ENOTSUP`), so in container mode the driver's
server listens on `127.0.0.1` on an ephemeral port and the proxy dials
`host.docker.internal:<port>`. Any local process can dial a loopback port,
so every connection must first send a per-run random secret, which the
driver writes to `gm_bench_proxy.secret` in the scratch directory (mode
0600) and never onto a command line; a connection without it is closed
unserved and counted as `proxy_connections_refused` in `harness_run`. The
agent can read the secret, which gives it nothing the proxy does not
already give it: every call it makes lands in the ledger, and a call that
bypasses the harness shows up as a ledger-versus-harness disagreement.
Same-user runs keep the Unix socket.

Egress. Without a rule, `host.docker.internal` reaches every service on
the host loopback, not only the driver's port. A review red-team run did
exactly that: the agent port-scanned the host gateway and read an Ollama
API, an agent server's UI, and a tunnel's metrics and config. So
`gmb-egress` installs `iptables` rules in the container's own network
namespace before the harness starts: loopback inside the container,
the driver's port on the host gateway, and DNS to the container's
resolvers are allowed; the host gateway on any other port, every private,
loopback, link-local, carrier-grade NAT and multicast IPv4 range, and all
non-loopback IPv6 are rejected; the public internet is open for the model
provider. Before every episode the driver opens a canary listener on the
host loopback and runs the entrypoint with a probe: the episode does not
start if the canary is reachable, or if the harness would run as root or
keep any capability. Checked on Docker Desktop for macOS without a model:
7 host-loopback services were reachable from the unfirewalled image and
none from this one, and the proxy still reached the driver. The rule is
recorded as `harness.container.egress`. It does not stop the agent from
reaching the public internet, which is the harness's own model traffic.

Cleanup. A guard stop or timeout kills the `docker run` client and then
removes the container by name, because killing the client alone leaves the
container running. At the end of the episode every container and the home
volume are removed, each attempted even if an earlier `docker` call failed
or hung past its 60-second timeout, and the scratch directory (which holds
the secret) is always deleted. Anything `docker` could not remove is listed
in `harness_run.container_cleanup_problems` and on stderr; the episode's
result is still written.

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
echo 730541 | python scripts/agentic_red_team.py --model opencode/big-pickle --output /tmp/red-team
echo 730541 | python scripts/agentic_red_team.py --model opencode/big-pickle --output /tmp/red-team-container \
    --isolation container
```

Use a distinctive public seed of at least six digits (the script refuses a
shorter one): a seed such as 11 matches `python3.11`, protocol dates and
team ids in ordinary shell output, so the seed-in-output flags would be
true on any run where the agent does anything. The report lists every hit
with the text around it (`seed_matches`) so a match can be checked.

Launches the harness exactly as a run does, but with a brief that tells the
agent to find the seed by any means. The report lists every shell command
the agent ran, whether the seed appeared in its output, and whether any
output showed the driver (the red-team script's name or the checkout path).
Expect `SEED FOUND` on a same-user machine: `ps` shows the driver's command
line. Expect `SEED NOT FOUND` only when the harness runs as another user or
in a container.

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
  client, server restart, sandbox checks, event parsing, the TCP transport
  and its secret (including which dials count as refused), admission after
  stop, the container launch command and its egress probe, and cleanup
  when `docker` hangs (against a stand-in `docker`)
- `tests/test_agentic_conformance.py`: the server driven by the official
  `mcp` SDK client (dev extra; skipped when not installed)
- `tests/test_agentic_publication.py`: the compact artifact is bound to its
  raw run, redacted, graded by the spec's rules, and rejects drift or
  tampering
- `tests/test_bench_v2_panel.py`: the committed 32-seed lane is internally
  consistent and extends the `sota-v5` panel, the Keychain launcher refuses
  an escrow that misses any digest, and seeds stay off command lines,
  environment variables, and progress output
