# Changelog

This changelog records public GM-Bench releases: what evidence each one freezes
and what it does not claim. Frozen releases are never rerun or rewritten; a
correction becomes a new contract version rather than an edit to an old one.

## Unreleased — GM-Bench 2.0 spec and agentic lane scaffolding

Added 2026-09-20. Nothing published changes.

- Naming: the frozen `sota-v5` contract, with its decision-model lane, is
  **GM-Bench 1.0**. **GM-Bench 2.0** is a new contract, specified in
  `docs/bench_v2_spec.md`: the same simulator and seeds, driven by a model's
  own harness through an MCP tool server instead of one prompt per phase.
  Rows are model + harness + harness version, budgets are reported rather
  than capped, and the panel is 32 private seeds (the 29 from 1.0 plus 3).
- Code: `gm_bench/agentic/` (tool surface, task brief, episode engine with a
  replayable ledger, standard-library MCP server, OpenCode driver, ledger
  audit) and the `gm-bench agentic` subcommand. Operator guide in
  `docs/agentic_lane.md`. No 2.0 result is published or claimed yet.
- Publication: `gm-bench agentic-redact` writes one compact artifact per row
  under `results/agentic/` (format `gm-bench-agentic-summary-v1`), bound to
  the operator-held raw run by SHA-256, seeds redacted, graded `panel` or
  `smoke` by the spec's rules (32 seeds, redaction, harness isolated from
  the driver). CI validates every committed row against the checkout's 2.0
  contract. Rows committed so far are `smoke` grade on public seeds.
- Sandbox: the engine and seed stay in the driver process and serve MCP over
  a private socket through a standard-library proxy the harness launches.
  A red-team probe (`scripts/agentic_red_team.py`) confirmed the agent
  learns nothing from its workspace and everything from `ps` on a same-user
  machine, so isolation is recorded per row and required for panel grade.
- Private panel: the 32-seed panel is drawn and frozen in
  `config/bench_v2_lane.json` by digest only (execution hash, the hash a
  panel row must carry, and a salted hiding commitment). Seeds 1 to 29 are
  the `sota-v5` private panel in its committed order; three new seeds were
  drawn 2026-09-22 with the same generator and escrowed in the Keychain.
  `scripts/run_bench_v2_panel_from_keychain.py` verifies the escrow and runs
  the panel with seeds on standard input (`gm-bench agentic --seeds-stdin`),
  never on a command line. With `--seeds-stdin`, episode directories are
  named by position (`episode-00`, ...) so the harness's open files do not
  name a seed, and every harness now gets `/dev/null` as stdin. Panel
  execution waits for the owner attestation.
- Site and panel-row checks: `agentic-validate` and `agentic-redact` reject a
  `panel`-grade row whose `panel.sha256` or distinct-seed count differs from
  the frozen panel in `config/bench_v2_lane.json` (smoke rows are exempt).
  `web/scripts/build_study.py` emits an `agentic_lane` block with panel-grade
  rows only, and the site gains a GM-Bench 2.0 section that renders nothing
  until such a row exists. A row whose model is not listed under
  `model_pinning` in the lane config shows the spec's `unpinned` flag and
  may-not-be-reproducible sentence; rows are ordered by model and harness,
  not score, and show no 1.0 row's score. The results-data validator
  keeps 2.0 rows out of every 1.0 table. No panel-grade row exists yet, so
  the site is unchanged.
- Reference contrast: a `panel`-grade artifact now carries the spec's one
  supported inference, a `reference` block comparing the row with
  `pick-trader` on the same seeds and seasons. `agentic-redact` computes it
  from the raw run's seeds in-process, playing `pick-trader` and `random`
  through the 1.0 runner's baseline path with the baseline cache off, so the
  numbers match a 1.0 run on those seeds, `--raw` recomputes them from the
  simulator rather than a local file, and no private seed lands in a cache
  key. It holds the pick-trader and random means, the paired
  lift with its 95% interval, standard deviation, sign-flip p-value, and seed
  win rate, with `per_seed` empty and no seeds or paths. Smoke rows get none.
  Validation rejects a panel row without the block, a block off the row's
  seed count, per-seed values, or another agent, and a smoke row with one,
  plus numbers the paired statistics cannot produce (a lift that is not the
  row mean minus pick-trader's, an interval that excludes its lift or is
  wider than its spread allows, a 0 or 1 win rate against the lift's sign);
  `agentic-validate --raw` recomputes it. `config/bench_v2_lane.json` gains
  `reference_scores`, the frozen panel's 5-season pick-trader (249.18) and
  random (90.367) means, computed directly on the escrowed panel; every
  5-season panel row must carry them, and rows at any other season count
  must agree with each other. The site's 2.0 section shows it as
  "vs pick-trader (same seeds)", and the results-data validator now requires
  that on-panel reference and rejects any other p-value on a 2.0 row.
- Container isolation: `gm-bench agentic --isolation container` runs the
  OpenCode harness in Docker (pinned image, only the scratch directory
  mounted, no host processes, config, or credentials visible) while the
  engine and seed stay in the driver, which now records the isolation it
  launched; `agentic-redact` refuses a stronger claim. The container's
  egress is firewalled: it reaches the public internet and DNS, and on the
  host only the driver's port, so host-loopback services (model servers,
  agent servers, tunnels) are out of reach; a canary check proves this
  before every episode and `harness.container.egress` records the rule.
  The contract moves to `07de948a4f4afbae`: the socket server gains a
  loopback TCP transport with a per-run secret (Docker Desktop cannot pass
  a Unix socket through a bind mount), no longer serves a connection
  accepted after `stop()` begins, and counts only served connections in
  `proxy_connections` and every failed secret presentation (including
  non-UTF-8 bytes) in `proxy_connections_refused`, and the engine can take
  a provider-stall backoff off the phase guard clock (below), so the
  committed smoke row must be rerun on the new contract.
- Provider stalls: a harness run that ends on a retryable provider error
  (a 429 rate limit, an overload, a 5xx) is no longer treated as the agent
  stopping. The driver waits (60 s, doubling, capped at 600 s; by default
  at most 48 retries and 6 hours per episode, set with
  `--max-provider-stalls` and `--max-provider-stall-wait-seconds` and
  recorded in `run.json` and the published row, so a panel can wait out a
  provider's quota window) and resumes the session without
  spending a nudge, and records `provider_stalls` and
  `provider_stall_wait_seconds` per episode, carried into published rows.
  The wait is taken off the open phase's guard clock and logged in the
  ledger as a `clock_pause` event, which replay and the audit ignore.
- Second harness: `gm-bench agentic --harness codex` drives the Codex CLI
  (`codex exec --json`, written against Codex CLI 0.156.1) through the same
  episode loop as OpenCode, which now sits behind a small driver interface
  (`gm_bench/agentic/harness.py`; OpenCode's names and behaviour are
  unchanged). Each episode gets its own private `CODEX_HOME`, outside the
  agent's working directory, holding one staged MCP server entry whose
  tools are approved (`codex exec` would otherwise refuse every GM-Bench
  call in its `workspace-write` sandbox), so the host `~/.codex` (login,
  `AGENTS.md`, skills, rules) and `~/.agents/skills` never reach the
  harness. Nudges and provider-stall
  retries resume the same session with `codex exec resume`. Credentials come
  from `--codex-auth-file` (or `CODEX_API_KEY` for same-user runs); in
  container mode the file is written into the episode's home volume over
  stdin, never onto a command line or into the mounted scratch directory,
  and the harness runs from its own pinned image
  (`@openai/codex@0.156.1`). Credential values the agent prints are
  redacted from the retained event stream and stderr log. Codex reports
  tokens but not cost, per-call counts, or compactions, and those are
  recorded and published as unmeasured (no list-price cost estimate, no
  summed zero compactions). Tool calls Codex refuses before dispatch are
  counted apart, not as harness calls. `agentic-validate` recounts tool
  calls from a Codex event stream as it does for OpenCode. Tested only against a stand-in `codex` and `docker`;
  no Codex episode has been run and no Codex result is claimed.
- Codex API-equivalent cost: `cost_usd` stays unmeasured, and beside it a
  Codex episode now records `usage.harness.api_equivalent_cost_usd`, what
  its tokens would cost at OpenAI API list price with cached input and
  cache writes at their own rates, labelled `cost_basis:
  "api-list-price-estimate"` and `billed_by_harness: false`, with the
  pricing entry used and a flag when a turn grew past the 272K
  long-context threshold (short-context rates are always used, so the
  estimate may then be low). It reaches the compact artifact, the run's
  `agentic_summary`, and the site, which marks it `est.` and never shows
  it as a billed cost. `gm_bench/pricing.json` entries may now carry
  `cached_input_per_mtok`, `cache_write_per_mtok`,
  `long_context_input_tokens`, and `verified`; existing entries are
  unchanged. Added `gpt-6-luna` ($0.10 input, $0.01 cached, $0.125 cache
  write, $0.50 output per million tokens) and `gpt-6-sol` ($2.00, $0.20,
  $2.50, $10.00), checked 2026-09-23 against OpenAI's developer pricing
  page and model pages.
- One token shape for every harness: `input_tokens` is now the inclusive
  total (uncached + cached + cache-write, each also published as
  `uncached_input_tokens`, `cached_input_tokens`,
  `cache_write_input_tokens`) and `output_tokens` includes reasoning, with
  `reasoning_tokens` a subset, marked `token_shape: "inclusive-v1"`. Codex
  already reported that way; the OpenCode parser now adds cache reads and
  writes into input and reasoning into output (as T3 Code's OpenCode
  adapter does), so OpenCode token totals and `max_output_tokens_per_call`
  are larger than in earlier runs. The committed OpenCode smoke row predates
  the shape and still validates; the site labels such rows' tokens as the
  harness's own convention.
- Corrected stale list prices in `gm_bench/pricing.json` from the official
  pages, checked 2026-09-23: `gpt-5.6-terra` $2/$12 (was $2.50/$15),
  `gpt-5.6-luna` $0.20/$1.20 (was $1/$6), and `claude-sonnet-5` $2/$10
  (was $3/$15), with their cached-input and cache-write rates. `gpt-5.6-sol`
  stays at $5/$30: OpenAI lists its $4/$20 as promotional pricing available
  at least through 2026-11-21, and this table pins undiscounted rates.
  Published results do not change: their costs are what the provider
  reported when they ran.
- Codex quota windows: after each episode the driver reads the
  subscription's usage windows from the Codex session rollout (percent used,
  window length, reset time, and plan; never credits or tokens) into
  `harness_run.quota_windows` and `plan_type`, and a panel pauses before
  the next episode until a window at or above 95% resets (bounded by
  `--max-provider-stall-wait-seconds`), recorded in `run.json`
  `quota_pauses`. Both reach the compact artifact and a short quota note on
  the site row.
- Codex usage limits are quota exhaustion, not provider stalls. The first
  real Codex launch ended its first turn on "You’ve hit your usage limit
  ... try again at Sep 24th, 2026 4:19 PM", which the driver had treated as
  a stall and started a 60-second backoff ladder that could have spent the
  whole 6-hour wait budget. The driver now reads the reset time (Codex's
  local-time format, ordinal suffixes, 12-hour clock, same-day time only),
  pauses until it plus a minute when that fits the wait budget and resumes
  the session (neither a nudge nor a stall retry), and otherwise stops the
  episode (`harness_run.ended_by_quota`) and the panel (`run.json`
  `stopped_for_quota`) instead of starting seeds that would fail the same
  way.
- Third harness: `gm-bench agentic --harness claude` drives Claude Code
  (`claude -p --output-format stream-json`, written against 2.1.281) through
  the same episode loop. Each same-user episode gets a
  private `CLAUDE_CONFIG_DIR` holding one staged MCP server, loaded with
  `--strict-mcp-config`, `--setting-sources user` and
  `--disable-slash-commands`, so the host's settings, login, `CLAUDE.md`,
  skills, plugins, hooks and MCP servers never reach the agent; the
  GM-Bench and code tools run under `--permission-mode dontAsk` with an
  allow list. Nudges resume with `--resume`. The credential is a
  `claude setup-token` token from `--claude-token-file` (or
  `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_API_KEY` from the environment),
  redacted from the evidence. Cost is unmeasured with a per-model
  API-equivalent estimate beside it; usage limits pause or stop the episode
  and panel as for Codex, including a run that waits inside the process on
  a rejected window, which the shared loop now polls for and stops
  (`HarnessDriver.invocation_parked`). The contract fingerprint is
  unchanged.
- Claude Code in a container: `--harness claude --isolation container` runs
  Claude Code 2.1.281 from its own pinned image
  (`gm-bench-agentic-claude:2.1.281-<Dockerfile hash>`: the shared
  digest-pinned Node base, egress firewall entrypoint and unprivileged
  user, plus a `gmb-claude` launcher). It needs `--claude-token-file`: the
  token travels on the stdin of a throwaway `docker run` into the episode's
  home volume (mode 0600) and the launcher exports it inside the container,
  so it is never on a `docker run` command line, in `-e`, in `docker
  inspect`, or in the bind-mounted scratch, and it is redacted from the
  evidence as before. The agent runs as the same user as Claude Code, so it
  could plant a `settings.json` (hooks, an `env` block) or `CLAUDE.md` in the
  config directory for the next resume: the image makes that directory
  root-owned and sticky with read-only placeholders, the launcher checks the
  layout before every launch and refuses to start on a changed one, and
  same-user runs now remove those entries and rewrite `mcp.json` before
  every launch (`harness_run.config_dir_guard`, `config_dir_findings`; new
  `HarnessDriver.before_invocation`). The run records `isolation: container`
  and the image under `harness.container`, so a container Claude row can be
  panel grade under the existing rules. A Docker that is missing or not
  running now ends `gm-bench agentic` with a one-line error. Tested against
  a stand-in `claude` and `docker` and, with no model call, against the real
  image (opt-in `GM_BENCH_DOCKER_TESTS=1`); no container Claude episode has
  run and no Claude result is claimed. The contract fingerprint is
  unchanged.

## Unreleased — decision-model lane beside the `sota-v5` headline

Added 2026-09-18. Nothing in the frozen `sota-v5` release changes; the eleven
headline rows, the Holm family of sixteen, and the release archive are as
published on 2026-09-03.

- New lane: `decision-api`, for a model that answers typed questions instead
  of writing the action batch. The adapter (`examples/typesafe_jev_agent.py`)
  asks TypeSafe's Jev a fixed question set per decision and composes the
  batch under published rules, so a row measures the model plus that scaffold.
- One row: `typesafe/jev-1.13` (served `jev-1.13-20260917`) over OpenRouter's
  decisions endpoint on the `sota-v5` contract and the same 29-seed private
  panel. Mean 229.0, +53.7 against the baseline-panel mean, -18.1 against
  `pick-trader` (unadjusted sign-flip p 0.081), 8 illegal actions, $0.33.
  Artifact in `results/leaderboard/decision-lane/`, analysis in
  `results/analysis/decision-lane-typesafe-jev-1.13-openrouter.md`.
- Publication shape: the row is redacted like the headline rows, validates
  under the `sota-v5` policy with its own scaffold fingerprint
  (`e1fc1e298283f465`, added to the policy's fingerprint map), and is served
  on the site in a separate "Decision-model lane" section. It never enters
  the headline `models` array, the eligible-headline count, the shot chart, or
  the Holm family, and CI checks that separation.
- Not claimed: no pre-registration, no Holm-adjusted p-value, no comparison
  with any headline chat-lane row.

## sota-v5-publication-2026-09-03 — first public panel under `sota-v5`

Released 2026-09-03. Contract fingerprint `a600b7da0c302231`, OpenRouter
scaffold `c582e126bbb6af10`.

- Frozen evidence: a private 29-seed panel, one episode per seed, zero repair
  attempts, a 4,096-token output ceiling, and the v6-spec sixteen-model cohort.
  The seed panel is committed by execution hash and salted hiding commitment in
  `config/sota_v5_lane.json`; seed values and raw traces are not published.
- Sixteen pre-registered cells, all accounted for: eleven strict, route-matched,
  cost-complete headline rows at 580 of 580 decisions each; three ineligible on
  model behavior under rules frozen before the panel ran (gpt-oss-20b at a
  0.0207 decision failure rate over the 0.020 gate, claude-haiku-4.5 fail-fast
  at seed 14, glm-5 fail-fast at seed 25); and two excluded at the two-attempt
  infrastructure limit with no artifact (qwen3.8-flash on HTTP 429, gpt-5.6-sol
  on billed responses with no choices).
- Result: the analysis is reference-only against the deterministic
  `pick-trader` baseline (mean 247.109). Every eligible model trails it. Ten of
  the eleven headline rows reject at Holm-adjusted alpha 0.05 against the
  registered family of sixteen; gemini-3.7-flash (mean lift -23.4, Holm-adjusted
  p 0.221) does not. No model-to-model tiers or ordinal ranking are assigned.
- Limits: within-seed noise is unmeasured under the one-repeat lane, so the
  minimum detectable difference rests on the calibration panel's assumed repeat
  noise. The accounted-for rule and the headline floor of eight were amended
  after the panel completed; the amendment is recorded as a post-data owner
  decision in
  `docs/run_logs/sota-v5-v6-route-and-cohort-amendment-2026-09-01.md`. Nothing
  about how a row was run, scored, or gated changed.
- Also recorded and not fixed: the luna row billed about $0.125 per million
  prompt tokens against the $0.10 snapshot; transient-retry counts live only in
  the spend guard's ledger; the grok-4.6 attempt-1 reservation is still marked
  active.
- Artifacts: `releases/sota-v5-publication-2026-09-03/` holds the manifest,
  `SHA256SUMS.txt`, and a README. The archive
  `gm-bench-sota-v5-publication-2026-09-03.zip` (SHA-256
  `7fa7ae546132e96c87546683bbe4de4d88c2715c40b439ee48332d166829eef2`) is
  attached to the release rather than committed. See
  `docs/REPRODUCING_SOTA_V5_RELEASE.md` for verification without provider
  credentials.

## sota-v2-phase-one-2026-07-19 — phase-one public study

Released 2026-07-19. This is the study the public website serves.

- Frozen evidence: eight of ten pre-registered OpenRouter cells produced strict,
  route-matched, cost-complete `sota-v2` rows on the public eight-seed panel
  under a shared 4,096-token native-minimum-reasoning lane. Grok 4.5 and
  Mistral Medium 3.5 completed but were held as diagnostics for incomplete
  usage and cost coverage.
- Result: every eligible model trailed the `pick-trader` heuristic (411.619),
  and all eight rows fell in one overlapping uncertainty tier, so no ordinal
  model ranking was published.
- Context: this release followed the withdrawal of the archived v1 comparison,
  which was confounded by a scout protocol bug, unequal output budgets, and
  mixed execution lanes. The archived v1 data is retained as withdrawn
  historical evidence, not current evidence.
- Artifacts: `releases/sota-v2-phase-one-2026-07-19/`, the findings writeup in
  `docs/blog/sota-v2-findings.md`, and the clean-clone guide in
  `docs/REPRODUCING_SOTA_V2_RELEASE.md`.
