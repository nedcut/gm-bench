# Running the agentic lane (GM-Bench 2.0)

The frozen decisions are in `docs/bench_v2_spec.md`. This page is the
operator's view: what a run does, what it writes, and how to read it.

## What happens in a run

```bash
python -m gm_bench agentic --harness opencode --model opencode/space-bunny-free \
  --seeds 11 12 --seasons 5 --output /tmp/agentic-space-bunny-dev
```

The examples on this page use `opencode/space-bunny-free`, the free
OpenCode model behind the committed smoke row. Free `opencode/*` models come
and go and have quotas: `opencode/big-pickle`, used in the early smokes,
exhausted its free quota before the contract freeze. Run `opencode models`
to see what is free today, and substitute.

For each seed, serially:

1. The driver builds the episode engine in its own process and serves it as
   an MCP server over a private Unix socket (or, with `--isolation
   container`, a loopback TCP port; see "Running the harness in a container"
   below). The seed is never written where the agent could find it; the only
   copy on disk is the ledger header under `--output`, a directory the agent
   is never told about.
2. It creates an empty scratch directory holding a standard-library proxy
   script (`gm_bench_proxy.py`, copied from `gm_bench/agentic/_proxy.py`), a
   standard-library launcher (`gm_bench_opencode_launch.py`, from
   `gm_bench/agentic/_opencode_launch.py`), and an `opencode.json` that
   launches the proxy on the harness's own `python3` with the socket path as
   its only argument, with code mode off so each model tool call is one
   ledger entry, and denies the `execute` permission so OpenCode offers no
   Code Mode tool at all.
3. It checks the sandbox and refuses to start if the scratch directory sits
   under a GM-Bench checkout or if `python3` on the harness's `PATH` can
   `import gm_bench`. The harness environment is the operator's minus every
   `GM_BENCH_*` variable, Python path overrides, and the virtualenv. A
   same-user OpenCode run also gets a private home (mode 0700, outside the
   scratch, removed at episode end): `HOME` and every `XDG_*` base
   directory point into it and every `OPENCODE_*` variable is dropped.
   Otherwise OpenCode reads the operator's `~/.config/opencode/AGENTS.md`
   and the skills in `~/.agents/skills` and `~/.claude/skills`, and puts
   them in the prompt (see "The prompt check" below).
4. It runs `opencode run --format json --auto --model <model>` through the
   launcher in the scratch directory, on a private server whose MCP servers
   have connected (see "OpenCode 2.x" below), with the task brief from
   `gm_bench/agentic/brief.py` as the message, and captures the event
   stream to `seed-<n>/opencode-events.jsonl`.
5. When the harness exits, the driver rebuilds the episode from
   `seed-<n>/ledger.jsonl`, closes any phase the agent left open as a failed
   decision, joins the harness's token and cost telemetry, scores, and writes
   `seed-<n>/result.json`. The run-level `run.json` carries every episode,
   the usual `summary` block, and an `agentic_summary`. Evidence paths in
   `harness_run` are relative to the run directory, so the directory can be
   moved and still validate.

### OpenCode 2.x

The driver supports OpenCode 2.x only (2.0.27 in the container image).
Rows played on 1.18.31 still validate: each row records the driver commit
that played it. What changed from 1.18, read from the 2.0.27 source and
checked against the binary on 2026-10-12:

- `opencode run` no longer accepts `--pure`, `--dir` or `--variant`; given
  any of them it prints its help and launches nothing. A variant is now
  part of the model, `--model provider/model#variant` (`--variant` on the
  CLI is passed that way).
- `run` attaches to a shared background service by default. Each driver
  invocation gets a private server of its own instead, started in the
  scratch directory with the episode's private home; no episode shares a
  server or a session store with another, or with the operator's own
  OpenCode. `--session <id>` resumes from the session store in that home,
  so nudges keep their context.
- `run --standalone` starts that private server and sends the prompt at
  once, while the server is still connecting its MCP servers in the
  background, and each model request offers the tools of the servers
  connected by then (`MCP.tools` does not wait for a server's start-up;
  `MCP.callTool` does; unchanged in 2.0.28). The GM-Bench proxy takes most
  of a second to connect, so the first model request of every invocation
  (the brief, and every nudge or stall resume) went out without the
  GM-Bench tools. The deepseek-v4.1-flash panel played on 2.0.27 on
  2026-10-13 shows it: almost every episode opens with the agent probing
  Code Mode's `execute` (148 calls, every one answered "Unknown tool"),
  the shell and the scratch files for tools that were not there yet, then
  finds them on its second step. So each `run` goes through the staged
  launcher: it starts `opencode serve --hostname 127.0.0.1 --port 0` with a
  password of its own, polls `GET /api/mcp` until no MCP server is
  pending, refuses to go on (exit 1, on stderr) if one failed to connect or
  60 s pass, and only then runs `opencode run --server <url>` with the
  driver's arguments. OpenCode keeps `OPENCODE_SERVER_PASSWORD` and
  `OPENCODE_PASSWORD` out of the environment of the processes it starts, so
  the agent's shell does not see the password. The server goes when the
  client exits, when the launcher is signalled, and, through a guard
  process the launcher forks, when the launcher is killed outright (as a
  same-user harness is on a timeout or a stall). `session export` and
  `auth import` still run `--standalone`: they need no MCP server.
- Code Mode: `codemode: false` on the GM-Bench server keeps its tools
  direct (they never appear inside `execute`), but 2.x still offers
  `execute` for its own built-in tools, which default to Code Mode
  (session, worktree and MCP-resource helpers). The config denies the
  `execute` permission, which removes the tool from the request.
- The workspace is the directory `run` starts in, read from `PWD` before
  the process's working directory. Same-user runs set `PWD` to the scratch
  directory; without that, the driver's own directory (the checkout) would
  be the agent's workspace. A container starts in the mounted scratch.
- Without `--pure`, 2.x loads what its config discovery finds: the global
  config directory, `~/.claude` and `~/.agents` (instructions, skills,
  plugins), and `AGENTS.md`, `opencode.json`, `.opencode`, `.claude` and
  `.agents` walking up from the workspace. The private home and the empty
  scratch leave none of that; the prompt check proves it on every panel.
- Errors are `{"type": ..., "message": ..., "status": ..., "response":
  {"body": ...}}` (for example `provider.no-route`, `provider.rate-limit`,
  `provider.quota`), not 1.18's `{"name": ..., "data": {...}}`. The
  detectors below read both.
- The JSON stream stops printing step events once the session goes idle, so
  the last model step of each invocation has no `step_finish` and the
  stream undercounts tokens. The driver reads the counts from the session
  store instead (see "Reading the result").
- Credentials live in OpenCode's database; a staged `auth.json` is ignored
  (see "Running the harness in a container").
- OpenCode 2.x is not published to npm (`opencode-ai` stops at 1.19.0); the
  image installs the release binary.
- 2.x checks a tool call's arguments against the tool's input schema
  itself, before the tool runs (`cu` and `ip` in 2.0.27's tool runtime).
  A call that fails the check ends `error` with `Invalid arguments for tool
  "<name>":` and never reaches the MCP server, so it is not in the ledger.
  The event parser counts such a call under `harness_tool_calls_skipped`,
  not as a GM-Bench call, as it does Codex's pre-dispatch refusals; before
  2026-10-13 it counted it, and the ledger-versus-harness check failed.

The OpenCode 2.0.27 panel on `opencode-go/deepseek-v4.1-flash` (the same
model and OpenCode Go plan as the 1.18.31 row; 2026-10-13, driver commit
`93b1f7c`, the launcher's first panel) is committed at
`results/agentic/opencode-2.0.27-deepseek-v4.1-flash-panel-32x5.json`:
mean 244.6, 640/640 phases closed by the agent, no nudges, provider stalls
or compactions, 160.4 tool calls and 14.6 min per episode, 661K tokens
per decision (cached input included), $4.91 as OpenCode reports it. In episode 14 OpenCode refused one `trade` call on
its schema check (no `partner_team_id`); the run recorded 166/167, and the
row publishes the recount, 166/166, with the recorded figure beside it.
Episode 19 exited 1 with an empty stderr after the agent had closed all 20
phases; the run records it as a warning. The event streams carry one call
to `gm-bench-scout`, a tool name that does not exist, and no shell, file
or `execute` call. The first 2.0.27 panel, played before the launcher, is
not published (see above).

The OpenCode 2.0.27 panel on `opencode-go/muse-spark-1.3-contributor`
(Meta Muse Spark 1.3 on its Contributor tier through OpenCode Go;
2026-10-14, driver commit `3b82ca1`, driver digest `0c20d2de9ce62901`, the
same image as the DeepSeek 2.0.27 row) is committed at
`results/agentic/opencode-2.0.27-muse-spark-1.3-contributor-panel-32x5.json`:
mean 250.3, 640/640 phases closed by the agent, one illegal move, no
nudges, provider stalls, silent harness kills or compactions, 149.3 tool
calls (all GM-Bench calls; no shell, file or `execute` call) and 5.6 min
per episode, 604K tokens per decision (cached input included, from the
session export in every episode). OpenCode reports $1.70 for the panel
(its own figure at the Contributor rates, counted against the OpenCode Go
plan's limits rather than billed per token); the row also carries $69.90,
the same tokens at Muse Spark 1.3's standard list price (see "Publishing
a row").
The Contributor tier is discounted because Meta may train on the prompts
and completions, and OpenCode serves it only when the workspace allows
paid endpoints that train on request data: the first smoke attempt, made
without that setting, was refused with a 400 before any move (nothing
spent, not published). A
five-season container smoke on a public seed is committed at
`results/agentic/opencode-2.0.27-muse-spark-1.3-contributor-smoke-1x5.json`:
score 281.6, 154 tool calls, 5.8 min, $0.05 as OpenCode reports it.

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
then resumes the session. The resume text is not the nudge reminder: it
tells the agent the provider failed, not the agent, and spends no reminder
number (`PROVIDER_RESUME_MESSAGE` in `opencode.py`, recorded per episode as
`harness_run.provider_resume_message`; quota resumes send it too). A stall
retry does not spend a nudge, and a retry that stalls again without a tool
call does not end the loop. The per-episode limits default to 48 retries and
6 hours of waiting (`--max-provider-stalls`, `--max-provider-stall-wait-seconds`,
recorded in `run.json` and the published row), long enough to wait out a
free-tier quota window; with the 600 s cap the 6-hour budget binds first, at
38 retries. Stall backoff and in-episode quota pauses (below) also share one
cap, `--max-provider-wait-seconds` (default 6 hours, recorded in `run.json`
and `harness_run.max_provider_wait_seconds`), so one episode never waits 12.

Past a limit the provider, not the agent, has ended the episode. The driver
still closes the open phases (as `harness_exit`: the engine has no other
way), but records `harness_run.ended_by_provider` (`reason`:
`stall_retry_limit`, `stall_wait_budget`, `provider_wait_budget`,
`startup_server_error_limit` or `no_session_to_resume`; the season and phase;
the stalls and wait), and `run_panel` starts no further seed, recording
`stopped_for_provider` in `run.json`. `agentic-validate` reports such an
episode as a problem and `agentic-redact` refuses the run: those phases were
never played, so the score is not the model's. Runs recorded before the
field are read the same way when their last invocation was a provider stall
and phases were left open: the 2026-09-26 `muse-spark` panel's episodes 15
(39 stalls, 5 h 55 min of backoff, 16 phases never played, scored 174.8) and
16 (no tool call at all, scored 64.3) are exactly that. The wait is not phase-guard time: the driver
takes it off the open phase's clock (`AgenticEpisode.exclude_from_phase_clock`,
logged in the ledger as a `clock_pause` event that replay and the audit
ignore, and left out of the phase's recorded `seconds`), so only time a
harness was running counts toward the guard. Each nudge entry records
`stall_retry`, `backoff_seconds` and `provider_stall`, and `harness_run`
records `provider_stalls` and `provider_stall_wait_seconds`.

OpenCode's own server can also fail at startup: in two 8-seed container runs
of `opencode/space-bunny-free` on 1.18.31, 9 of 16 episodes opened with a single
`error` event (`"name": "UnknownError"`, message "Unexpected server error.
Check server logs for details.") about a second after launch, before any
tool call, and the resumed session then played the whole episode. OpenCode
2.x reports the same race (a model missing from the catalog snapshot it
ships with, before the first catalog download lands in the session store's
cache) as `provider.no-route`, "Model unavailable: <model>". Either error
is a provider stall (same backoff, budget and clock pause) only when
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

OpenCode's own gateway (`opencode.ai/zen`) answers a free model whose
allowance is spent with a 429 whose body names `FreeUsageLimitError`.
That is quota exhaustion, not a stall (`opencode.quota_exhaustion`).
OpenCode 1.18 marked it retryable (in the `muse-spark` panel it was
followed by hours of silent retries) and sent its `retry-after` header in
the error. OpenCode 2.x classifies it as a spent quota, does not retry it,
and reports it as `provider.quota` with the body but no headers, so its
reset is always unknown: the episode stops at once as `ended_by_quota`
(`message_class: "free_usage_limit"`) and the panel stops, as for Codex's
usage limit below. Any other 2.x `provider.quota` error (a 402, an
exhausted balance) is handled the same way, as `provider_quota`.

A spent OpenCode Go window (`opencode-go/*`, see "Running the harness in a
container") is handled the same way, as `message_class: "go_usage_limit"`:
the body names `GoUsageLimitError`. On OpenCode 2.x that error arrives at
once (2.x does not retry a quota) and without its `retry-after` header, so
the reset is unknown and the episode and the panel stop, even for a
5-hour window that would have reset within the wait budget; restart the
panel after the window resets. (On 1.18 the header gave the reset, a
window within the budget paused the episode and resumed it, and 1.18's own
silent retries could hide the error entirely.) No Go run has recorded this
error yet. Watch the Go usage page during a panel.

The other provider errors 2.x reports by type. `provider.rate-limit`,
`provider.internal`, `provider.transport`, `provider.invalid-output`,
`provider.unknown` and `provider.timeout` are the transient ones (2.x's own
retry policy, `isRetryable`, plus a timeout) and are stalls; OpenCode has
already retried them itself, 10 times over about 84 s, before the error
reaches the stream. Any other `provider.*` error (`provider.invalid-request`,
`provider.auth`, `provider.no-route` after the invocation acted,
`provider.content-filter`) is the provider refusing: when it ends an
unfinished episode's last invocation without a tool call, the episode is
recorded as ended by the provider (`reason: "provider_error"`), as a
non-retryable 1.18 `APIError` was.

`harness_run.exit_code` is the first launch's exit code, and
`harness_run.final_exit_code` the last invocation's (the first launch's when
there was no nudge, retry or resume); each nudge entry keeps its own
`exit_code`. `agentic-validate` warns on `final_exit_code`, so an episode
that recovered from a failed first launch does not warn. Runs recorded
before `final_exit_code` existed are read from `exit_code`, as before.

OpenCode retries a 429 inside the harness and prints nothing to its event
stream while it does (2.x: up to 10 times, each gap at least the provider's
`retry-after`, capped at 15 minutes), so a rate-limited harness can look
hung rather than end on an `error` event. A harness invocation that has appended no byte to
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
  harness reports it (`null` when it does not; OpenCode's figure for a
  discounted tier is below the model's list price), and a `harness` block with
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
  convention, and publication checks the sums only for shaped rows.
  OpenCode 2.x's stream omits the last model step of every invocation (no
  `step_finish` once the session goes idle), so at the end of the episode
  the driver runs `opencode session export <id> --standalone` in the
  episode's home (in the container, on its home volume) and sums the
  session's assistant messages (one per model step) and compactions
  instead. `usage.harness.token_source` says which source the counts came
  from: `session_export`, or `event_stream` with the reason in
  `usage.harness.session_export_error` when the export failed. Event-stream
  counts undercount; they are labelled, not hidden. The session's own
  total (`info.tokens`) is not used, because it also counts OpenCode's side
  requests such as the session title
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
audit_ledger("/tmp/agentic-space-bunny-dev/seed-11/ledger.jsonl")
```

Every tool reply's entity ids are recorded, so the audit can list moves that
named a player, prospect, team, or offer no earlier reply exposed. Accepted
moves on unseen ids are `violations`; rejected ones are `suspicious`. Ids are
sequential, so models do guess them: a successful read on a guessed id
(`scout`, `inspect_player`, `inspect_team`) is reported as a `guessed_read`
and the id counts as exposed from that reply on. An accepted `draft` on a
guessed prospect id is a `guessed_draft_pick`, not a violation: prospect ids
are `1_000_000 + season * 10_000 + index` and the index is independent of
hidden potential, so the pick is blind. Validation reports it as a warning.
Likewise an accepted `sign_free_agent` on a guessed player id is a
`guessed_signing` under the general 2026-10-14 policy, for every model and
season, including players kept after signing. There is no typo, minimum-salary
or release condition. IDs encode position slots; initial-pool correlation is
not evidence that leakage is absent. Both rules were adopted after the
panel they admit had run (see the spec's "Changes after the freeze").
The audit reports, it does not decide; publication does.

## The prompt check

Before a panel's first episode, `gm-bench agentic` proves what the harness
would send the model (`gm_bench/agentic/prompt_check.py`). It launches the
harness once, set up exactly as an episode's first invocation (same driver,
environment, staged files, command line and brief). The only change is
that the model endpoint is a capture server on the loopback:
`ANTHROPIC_BASE_URL` for Claude Code, `openai_base_url` and
`chatgpt_base_url` for Codex (plus uncompressed request bodies), and the
model's provider `baseURL` for OpenCode. The server records each model
request and answers with one word, so no provider is contacted and nothing
is spent. It also acts as the harness's HTTP(S) proxy and refuses every
other connection, recording the host, except the public model catalog
OpenCode downloads to resolve a model name (`models.opencode.ai`), which it
passes through and records as `forwarded_hosts`. A private home starts
without that catalog, so for a model missing from the snapshot OpenCode
ships with (`opencode/space-bunny-free` on 1.18.32), the first launch fails
at startup (1.18: "Unexpected server error"; 2.x: `provider.no-route`)
before any model request, as it does in an episode. The episode retries that as a provider stall by resuming
the session with a nudge, and the check does the same (`stall_retries`, at
most 3); the resumed launch finds the downloaded catalog.

The check then launches the harness a second time the same way, with the
operator's home swapped for an empty synthetic one: `HOME` and every
environment variable that names a path inside the home point into the empty
directory (`*PATH` search paths are kept so the harness and its interpreter
are still found). Any prompt line the first capture sent and the second did
not came from the operator's home, wherever the harness read it (a plugin's
`SKILL.md`, a file a `CLAUDE.md` imports, a memory, an unlisted config
directory). Before the comparison, what differs between any two launches is
replaced by placeholders: temporary paths (scratch, private homes, sockets),
the capture server's port, UUIDs and other long ids, dates and times. The
record keeps only counts (`empty_home`); the error that stops the panel
quotes up to three of the lines, truncated, so the operator can find them.
If the second launch sends no model request, the check fails: nothing then
shows which of the prompt came from the home. Cursor's check is a recorded
chat (below) and has no second launch.

The empty home hides only the home the environment names. A harness that
looks up its home another way (the user database) sees the real one in both
launches, so the captured requests are also searched for the operator's
content directly:

- the operator's home directory path;
- any line of 40 characters or more from their instruction files
  (`~/AGENTS.md`, `~/.agents/AGENTS.md`, `~/.codex/AGENTS.md`,
  `~/.claude/CLAUDE.md`, `~/.config/opencode/AGENTS.md`, and others),
  Claude Code's rules (`~/.claude/rules`) and per-project memories
  (`~/.claude/projects/*/memory`), the files named by OpenCode's
  `instructions`, and any file an instruction file imports with an `@path`
  line (one level);
- the description of any skill under `~/.agents/skills`, `~/.claude/skills`,
  the installed Claude Code plugins (`~/.claude/plugins/cache`),
  `~/.codex/skills` or `~/.config/opencode/skills` (dot directories such as
  Codex's bundled `skills/.system` are skipped).

A check that captured no model request fails too, because it proved
nothing. If the check finds anything, the panel does not start
(`PromptCheckError`). The record is kept as `run.json` `prompt_check` and
published with the row. `agentic-validate` and the published-row check
refuse a run whose recorded check has problems. `--skip-prompt-check` is
for development and records `prompt_check: null`: `agentic-validate` warns,
and the published-row check refuses such a same-user row at any grade. Rows
recorded before the check existed (no `prompt_check` key and no
`prompt_check.py` in the driver's files) and container rows are unaffected.

Only the first invocation is captured. Nudges and provider-stall retries
resume the same session in the same launch, so they run in the private home,
config directory and environment the check proved, with the driver's own
nudge text in place of the brief: they load no configuration the first
invocation did not. What a resume can add is what the agent itself wrote
during the episode. The Claude and Cursor drivers remove config the agent
writes into their homes before every invocation; for Codex and OpenCode it
is the agent's own work, in its own session.

Cursor builds its prompt on Cursor's servers, so its check is a one-word
chat whose recorded context is audited instead (see "Cursor harness"),
followed by the same search. Container runs of the other harnesses are
recorded as not checked: only the scratch directory and a fresh home volume
reach the harness, and its egress firewall keeps it from reaching a
loopback server. A Cursor container panel is checked anyway, in its image:
Cursor's servers add the account's User Rules whatever the isolation.

What the check cannot see: anything a provider adds on its own servers, and
what an account endpoint would return (a ChatGPT-login Codex fetches
plugins, apps and user settings at startup; the check answers those itself).

To see what a real account adds, Codex was also run once on 2026-09-27 with
the operator's ChatGPT login, its account endpoints reached for real and only
the model request sent to the capture server. The prompt grew from 61,427 to
64,033 characters. All of the extra text was OpenAI's generic plugin
catalog: a longer `<recommended_plugins>` list of curated plugins that are
not installed (Dropbox, Box, Figma, GitHub, Gmail, Google Drive, Linear,
Notion, Slack, Teams and others), a `request_plugin_install` tool, and
reworded apps instructions. Nothing specific to the account appeared: no
installed apps or connectors, no custom instructions or memories, and none
of the operator's content. The catalog is the same for any ChatGPT login,
so it counts as part of the harness, but it is fetched at startup and can
change without a Codex release.

That run read only the prompt text, and so missed what the account adds as
tools. In code mode (the model catalog's `tool_mode = "code_mode_only"`,
which `gpt-6-luna` and `gpt-6.1-sol` carry as of 2026-10-12) Codex declares
its built-ins in the prompt but defers every MCP tool: the agent finds them
in the `exec` tool's `ALL_TOOLS` and can call them, and the prompt never
names them. On 2026-10-12 a capture that asked `exec` for `ALL_TOOLS`
found 668 tools from the account's connected ChatGPT apps
(`mcp__codex_apps__*`: Gmail, GitHub, Google Drive, Calendar and Contacts,
Linear, Atlassian, Neon, Adobe, Jam, Hugging Face, Wispr Flow and others).
It also found 24 account-installed plugins synced into the home, whose own
MCP servers started in the harness. That was on 0.156.1 and on 0.162.1.
The driver now turns all of it off (see "Account plugins and apps" under
"Codex harness"). Since the prompt check cannot see account tools,
`scripts/audit_codex_tools.py` audits the whole tool set against the real
account before a Codex panel, and that audit is required.

Claude Code 2.1.281 was audited the same way on 2026-10-13, in its
container image with the real `setup-token` token. Only the model request
was answered locally (a TLS-intercepting proxy for `api.anthropic.com`,
not `ANTHROPIC_BASE_URL`); every other call reached Anthropic. Nothing
account-specific reached the agent: the requests offered only the allowed
built-ins and `ToolSearch`, and the deferred list held `NotebookEdit` and
the 24 `mcp__gm-bench__*` tools and nothing else, also after a 25-second
wait. The account calls were remote managed settings
(`/api/claude_code/settings`, 404) and policy limits (one restriction).
Claude Code does try to load the account's claude.ai connectors (Gmail,
Drive and the like) despite `--strict-mcp-config`; the `setup-token`
token's `user:inference` scope stopped it (`Missing user:mcp_servers
scope`). The driver now sets `ENABLE_CLAUDEAI_MCP_SERVERS=false`, which
skips that fetch whatever the credential. No committed Claude row records
a tool outside the allowed built-ins and GM-Bench. Two limits of the
prompt check for Claude Code follow from this. With `ANTHROPIC_BASE_URL`
on a non-Anthropic host, Claude Code turns tool search off and inlines all
24 GM-Bench schemas, so the check does not see the deferred layout an
episode has. And it never sees the account's remote managed settings: if
the account joins an organization that sets them, they apply silently, and
no flag turns that fetch off. Check that the account belongs to no such
organization before a Claude panel.

First results, 2026-09-27, same-user, on the operator's Mac:

| Harness | Model requests | Operator content |
|---|---|---|
| OpenCode 1.18.32 as launched before this fix | 2 | home path 19 times, 21 lines of `~/.agents/AGENTS.md`, 16 operator skills |
| OpenCode 1.18.32 with the private home | 2 | none |
| OpenCode 2.0.27 without the private home (2026-10-12, a test of the check) | 2 | home path once, 21 lines of `~/.agents/AGENTS.md`, 16 operator skills; 91 lines only with the operator's home |
| OpenCode 2.0.27 with the private home (2026-10-12) | 2 | none; 0 lines only with the operator's home |
| Claude Code (`claude` on PATH) | 1 | none |
| Codex 0.157.1 (native binary) | 1 | none |
| Cursor 2026.09.26-dd393fe (`composer-2.5`, the recorded context) | 1 | none; Cursor's 7 default rules and none of the account's own |

With the `codex` on that Mac's PATH (a Node wrapper) the check failed
closed: the wrapper's `node` is a version-manager shim that tries to
download Node into the fresh home, so the harness never reached the model.
Pass the native binary with `--binary` there.

## Validating a run

```bash
python -m gm_bench agentic-validate /tmp/agentic-space-bunny-dev
```

Exit code 0 means every episode's ledger replays to the recorded score, its
header seed matches the episode, it audits clean, the GM-Bench tool calls in
the retained `opencode-events.jsonl` (or `codex-events.jsonl`,
`claude-events.jsonl`) equal the replayed ledger's, and the run's contract
block matches this checkout's `agentic_contract()`. The agreement the driver
recorded is checked against that recount, not trusted: a recorded agreement
the recount contradicts is a problem. A recorded mismatch that the recount
resolves, because the driver's event parser has since been fixed, is a
warning, and `agentic-redact` publishes the recount with the recorded figure
beside it as `recorded`. The recount compares each tool, not only the total,
so two offsetting differences are a problem. Failed phases, timeouts, guard
stops, and missing telemetry are warnings: reported, never hidden, never
fatal. A missing event stream is a problem, and so is an episode the
provider ended (above).

Replay skips one kind of ledger entry: a call whose arguments were not a
JSON object is rejected live (`invalid arguments: arguments must be an
object`) but logged with `arguments: {}` (the engine's `_log_call`, a
contract source), and replaying `{}` could execute it, for example close a
phase with `end_phase`. Validation counts such an entry and does not
execute it, with a warning.

`agentic-validate` names episodes by index only and prints `<redacted>`
for every seed, in text and in `--json`, because a private-panel run's seeds
must never reach a terminal or a log. `--show-seeds` prints them for a run
on public seeds.

## Publishing a row

The committed OpenCode smoke row was produced this way (2026-09-25,
OpenCode 1.18.31, Docker running): run, redact, then validate the artifact
alone and against its raw run.

```bash
python -m gm_bench agentic --harness opencode --isolation container \
    --model opencode/space-bunny-free --seeds 1 2 3 4 5 6 7 8 --seasons 5 \
    --output /tmp/agentic-space-bunny
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
the fresh redaction and requires it to be identical. Beyond 20 seeds the
sign-flip test samples 20,000 flips; when none is as extreme as the observed
lift the runner reports 0.0, which the test cannot resolve, so the block
publishes the bound `1 / 20001` (`5e-05`) with
`sign_flip_p_value_upper_bound: true`, and validation rejects a bare 0.0 on
such a panel. `paired_lift_stddev`, like the site's score spread, is a
population standard deviation (divides by n).

Four more things are derived at redaction, all optional so older rows
still validate:

- `empty_phases`, per episode and for the row (`count` of `phases`): phases
  whose every ledger call was `get_status` or `end_phase`, so the agent read
  nothing beyond the status and made no move (`validate.EMPTY_PHASE_DEFINITION`).
- `effective_reasoning_effort`: the `--variant` the run passed (`requested`,
  `null` for the harness default) and what the harness itself reported
  (`reported`). Codex records the effort in its session rollout's
  `turn_context` records, which the driver now reads before the home goes
  (`harness_run.reasoning_effort`); runs before that kept none. Claude Code
  2.1.281's stream carries no effort level, and OpenCode's none either, so
  `reported` is `null` with a `note` saying why.
- For a Claude Code or Codex row, the API-equivalent cost is re-derived
  from the retained `claude-events.jsonl` or `codex-events.jsonl` with
  this checkout's parser and `pricing.json`. The run recorded its cost
  when it played, so a parser fix, or a price entry added after the panel,
  would otherwise never reach a published row. The re-derivation must give exactly the recorded
  token counts or the redaction is refused; a cost that differs is
  published with `usage.harness.api_equivalent_recomputed` (`recorded`
  figures, the `driver_digest` that re-derived them) and the row's
  `agentic_summary` keeps its recorded API fields under
  `api_equivalent_recorded`. `--raw` accepts it only when the fresh
  redaction reproduces it (the digest may differ).
- For an OpenCode row whose model (its id without the `provider/` prefix)
  `pricing.json` lists, an API-equivalent list-price estimate is added
  beside the cost OpenCode reports (`cost_usd`), from each episode's recorded token counts
  (OpenCode leaves no event stream to re-derive them from). The driver
  records no estimate for OpenCode, so the empty recorded fields are kept
  under `usage.harness.api_equivalent_recomputed` and the summary's under
  `api_equivalent_recorded`. An entry with `list_price_key` is a
  discounted tier: this estimate prices its tokens at the named entry's
  undiscounted rates, and `pricing_source.discounted_tier_key` names the
  tier (`muse-spark-1.3-contributor` is priced at `muse-spark-1.3`). Only
  this OpenCode estimate reads the field;
  `telemetry.api_equivalent_cost_usd`, which prices runs as they play,
  ignores it. Rows
  recorded before the shared token shape, and unpriced models such as
  `deepseek-v4.1-flash`, are unchanged.

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

The site also shows the other six scripted baselines from the 1.0 tables
beside the panel rows, as context only: no row is tested against any of
them. Their 5-season means on the same panel are recorded under
`scripted_bot_scores` in `config/bench_v2_lane.json` (computed 2026-10-12 the
same way, means only): strategic 242.899, shrewd 228.809, win-now 178.751,
value 174.355, rebuild 124.26, conservative 123.925. That block repeats
pick-trader and random, and the site build and data check reject it if
those two differ from `reference_scores`.

## Running the harness in a container

```bash
python -m gm_bench agentic --isolation container --model opencode/space-bunny-free \
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

A native Docker Engine on a Linux host (Docker Engine in Linux or in WSL 2,
not Docker Desktop) also works; checked on 2026-10-12 with Docker 29.7.2 in
WSL 2 Ubuntu 24.04 (linux/amd64). Such an engine resolves no
`host.docker.internal` and a container cannot reach the host loopback, so
when `docker info` names an operating system other than Docker Desktop on
a Linux host, the driver listens on the default bridge's gateway (the
host's `docker0` address, usually `172.17.0.1`) instead of `127.0.0.1` and
starts every container with `--add-host host.docker.internal:<gateway>`.
The gateway is recorded as `harness.container.host_gateway`; Docker
Desktop runs record none. The egress canary binds the same address, so the
probe tests the rule where the driver actually listens. Nothing needs
configuring: the user only needs access to the Docker socket.

The image. On the first run the driver builds
`gm-bench-agentic-opencode:<opencode version>-<Dockerfile hash>` from a
Dockerfile it pipes to `docker build` (no build context): a digest-pinned
`node:22-bookworm-slim` base, Debian's `python3` for the proxy, `procps`,
`iptables` for the egress rule, the `gmb-egress` entrypoint, and
OpenCode 2.0.27. OpenCode 2.x is not on npm, so the image downloads the
release tarball for the build architecture
(`https://opencode.ai/files/bin/2.0.27/opencode-linux-<arch>.tar.gz`),
checks it against a pinned SHA-256 (the same files and sums the anomalyco
Homebrew tap's `opencode-v2` formula pins) and installs the binary
root-owned. Images before 2.x installed `opencode-ai@1.18.31` from npm. It
refuses to run if the image reports a different OpenCode version
(`opencode --version` prints `opencode v2.0.27` on 2.x). `run.json` records the image tag, image id
(the content digest of what ran), base image, Dockerfile SHA-256, OpenCode
version, Docker server version, and the egress rule under
`harness.container`, and that block is carried into the published
artifact. `--binary` is ignored in container
mode.

Authentication. The free `opencode/*` models need no credentials: OpenCode
stores none for them (`opencode auth list` shows none) and the container
lists and runs them anonymously. Nothing is
provisioned unless you pass `--opencode-auth-file`. Do not mount
`~/.config/opencode` or the home directory to get a key, because that
directory's `AGENTS.md`, skills and commands would change what the harness
plays with. The harness's only configuration is the staged `opencode.json`.

OpenCode Go subscription models (`opencode-go/*`) take one OpenCode API key:

```bash
python -m gm_bench agentic --isolation container --model opencode-go/kimi-k3 \
  --opencode-auth-file ~/.config/gm-bench/opencode-go-key \
  --seeds 11 --seasons 1 --output /tmp/agentic-opencode-go
```

- `--opencode-auth-file <path>`: a file holding the key alone on one line.
  Keep it outside the checkout, mode 0600. The driver stores it in
  OpenCode's own credential store for the Go provider (`opencode-go`) only.
  The same key would also unlock paid Zen (`opencode/*`) models, billed to
  the account's Zen balance, and would move free Zen models off OpenCode's
  shared anonymous key, so it is not stored for `opencode`. OpenCode 2.x
  keeps credentials in its database and imports a 1.x `auth.json` only as
  a database migration, which a fresh database skips, so a staged
  `auth.json` is never read. The driver instead writes the key in `opencode
  auth export`'s format (`[{"integrationID": "opencode-go", "value":
  {"type": "key", "key": ...}, ...}]`, mode 0600) into OpenCode's data
  directory, runs `opencode auth import <file> --standalone`, and removes
  the file. Same-user runs do this in the private data directory
  (`$XDG_DATA_HOME/opencode/`, run from the private home, removed with it).
  Container runs get the file in the per-episode home volume
  (`/home/node/.local/share/opencode/`) over the stdin of a throwaway
  `docker run`, as the Codex and Claude credentials are, and import it in
  a container on that volume as the `node` user. It never goes on a
  command line, into a `docker run -e` variable, into the harness
  environment, or into the scratch directory. Checked on 2026-10-12 with a
  dummy key (no model call): the import lists 31 `opencode-go/*` models,
  including `opencode-go/deepseek-v4.1-flash`, and the same 11 free
  `opencode/*` models as no key; a staged `auth.json` lists no
  `opencode-go/*` model.
- An `opencode-go/*` model without the file is refused before anything
  runs: OpenCode does not load the Go provider without a key. The file with
  any other model, `opencode/*` included, is refused.
  The operator's own OpenCode login (`~/.local/share/opencode/auth.json`)
  and `OPENCODE_API_KEY` are never used.
- A `-contributor` model (`opencode-go/muse-spark-1.3-contributor`) is a
  discounted tier whose provider may train on the prompts and completions.
  OpenCode serves it only when the key's workspace allows paid endpoints
  that train on request data; otherwise the first request fails with a
  400 before any move. Turn that on deliberately, and price the model at
  its list rate as well (see "Publishing a row").

The trade-off, as for Codex and Claude Code: the agent can read its own
harness's credential, from the database in its home. The key is kept out of
the harness environment so a bare `env` does not show it, but a `cat` does.
That is the harness's key, not the benchmark's, and it gives no access to
the seed; it does give access to your Go allowance (and Zen balance), so use
a key you can revoke. What the agent prints lands in the retained event
stream, so when the episode ends the driver replaces the key with
`[REDACTED]` in `opencode-events.jsonl` and `opencode-stderr.log`. A kept
scratch directory is not redacted. `harness_run.auth` records `auth-file`
or `none`, and `harness_run.auth_providers` the provider ids the key was
stored for, never the value.

An image's bundled model catalog is older than OpenCode's live one (on
1.18.31, `opencode-go/grok-4.7` was missing until the catalog was
refreshed), so a container episode on a newer model may open on OpenCode's
startup error (1.18: `UnknownError`; 2.x: `provider.no-route`), which the
driver retries as a startup stall (see above).

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
server listens on `127.0.0.1` (on a native Linux engine, the bridge
gateway; see "Requirements" above) on an ephemeral port and the proxy dials
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
python -m gm_bench agentic --harness codex --model gpt-6-luna \
  --codex-auth-file /path/to/codex-auth.json \
  --seeds 11 --seasons 1 --output /tmp/agentic-codex
python -m gm_bench agentic --harness codex --isolation container --model gpt-6-luna \
  --codex-auth-file /path/to/codex-auth.json \
  --seeds 11 --seasons 1 --output /tmp/agentic-codex-container
```

These are the model and flags the committed `gpt-6-luna` rows used; the
`gpt-6.1-sol` and `gpt-6-astra` panels used the same flags with their own `--model`. No committed
row passes `--variant`, on any harness, so every row ran at the harness's
default reasoning effort. `--variant` sets it explicitly (for Codex,
`-c model_reasoning_effort="<variant>"`), and a row run with it is a
different row.

The Codex CLI is the second harness (`gm_bench/agentic/codex.py`, written
against Codex CLI 0.156.1, which played the committed `gpt-6-luna` rows,
and re-verified against 0.162.1, which the container image now pins and
which played the `gpt-6.1-sol` and `gpt-6-astra` panels; see "Codex 0.162.1" below). It runs through the same episode loop
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
That cost is a lower bound. The row carries
`api_equivalent_long_context_possible: true`: an episode sends about 10M
input tokens, and in some turns the input grew by more than the 272K-token
long-context threshold, so some requests may have been billed at the
long-context tier (2x input and cache, 1.5x output). The
estimate always uses short-context rates (see "API-equivalent cost
estimate" below), so the true API-price cost may be higher. The second,
on `gpt-6.1-sol` with Codex 0.162.1 (2026-10-13, driver commit `1411e2e`,
the account's apps and plugins turned off), is committed at
`results/agentic/codex-0.162.1-gpt-6.1-sol-panel-32x5.json`: mean 273.2,
640/640 phases closed by the agent, no nudges or quota pauses, 9 provider
stalls (780 s of backoff), 170.1 tool calls and 8.5 min per episode, $17.38
at API prices for the panel, also a lower bound
(`api_equivalent_long_context_possible: true`). On a ChatGPT `prolite`
plan the weekly window peaked at 7% used. The third, on `gpt-6-astra`
(2026-10-13, driver commit `5d56c71`, the same Codex 0.162.1 setup), is
committed at `results/agentic/codex-0.162.1-gpt-6-astra-panel-32x5.json`:
mean 288.4, 640/640 phases closed by the agent, no nudges, provider stalls
or quota pauses, 154.9 tool calls and 4.8 min per episode, 123K tokens
per decision (cached input included), and only GM-Bench calls in the
event streams. `pricing.json` had no `gpt-6-astra`
entry when it ran, so the run recorded no estimate; redaction re-derived
it from the retained event streams: $115.04 for the panel, a lower bound
(every episode had a turn whose input grew past 272K). On the same
`prolite` plan the weekly window went from 11% to 49% used.

What a run does per episode:

1. Stages the proxy exactly as for OpenCode, plus a Codex home holding one
   `config.toml` with a single entry, `[mcp_servers.gm-bench]`, whose
   `command` and `args` launch `gm_bench_proxy.py` on the harness's own
   `python3` with the socket path (or `host.docker.internal:<port>` in a
   container), and whose `default_tools_approval_mode = "approve"` approves
   that server's tools. Nothing else is configured. The approval key is
   required: exec mode never asks for approval, so under `workspace-write`
   Codex (0.156.1 and 0.162.1 alike) would refuse every GM-Bench call (tools without a read-only
   annotation need approval) with "MCP tool call requires approval, but
   approval policy is never". It approves only this server.
2. Runs `codex exec --json --skip-git-repo-check --model <m>` with the task
   brief as the prompt and the scratch directory as the working directory,
   capturing `seed-<n>/codex-events.jsonl`. `--variant` becomes
   `-c model_reasoning_effort="<variant>"`. Exec mode never asks for
   approval. Every invocation also passes `-c features.apps=false -c
   features.plugins=false -c features.remote_plugin=false`, so nothing from
   the ChatGPT account reaches the agent (see "Account plugins and apps"
   below); `harness_run.disabled_features` records them.
3. Nudges and provider-stall retries run `codex exec resume <session id>
   <reminder>` on the same session (the id is the `thread_id` of the first
   `thread.started` event), so Codex keeps its context. `resume` accepts no
   `--sandbox` flag, so the sandbox and the disabled features are set with
   `-c` on every invocation.
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
  `{"auth_mode": "apikey", "OPENAI_API_KEY": "sk-..."}`. A ChatGPT login's
  `auth.json` also works. Keep the file outside the checkout and outside the
  run directory.

  Codex renews a ChatGPT login inside the episode when it is about eight days
  old or its access token has expired. Renewing replaces the refresh token,
  and the old one stops working. So when an episode ends the driver writes
  the login Codex left back over the `--codex-auth-file` (mode 0600,
  atomically), and the next episode starts from it. It skips the write if
  the file changed during the episode (you logged in again), and says so on
  stderr. `harness_run.auth_file_update` records `unchanged`, `updated`, or
  why it was not written. Only the file you pass is kept current: point
  `--codex-auth-file` at `~/.codex/auth.json` itself if your interactive
  Codex should keep working, because a renewed copy leaves the original
  signed out. Before this, runs from a copy signed the operator's Codex out
  (on 2026-09-27 its refresh token was refused as already used).
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
`tokens`, as staged and as Codex left them after any refresh, read from the
private `CODEX_HOME` or, in a container, from the home volume before it is
removed; or the `CODEX_API_KEY` value) with `[REDACTED]` in `codex-events.jsonl` and
`codex-stderr.log`. A kept scratch directory is not redacted: it holds
whatever the agent wrote there. `harness_run.auth` records which source was
used (`auth-file` or `CODEX_API_KEY`), never the value.

The image. `gm-bench-agentic-codex:0.162.1-<Dockerfile hash>` is built on
first use from the same digest-pinned base and egress entrypoint as the
OpenCode image, with `@openai/codex@0.162.1` instead of `opencode-ai`; the
OpenCode image is unchanged. `run.json` records it under
`harness.container`, with `codex_version` as the image reports it. The
committed `gpt-6-luna` rows ran in `gm-bench-agentic-codex:0.156.1-578af3e044d4`
and keep validating at the driver commit they record; the `gpt-6.1-sol`
and `gpt-6-astra` panels ran in `gm-bench-agentic-codex:0.162.1-f8095c887ac3`.

### Account plugins and apps

A ChatGPT login brings the account into the harness, and until 2026-10-12
the driver let it in. Two Codex mechanisms do this, and both are on by
default in 0.156.1 and 0.162.1 (`codex-rs/features/src/lib.rs`: `apps`,
`plugins`, `remote_plugin`). The source lines are in the `codex.py`
docstring.

- **Installed plugins.** A few seconds after start, Codex syncs the
  plugins installed on the account into
  `CODEX_HOME/plugins/cache/openai-curated-remote` and refreshes MCP.
  Those plugins' MCP servers then start inside the harness. On the
  operator's account that was 24 plugins, with servers for `neon` (an
  HTTP server at `mcp.neon.tech`, which fails for want of OAuth: the
  `AuthRequired ... mcp.neon.tech` line in `codex-stderr.log`),
  `codex-security`, `creative-production` and `xcodebuildmcp`.
- **Connected apps.** The hosted `codex_apps` MCP server serves the
  account's connected ChatGPT apps as tools. On 2026-10-12 that was 668
  tools: Gmail (read, send, delete), GitHub, Google Drive, Calendar and
  Contacts, Linear, Atlassian, Neon, Adobe, Jam, Hugging Face, Wispr Flow
  meetings and notes, and ChatGPT spaces.

In code mode Codex defers every MCP tool. The model catalog puts
`gpt-6-luna` and `gpt-6.1-sol` in code mode (`tool_mode =
"code_mode_only"`). A deferred tool is absent from the prompt text but
listed in the `exec` tool's `ALL_TOOLS`, and the agent can call it from
there. The prompt carried only the generic `<recommended_plugins>` list and
a `request_plugin_install` tool. So neither the 2026-09-27 account capture
nor the prompt check could see the app tools.

The driver now passes `-c features.apps=false -c features.plugins=false -c
features.remote_plugin=false` on every invocation (`codex.DISABLED_FEATURES`),
in both isolations. They go on the command line, not in the staged
`config.toml`, because `-c` overrides every config layer and the agent can
rewrite the `config.toml` in its own home between invocations. Captured on
2026-10-12:

| | Default | Disabled |
|---|---|---|
| Account tools in `ALL_TOOLS` (besides the built-ins and GM-Bench tools) | 668 `codex_apps` | 0 |
| Account plugins synced | 24 | 0 |
| Plugin MCP servers started | 4 | 0 |
| First request (0.162.1, `gpt-6.1-sol`, one-line prompt) | 72,766 characters | 70,698 characters |
| First request (0.156.1, `gpt-6-luna`, one-line prompt) | 69,116 characters | 67,049 characters |

The prompt loses only the `<recommended_plugins>` block and
`request_plugin_install`; the built-ins, the bundled `.system` skills and
the `gm-bench` server are unchanged. `apps=false` alone keeps the plugin
sync and its MCP servers, and `plugins=false` alone keeps the 668 app
tools. `remote_plugin=false` changes nothing more today.

A row run with these flags does not have the same Codex built-ins as the
committed `codex/0.156.1 · gpt-6-luna` rows, which ran with the account's
apps and plugins available. Those rows record no tool call other than
GM-Bench calls (`tool_calls_by_tool` in all four artifacts). Which apps
were connected on 2026-09-26 was not recorded.

**Tool audit (required before a Codex panel).** Run it with the auth file
the panel will use, under the subscription lock:

```bash
flock /tmp/gmb-subscription-smoke.lock \
  uv run python scripts/audit_codex_tools.py --codex-auth-file /path/to/codex-auth.json --model gpt-6.1-sol
```

It plays one throwaway episode on public seed 11 in the Codex image. The
driver stages it exactly as an episode's first invocation: real engine and
proxy, home volume with the login, same command line. Only the model
request (`openai_base_url`, which carries a ChatGPT login's
`/backend-api/codex/responses`) goes to a capture server on the host.
Codex's account endpoints and the model catalog reach ChatGPT for real.
The capture server answers the first request with a code-mode `exec` call.
That call waits 15 seconds for the plugin sync, then prints `ALL_TOOLS`,
and the follow-up request gets a one-word reply. Nothing is spent. Because
the capture server listens on a second host port, the episode runs without
the egress firewall; it holds only a public seed.

The audit prints tool counts by server and PASS or FAIL, never request
text or credentials. It fails on any MCP tool not under `mcp__gm_bench__`,
a plugin-install tool, a `<recommended_plugins>` list, or an account
plugin synced into the home. It also fails if no GM-Bench tool is
reachable. `--without-disabled-features` drops the driver's flags, and
`--codex-version 0.156.1` audits the image the committed rows ran in. On
2026-10-13 with the operator's login:

| Image, model | Flags | Tools by server | Plugins synced | Result |
|---|---|---|---|---|
| 0.162.1, `gpt-6.1-sol` | on | 24 built-in, 24 `gm_bench` | 0 | PASS |
| 0.162.1, `gpt-6.1-sol` | off | 25 built-in, 668 `codex_apps`, 24 `gm_bench` | 24 | FAIL |
| 0.156.1, `gpt-6-luna` | on | 24 built-in, 24 `gm_bench` | 0 | PASS |
| 0.156.1, `gpt-6-luna` | off | 25 built-in, 668 `codex_apps`, 24 `gm_bench` | 24 | FAIL |

(The built-in counts include the `exec`, `wait`, collaboration and clock
tools the request declares, which `ALL_TOOLS` does not list.)

### Codex 0.162.1

The container image pins Codex CLI 0.162.1 (from 0.156.1, 2026-10-12)
because the ChatGPT backend refuses newer models to the old client: on
0.156.1, `gpt-6.1-sol` failed with a 400 "The 'gpt-6.1-sol' model is not
supported when using Codex with a ChatGPT account" and a warning that the
model's metadata was not found. Every claim the driver relies on (listed
at the top of `gm_bench/agentic/codex.py`) was re-read from the source at
tag `rust-v0.162.1` and the 0.162.1 binary. What changed that touches the
driver:

- Nothing in the `codex exec --json` stream: `exec/src/exec_events.rs` and
  `exec/src/event_processor_with_jsonl_output.rs` are byte-identical
  between the tags, so the events, item types, and the running usage total
  are the same. The flags the driver passes, the `-c` keys it sets
  (`sandbox_mode`, `sandbox_workspace_write.network_access`,
  `model_reasoning_effort`, `default_tools_approval_mode`, and the capture
  overrides), the forced `approval_policy = never`, the MCP auto-approval
  rule, the pre-dispatch refusal messages, the `auth.json` format, the
  file credential store, and the eight-day login refresh are unchanged.
- The rollout persistence filter was rewritten (`persisted_event_msg` in
  `rollout/src/policy.rs`), but it still persists every `token_count`
  (with `rate_limits`) and every `turn_context` (with `effort`), so the
  quota windows and reasoning effort read the same way. A background
  worker now compresses rollouts older than seven days to `.zst`; an
  episode's home is new, so the driver never meets one.
- The usage-limit message links `chatgpt.com/settings/usage` (was
  `chatgpt.com/codex/settings/usage`) and covers a new `promax` plan; the
  "try again at" time is formatted as before.
- Codex now retries "Selected model is at capacity" and "exceeded retry
  limit" itself when the server advised a delay, so fewer of them reach
  `turn.failed`; the text is unchanged and still a provider stall. A new
  "Flex capacity unavailable." error comes only from the flex service
  tier, which the driver never selects.
- A new `exec` flag (`--cyber-access-program`) and an experimental
  Daybreak feature (off by default) are not used.

A five-season container smoke of `gpt-6.1-sol` on 0.162.1 (seed 11,
2026-10-12, not committed) closed 20/20 phases itself in one turn, with no
nudges, stalls or failed decisions, 165 tool calls (harness and ledger
agree), 6.5 min, score 200.6, and validated. As on 0.156.1, a run without
`--variant` records no reasoning effort: the rollout's `turn_context`
carries `effort` only when one is selected.

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
  and `null` when the entry names no threshold. The run's summary flag is
  likewise `null`, not `false`, when every episode's is `null`.

  The committed `gpt-6-luna` rows carry `true`: an episode is one turn of
  about 10M input tokens, so the per-turn bound says nothing about any one
  request. Pricing any request at the long-context tier needs its own input
  size, which lives only in the session rollout; that goes with the
  episode's home and is not retained. (`pricing.json` also records only the
  threshold, not long-context rates.) So those rows stay at short-context
  rates with this caveat, and the estimate may be low.

What it is not: a bill, a measured cost, or a number comparable to an
OpenCode row's `cost_usd`. It ignores Batch, Flex, Fast mode, and regional
processing prices, and it is only as current as the entry's `verified`
date. It never feeds `cost_usd` or `cost_decisions`. The run's
`agentic_summary` sums it over the episodes that have one
(`api_equivalent_cost_usd`, `api_equivalent_cost_episodes`,
`api_equivalent_long_context_possible`); the compact artifact keeps the
episode fields; and the site shows the cost cell as `$0.123 est.` with the
basis in its tooltip when a row has an estimate but no billed cost, or
`unmeasured` when it has neither. Otherwise the cost the harness reports
wins, except on a discounted data-sharing tier (a `discounted_tier_key` on
the estimate): there the site shows the list-price estimate, labelled as
one, with the reported figure beside it in the model panel, so the row is
not read as the model's price (`muse-spark-1.3-contributor`: $2.18 per
game estimated, $0.05 a game as OpenCode reports it). The site data check rejects a row whose
estimate equals its billed `cost_usd`.

Price the model before the run. A run prices its tokens as it plays, from
the `pricing.json` this checkout has, so add and verify the model's entry
(input, output, cache reads, cache writes including Anthropic's 1-hour
tier, and any long-context threshold) before the smoke, not after the
panel. The `claude-haiku-5-5` and `gpt-6-astra` panels (2026-10-13) ran
without one and recorded no estimate; the `claude-sonnet-5-5` and
`claude-opus-5-5` panels were priced first. A new id can also resolve to an
older model's prefix entry (`claude-sonnet-5-5` would have matched
`claude-sonnet-5`) or to none (`claude-opus-5-5` matched no entry), so check the
entry it actually resolves to with `telemetry.model_price_entry`. `agentic-redact` re-derives the
estimate for a Claude Code or Codex row from its retained event streams
(`claude-events.jsonl`, `codex-events.jsonl`) with this checkout's
`pricing.json`, refusing if the stream no longer gives the recorded token
counts; an OpenCode row gets one at redaction from its recorded token
counts when its model is priced (see "Publishing a row"), and a Cursor row
publishes whatever the run recorded, `null` for an unpriced model. Muse
Spark 1.3 was priced (both tiers, verified 2026-10-14) before its smoke.
Note any
tiered price the
estimator can only bound (a `long_context_input_tokens` threshold) in the
row's disclosures.

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
prices. The 32-seed private panel at five seasons in a container
(2026-09-27) is committed at
`results/agentic/claude-2.1.281-claude-sonnet-5-panel-32x5.json`: mean
227.4, 640/640 phases closed by the agent, no nudges, provider stalls or
compactions, 14.5 min per episode, $157 at API prices for the panel, and no
subscription limit hit. One episode's recorded tool-call agreement (165/166)
came from a parser bug and is published as the recount (165/165). A
second panel on `claude-haiku-4-5` (2026-09-27) is committed at
`results/agentic/claude-2.1.281-claude-haiku-4-5-panel-32x5.json`: mean
130.1, 640/640 phases closed by the agent, 3 nudges, no provider stalls,
6.1 min per episode, $27.71 at API prices (first published as $25.14: the
1-hour cache writes were priced at the 5-minute rate, see Cost below; the
row now carries the re-derived figure with the recorded one beside it). In
late seasons it drafted six
guessed prospect ids without listing the class; they are reported as
guessed draft picks (warnings), not violations. A third panel, on
`claude-haiku-5-5` (2026-10-13, driver commit `3e8e600`, the first Claude
row without the account's claude.ai connectors), is committed at
`results/agentic/claude-2.1.281-claude-haiku-5-5-panel-32x5.json`: mean
202.7, 640/640 phases closed by the agent, 1 nudge, no provider stalls or
quota pauses, 31 compactions, 6.4 min per episode, and $4.89 at API prices
for the panel, a lower bound. Haiku 5.5 charges 5x on every category for a
request whose prompt is over 100,000 tokens (`long_context_input_tokens`),
and 1,037 of the panel's 2,837 requests were; repricing them from the
per-request frames gives about $12 to $16. `pricing.json` had no Haiku 5.5
entry when the panel ran, so the estimate was re-derived at redaction (see
Cost below). Claude Sonnet 5.5 was priced before its first run (#197; a
five-season container smoke on seed 11 is committed at
`results/agentic/claude-2.1.281-claude-sonnet-5-5-smoke-1x5.json`: score
146.5, 111 tool calls, 3.1 min, $1.28 at API prices). Its panel
(2026-10-13 to 10-14, driver commit `0f3042d`) is committed at
`results/agentic/claude-2.1.281-claude-sonnet-5-5-panel-32x5.json`: mean
217.1, 640/640 phases closed by the agent, no nudges, provider stalls,
quota pauses or compactions, 2.9 min per episode, and $38.31 at API prices
for the panel (Sonnet 5's was $157; Sonnet 5.5's cache reads cost half as
much, and it used about a third of the input tokens). In one episode it
signed a free agent the listing had not shown and released him soon
afterward; that is reported as a guessed signing (a warning), under a rule
adopted after the panel ran. Claude Opus 5.5 was also priced before its
first run (`73c949b`; a five-season container smoke on seed 11 is committed
at `results/agentic/claude-2.1.281-claude-opus-5-5-smoke-1x5.json`: score
287.1, 135 tool calls, 9.0 min, $3.64 at API prices). Its panel
(2026-10-14, driver commit `73c949b`, driver digest `0c20d2de9ce62901`, the
same driver files as the Sonnet 5.5 row) is committed at
`results/agentic/claude-2.1.281-claude-opus-5-5-panel-32x5.json`: mean
202.5, 640/640 phases closed by the agent, no nudges, provider stalls or
compactions, 6.5 min per episode, and $129.12 at API prices for the panel
(339.2M of its 344.4M input tokens were cache reads). It is the first
Claude row with a quota pause: after episode 25 the five-hour window read
98% used (a Max 5x plan, which the artifact does not record), and the
driver waited about 3.0 hours for the reset; no episode was ended by
quota. Every Claude episode spends your Claude subscription's
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
   row identity), telemetry and error reports. `ENABLE_CLAUDEAI_MCP_SERVERS=false`
   stops the fetch of the account's claude.ai connectors (see "Account
   connectors" below).
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
`pricing_source.cache_write_1h_rate`). Frames name the dated snapshot
(`claude-haiku-4-5-20251001`) where `modelUsage` names the alias
(`claude-haiku-4-5`), so the two are matched with the date suffix removed;
before 2026-09-28 they were matched exactly, which found no 1-hour writes
for Haiku. On three live `claude-sonnet-5` smokes this matched Claude
Code's own figure to the microdollar, and on the Haiku panel it now matches
too ($27.707858 against Claude Code's $27.707856).

A resumed session does not double-count: since 2.1.277 each result carries
the session's running total, and the parser keeps the last one per session.
On the Haiku panel's three resumed episodes (0, 22, 26) the final result's
input, cache-read and cache-write totals equal the sum over distinct message
ids of the frames exactly. Claude
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
kill. The driver can also record windows streamed with a `utilization`
figure as `harness_run.quota_windows`, which drives the
between-episode pause at 95% used. In practice Claude Code 2.1.281 streams
a window only once it is nearly spent. Two committed rows have any: on the
`claude-haiku-5-5` panel episodes 1 and 2 recorded the five-hour window at
91% and 95%, with no quota pause recorded, and on the `claude-opus-5-5`
panel episodes 24 and 25 recorded it at 92% and 98%, and the
between-episode pause fired once, after episode 25 (it waited 10,963 s for
the 19:00 UTC reset). Every other committed Claude row has empty
`quota_windows` and no quota pauses. Until a window is streamed, the first
sign of a spent window is the rejection itself. Check your usage before a
panel.

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
`CLAUDE_CODE_OAUTH_TOKEN` with `CLAUDE_CONFIG_DIR=/home/node/.claude`,
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` and
`ENABLE_CLAUDEAI_MCP_SERVERS=false`, and execs `claude` with the
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

## What else the agent can use

Each harness runs with its own tools beside the GM-Bench tools, and they
differ. This is part of what a row measures, since a row is model plus
harness.

- **Claude Code** runs with `--tools
  Bash,Read,Edit,Write,Glob,Grep,NotebookEdit,ToolSearch`. It has no web
  fetch or web search tool, and `dontAsk` denies any other tool. Its
  GM-Bench tools are deferred: the model sees them by name only and calls
  ToolSearch to load a tool's schema before first use (see "Claude Code
  harness"). The five panel rows made 200 (`claude-sonnet-5`), 167
  (`claude-haiku-4-5`), 146 (`claude-haiku-5-5`), 37
  (`claude-sonnet-5-5`) and 82 (`claude-opus-5-5`) ToolSearch calls over
  32 episodes. `claude-opus-5-5` also made 47 Bash, 9 Write, 1 Edit and 1
  Grep calls. They listed `/work` and Claude Code's memory folder and wrote
  notes to that folder (in the episode's home volume) or to
  `/work/notes.md`. Each episode's container starts with the folder empty,
  so nothing carried between episodes; no call read the proxy secret,
  credentials, the environment or seeds, and `config_dir_findings` is
  empty in all 32 episodes.
- **OpenCode and Codex** run with their built-in tool sets unrestricted,
  including any web tool the harness ships (OpenCode's web fetch, Codex's
  web search). OpenCode puts every GM-Bench tool schema in the first
  prompt, through the launcher (see "OpenCode 2.x"); on 2.0.27 without it
  the first request of each invocation had none. OpenCode's Code Mode
  `execute` tool is denied. Codex does not when the model is in code mode, as `gpt-6-luna`
  and `gpt-6.1-sol` are by the model catalog as of 2026-10-12. The prompt
  then declares Codex's built-ins and the JavaScript `exec` tool. The 24
  GM-Bench tools are deferred: they are absent from the first request (no
  schema and not even a name) and callable from `exec` as
  `tools.mcp__gm_bench__<tool>`, listed in `ALL_TOOLS`. The brief names
  them. That is true on 0.162.1 and, with the 2026-10-12 catalog, on 0.156.1
  (`scripts/audit_codex_tools.py`). The catalog decides code mode, not the
  Codex version, and the catalog `gpt-6-luna` had on 2026-09-26 was not
  recorded, so whether the committed Luna rows saw the schemas up front is
  not known. Codex no longer gets the ChatGPT account's apps and plugins
  (see "Account plugins and apps"); the committed Codex rows ran with them
  available and called none.
- **Cursor** runs with its built-in tools unrestricted (`--force` runs
  every tool call without asking). It reads a GM-Bench tool's schema from
  its own cache (`get_mcp_tools`, which never reaches the server) before
  calling it; the `composer-2.5` panel made 259 such reads over 32
  episodes.

Network. In a container the egress rule blocks the host and private
networks but allows the public internet, because the harness needs its
model provider. So an agent can reach anything public, including this
repository: the simulator source, the scripted `pick-trader` policy
(`gm_bench/agents.py`), and these docs. It cannot reach a panel seed that
way (see "Red-teaming the sandbox"), but it could read how the benchmark
works and what the reference policy does.

No panel agent used the web. The committed Codex panel row records no
harness tool event except GM-Bench calls: no shell command and no web
search. The Claude rows record `Bash`, `Read`, `Edit`, `Write` and
`ToolSearch` events only, and the pre-release audit of the retained Claude
event streams found no shell command that contacted an external host. The
Cursor row records GM-Bench calls, `get_mcp_tools` schema reads, and one
malformed MCP call that Cursor rejected before it reached any server
(`unknown_unknown`): no shell command, file tool or web tool.
Nothing enforces this for future rows; check a new row's event stream
before publishing it.

## Cursor harness

```bash
python -m gm_bench agentic --harness cursor --model composer-2.5 \
  --cursor-token-file /path/to/cursor-token \
  --seeds 11 --seasons 1 --output /tmp/agentic-cursor
```

The Cursor CLI (`cursor-agent`) is the fourth harness
(`gm_bench/agentic/cursor.py`, written against Cursor CLI
2026.09.26-dd393fe). It runs through the same episode loop as the others. A
Cursor row is its own row, `cursor/<version> · <model>`.

**Status: same-user and container; one panel row published.** Same-user
rows are `smoke` grade; `--isolation container` (below) is what a
panel-grade row needs. Every Cursor episode spends your Cursor plan. Run it
serially.

The 32-seed private panel at five seasons in a container (`composer-2.5`,
2026-09-28, driver commit `b3d7de7`) is committed at
`results/agentic/cursor-2026.09.26-dd393fe-composer-2.5-panel-32x5.json`:
mean 230.6 (SD 27.7), 18.6 below `pick-trader` (95% interval -35.6 to
-1.4, p = 0.047), 640/640 phases closed by the agent, 0 failed decisions,
55 penalized illegal moves, no nudges, provider stalls or guard stops,
127.6 tool calls and 3.5 min per episode. 125 of the 640 phases were
empty (only `get_status` and `end_phase`). The prompt audit passed on all
32 episodes with Cursor's seven default rules and nothing else. Cost is
unmeasured: Cursor reports none, and `composer-2.5` has no price in
`gm_bench/pricing.json`, so there is no API-equivalent estimate either.
Cursor reports no reasoning effort or reasoning tokens, and compactions
are unmeasured. The model is unpinned.

A live same-user smoke ran on 2026-09-27: `composer-2.5`, seed 11, one
season. It scored 113.9 with 4/4 phases closed by the agent and 41 GM-Bench
tool calls, the same count in the ledger and in Cursor's event stream. It
had no illegal moves, nudges or provider stalls, took 87 s, and used 1.20M
input tokens (1.14M of them cache reads) and 10k output tokens. No
credential was in any saved file. The account had 8 User Rules (13,337
characters) in the prompt, so the run proves the driver works and is not a
clean row. The prompt gate below was added after it and refused that
account. After the account's one rule of its own was deleted, the same
smoke was rerun with the gate on: the prompt held only Cursor's own
sections and its seven default rules, and the run scored 122.8 with 0/4
failed decisions, 32 GM-Bench tool calls, 1.03M input tokens (0.99M cache
reads) and 11k output tokens, and passed `agentic-validate`.

What a run does per episode:

1. Stages the proxy, and makes one private directory (mode 0700, outside
   the scratch, removed at episode end even with `--keep-scratch`) holding
   the harness's `HOME`, `CURSOR_CONFIG_DIR` and `CURSOR_DATA_DIR`. The only
   staged file is `$HOME/.cursor/mcp.json` with one stdio server,
   `gm-bench`, which launches the proxy (by absolute path) on the harness's
   own `python3` with the socket path. Every other `CURSOR_*` variable is
   dropped, `AGENT_CLI_CREDENTIAL_STORE=memory` keeps the macOS Keychain out
   of the run, and `DIRENV_DISABLE=1` stops Cursor loading an `.envrc`
   above the scratch.
2. Runs `cursor-agent -p --output-format stream-json --trust --force
   --approve-mcps --sandbox disabled --model <m> <brief>` in the scratch
   directory, capturing `seed-<n>/cursor-events.jsonl`. Cursor puts the
   reasoning effort in the model id (`gpt-5.6-sol-high`), so `--variant` is
   refused.
3. Nudges and provider-stall retries run the same command with `--resume
   <session id>`, which keeps the chat's context.
4. Before every invocation it removes project config the agent could have
   written into the scratch (`.cursor/`, `.cursorrules`) and hooks, rules,
   skills, agents, commands and permission files in `$HOME/.cursor`, and
   rewrites `mcp.json`. What it removed is recorded as
   `harness_run.config_dir_findings`.

Authentication. `--cursor-token-file <path>` holds one token: a Cursor API
key (handed over as `CURSOR_API_KEY`) or a session token, which is a JWT
(handed over as `CURSOR_AUTH_TOKEN`). Without the file, `CURSOR_API_KEY` or
`CURSOR_AUTH_TOKEN` from your environment is used. The host's Keychain login
is never read. The value is replaced with `[REDACTED]` in
`cursor-events.jsonl` and `cursor-stderr.log` when the episode ends.

**What reaches the prompt, and the prompt gate.** Cursor's servers add the
account's cloud-synced User Rules (Cursor Settings, Rules) to every prompt.
The CLI never fetches them and has no switch to leave them out, so no
client setting or proxy can remove them. The driver proves the prompt
instead. Cursor stores each chat's context message (the one carrying
`<user_info>`) in `CURSOR_CONFIG_DIR/chats`, and the driver lists the
outermost sections of every such message. Cursor itself adds `user_info`,
`agent_transcripts`, `agent_skills` (its 14 bundled skills),
`dynamic_tools`, `mcp_instructions`, `project_layout` and `git_status`.
Anything else is unexpected: `rules` (User Rules or workspace rules), cloud
instructions, memories, or a section Cursor adds in a later version.

Cursor's servers also put seven rules of their own in the User Rules slot
of every account's prompt (git commits, pull requests, following
instructions, "this is a real environment", communicating with the user,
reading conversation history, code principles; 11,804 characters). They
are not in the account's Rules settings and cannot be removed: on
2026-09-27, after the account's only visible rule was deleted, these seven
were still sent. The set depends on the model: grok-4.7 gets the git-commit
and pull-request rules plus two others (verifying web-app changes in a
browser, and stating points in affirmative language), recorded 2026-09-28
by a one-word probe and absent from the account's own rules. They are part
of the harness, so the driver lists their
SHA-256 digests (`CURSOR_DEFAULT_RULES`) and a `rules` section is expected
when it holds nothing but those, in exactly the shape Cursor sends: `<rules>`,
Cursor's fixed preamble sentence, one `<user_rules>` (bare or with Cursor's
`description` attribute), and `<user_rule>` elements with no attributes and
no text between them. The gate fails closed. Any other User Rule, any other
text or subsection in `rules`, a `rules` or `user_rule` tag with other
attributes, a rule tag outside a `rules` section, or a default whose wording
Cursor changes is refused until someone reviews it and adds it here.

- Before a panel, the prompt check (see "The prompt check") makes one
  one-word call (`--mode ask`, "Reply with the single word ok.") in a
  throwaway workspace with an episode's private `HOME`, config directory and
  credential. It refuses to start if that prompt has an unexpected section
  or any of the operator's own content. The call has no MCP server (no
  staged `mcp.json`, `--force` or `--approve-mcps`), so it costs one tiny
  model call; each episode's own prompt is audited again when it ends.
- Every episode records `harness_run.prompt_audit` (section names, the
  unexpected ones, how many of Cursor's default rules were present, how
  many other User Rules and characters, and how many rules slots were in an
  unrecognised shape, never their text), and published rows carry it.
- `agentic-validate` and the published-row check refuse a Cursor episode
  whose audit is missing, lists an unexpected section, counts any User Rule
  that is not a default, or counts an unrecognised rules slot.

To run Cursor on an account that has its own User Rules, copy the rules
somewhere, clear them in Cursor Settings, run, and restore them
afterwards.

**Container isolation.** `--isolation container` runs the CLI from its own
image, `gm-bench-agentic-cursor:2026.09.26-dd393fe-<Dockerfile digest>`,
built locally on first use (`container.CURSOR_IMAGE`). Cursor ships the CLI
as a tarball with its own Node, not an npm package, so the image downloads
the release tarball the official installer (`https://cursor.com/install`)
would fetch, `downloads.cursor.com/lab/2026.09.26-dd393fe/linux/<arch>/agent-cli-package.tar.gz`,
checks it against a pinned SHA-256 (`arm64`
`ab1178d0d8c10b254e7e427d1d673533a389338424e75034be9ab9da02845bde`,
`x64` `8085fd120f5c71f4eae7fea26a043718e5644e3071e4fab3220a0e58c51f9593`),
and unpacks it root-owned under `/opt/cursor-agent`. Everything else is
the shared image: the digest-pinned Node base, Debian's `python3` for the
proxy, the egress firewall, the unprivileged `node` user. The run records
the image tag, id, Dockerfile SHA-256 and the `cursor_version` the image
reports under `harness.container`.

```bash
python -m gm_bench agentic --harness cursor --model composer-2.5 \
  --isolation container --cursor-token-file /path/to/cursor-token \
  --seeds 11 --seasons 1 --output /tmp/agentic-cursor-container
```

- The container gets no environment, so `--cursor-token-file` is required.
  The token travels on the stdin of a throwaway `docker run` into the
  episode's home volume (`/home/node/.gmb-cursor-token`, mode 0600, with the
  variable the API-key-or-JWT rule picks), never onto a command line, into
  a `docker run -e` variable, or into the scratch, and is removed with the
  volume. `mcp.json` (the proxy under `/work` on the container's `python3`)
  is seeded the same way.
- Every invocation starts in the image's launcher, `/usr/local/bin/gmb-cursor`,
  with the `mcp.json` text as its first argument. Each invocation is a fresh
  container, so nothing the agent started in the previous one is still
  running. The launcher removes the same scratch and `$HOME/.cursor` entries
  the same-user guard removes, restores `mcp.json`, points `HOME`,
  `CURSOR_CONFIG_DIR` and `CURSOR_DATA_DIR` at the volume, sets
  `AGENT_CLI_CREDENTIAL_STORE=memory` and `DIRENV_DISABLE=1`, exports the
  token, and execs the pinned CLI. Each removal is a `gmb-cursor:` line on
  stderr, collected into `config_dir_findings`. If a config directory is a
  symlink or not a directory, an entry cannot be removed, or the token is
  missing, it refuses to start the CLI (exit 96, `gmb-cursor: refused:`).
  A read-only root-owned layout like Claude's cannot work here, because
  Cursor writes `$HOME/.cursor` itself on every start.
- The prompt audit reads the chat stores out of the volume before it is
  removed, and gates publication exactly as a same-user audit does.
- The pre-panel prompt check runs in the image too (a container of its own
  with no MCP server), where the other harnesses' container panels are
  recorded as not checked. Account rules come from Cursor's servers whatever
  the isolation, so the check refuses such a panel before its first episode.

On 2026-09-28 the image was built on Docker 29.3.1 (linux/arm64, image id
`sha256:38117c574e2e...`), reported `2026.09.26-dd393fe` with no network,
passed the sandbox and egress-canary checks, and the launcher ran `--version`
with a dummy key, removed planted config, and refused a symlinked config
directory and a missing token. The `composer-2.5` panel (above) ran in this
image.

Telemetry. `result.usage` covers one process, not the session, so the
episode's tokens are the sum of every result (`inputTokens` is uncached;
`cacheReadTokens` and `cacheWriteTokens` are added to make the inclusive
input). A killed invocation writes no result, so its tokens are lost and
`usage_complete` is false. `api_calls` counts completed invocations;
`harness.model_steps` counts distinct `model_call_id` values on tool events,
which is a lower bound on model requests. Cost is `None`, and the
API-equivalent estimate is `None` for any model `pricing.json` does not
price, including Cursor's Composer models. GM-Bench calls are
`mcpToolCall` events recorded as `gm-bench_<tool>`. `getMcpToolsToolCall`
(Cursor reading a tool schema from its cache) never reaches the server and
is recorded as `get_mcp_tools`.

Errors. A failed run prints plain text on stderr and writes no `result`.
The driver reads the stderr that each invocation added. Rate limits,
`resource_exhausted`, `unavailable`, 408, 425, 429 and 5xx statuses,
timeouts and dropped connections count as provider stalls. A spent plan
allowance (`usage limit`, `hit your ... limit`) is quota exhaustion. Cursor
gives no reset time, so the episode and the panel stop. Neither message has
been seen live yet.

## Private panel

A full row is the 32-seed private panel (`docs/bench_v2_spec.md`, Panel
design). `config/bench_v2_lane.json` commits to it by digest only: the
execution hash of the ordered seeds, `artifact_panel_sha256` (the
`panel.sha256` a published panel row must carry), and a salted hiding
commitment. Positions 1 to 29 are the `sota-v5` private panel in its
committed order, which is what pairs a model's 1.0 and 2.0 scores per seed;
positions 30 to 32 were drawn 2026-09-22 by
`scripts/draw_bench_v2_private_panel.py` with the generator that drew v5.
The seeds and salt live in the macOS Keychain
(`gm-bench-bench-v2-private-panel`).

On a host without the Keychain (a Linux driver host), the launcher reads a
copy of the same record from
`~/.config/gm-bench/gm-bench-bench-v2-private-panel.escrow`: the exact
output of `security find-generic-password -s gm-bench-bench-v2-private-panel
-a nedcutler -w`, made on the Mac, owned by you, with no group or other
access on the file or on `~/.config/gm-bench`. A link, a shared file or a
missing file is refused. The copy is checked against the same committed
digests as the Keychain, so it cannot give the driver a different panel;
what it adds is one more place the seeds are kept, so keep that host's
disk to yourself. Make the copy in a Terminal on the Mac itself: over SSH
the login Keychain refuses (`security` exits 36, interaction not allowed).

```bash
python scripts/run_bench_v2_panel_from_keychain.py --verify-only
python scripts/run_bench_v2_panel_from_keychain.py \
    --harness codex --isolation container --model gpt-6-luna \
    --codex-auth-file /path/to/codex-auth.json \
    --output /path/outside/the/checkout/run
```

Always pass `--isolation container`. The launcher keeps the seeds off
command lines, but without a container the harness runs as your user: the
agent's shell can `ps` the driver, find the run directory, and read the
seeds from the ledger headers there, as the same-user red-team probe did.
Such a run redacts as `smoke` at best, and it has exposed private seeds to
the model. Never run a same-user panel on the private seeds.

`--verify-only` checks the escrow against every committed digest and prints
only the result. A run first refuses to start while any driver or contract
file differs from `HEAD` (or the checkout is not a git work tree), before it
touches the Keychain: commit the change, so the row names a commit that
replays it. It then checks the same digests, refuses to start until the
lane's `owner_attestation_status` is `attested-before-seed-access`, and then
runs `gm-bench agentic --seeds-stdin` in its own process with the seeds on
standard input. No command line or environment variable carries them.
It refuses to start without `--isolation container`: a same-user harness
runs as your user and its shell can read the run directory (and `ps`), so
the private seeds would leak. Only
`--i-understand-same-user-leaks-private-seeds` overrides that.
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
    | python scripts/agentic_red_team.py --model opencode/space-bunny-free --output /tmp/red-team-container \
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
