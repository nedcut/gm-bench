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
the loop. The per-episode limits default to 48 retries and 6 hours of
waiting (`--max-provider-stalls`, `--max-provider-stall-wait-seconds`,
recorded in `run.json` and the published row), long enough to wait out a
free-tier quota window; with the 600 s cap the 6-hour budget binds first, at
38 retries. Past either limit a stall is handled like any other exit. The wait is not phase-guard time: the driver
takes it off the open phase's clock (`AgenticEpisode.exclude_from_phase_clock`,
logged in the ledger as a `clock_pause` event that replay and the audit
ignore, and left out of the phase's recorded `seconds`), so only time a
harness was running counts toward the guard. Each nudge entry records
`stall_retry`, `backoff_seconds` and `provider_stall`, and `harness_run`
records `provider_stalls` and `provider_stall_wait_seconds`.

OpenCode's own server can also fail at startup: in two 8-seed container runs
of `opencode/space-bunny-free`, 9 of 16 episodes opened with a single
`error` event (`"name": "UnknownError"`, message "Unexpected server error.
Check server logs for details.") about a second after launch, before any
tool call, and the resumed session then played the whole episode. That
error is a provider stall (same backoff, budget and clock pause) only when
it ends an invocation that did nothing else first: no tool call, no model
text, no finished model step (a `step_start` alone is allowed). The same
error after the invocation acted goes through the nudge path as before: it
may come from the episode's own state and repeat, and each retry would
re-send the context. The first retry still waits the full 60 s; no quota is
spent while it waits. OpenCode gives the same error for persistent faults too
(a deprecated model, for one), which no wait fixes, so it is retried at most
3 times in a row (`MAX_STARTUP_SERVER_ERROR_RETRIES`, 60 + 120 + 240 s); a
fourth in a row ends the loop as an exhausted stall budget does, instead of
backing off for up to the six-hour stall budget.

`harness_run.exit_code` is the first launch's exit code, and
`harness_run.final_exit_code` the last invocation's (the first launch's when
there was no nudge, retry or resume); each nudge entry keeps its own
`exit_code`. `agentic-validate` warns on `final_exit_code`, so an episode
that recovered from a failed first launch does not warn. Runs recorded
before `final_exit_code` existed are read from `exit_code`, as before.

OpenCode retries a 429 inside the harness and prints nothing to its event
stream while it does, so a rate-limited harness can look hung rather than
end on an `error` event. A harness invocation that has appended no byte to
its event stream and made no ledger tool call for 240 s since launch
(`--silent-harness-seconds`, recorded in `run.json` and the published row;
0 disables it) is a **silent harness**: the driver stops it through the
same kill path as the phase guard and handles it as a provider stall, with
the same backoff, retry budget and clock pause. The silent window itself is
also taken off the open phase's clock (a `clock_pause` with reason
`silent_harness`). A silent stop is not a guard stop, a nudge, or a
no-progress relaunch. Silence is counted from launch, so a harness that has
emitted any event (a `step_start` for a slow first model call, say) is never
silent for the rest of that run; one that emits events and then stops
calling tools is left to the phase guard as before. A launch stopped as
silent before it opened a session is retried as a new session with the task
brief. The nudge entry records `silent`, and `harness_run` records
`silent_kills` (each is also one of `provider_stalls`).

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
  block. Tokens are in one shape for every harness (`token_shape:
  "inclusive-v1"`): `input_tokens` is the inclusive total,
  `uncached_input_tokens + cached_input_tokens + cache_write_input_tokens`;
  `output_tokens` includes reasoning, and `reasoning_tokens` is the part of
  it that was reasoning (never added on top). Codex already reports that
  way; OpenCode's step records put uncached input in `tokens.input` and
  leave reasoning out of `tokens.output`, so the parser adds cache reads and
  writes into input and reasoning into output, as T3 Code's OpenCode
  adapter does. Runs recorded before this shape carry no `token_shape` (their
  OpenCode input excludes cached tokens and their output excludes reasoning);
  they still validate, the site labels their tokens as the harness's own
  convention, and publication checks the sums only for shaped rows
- `harness_run`: the command (brief elided), first and final exit codes, timeout flag, wall
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
the retained `opencode-events.jsonl` (or `codex-events.jsonl`) equal the
replayed ledger's (the recorded agreement is checked against that recount,
not trusted), and the run's contract block matches this checkout's
`agentic_contract()`. Failed phases, timeouts, guard stops, and missing
telemetry are warnings: reported, never hidden, never fatal. A missing event
stream is a problem.

## Publishing a row

```bash
python -m gm_bench agentic-redact /tmp/agentic-space-bunny \
    --output results/agentic/opencode-1.18.31-space-bunny-free-smoke-8x5.json \
    --isolation container --public-seeds
python -m gm_bench agentic-validate results/agentic/opencode-1.18.31-space-bunny-free-smoke-8x5.json
python -m gm_bench agentic-validate results/agentic/opencode-1.18.31-space-bunny-free-smoke-8x5.json \
    --raw /tmp/agentic-space-bunny
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
`count`; `smoke` rows are exempt. A `panel` row also needs the run's `driver` block
to show the driver files (`gm_bench/agentic/provenance.py`) matched a
commit from start to end: `git_head` set, `git_driver_clean` true,
`changed_during_run` false. A run that is panel-sized but played on
uncommitted driver code redacts as `smoke`. Validating a row in a checkout
whose driver has since changed prints a warning with the row's commit, not
an error. On the site, a row is flagged `unpinned`
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
`--isolation container` runs the harness in Docker while the engine,
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

## Codex harness

```bash
python -m gm_bench agentic --harness codex --model gpt-5.5 --variant low \
  --codex-auth-file /path/to/codex-auth.json \
  --seeds 11 --seasons 1 --output /tmp/agentic-codex
python -m gm_bench agentic --harness codex --isolation container --model gpt-5.5 \
  --codex-auth-file /path/to/codex-auth.json \
  --seeds 11 --seasons 1 --output /tmp/agentic-codex-container
```

The Codex CLI is the second harness (`gm_bench/agentic/codex.py`, written
and tested against Codex CLI 0.156.1). It runs through the same episode loop
as OpenCode: same engine, proxy, sandbox check, nudges, provider-stall
retries, phase guard, ledger, and validation. A Codex row is its own row,
`codex/<version> · <model>`, never merged with an OpenCode row on the same
model.

**Cost.** Every Codex episode spends your OpenAI API budget or your ChatGPT
plan's Codex quota; there are no free models. Run it serially (the driver
has no parallel mode), smoke one short episode before a panel, and budget a
full panel as hours of quota. The driver is tested against a stand-in
`codex` and a stand-in `docker` (`tests/test_agentic_codex.py`), and two live
1-season smokes on `gpt-6-luna` (seed 11, same-user and container,
2026-09-24) closed all four phases. A five-season container smoke on seed
11 (2026-09-25) is committed at
`results/agentic/codex-0.156.1-gpt-6-luna-smoke-1x5.json`: score 232.5,
20/20 phases closed by the agent, no nudges or provider stalls, 134 tool
calls, 10.7 min, 13.0M input tokens, $0.18 at API prices. After it the
Codex five-hour quota window read 78% used; the run records only that end
reading, so check the window before a panel. The first panel-grade row,
the 32-seed private panel at five seasons in a container (2026-09-26), is
committed at `results/agentic/codex-0.156.1-gpt-6-luna-panel-32x5.json`:
mean 227.4, 640/640 phases closed by the agent, no nudges, provider stalls
or quota pauses, 10.3 min per episode, $4.54 at API prices for the panel.

What a run does per episode:

1. Stages the proxy exactly as for OpenCode, plus a Codex home holding one
   `config.toml` with a single entry, `[mcp_servers.gm-bench]`, whose
   `command` and `args` launch `gm_bench_proxy.py` on the harness's own
   `python3` with the socket path (or `host.docker.internal:<port>` in a
   container), and whose `default_tools_approval_mode = "approve"` approves
   that server's tools. Nothing else is configured. The approval key is
   required: exec mode never asks for approval, so under `workspace-write`
   Codex 0.156.1 would refuse every GM-Bench call (tools without a read-only
   annotation need approval) with "MCP tool call requires approval, but
   approval policy is never". It approves only this server.
2. Runs `codex exec --json --skip-git-repo-check --model <m>` with the task
   brief as the prompt and the scratch directory as the working directory,
   capturing `seed-<n>/codex-events.jsonl`. `--variant` becomes
   `-c model_reasoning_effort="<variant>"`. Exec mode never asks for
   approval.
3. Nudges and provider-stall retries run `codex exec resume <session id>
   <reminder>` on the same session (the id is the `thread_id` of the first
   `thread.started` event), so Codex keeps its context. `resume` accepts no
   `--sandbox` flag, so the sandbox is set with `-c` on every invocation.
4. A run whose last event is `turn.failed` or `error` with a retryable
   message (a 408, 425, 429 or 5xx status, "rate limit", "high demand",
   "at capacity", a dropped stream or connection, a timeout) is a provider
   stall; "Quota exceeded", a 401, or a full context window are not.
5. A run that ends on "You’ve hit your usage limit ... try again at <time>"
   is quota exhaustion, never a stall or a nudge (see Quota windows below).

What the harness does not inherit. Codex keeps its login, `AGENTS.md`,
skills, rules, plugins, and sessions under `CODEX_HOME` (default
`~/.codex`), and also loads skills from `~/.agents/skills`. Same-user runs
set `CODEX_HOME` to a private directory (mode 0700) outside the scratch,
removed when the episode ends even with `--keep-scratch`, and
`HOME=<scratch>`, and drop every other `CODEX_*` variable, so none of the
operator's Codex state reaches the agent and neither the credential nor
Codex's session logs sit in the agent's working directory.
A consequence: the harness's `python3` must not depend on `HOME` (a pyenv
shim would); use a system or Homebrew interpreter on `PATH`. In a container
the harness home is the per-episode volume (`/home/node/.codex`).

Sandbox. Same-user runs use Codex's `workspace-write` sandbox (commands can
write only the scratch directory and temp directories) with network access
on, the least permission that still lets the agent run code there; reads
are not confined, so same-user rows stay `smoke` grade exactly as OpenCode's
do. In a container Codex's own Linux sandbox cannot start (it needs user
namespaces, which Docker's default seccomp profile refuses), so it runs with
`danger-full-access` and the container is the sandbox: unprivileged user, no
capabilities, the egress firewall, and only the scratch directory and the
home volume mounted. `harness_run.sandbox_mode` records which.

Authentication. Because the host `~/.codex` is not used, the ChatGPT login
there is not inherited. Give the harness a credential deliberately:

- `--codex-auth-file <path>`: a Codex `auth.json`. An API-key file is
  `{"auth_mode": "apikey", "OPENAI_API_KEY": "sk-..."}`; a copy of a ChatGPT
  login's `~/.codex/auth.json` also works, but Codex may rotate its refresh
  token inside the episode, which can sign the host copy out. Keep the file
  outside the checkout and outside the run directory.
- Same-user only: `CODEX_API_KEY` in your environment, which `codex exec`
  reads. It is dropped when `--codex-auth-file` is given, so the file is
  what Codex uses.

Container runs pass no environment, so they need `--codex-auth-file`, and
the driver refuses to start without it. The file is written into the
episode's home volume by a throwaway `docker run -i` (no network, no
capabilities, only the volume mounted) that reads it as a tar stream on
standard input; it never appears on a command line, in an environment
variable, or in the bind-mounted scratch directory, and it is deleted with
the volume when the episode ends. In same-user runs it is copied to
`auth.json` (mode 0600) in the private `CODEX_HOME` and deleted with it
when the episode ends, even with `--keep-scratch`. The exposure is the same
as for the proxy secret: the agent can read its own harness's credential.
That is the harness's key, not the benchmark's; it gives no access to the
seed, the ledger, or the host. Anything the agent prints lands in the event
stream (`command_execution.aggregated_output`), so when the episode ends the
driver replaces every credential value (the file's `OPENAI_API_KEY` and
`tokens`, as staged and, same-user, as Codex left them after any refresh;
or the `CODEX_API_KEY` value) with `[REDACTED]` in `codex-events.jsonl` and
`codex-stderr.log`. A kept scratch directory is not redacted: it holds
whatever the agent wrote there. `harness_run.auth` records which source was
used (`auth-file` or `CODEX_API_KEY`), never the value.

The image. `gm-bench-agentic-codex:0.156.1-<Dockerfile hash>` is built on
first use from the same digest-pinned base and egress entrypoint as the
OpenCode image, with `@openai/codex@0.156.1` instead of `opencode-ai`; the
OpenCode image is unchanged. `run.json` records it under
`harness.container`, with `codex_version` as the image reports it.

Telemetry. `codex exec --json` reports a running token total per session on
`turn.completed` (input including cached, cached, cache writes, output,
reasoning), restored on resume, so the episode's tokens are the last total
of its session. A final invocation that fails before its turn completes is
not in that total. The stream reports no cost, no per-model-call records,
and no compaction events: `usage.cost_usd` is `null` and `cost_decisions`
0 (a ChatGPT plan is not billed per token, and Codex reports no charge),
so a Codex row publishes no cost; `api_calls` counts
completed turns (`usage.harness.api_calls_are`);
`max_output_tokens_per_call` is left out of the episode's usage; and
`compactions` is `null`, unmeasured, in the episode, the run's
`agentic_summary`, and the site row. GM-Bench tool calls are
`mcp_tool_call` items with `server` `gm-bench` and are counted as
`gm-bench_<tool>`; an item Codex refused before dispatching it (it
completes `failed` with an approval, "not available to the model",
"blocked by", or "user cancelled" message) never reached the server, so it
is counted under `usage.harness.tool_calls_skipped` instead. That keeps the
ledger-versus-harness check honest: calls the agent made by running the
proxy from a shell are in the ledger but not in the harness count, and the
check fails. `agentic-validate` recounts them from the retained
`codex-events.jsonl` against the replayed ledger. The staged config
is kept as `harness_run.harness_config`.

API-equivalent cost estimate. Beside the unmeasured cost, a Codex episode
records what its tokens would have cost on the OpenAI API at list price,
the figure other tools show for a subscription run:

- `usage.harness.api_equivalent_cost_usd`: uncached input (`input_tokens`
  minus cached minus cache-write tokens, since Codex reports both inside
  `input_tokens`) at `input_per_mtok`, cached input at
  `cached_input_per_mtok`, cache writes at `cache_write_per_mtok`, and
  output at `output_per_mtok`. Reasoning is not added again: Codex copies
  the Responses API's `output_tokens`, which already includes reasoning.
  Prices come from `gm_bench/pricing.json` (or a `GM_BENCH_PRICING`
  override) by exact id, then longest prefix; a provider default never
  applies. An unpriced model, or an episode with no usage, gets `null`.
- `cost_basis: "api-list-price-estimate"`, `billed_by_harness: false`, and
  `pricing_source` (`key` matched, the entry's `verified` date, and whether
  cached input and cache writes were priced at their own rates or, when the
  entry has none, at the input rate).
- `long_context_requests_possible`: OpenAI prices a request with more than
  272K input tokens (`long_context_input_tokens` in the entry) at 2x input
  and cache rates and 1.5x output. Codex reports running totals per turn,
  and a turn can make several model requests, so per-request size is not
  observable. The estimate always uses short-context rates, and this flag
  is `true` when some turn's input grew by more than the threshold (some
  request may then have been billed at the long-context tier, so the
  estimate may be low), `false` when no turn did (so no request can have),
  and `null` when the entry names no threshold.

What it is not: a bill, a measured cost, or a number comparable to an
OpenCode row's `cost_usd`. It ignores Batch, Flex, Fast mode, and regional
processing prices, and it is only as current as the entry's `verified`
date. It never feeds `cost_usd` or `cost_decisions`. The run's
`agentic_summary` sums it over the episodes that have one
(`api_equivalent_cost_usd`, `api_equivalent_cost_episodes`,
`api_equivalent_long_context_possible`); the compact artifact keeps the
episode fields; and the site shows the cost cell as `$0.123 est.` with the
basis in its tooltip when a row has an estimate but no billed cost, or
`unmeasured` when it has neither. The site data check rejects a row whose
estimate equals its billed `cost_usd`.

Quota windows. `codex exec --json` carries no rate limits, but Codex writes
each `token_count` event, with the account's rate-limit snapshot, to the
session rollout (`CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`). Once
per episode, after the last invocation and before the private
`CODEX_HOME` (or, in a container, the home volume) is removed, the driver
reads those lines (in a container, through a throwaway `docker run` with no
network that prints only the `token_count` lines) and records
`harness_run.quota_windows` (`window_minutes`, `used_percent`,
`resets_at_utc`) and `harness_run.plan_type`. Only the main allowance
counts (`limit_id` `codex` or absent); later snapshots update earlier ones
field by field, the rule T3 Code uses. Credits, balances, tokens and
everything else in the rollout are never recorded. An API-key login
reports no windows, so the list is empty. Compressed (`.jsonl.zst`)
rollouts are skipped; Codex compresses only cold sessions, and each
episode's home is new.

Quota exhaustion. The subscription window can also run out mid-panel, and
then the first signal is the message itself: `You’ve hit your usage limit.
... try again at Sep 24th, 2026 4:19 PM.` (on the first real launch this
was the very first turn). Codex writes that time in the Codex process's
local zone (`%b %-d<suffix>, %Y %-I:%M %p`, or only `%-I:%M %p` when the
reset is later the same day, or "try again later" when it does not know).
The driver matches `\busage limit\b` (case-insensitive) in the last
`turn.failed` or `error` message and reads the time with

```
try again at\s+(?:(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4}),?\s+)?(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<meridiem>[AaPp])\.?\s*[Mm]\.?
```

(case-insensitive), in the host's zone for same-user runs and UTC in a
container, which sets no `TZ`; anything it cannot read is an unknown reset.
Then:

- if the reset plus 60 seconds is in the future and within
  `--max-provider-stall-wait-seconds` (less any quota pause already taken
  in the episode), the driver prints a `quota_exhausted` progress event
  (`action: pause`), sleeps until then with the open phase's clock
  paused as for a stall, records the pause in `harness_run.quota_pauses`
  (season, phase, reset, wait) and resumes the same session. That
  relaunch is marked `quota_resume` in `harness_run.nudges` and counts
  neither as a nudge nor as a stall retry;
- otherwise (reset unknown, already past, or too far off) the episode stops
  at once: the phases left open are closed as when the harness exits, and
  `harness_run.ended_by_quota` records `{"reset_at_utc", "message_class":
  "usage_limit"}`. `run_panel` then starts no further seed, since each
  would fail the same way, and `run.json` records `stopped_for_quota`
  (`after_episode`, `episodes_not_run`, the reset). Such a run lists more
  seeds than episodes and does not validate for publication; rerun it
  after the reset.

In-episode pauses are also listed in the run's `quota_pauses` with their
`episode` position. The windows read from the rollout still apply
separately, before an episode starts.

Before the next episode, if a window of the last one is at or above
`QUOTA_PAUSE_PERCENT` (95) used, `run_panel` sleeps until that window
resets plus 60 seconds (the latest such reset when several are exhausted),
never longer than `--max-provider-stall-wait-seconds`, prints a
`quota_pause` progress event, and records the pause in `run.json`
`quota_pauses` (`after_episode` by position, never seed, `window_minutes`,
`used_percent`, `resets_at_utc`, `wait_seconds`, and `capped` when the
bound cut the wait short). The windows and pauses reach the compact
artifact, and the site row's notes carry a short quota line (plan, peak
use of a window, pauses).

The Keychain panel launcher passes `--harness codex` and
`--codex-auth-file` through unchanged.

## Claude Code harness

```bash
python -m gm_bench agentic --harness claude --model claude-sonnet-5 \
  --claude-token-file /path/to/claude-token \
  --seeds 11 --seasons 1 --output /tmp/agentic-claude
```

The Claude Code CLI is the third harness (`gm_bench/agentic/claude.py`,
written against Claude Code 2.1.281). It runs through the same episode loop
as OpenCode and Codex. A Claude row is its own row, `claude/<version> ·
<model>`.

**Status: same-user and container runs have been smoked live** (one
season of `claude-sonnet-5` on seed 11 each, 2026-09-24; the container
episode scored 118.9 with no config-directory findings and no credential
in any saved file). A five-season container smoke on seed 11 (2026-09-25)
is committed at `results/agentic/claude-2.1.281-claude-sonnet-5-smoke-1x5.json`:
score 248.0, 20/20 phases closed by the agent, no nudges, provider stalls or
compactions, 180 tool calls, 19.8 min, 16.8M input tokens, $5.05 at API
prices. No panel-grade Claude row exists yet. Every Claude episode spends your Claude subscription's
quota (or API money with `ANTHROPIC_API_KEY`). Run it serially (the driver
has no parallel mode), smoke one short episode before a panel, and budget a
full panel as hours of quota.

Same-user rows are `smoke` grade. A panel-grade Claude row needs
`--isolation container` (below).

What a run does per episode:

1. Stages the proxy exactly as for OpenCode, plus a private
   `CLAUDE_CONFIG_DIR` (mode 0700, outside the scratch, removed at episode
   end even with `--keep-scratch`) holding one `mcp.json` with a single
   stdio server, `gm-bench`, that launches `gm_bench_proxy.py` on the
   harness's own `python3` with the socket path. `HOME` is the scratch
   directory, and every other `CLAUDE_*`, `CLAUDECODE` and `ANTHROPIC_*`
   variable is dropped. `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` stops
   the auto-updater (a harness that upgrades itself mid-panel changes the
   row identity), telemetry and error reports.
2. Runs `claude -p --output-format stream-json --verbose --mcp-config
   <private>/mcp.json --strict-mcp-config --setting-sources user
   --disable-slash-commands --tools
   Bash,Read,Edit,Write,Glob,Grep,NotebookEdit,ToolSearch --allowedTools
   mcp__gm-bench,Bash,Read,Edit,Write,Glob,Grep,NotebookEdit
   --permission-mode dontAsk --permission-prompts none --model <m> --
   <brief>` in the scratch directory, capturing
   `seed-<n>/claude-events.jsonl`. `--variant` becomes `--effort <level>`.
   The prompt follows `--` because `--mcp-config` and `--allowedTools` take
   variadic values.
3. Nudges, provider-stall retries and quota resumes run the same command
   with `--resume <session id>`, the `session_id` of the latest
   `system/init` event, so Claude Code keeps its context.

What that flag set keeps out. `--tools` limits the built-in tools the model
is shown to the code tools and ToolSearch, so it is never offered web,
subagent, workflow or scheduling tools that `dontAsk` would then deny (the
first live smoke showed all of them in the tool list).

Deferred game tools are kept on purpose. Claude Code shows MCP tools by
name only and the model calls ToolSearch to load a tool's schema before
its first use, where OpenCode and Codex put every schema in the first
prompt. That lookup is part of Claude Code as shipped, and this lane
measures each harness as its users run it, so tool search is left at
Claude Code's default rather than turned off for parity; its cost, if any,
counts against the harness. ToolSearch calls appear in
`harness.tool_events` and the run records `visible_tools`.

`--strict-mcp-config` loads only the staged
server, never your own MCP servers. The private config directory means none
of your `~/.claude` settings, login, `CLAUDE.md`, skills, plugins, hooks,
auto memory or sessions reach the agent. `--setting-sources user` reads
only that empty private directory, so a `.claude/settings.json` the agent
writes into its scratch directory is not loaded on the next resume.
`--disable-slash-commands` removes every skill and custom command, bundled
ones included. Machine-wide managed settings, if an administrator installed
any, still apply. `--bare` is not used because it ignores the subscription
token.

Permissions. `dontAsk` with that allow list runs the GM-Bench tools and the
code tools without a prompt and denies everything else (web fetch and
search, any other MCP server) at once, recording it in the result's
`permission_denials`; `--permission-prompts none` tells Claude not to retry
a denied call. `bypassPermissions` was not used: it turns off the
permission layer for every tool, which Claude Code's documentation
recommends only for sandboxes without internet access. Neither mode
confines reads or shell commands to the scratch directory (a bare `Bash`
rule allows any command), so same-user rows stay `smoke` grade exactly as
OpenCode's and Codex's do.

Authentication. The private config directory also means your `/login`
credential (in the macOS Keychain, keyed to the config directory) is not
found and never read. Give the harness one credential deliberately:

- `--claude-token-file <path>`: a file holding one token from `claude
  setup-token`, a one-year OAuth token that draws on your Claude
  subscription and can only make model requests. The driver hands it to
  the harness as `CLAUDE_CODE_OAUTH_TOKEN`. Keep the file outside the
  checkout and the run directory, mode 0600.
- Same-user without the file: `CLAUDE_CODE_OAUTH_TOKEN` from your
  environment, or else `ANTHROPIC_API_KEY` (API billing). Only one is
  passed; with both set, the subscription token wins.

The trade-off: the token is a long-lived bearer credential for your
subscription, separate from your interactive login and not rotated by the
run, and it sits in the harness's environment, which the agent's shell can
print. That is the harness's credential, not the benchmark's; it gives no
access to the seed. When the episode ends the driver replaces its value
with `[REDACTED]` in `claude-events.jsonl` and `claude-stderr.log`; a kept
scratch directory is not redacted. `harness_run.auth` records the source
(`token-file`, `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`), never the
value.

Telemetry. GM-Bench calls are `tool_use` blocks named
`mcp__gm-bench__<tool>`, counted once per tool-use id as
`gm-bench_<tool>`; a call Claude Code denied (`permission_denied`, or
`permission_denials` on the result) never reached the server and is
counted under `usage.harness.tool_calls_skipped`. Tokens come from the
result's `modelUsage` (every model call, subagents and compaction
included); since Claude Code 2.1.277 a resumed session's result carries the
session's whole total, so the episode uses the last result per session
(a sum on older versions). An invocation that was killed (phase guard,
timeout, parked quota stop) writes no result, so its input and cache
tokens are recovered from its assistant messages, once per message id; its
output is only a lower bound there, and `usage.harness.usage_complete` is
false. `api_calls` counts distinct assistant message ids (API responses),
compactions are counted from `compact_boundary`, and
`max_output_tokens_per_call` is left out.

Cost. `total_cost_usd` is Claude Code's client-side estimate, not a bill,
and a subscription is not billed per token, so `usage.cost_usd` is `null`
as for Codex. `usage.harness.api_equivalent_cost_usd` prices each model in
`modelUsage` at its `pricing.json` entry (for example `claude-sonnet-5`,
with cached input at the cached rate), labelled
`api-list-price-estimate` and `billed_by_harness: false`; any unpriced
model with tokens leaves it `null`. On a subscription Claude Code writes
1-hour cache entries, which Anthropic prices at 2x input rather than the
5-minute 1.25x. `modelUsage` does not split the two, but each assistant
frame's `usage.cache_creation` does, so each model's 1-hour share of its
frame writes is priced at `cache_write_1h_per_mtok` (the entry's
`cache_write_per_mtok` when it has none, labelled in
`pricing_source.cache_write_1h_rate`). On three live `claude-sonnet-5`
smokes this matched Claude Code's own figure to the microdollar. Claude
Code's own figure is kept as
`usage.harness.harness_cost_estimate_usd` for comparison only.

Stalls and quota. A failed result with a 408, 425, 429, 5xx or 529 status,
an `overloaded`, `rate_limit` or `server_error` assistant error, or a
transient message ("Repeated 529 Overloaded errors", "Request timed out",
...) is a provider stall. A spent subscription window is a
`rate_limit_event` with `status: rejected` (not covered by overage) or a
message such as "You've hit your session limit"; the reset comes from the
event's `resetsAt`. The loop then pauses until the reset and resumes, or
stops the episode and the panel, exactly as for Codex's usage limit;
"Credit balance is too low" stops them too. Claude Code can wait inside
the process for a rejected window to reset instead of exiting, so the
loop also polls the running invocation and stops it when a rejection is
open and no result has arrived; that stop is a quota pause, not a guard
kill. The streamed windows (utilization and reset per `rateLimitType`)
are recorded as `harness_run.quota_windows` and drive the between-episode
pause at 95% used.

The config directory between invocations. The agent's shell runs as the
same user as Claude Code, so between two invocations it could write a
`settings.json` (hooks, an `env` block such as `ANTHROPIC_BASE_URL`,
permission rules), a `CLAUDE.md` or a `rules/` file into
`CLAUDE_CONFIG_DIR`, and `--setting-sources user` would load it on the next
resume. In same-user runs the driver removes those entries
(`settings.json`, `settings.local.json`, `CLAUDE.md`, `CLAUDE.local.md`,
`rules`, `agents`, `commands`, `skills`, `output-styles`, `hooks`) and
rewrites `mcp.json` before every invocation, and lists what it removed in
`harness_run.config_dir_findings`. An agent process left running in the
background could still race that, one more reason same-user rows are smoke
grade. Container runs close the gap instead (below).

### Claude Code in a container

```bash
python -m gm_bench agentic --harness claude --isolation container \
  --model claude-sonnet-5 --claude-token-file /path/to/claude-token \
  --seeds 11 --seasons 1 --output /tmp/agentic-claude-container
```

The image. The driver builds
`gm-bench-agentic-claude:2.1.281-<Dockerfile hash>` the same way as the
OpenCode and Codex images (same digest-pinned base, `python3` for the
proxy, `gmb-egress` firewall entrypoint, unprivileged `node` user), with
`@anthropic-ai/claude-code@2.1.281`. It refuses to run if the image reports
a different Claude Code version. On top it adds the `gmb-claude` launcher
and a root-owned config layout (below). With the base layers cached from the
OpenCode image the build took 14 s on the maintainer's machine. `run.json`
records the image tag, image id, base image, Dockerfile SHA-256,
`claude_version`, Docker server version and egress rule under
`harness.container`, as for the other harnesses, so a container Claude row
can be panel grade under the existing publication rules. `--binary` is
ignored.

Authentication. The container gets no environment, so
`--claude-token-file` is required; there is no fallback to
`CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`. The token travels on the
stdin of a throwaway `docker run` (no network, no capabilities, only the
home volume mounted) into the episode's home volume as
`/home/node/.gmb-claude-token`, mode 0600, and is removed with the volume.
Each invocation runs `gmb-claude`, which reads that file, exports it as
`CLAUDE_CODE_OAUTH_TOKEN` with `CLAUDE_CONFIG_DIR=/home/node/.claude` and
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, and execs `claude` with the
driver's arguments. The token is never on the `docker run` command line or
in a `-e` variable, so neither `ps` on the host nor `docker inspect` shows
it; the only credential-bearing thing that leaves the host process is that
tar stream. As in same-user runs the agent's shell can print it, and it is
redacted from `claude-events.jsonl` and `claude-stderr.log` at episode end.
`harness_run.auth` is `token-file` and `harness_run.credential_handoff`
says how it travelled.

The MCP config is passed inline (`--mcp-config '{"mcpServers": ...}'`), not
as a file, so no file the agent can write holds it. It names only
`python3`, `gm_bench_proxy.py` and `host.docker.internal:<port>`; the proxy
secret stays in the scratch file beside the proxy as for the other
harnesses.

The config directory. The home volume is writable by `node`, which is both
Claude Code and the agent's shell, so the image makes
`/home/node/.claude` root-owned, sticky and world-writable (mode 1777),
with root-owned read-only placeholders: an empty `{}` `settings.json`,
empty `settings.local.json`, `CLAUDE.md` and `CLAUDE.local.md`, and empty
mode-0555 `rules`, `agents`, `commands`, `skills`, `output-styles` and
`hooks` directories. Docker copies that layout, owners and modes included,
into each new volume. Claude Code can still create its transcripts,
`.claude.json`, backups and caches there (checked against the real image:
`claude mcp list` starts cleanly with no network), but the agent cannot
write, replace, remove or fill a placeholder. It can still rename the whole
directory away, because that needs only write access to the home, so
before every invocation `gmb-claude` checks the layout (owner, mode, type,
empty placeholders, `settings.json` still `{}`) and refuses to start Claude
Code on any change, exiting 96 with a `gmb-claude: refused:` line on stderr.
That invocation then writes no events, so the episode ends without a
further nudge, and the refusal is listed in
`harness_run.config_dir_findings`. No agent process survives between
invocations, because each one is its own `docker run --rm` whose processes
end with it. Machine-wide managed settings are not installed in the image.

What does not fit the shared interface, and was added to it: the park
poll (`HarnessDriver.invocation_parked`, used only when
`polls_for_park` is set), and a hook that runs before every invocation
(`HarnessDriver.before_invocation`, the same-user config re-stage).

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
only the result. A run first refuses to start while any driver or contract
file differs from `HEAD` (or the checkout is not a git work tree), before it
touches the Keychain: commit the change, so the row names a commit that
replays it. It then checks the same digests, refuses to start until the
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
python3 -c 'import secrets; print((1 << 32) + secrets.randbelow((1 << 63) - (1 << 32)))' \
    | python scripts/agentic_red_team.py --model opencode/big-pickle --output /tmp/red-team-container \
    --isolation container
```

Pipe in a fresh seed from the private-panel range, 2**32 to 2**63 - 1; the
script refuses any other. The simulator source is public, so an agent with
web access can download it, rebuild leagues offline, and test candidate
seeds against what `get_status` shows. A small or documented seed falls to
that (a 2026-09-24 probe found the example seed this section used to
print, after recognising the probe's brief in the public script), which
says nothing about a panel seed. A large seed also keeps the
seed-in-output flags from matching `python3.11`, protocol dates and team
ids in ordinary shell output. The report lists every hit with the text
around it (`seed_matches`) so a match can be checked.

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
- `tests/test_agentic_codex.py`: the Codex driver against a stand-in `codex`
  that launches the proxy from the staged config and makes real tool calls
  (ledger equals harness events, a nudge and a stall retry by `exec
  resume`), no host Codex state in the harness, the tool-approval key (the
  stand-in refuses every call without it, as Codex does, and the
  agreement check then fails on shell-driven proxy calls), credential
  redaction from the run directory, no billed cost or compaction count
  published for Codex and the API-equivalent estimate kept apart from it, the event parser and stall rule, the Codex image, the container
  auth hand-off (only in the volume, never on a command line) against a
  stand-in `docker`, and CLI dispatch
- `tests/test_agentic_claude.py`: the Claude Code driver against a stand-in
  `claude` that launches the proxy from the staged `--mcp-config` and makes
  real tool calls (ledger equals harness events, a nudge and a stall retry
  by `--resume`), the exact flag set, no host Claude state or variables in
  the harness, the session's running token total, per-model API-equivalent
  estimate and no billed cost, usage-limit pause and stop, a parked
  invocation stopped and paused rather than guard-killed, a silent harness,
  credential redaction, the same-user config re-stage, container runs
  against a stand-in `docker` that runs the image's real `gmb-claude`
  launcher (the token only in the home volume, never in argv or `-e`,
  inline MCP config, redaction, refusal on a changed config directory, the
  run record and a `container` artifact), CLI dispatch and a Docker that is
  not running; with `GM_BENCH_DOCKER_TESTS=1`, the real Claude image (egress
  canary, `docker inspect`, and the config layout under attack, running
  only `claude --version`)
- `tests/test_agentic_conformance.py`: the server driven by the official
  `mcp` SDK client (dev extra; skipped when not installed)
- `tests/test_agentic_publication.py`: the compact artifact is bound to its
  raw run, redacted, graded by the spec's rules, and rejects drift or
  tampering
- `tests/test_bench_v2_panel.py`: the committed 32-seed lane is internally
  consistent and extends the `sota-v5` panel, the Keychain launcher refuses
  an escrow that misses any digest, and seeds stay off command lines,
  environment variables, and progress output
