# Changelog

This changelog records public GM-Bench releases: what evidence each one freezes
and what it does not claim. Frozen releases are never rerun or rewritten; a
correction becomes a new contract version rather than an edit to an old one.

## Unreleased — GM-Bench 2.0

Work began 2026-09-20; the contract froze 2026-09-25; three panel-grade rows
were published 2026-09-27, a fourth 2026-09-28, a fifth 2026-10-12 (its
panel ran 2026-09-28 to 09-29), a sixth to ninth 2026-10-13, and a tenth
to twelfth 2026-10-14. Not yet tagged. Nothing in GM-Bench 1.0 changes.

Summary:

- **Contract.** GM-Bench 2.0 (`gm-bench-2.0`, agentic fingerprint
  `07de948a4f4afbae`, on the 1.0 contract `a600b7da0c302231`): the 1.0
  simulator and scoring, driven by a model inside its own agent harness
  through a standard-library MCP tool server, one continuous five-season
  session per episode. Budgets are reported, not capped. A row is model +
  harness + harness version. Specified in `docs/bench_v2_spec.md`,
  operated with `docs/agentic_lane.md`. The fingerprint covers
  `gm_bench/agentic/{tools,brief,episode,mcp_server}.py` and has not moved
  since the freeze.
- **Harnesses.** The committed rows ran on OpenCode 1.18.31 and 2.0.27, Codex CLI
  0.156.1 and 0.162.1, Claude Code 2.1.281 and the Cursor CLI
  2026.09.26-dd393fe, each from a pinned Docker image. The images now pin
  OpenCode 2.0.27 and Codex CLI 0.162.1.
  Every committed row ran at the harness's default reasoning effort (no
  `--variant`). Claude Code runs without web tools and with its GM-Bench
  tools deferred behind ToolSearch; OpenCode, Codex and Cursor keep their
  built-in tools. Cursor's servers add seven default User Rules to every
  prompt; a prompt gate admits those and refuses any other rule.
- **Isolation.** The engine and seeds stay in the driver process. Panel
  rows need the harness in a container (`--isolation container`) with a
  firewall that allows only the public internet, DNS and the driver's port.
  No driver launches `separate-user` isolation. Red-team probes found the
  seed on a same-user machine (through `ps`) and did not find a private-range
  seed from inside a container.
- **Panel rows** (32 private seeds, five seasons, container, all flagged
  `unpinned`), each compared only with `pick-trader` (249.18 on these 32
  seeds):
  - Codex 0.156.1 · `gpt-6-luna`: mean 227.4, lift −21.8 (95% interval
    −43.3 to +0.1), not significant.
  - Claude Code 2.1.281 · `claude-sonnet-5`: mean 227.4, lift −21.8
    (−47.2 to +3.5), not significant.
  - Claude Code 2.1.281 · `claude-haiku-4-5`: mean 130.1, lift −119.1
    (−132.8 to −104.5), below `pick-trader` on every seed. Admitted under
    the post-hoc guessed-draft-pick rule below.
  - Cursor 2026.09.26-dd393fe · `composer-2.5`: mean 230.6, lift −18.6
    (−35.6 to −1.4, p = 0.047), significant; ahead of `pick-trader` on 12
    of 32 seeds. No cost figure: Cursor reports none and `composer-2.5`
    has no list price.
  - OpenCode 1.18.31 · `opencode-go/deepseek-v4.1-flash`: mean 247.1, lift
    −2.0 (−22.4 to +18.0, p = 0.84), not significant; ahead of
    `pick-trader` on 15 of 32 seeds. OpenCode reports $3.69 for the panel.
  - Codex 0.162.1 · `gpt-6.1-sol`: mean 273.2, lift +24.0 (+1.6 to +45.8,
    p = 0.046), significant; ahead of `pick-trader` on 23 of 32 seeds. The
    first 2.0 row whose interval lies above zero. No measured cost.
  - Claude Code 2.1.281 · `claude-haiku-5-5`: mean 202.7, lift −46.5
    (−66.7 to −26.7, p = 0.0002), significant; ahead of `pick-trader` on 9
    of 32 seeds; 393K tokens per decision. No measured cost; the
    API-equivalent estimate ($4.89) is a
    lower bound, about $12 to $16 with Haiku 5.5's over-100K-token tier.
  - Codex 0.162.1 · `gpt-6-astra`: mean 288.4, lift +39.2 (+15.6 to
    +63.1, p = 0.0036), significant, and still so under a Holm correction
    across the twelve rows; ahead of `pick-trader` on 20 of 32 seeds; 123K
    tokens per decision. No measured cost; the API-equivalent estimate
    ($115.04) is a lower bound.
  - OpenCode 2.0.27 · `opencode-go/deepseek-v4.1-flash`: mean 244.6, lift
    −4.6 (−25.8 to +17.0, p = 0.67), not significant; ahead of
    `pick-trader` on 12 of 32 seeds; 661K tokens per decision. OpenCode
    reports $4.91 for the panel.
  - Claude Code 2.1.281 · `claude-sonnet-5-5`: mean 217.1, lift −32.1
    (−56.3 to −9.7, p = 0.012), significant, but not under a Holm
    correction across the twelve rows (adjusted p about 0.097); ahead of
    `pick-trader` on 11 of 32 seeds; 295K tokens per decision. No measured
    cost; the API-equivalent estimate is $38.31. Admitted under the
    post-hoc guessed-signing rule below.
  - Claude Code 2.1.281 · `claude-opus-5-5`: mean 202.5, lift −46.7
    (−69.6 to −21.3, p = 0.001), significant, and still so under a Holm
    correction across the twelve rows (adjusted p about 0.010); ahead of
    `pick-trader` on 7 of 32 seeds; 540K tokens per decision. No measured
    cost; the API-equivalent estimate is $129.12.
  - OpenCode 2.0.27 · `opencode-go/muse-spark-1.3-contributor`: mean
    250.3, lift +1.2 (−17.2 to +19.5, p = 0.91), not significant; ahead of
    `pick-trader` on 16 of 32 seeds; 604K tokens per decision. OpenCode
    reports $1.70 for the panel (its own figure at Muse Spark 1.3's
    discounted Contributor rates, where Meta may train on the prompts and
    completions, counted against the OpenCode Go plan's limits rather than
    billed per token); the same tokens at the model's list price are an
    estimated $69.90.

  The realized paired-lift SDs (62.5 and 73.4) put the panel's minimum
  detectable difference against `pick-trader` at about 31 to 36 points, so
  the two −21.8 lifts mean "cannot tell", not "on par". The `gpt-6.1-sol`
  lift (+24.0, lift SD 64.0, MDD about 32) is significant but smaller than
  that row's own MDD, and the interval's lower bound is +1.6: one unpinned
  row on one panel, resolved with little margin. The `gpt-6-astra` lift
  (+39.2, lift SD 68.6, MDD about 34) is larger than its row's MDD. The
  `claude-sonnet-5-5` lift (−32.1, lift SD 67.5, MDD about 33) is about
  the size of its row's MDD. The `claude-opus-5-5` lift (−46.7, lift SD
  68.8, MDD about 34) is larger than its row's MDD. The Muse Spark 1.3
  lift (+1.2, lift SD 53.8, MDD about 27) is "cannot tell".
- **Smoke rows and noise probes** (public seeds, not on the site): an 8-seed
  OpenCode row on `opencode/space-bunny-free`, one five-season episode each
  on Codex, Claude Code and OpenCode 2.0.27, and a 4 seeds × 2 runs repeat-noise probe on
  each paid harness.
- **Changes after the freeze**, none of which moved the fingerprint:
  driver fixes and driver provenance (every row records the driver commit
  that played it; the Codex and `claude-sonnet-5` panels ran at `4d742cc`,
  `claude-haiku-4-5` at `21b71dc`, which differs only in Claude Code
  tool-call counting, `composer-2.5` at `b3d7de7`, the first commit
  with the Cursor container driver, `deepseek-v4.1-flash` at `07de4b2`,
  the first with OpenCode Go keys, `gpt-6.1-sol` at `1411e2e`, the
  first with Codex 0.162.1 and without the account's apps and plugins, and
  `claude-haiku-5-5` at `3e8e600`, the first Claude row without the
  account's claude.ai connectors, the OpenCode 2.0.27 `deepseek-v4.1-flash`
  at `93b1f7c`, the first with the OpenCode 2.x launcher, `gpt-6-astra`
  at `5d56c71`, `claude-sonnet-5-5` at `0f3042d`, `claude-opus-5-5`
  at `73c949b`, and `muse-spark-1.3-contributor` at `3b82ca1`, both with
  the same driver files as `0f3042d`); a
  validation rule that publishes a
  tool-call recount when it resolves a recorded mismatch (one
  `claude-sonnet-5` episode and one OpenCode 2.0.27 episode); and
  two post-hoc audit rules, each adopted after the panel it admits had
  run: a draft pick on a guessed prospect id (2026-09-27, the Haiku 4.5
  panel) and a free-agent signing on a guessed player id (2026-10-14, the
  Sonnet 5.5 panel) are warnings, not violations. The spec now states which files are frozen and which rules may
  change without a new version, and lists every post-freeze change with
  the rows it affected.
- **Not claimed:** no ranking of rows, harnesses or models; no p-value
  between two rows; no 1.0-versus-2.0 pairing (no 2.0 model has a 1.0 row).
  Contract-level defects found after the freeze are queued in
  `docs/bench_v2_1_queue.md`.

### Development log

The entries below were written as the work landed, roughly in order.
Interim statements that nothing was published yet have been removed or
dated; the summary above is the current state.

- Twelfth panel-grade 2.0 row (2026-10-14): OpenCode 2.0.27 on
  `opencode-go/muse-spark-1.3-contributor` (Meta Muse Spark 1.3, Contributor
  tier, through OpenCode Go), the frozen 32-seed private panel at five
  seasons, container isolation, played 2026-10-14 from clean `main` at
  `3b82ca1` (driver digest `0c20d2de9ce62901`, the same as the
  `claude-sonnet-5-5` and `claude-opus-5-5` rows'; image
  `gm-bench-agentic-opencode:2.0.27-68c6a0dff0b9`; phase guard 1,200 s; no
  `--variant`)
  (`results/agentic/opencode-2.0.27-muse-spark-1.3-contributor-panel-32x5.json`).
  Mean 250.3 (SD 48.6, seed means 154.6 to 363.8), 640/640 phases closed
  by the agent, 0 failed decisions, 1 penalized illegal move (episode 23
  released a player not on its roster), 0 nudges, 14 empty phases, no
  guard stops, no provider stalls, no silent harness kills, no
  compactions, 604K tokens per decision (cached input included), 149.3
  tool calls and 5.6 min per episode (2.98 h for the panel), ledger =
  harness on 32/32 episodes (4,778/4,778 calls), all of them GM-Bench
  calls: no shell, file or `execute` call. The ledger audit found no
  violations, nothing suspicious and no guessed reads, drafts or signings.
  Against `pick-trader` the paired lift is +1.2, 95% interval −17.2 to
  +19.5, sign-flip p 0.91, ahead on 16 of 32 seeds, with a realized MDD of
  about 27: level with `pick-trader`, as both DeepSeek rows are. Against
  the OpenCode 2.0.27 `deepseek-v4.1-flash` row on the same seeds it is
  +5.7 per seed and ahead on 19 of 32, no real difference, with fewer
  calls (149 against 160 per episode) and less time (5.6 against 14.6
  min). Tokens come from OpenCode's session export in every episode:
  385.7M input (98.0% cache reads), 0.80M output (0.47M reasoning).
  OpenCode reports $1.70 for the panel (its own figure at the Contributor
  rates, $0.10 input, $0.002 cached input, $0.20 output per million
  tokens, counted against the OpenCode Go plan's limits rather than billed
  per token; a recompute from the tokens matches). The Contributor tier is discounted
  because Meta may train on its prompts and completions, and OpenCode
  serves it only to a workspace that allows paid endpoints that train on
  request data: the first smoke attempt was refused with a 400 for that
  reason before any move (nothing spent, not published). At Muse Spark
  1.3's standard list price ($1.25, $0.15 cached, $4.25 output, no
  long-context premium) the same tokens cost an estimated $69.90 (about
  41x). Reasoning effort is the harness default (OpenCode reports none).
  The model is unpinned.

- Meta Muse Spark 1.3 priced and smoked (2026-10-14): `muse-spark-1.3`
  and `muse-spark-1.3-contributor` entries in `gm_bench/pricing.json`
  (verified 2026-10-14 against https://dev.meta.ai/docs/pricing-rate-limits/),
  and a one-episode, five-season container smoke on a public seed
  (`results/agentic/opencode-2.0.27-muse-spark-1.3-contributor-smoke-1x5.json`,
  score 281.6, $0.05 as OpenCode reports it). `agentic-redact` now adds an
  API-equivalent list-price estimate to an OpenCode row on a discounted tier
  with a `list_price_key` in `pricing.json`, from the recorded
  token counts, beside the cost OpenCode reports (`cost_usd`). A new
  optional pricing field, `list_price_key`, marks a discounted tier, and
  only this OpenCode estimate reads it: it prices that tier's tokens at
  the named entry's undiscounted rates and records `discounted_tier_key`
  (`telemetry.api_equivalent_cost_usd` is unchanged). The recorded (empty) fields
  are kept under `api_equivalent_recomputed`, and the summary's under
  `api_equivalent_recorded`. Rows recorded before the shared token shape,
  and unpriced models such as the two DeepSeek rows, are unchanged. The
  site shows a row whose reported cost is at a discounted data-sharing
  tier at the model's list price ($2.18 per game, labelled an estimate),
  with OpenCode's $0.05 a game beside it in the model panel; every other
  row keeps showing the cost its harness reports when it has one.

- Eleventh panel-grade 2.0 row (2026-10-14): Claude Code 2.1.281 on
  `claude-opus-5-5`, the frozen 32-seed private panel at five seasons,
  container isolation, played 2026-10-14 (about 13:13 to 19:45 UTC) at
  `73c949b` (branch `price-claude-opus-5-5`: `main` at `0f3042d` plus the
  Sonnet 5.5 pricing entry and smoke (#197) and the Opus pricing entry;
  clean driver, digest
  `0c20d2de9ce62901`, the same as the `claude-sonnet-5-5` row's; image
  `gm-bench-agentic-claude:2.1.281-f0e72cbaea92`)
  (`results/agentic/claude-2.1.281-claude-opus-5-5-panel-32x5.json`).
  Mean 202.5 (SD 56.4, seed means 120.3 to 327.8), 640/640 phases closed
  by the agent, 0 failed decisions, 59 penalized illegal moves (147.5
  penalty points; 33 of them a draft-pick season outside the tradable
  window), 0 nudges, 78 empty phases, no guard stops, no provider stalls,
  no compactions, 540K tokens per decision (cached input included), 152.7
  GM-Bench tool calls and 6.5 min per episode, ledger = harness on 32/32
  episodes (4,887/4,887 calls). One quota pause: after episode 25 the
  five-hour window read 98% used, and the driver waited about 3.0 hours
  (10,963 s) for the 19:00 UTC reset and went on, the first quota pause on
  a Claude row; no episode was ended by quota. Against `pick-trader` the
  paired lift is −46.7, 95% interval −69.6 to −21.3, sign-flip p 0.001,
  ahead on 7 of 32 seeds, with a realized MDD of about 34; Holm-adjusted
  across the eleven rows, p is about 0.009. Against Sonnet 5.5 it gained
  about 12 points per episode on wins, playoffs and titles and lost about
  23 on the end-of-episode roster credit: it played the last season to
  win now and let contracts run out, and three episodes ended with zero
  total assets and zero roster depth. Besides GM-Bench calls the agent made 82
  ToolSearch, 47 Bash, 9 Write, 1 Edit and 1 Grep calls; the Bash, Write
  and Edit calls listed `/work` and Claude Code's memory folder and wrote
  notes into the container's `~/.claude` memory folder or
  `/work/notes.md`. Each episode starts in a fresh container with that
  folder empty, so nothing carried between episodes; no call read the
  proxy secret, credentials, the environment or seeds, and
  `config_dir_findings` is empty in all 32 episodes. The agent made 83
  `draft` calls in 160 draft phases and 695 `trade` calls (21.7 per
  episode; most refused at no cost). Claude Code reports no cost; the
  API-equivalent estimate is $129.12 for the panel ($4.04 per episode),
  priced from the Opus 5.5 entry added before the run (`73c949b`). 339.2M
  of the 344.4M input tokens were cache reads. Reasoning effort is the
  harness default (Claude Code reports none). The model is unpinned.

- Claude Opus 5.5 priced and smoked (2026-10-14): a `claude-opus-5-5`
  entry in `gm_bench/pricing.json` (verified against platform.claude.com
  pricing; $4 input, $20 output, $0.20 cache hits, no long-context tier;
  without its own key the id matched no entry), and a one-episode,
  five-season container smoke on public seed 11
  (`results/agentic/claude-2.1.281-claude-opus-5-5-smoke-1x5.json`, score
  287.1, $3.64 API-equivalent).

- Tenth panel-grade 2.0 row (2026-10-14): Claude Code 2.1.281 on
  `claude-sonnet-5-5`, the frozen 32-seed private panel at five seasons,
  container isolation, played 2026-10-13 to 10-14 from clean `main` at
  `0f3042d` (#196; driver digest `0c20d2de9ce62901`, image
  `gm-bench-agentic-claude:2.1.281-f0e72cbaea92`)
  (`results/agentic/claude-2.1.281-claude-sonnet-5-5-panel-32x5.json`).
  Mean 217.1 (SD 50.3, seed means 127.6 to 341.5), 640/640 phases closed
  by the agent, 0 failed decisions, 37 penalized illegal moves, 0 nudges,
  84 empty phases, no guard stops, no provider stalls, no quota pauses, no
  compactions, 295K tokens per decision (cached input included), 106.6
  GM-Bench tool calls and 2.9 min per episode, ledger = harness on 32/32
  episodes. Besides GM-Bench calls the agent made only 37 ToolSearch
  calls. The agent made 157 `draft` calls in 160 draft phases and 157
  `trade` calls. Against `pick-trader` the paired lift is −32.1, 95%
  interval −56.3 to −9.7, sign-flip p 0.012, ahead on 11 of 32 seeds,
  with a realized MDD of about 33; Holm-adjusted across the ten rows, p is
  about 0.085. The row is admitted under a post-hoc audit rule adopted
  2026-10-14, after the panel ran (#198): in episode 19, preseason of
  season 1, the agent listed 24 of the 36 free agents, signed player 302,
  which the listing had not shown, for one year at the minimum salary,
  said it had used an id it did not mean to, inspected him and released
  him. Under the original rule that accepted signing was a violation and
  failed validation. An accepted `sign_free_agent` whose only unseen id is
  the player it signed is now a `guessed_signing`, a validation warning:
  the general rule applies to every model and season, including retained
  players, without a typo, salary or release condition. IDs encode position
  slots; initial-pool potential correlation does not prove absence of leakage.
  Both-rule raw coverage is recorded in
  `docs/audit-signing-retrospective-2026-10-14.md`. The
  other warnings are a rejected move on an unseen id (episode 3) and the
  guessed read that followed the signing. Claude Code reports no cost; the
  API-equivalent estimate is $38.31 for the panel ($1.20 per episode),
  priced from the Sonnet 5.5 entry added before the run (#197). 184.6M of
  the 188.3M input tokens were cache reads. Reasoning effort is the
  harness default (Claude Code reports none). The model is unpinned.

- Claude Sonnet 5.5 priced and smoked (2026-10-13, #197): a
  `claude-sonnet-5-5` entry in `gm_bench/pricing.json` (verified against
  platform.claude.com pricing; $0.10 cache hits, half Sonnet 5's; without
  its own key the id resolved to the `claude-sonnet-5` prefix), and a
  one-episode, five-season container smoke on public seed 11
  (`results/agentic/claude-2.1.281-claude-sonnet-5-5-smoke-1x5.json`,
  score 146.5, $1.28 API-equivalent).

- Eighth and ninth panel-grade 2.0 rows (2026-10-13), both on the frozen
  32-seed private panel at five seasons, container isolation, driver
  digest `5232221e589b7553`, with a publication change and a driver fix
  they needed:
  - Codex 0.162.1 on `gpt-6-astra`, played 2026-10-13 from clean `main` at
    `5d56c71` (#194; image `gm-bench-agentic-codex:0.162.1-f8095c887ac3`,
    the account's apps, plugins and connectors off)
    (`results/agentic/codex-0.162.1-gpt-6-astra-panel-32x5.json`). Mean
    288.4 (SD 61.1, seed means 203.5 to 409.1), 640/640 phases closed by
    the agent, 0 failed decisions, 58 penalized illegal moves, 0 nudges, 17
    empty phases, no guard stops, no provider stalls, no quota pauses,
    154.9 tool calls and 4.8 min per episode, 123K tokens per decision,
    ledger = harness on 32/32 episodes, and only GM-Bench calls in the
    event streams. The agent made 49 `draft` calls in 160 draft phases and
    435 `trade` calls. Against `pick-trader` the paired lift is +39.2, 95%
    interval +15.6 to +63.1, sign-flip p 0.0036, ahead on 20 of 32 seeds,
    with a realized MDD of about 34; Holm-adjusted across the nine rows,
    p is about 0.025. Codex reports no cost. `pricing.json` had no GPT-6
    Astra entry when the panel ran; the entry was added (verified
    2026-10-13 against its model page: $10 input, $1 cached, $12.50 cache
    writes, $50 output, the 272K long-context tier), and `agentic-redact`
    now re-derives a Codex row's API-equivalent estimate from its retained
    `codex-events.jsonl`, as it already did a Claude Code row's (same
    token-count check, recorded figures kept beside it): $115.04 for the
    panel ($3.59 per episode), a lower bound because every episode had a
    turn whose input grew past 272K. A ChatGPT `prolite` plan's weekly
    window went from 11% to 49% used. Reasoning effort is the harness
    default. The model is unpinned.
  - OpenCode 2.0.27 on `opencode-go/deepseek-v4.1-flash`, played
    2026-10-13 from clean `main` at `93b1f7c` (#193; image
    `gm-bench-agentic-opencode:2.0.27-68c6a0dff0b9`), the same model and
    OpenCode Go plan as the 1.18.31 row, and the re-run of the 2.0.27
    panel #193 set aside
    (`results/agentic/opencode-2.0.27-deepseek-v4.1-flash-panel-32x5.json`).
    Mean 244.6 (SD 52.9, seed means 126.6 to 368.8), 640/640 phases closed
    by the agent, 0 failed decisions, 33 penalized illegal moves, 0
    nudges, 33 empty phases, no guard stops, provider stalls or
    compactions, 160.4 tool calls and 14.6 min per episode, 661K tokens
    per decision. The agent made 125 `draft` calls and 141 `trade` calls;
    besides GM-Bench calls the streams hold one call to `gm-bench-scout`, a
    tool name that does not exist. Against `pick-trader` the paired lift
    is −4.6, 95% interval −25.8 to +17.0, sign-flip p 0.67, ahead on 12 of
    32 seeds, realized MDD about 30: "cannot tell", 2.5 points from the
    1.18.31 row. OpenCode reports $4.91 for the panel. In episode 14
    OpenCode 2.0.27 refused one `trade` call on its own input-schema check
    (`Invalid arguments for tool ...`, raised before the tool runs), so it
    never reached GM-Bench, but the event parser counted it and the run
    recorded 166/167. The parser now counts such a refusal under
    `harness_tool_calls_skipped`, as it does Codex's pre-dispatch
    refusals (a driver change; the fingerprint is unchanged), and the row
    publishes the recount, 166/166, with the recorded figure beside it.
    Episode 19 exited 1 with an empty stderr after the agent had closed
    all 20 phases (a validation warning). The model is unpinned.

- Seventh panel-grade 2.0 row (2026-10-13): Claude Code 2.1.281 on
  `claude-haiku-5-5`, the frozen 32-seed private panel at five seasons,
  container isolation, played 2026-10-13 from clean `main` at `3e8e600`
  (#188; driver digest `5232221e589b7553`, image
  `gm-bench-agentic-claude:2.1.281-f0e72cbaea92`, the first Claude row
  without the account's claude.ai connectors)
  (`results/agentic/claude-2.1.281-claude-haiku-5-5-panel-32x5.json`).
  Mean 202.7 (SD 47.3, seed means 116.1 to 293.0), 640/640 phases closed
  by the agent, 0 failed decisions, 44 penalized illegal moves, 1 nudge,
  43 empty phases, no guard stops, no provider stalls, no quota pauses,
  31 compactions, 393K tokens per decision (cached input included),
  132.3 GM-Bench tool calls and 6.4 min per episode,
  ledger = harness on 32/32 episodes. Besides GM-Bench calls the agent made
  only 146 ToolSearch calls (Claude Code loads the deferred GM-Bench tool
  schemas through it). The agent made 151 `draft` calls in 160 draft
  phases and 121 `trade` calls. Against `pick-trader` the paired lift is
  −46.5, 95% interval −66.7 to −26.7, sign-flip p 0.0002, ahead on 9 of 32
  seeds, with a realized MDD of about 29. The validation warning is one
  rejected move on an unseen id (episode 4); no accepted move named an
  unseen id. Claude Code reports no cost. `pricing.json` had no Haiku 5.5
  entry when the panel ran, so the run recorded no API-equivalent
  estimate; the entry was added (verified 2026-10-13) and the redaction
  re-derived it from the retained event streams: $4.89 for the panel at
  the up-to-100K-token rates, flagged `api_equivalent_long_context_possible`.
  Haiku 5.5 prices a request whose prompt is over 100,000 tokens at 5x on
  every category; 1,037 of the 2,837 requests were, and repricing them
  from the per-request frames gives about $12 to $16 for the panel (output
  tokens are not per-request in Claude Code's stream, hence the range).
  Reasoning effort is the harness default (Claude Code reports none). The
  model is unpinned.

- Sixth panel-grade 2.0 row (2026-10-13): Codex 0.162.1 on `gpt-6.1-sol`,
  the frozen 32-seed private panel at five seasons, container isolation,
  played 2026-10-13 from clean `main` at `1411e2e` (#192; driver digest
  `23e83ff80184fec8`)
  (`results/agentic/codex-0.162.1-gpt-6.1-sol-panel-32x5.json`). Mean
  273.2 (SD 49.4, seed means 181.6 to 374.0), 640/640 phases closed by the
  agent, 0 failed decisions, 81 penalized illegal moves, 0 nudges, 0 empty
  phases, no guard stops, 9 provider stalls (780 s of backoff), 170.1 tool
  calls and 8.5 min per episode, ledger = harness on 32/32 episodes. The
  agent made 36 `draft` calls in 160 draft phases and 518 `trade` calls.
  Against `pick-trader` the paired lift is +24.0, 95% interval +1.6 to
  +45.8, sign-flip p 0.046, ahead on 23 of 32 seeds, with a realized MDD of
  about 32: significant, with little margin. It is the first 2.0 row whose
  interval clears `pick-trader`. Codex reports no cost; the API-equivalent
  estimate is $17.38 for the panel ($0.54 per episode), a lower bound
  because long-context requests are possible. The run used a ChatGPT
  `prolite` plan (at most 7% of the weekly window, no quota pauses), with
  the account's apps, plugins and connectors turned off (#192). Reasoning
  effort is the harness default (Codex reports none). The model is
  unpinned.

- OpenCode 2.x: GM-Bench tools in the first model request, and no Code
  Mode `execute` (2026-10-13, #193, driver only; the agentic fingerprint stays
  `07de948a4f4afbae`). The deepseek-v4.1-flash panel played on OpenCode
  2.0.27 showed nearly every episode opening with the agent probing
  `execute`, the shell and the scratch files for its tools (148 `execute`
  calls, each answered "Unknown tool"; 3 shell, 6 read and 2 write calls)
  before finding the GM-Bench tools on its second step. `run --standalone`
  sends the prompt before its server has connected the MCP servers, and
  2.0.27's `MCP.tools` lists only connected servers (2.0.28 is the same).
  Each `opencode run` now goes through a staged standard-library launcher
  (`gm_bench/agentic/_opencode_launch.py`, a new driver file) that starts
  `opencode serve` on loopback with its own password, waits until no MCP
  server is pending, and runs `run --server`. `opencode.json` also denies
  the `execute` permission: `codemode: false` already kept the GM-Bench
  tools out of Code Mode, but OpenCode still offered `execute` for its own
  built-in tools. That 2.0.27 panel is not published; it is re-run on the
  fixed driver. The committed 1.18.31 deepseek row is not affected by the
  launcher (it is 2.x only).

- Claude Code: no claude.ai connectors (2026-10-13, #192, driver only; the
  agentic fingerprint stays `07de948a4f4afbae`). An audit of Claude Code
  2.1.281 in its container image with the real `setup-token` token found
  nothing account-specific reaching the agent, but found that
  `--strict-mcp-config` does not stop the fetch of the account's claude.ai
  connectors; only the token's `user:inference` scope did. The driver now
  sets `ENABLE_CLAUDEAI_MCP_SERVERS=false` in the harness environment and
  in the image's `gmb-claude` launcher (the Claude image's Dockerfile hash
  moves from `1781dcc2b7da`, which played the committed Claude rows, to
  `f0e72cbaea92`). No committed Claude row recorded a tool outside the
  allowed built-ins and GM-Bench.

- Codex: no ChatGPT account plugins, apps or connectors (2026-10-13,
  #192, driver only; the agentic fingerprint stays `07de948a4f4afbae`). A Codex
  container smoke logged a failed connection to `mcp.neon.tech`, and a
  capture against the real account explained it. With a ChatGPT login,
  Codex 0.156.1 and 0.162.1 sync the account's installed plugins into the
  harness home and start their MCP servers (24 plugins; `neon`,
  `codex-security`, `creative-production`, `xcodebuildmcp`). The hosted
  `codex_apps` server also exposes the account's connected ChatGPT apps:
  668 tools including Gmail, GitHub, Google Drive and Neon. In code mode
  those tools are deferred, out of the prompt text but callable from
  `exec` and listed in `ALL_TOOLS`, so neither the 2026-09-27 account
  capture nor the prompt check saw them. The driver now passes `-c
  features.apps=false -c features.plugins=false -c
  features.remote_plugin=false` on every invocation and records them as
  `harness_run.disabled_features` (published in the compact artifact).
  The first prompt loses only the generic `<recommended_plugins>` list and
  the `request_plugin_install` tool. New `scripts/audit_codex_tools.py`
  audits the agent's whole tool set against the real account at no quota
  cost, and is required before a Codex panel: PASS on 0.162.1 and 0.156.1
  with the flags, FAIL without them. The committed `gpt-6-luna` rows ran
  with the account's apps and plugins available and recorded no
  non-GM-Bench tool call; their artifacts are unchanged. Also corrected:
  in code mode Codex defers the GM-Bench tool schemas too, so they are not
  in the first prompt. See "Account plugins and apps" in
  `docs/agentic_lane.md`.

- Codex CLI 0.162.1 (2026-10-12, #192, driver only; the agentic fingerprint
  stays `07de948a4f4afbae`). The Codex container image now pins 0.162.1
  (was 0.156.1): the ChatGPT backend refused `gpt-6.1-sol` to 0.156.1 with
  a 400 "not supported when using Codex with a ChatGPT account". Every
  claim in the driver's docstring was re-verified against the
  `rust-v0.162.1` source and binary. The `exec --json` stream is
  byte-identical in source; rollout `token_count` and `turn_context`
  records still persist; the usage-limit text now links
  `chatgpt.com/settings/usage`; no driver logic changed. `gpt-6.1-sol` is
  priced in `pricing.json` ($2 input, $0.10 cached, $2.50 cache write,
  $10 output, 272K long-context tier; verified 2026-10-12). The committed
  Codex rows were played on 0.156.1 and keep validating at the driver
  commit they record. See "Codex 0.162.1" in `docs/agentic_lane.md`.

- Fifth panel-grade 2.0 row (2026-10-12; the panel ran 2026-09-28 to
  09-29): OpenCode 1.18.31 on `opencode-go/deepseek-v4.1-flash`, the
  frozen 32-seed private panel at five seasons, container isolation,
  played from clean `main` at `07de4b2` (#172)
  (`results/agentic/opencode-1.18.31-deepseek-v4.1-flash-panel-32x5.json`).
  Mean 247.1 (SD 50.3), 640/640 phases closed by the agent, 0 failed
  decisions, 35 penalized illegal moves, 2 nudges, no provider stalls or
  guard stops, 156.3 tool calls and 12.3 min per episode, 56/640 empty
  phases. Against `pick-trader` the paired lift is −2.0, 95% interval
  −22.4 to +18.0, sign-flip p 0.84, with a realized MDD of about 29:
  "cannot tell". OpenCode's own cost figure is $3.69 for the panel; the
  run used an OpenCode Go subscription, which counts usage against the
  plan's limits rather than billing per token. Reasoning effort is the
  harness default (OpenCode reports none). The model is unpinned.

- Container isolation on a native Linux Docker Engine (2026-10-12, #191,
  driver only; the agentic fingerprint stays `07de948a4f4afbae`). The container
  driver assumed Docker Desktop, where `host.docker.internal` reaches the
  host loopback; a native engine (Linux, or WSL 2 without Docker Desktop)
  resolves no such name and cannot reach the host loopback, so the proxy
  could never dial the driver. On a Linux host whose engine is not Docker
  Desktop, the driver now listens on the default bridge's gateway, maps
  `host.docker.internal` to it with `--add-host`, binds the egress canary
  there too, and records the address as `harness.container.host_gateway`.
  Docker Desktop runs are unchanged. Off macOS, the private-panel launcher
  reads a private copy of the Keychain record from
  `~/.config/gm-bench/<service>.escrow` and checks it against the same
  committed digests.

- OpenCode 2.x (2026-10-12, #190, driver only; the agentic fingerprint stays
  `07de948a4f4afbae`). The OpenCode driver now runs OpenCode 2.x only, and
  the container image pins 2.0.27. OpenCode 2 rejects `--pure`, `--dir` and
  `--variant` (it prints help and launches nothing), so on 2.x the old
  driver ran no harness at all. The driver now runs `opencode run
  --standalone` (a private server per invocation, never 2.x's shared
  background service), with the variant as `--model provider/model#variant`
  and the workspace set through `PWD`, which 2.x reads before the working
  directory. Error detection reads 2.x's typed errors as well as 1.18's: a
  spent free or Go allowance (`provider.quota`) now stops the episode with
  the reset unknown, because 2.x drops the `retry-after` header. 2.x's JSON
  stream omits the last model step of every invocation, so token counts now
  come from `opencode session export`, labelled `usage.harness.token_source`.
  A staged `auth.json` is never read by 2.x, so the Go key is staged with
  `opencode auth import`. OpenCode 2.x is not on npm; the image installs
  the release tarball by pinned SHA-256. The prompt check passes on 2.0.27
  with the private home, and without it finds 21 lines of the operator's
  `AGENTS.md` and 16 skills, so the private home is still needed. Rows played
  on 1.18.31 keep validating at the driver commit they record. No committed
  row is affected.

- Cursor "out of usage" (2026-09-29, driver only; the agentic fingerprint
  stays `07de948a4f4afbae`). When the grok-4.7 panel spent the Cursor plan
  at episode 20, every launch printed "You're out of usage", which the
  usage-limit pattern missed: the driver nudged, and eleven empty episodes
  were scored as failed decisions instead of the panel stopping on quota.
  The pattern now matches it. That run is not publishable. No committed
  row is affected.

- OpenCode API keys (2026-09-28, driver only; the agentic fingerprint stays
  `07de948a4f4afbae`). `gm-bench agentic --harness opencode
  --opencode-auth-file <path>` runs OpenCode Go (`opencode-go/*`) models,
  same-user or in a container. The key is written as OpenCode's
  own `auth.json` for `opencode-go` only into the episode's private
  data directory or its home volume (over `docker run` stdin), never onto a
  command line or into the harness environment, and is redacted from the
  event stream and stderr log when the episode ends. An `opencode-go/*` model
  without the file is refused before anything runs. Each episode records
  `harness_run.auth` and `auth_providers`, never the key. A spent Go window
  (`GoUsageLimitError`, read from OpenCode's source, not yet seen live) is
  quota exhaustion with its `retry-after` reset, like `FreeUsageLimitError`.
  An episode the loop gives up on unfinished, whose last invocation made no
  tool call and ended on a provider API error OpenCode marks non-retryable
  (for example Go's 400 "This Go model requires Global regions"), is now
  `ended_by_provider` with reason
  `provider_error`, so it stops the panel and cannot be published; before,
  the first Go smoke scored such a refusal as four failed decisions. The
  recorded error message is redacted of the key.
  No committed row is affected.

- Fourth panel-grade 2.0 row (2026-09-28): the Cursor CLI
  2026.09.26-dd393fe on `composer-2.5`, the frozen 32-seed private panel at
  five seasons, container isolation, played from clean `main` at `b3d7de7`
  (`results/agentic/cursor-2026.09.26-dd393fe-composer-2.5-panel-32x5.json`).
  Mean 230.6 (SD 27.7), 640/640 phases closed by the agent, 0 failed
  decisions, 55 penalized illegal moves, no nudges, provider stalls or
  guard stops, 127.6 tool calls and 3.5 min per episode, 125/640 empty
  phases. Against `pick-trader` the paired lift is −18.6, 95% interval
  −35.6 to −1.4, sign-flip p 0.047: significantly below the scripted bar,
  with little margin (the row's MDD is about 25). The prompt audit passed
  on all 32 episodes with only Cursor's seven default rules. Cost is
  unmeasured (Cursor reports none; `composer-2.5` is not in
  `gm_bench/pricing.json`), as are reasoning effort and compactions. The
  model is unpinned.

- Cursor's grok defaults (2026-09-28, driver only; the agentic fingerprint
  stays `07de948a4f4afbae`). Cursor's servers send a per-model set of their
  own rules: grok-4.7 gets the git-commit and pull-request rules plus two
  not recorded before (verify web-app changes in a browser; state points in
  affirmative language), and the prompt check refused its first panel. A
  one-word probe showed both are absent from the account's rules; their
  digests join `CURSOR_DEFAULT_RULES`. No committed row is affected.

- Release fixes (2026-09-28, driver, validation and publication only; the
  agentic fingerprint stays `07de948a4f4afbae`). The `claude-haiku-4-5`
  panel row's API-equivalent cost is re-derived from its retained events:
  $27.71, not $25.14 (its 1-hour cache writes had been priced at the
  5-minute rate because frames name the dated snapshot); the row keeps the
  recorded figure beside it. Scores do not change. Every committed row was
  re-redacted from its raw run and now carries empty-phase counts
  (Haiku 301/640, Sonnet 0/640, Codex 1/640, space-bunny 6/160) and the
  reasoning effort requested and reported; the Haiku reference's
  sign-flip p-value is published as the bound 5e-05 instead of 0.0. An
  episode a provider ended past its stall budget now stops the panel and
  is refused for publication, as are the `muse-spark` panel's episodes 15
  and 16; OpenCode's `FreeUsageLimitError` is quota exhaustion; the
  Keychain panel launcher refuses same-user isolation.

- Cursor in a container (2026-09-28, driver only; the agentic fingerprint
  stays `07de948a4f4afbae`): `--harness cursor --isolation container` runs
  `cursor-agent` 2026.09.26-dd393fe from its own image. The image downloads
  the release tarball for its architecture from Cursor's CDN, checks a
  pinned SHA-256 (arm64 and x64), and unpacks it root-owned; the other
  images' Dockerfiles are byte-for-byte unchanged. The token and `mcp.json`
  are seeded into the episode's home volume over `docker run` stdin, and a
  launcher (`gmb-cursor`) removes config the agent planted, restores
  `mcp.json`, exports the token and execs the CLI in every invocation's
  fresh container, refusing (exit 96) on a home it cannot trust. The prompt
  audit reads the chats out of the volume and still gates publication, and
  the pre-panel prompt check runs in the image, because Cursor's servers
  add account rules whatever the isolation. The image built and passed its
  no-spend checks on 2026-09-28; no model has run in it yet.

- Prompt check (2026-09-27): before a panel, `gm-bench agentic` launches the
  harness against a loopback capture server twice, once as the operator and
  once with their home swapped for an empty one, and treats any prompt line
  only the first sent as the operator's. It also searches the capture for the
  operator's home path, instruction files (with their `@` imports, Claude
  rules and memories, OpenCode `instructions`) and skills (with installed
  Claude plugins). It refuses the panel on any hit, and on no captured
  request. The check is recorded as `run.json` `prompt_check` and published
  with the row, a recorded failure fails validation, and a same-user row
  whose check was skipped cannot be published. It found that same-user OpenCode sent
  the operator's global `AGENTS.md` and 16 personal skills. Same-user
  OpenCode now gets a private home and `XDG_*` directories. No committed row
  is affected: every one is a container run, whose home is a fresh volume.
  The check passes OpenCode's model catalog download (`models.opencode.ai`)
  through, and resumes a launch that failed at startup before any model
  request, as the episode does; without both, a model missing from
  OpenCode's bundled catalog (`space-bunny-free` on 1.18.32) failed the check.

- Fourth harness (2026-09-27): `gm-bench agentic --harness cursor` drives
  the Cursor CLI (`cursor-agent` 2026.09.26-dd393fe) through the same
  episode loop, in same-user isolation only (no pinned image yet). The
  driver uses a private `HOME`, `CURSOR_CONFIG_DIR` and `CURSOR_DATA_DIR`,
  keeps the Keychain out, takes a credential from `--cursor-token-file`,
  and gates the prompt. Cursor's servers add the account's cloud User Rules to
  every prompt, so the driver audits each chat's context sections and
  refuses to start a panel, validate an episode or publish a row whose
  prompt carries anything outside the harness's own context. Seven rules
  that Cursor's servers send to every account in the User Rules slot, which
  the account cannot see or remove, are matched by digest and count as the
  harness's own; any other rule, a reworded default, or a rules slot in
  any shape but Cursor's exact one is refused. The contract fingerprint
  does not move.
- Codex login write-back (2026-09-27): when Codex renews a ChatGPT login
  during an episode, the driver writes the renewed `auth.json` back over
  `--codex-auth-file` (same-user from the private `CODEX_HOME`, container
  from the home volume before it is removed), unless the file changed
  meanwhile. The next episode starts from the working login, and the
  operator's Codex is no longer signed out by a run. Each episode records
  `harness_run.auth_file_update`. The contract fingerprint does not move.
- Contract freeze (2026-09-25): the 2.0 contract is frozen as
  `gm-bench-2.0` at agentic fingerprint `07de948a4f4afbae`, and a test pins
  the pair, so any byte change to the tool surface, brief, episode engine or
  server fails CI until it is released as a new version. The fingerprint
  did not move (the version label is not a fingerprint source), but every
  row records the label, so the `space-bunny-free` smoke row was rerun
  under it (container, seeds 1 to 8, five seasons: mean 217.8, SD 20.5,
  160/160 phases closed by the agent, 0 failed decisions). All five gates
  before a paid run in `docs/bench_v2_spec.md` are met. Container red-team verdict: a probe using the example seed
  printed in `scripts/agentic_red_team.py` found it by downloading the
  public source and rebuilding that league offline, nothing from the host;
  a probe with a fresh seed from the private-panel range (2**32 to
  2**63 - 1) ran 20 minutes through generator reimplementation, privilege
  and namespace escapes, host port scans and unlisted MCP methods without
  finding it. The script now refuses a seed outside that range.
- Naming: the frozen `sota-v5` contract, with its decision-model lane, is
  **GM-Bench 1.0**. **GM-Bench 2.0** is a new contract, specified in
  `docs/bench_v2_spec.md`: the same simulator and seeds, driven by a model's
  own harness through an MCP tool server instead of one prompt per phase.
  Rows are model + harness + harness version, budgets are reported rather
  than capped, and the panel is 32 private seeds (the 29 from 1.0 plus 3).
- Code: `gm_bench/agentic/` (tool surface, task brief, episode engine with a
  replayable ledger, standard-library MCP server, OpenCode driver, ledger
  audit) and the `gm-bench agentic` subcommand. Operator guide in
  `docs/agentic_lane.md`.
- Publication: `gm-bench agentic-redact` writes one compact artifact per row
  under `results/agentic/` (format `gm-bench-agentic-summary-v1`), bound to
  the operator-held raw run by SHA-256, seeds redacted, graded `panel` or
  `smoke` by the spec's rules (32 seeds, redaction, harness isolated from
  the driver). CI validates every committed row against the checkout's 2.0
  contract. Smoke rows are committed on public seeds.
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
  execution waited for the owner attestation, recorded 2026-09-23.
- Site and panel-row checks: `agentic-validate` and `agentic-redact` reject a
  `panel`-grade row whose `panel.sha256` or distinct-seed count differs from
  the frozen panel in `config/bench_v2_lane.json` (smoke rows are exempt).
  `web/scripts/build_study.py` emits an `agentic_lane` block with panel-grade
  rows only, and the site gains a GM-Bench 2.0 section that renders nothing
  until such a row exists. A row whose model is not listed under
  `model_pinning` in the lane config shows the spec's `unpinned` flag and
  may-not-be-reproducible sentence; rows are ordered by model and harness,
  not score, and show no 1.0 row's score. The results-data validator
  keeps 2.0 rows out of every 1.0 table. The section stayed empty until the
  first panel-grade row (2026-09-27).
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
  committed smoke row must be rerun on the new contract. The rerun is
  `results/agentic/opencode-1.18.31-space-bunny-free-smoke-8x5.json`
  (container isolation, `opencode/space-bunny-free`, mean 225.8 over
  seeds 1 to 8 at five seasons); it replaces the `big-pickle` row, whose
  free quota was exhausted.
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
  recorded and published as unmeasured (no summed zero compactions; the
  API-price estimate below is kept apart from `cost_usd`). Tool calls Codex
  refuses before dispatch are counted apart, not as harness calls.
  `agentic-validate` recounts tool calls from a Codex event stream as it
  does for OpenCode. Proven against a stand-in `codex` and `docker`, and by
  two live 1-season smokes on `gpt-6-luna` (seed 11, same-user and
  container, 2026-09-24).
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
  API-equivalent estimate beside it, which prices the 1-hour cache writes
  Claude Code makes on a subscription at their own rate (the frames'
  `cache_creation` split; `cache_write_1h_per_mtok`, $4 for
  `claude-sonnet-5`) and matched Claude Code's own figure exactly on three
  live smokes (it had been about 15% low); usage limits pause or stop the episode
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
  image (opt-in `GM_BENCH_DOCKER_TESTS=1`), and live: a one-season
  `claude-sonnet-5` smoke on seed 11 in the container scored 118.9 with no
  config-directory findings and no credential in any saved file. The
  contract fingerprint is unchanged.
- Silent harness: OpenCode retries a 429 internally without printing any
  event, so a rate-limited run looked hung until the 20-minute phase guard
  killed it and its phases closed as `harness_exit`. The driver now stops an
  invocation that has printed no event and made no tool call for 240 s since
  launch (`--silent-harness-seconds`, 0 disables) and retries it as a
  provider stall, not a guard stop or a nudge; the silent window comes off
  the phase clock. Counted as `silent_kills` per episode (`silent` per nudge),
  `silent_harness_kills` in the run summary and site telemetry.
- Docs (2026-09-25): the README gains a short GM-Bench 2.0 status section
  (at the time: implemented, one smoke row, no panel-grade result), and `docs/bench_v2_spec.md`
  gains a current-behaviour repeat-noise measurement from the two
  `space-bunny-free` smoke runs on seeds 1 to 8: within-seed SD 43 over all
  eight seeds and 23 without seed 1, so a 32-seed panel resolves about 39 or
  28 points respectively for that model.
- OpenCode startup errors: in two 8-seed container runs of
  `opencode/space-bunny-free`, 9 of 16 episodes' first launch ended about a
  second in on OpenCode's `UnknownError` "Unexpected server error", with no
  tool call. The driver spent a nudge on it, and a second such error on the
  resume would have stopped the loop and failed every phase. That error is
  now a provider stall when it ends an invocation that had done nothing
  else (no tool call, model text or finished model step), retried at most 3
  times in a row because OpenCode gives the same error for persistent faults
  such as a deprecated model; after the invocation acted it is still nudged.
  `harness_run.final_exit_code` records
  the last invocation's exit code beside the first launch's `exit_code`, and
  `agentic-validate` warns on it, so an episode that recovered no longer
  reports `harness exit code 1`. Committed rows, which predate the field,
  validate unchanged. The contract fingerprint is unchanged.
- Driver provenance: the 2.0 fingerprint covers the tool surface, brief,
  engine and server, not the driver that plays the episode (the shared
  loop's nudges, retries, resumes and stall handling, the harness adapters,
  the container launcher, the proxy), so two rows could share a fingerprint
  and harness version yet have been played by different driver code. Every
  run now records a `driver` block in `run.json`, carried into the
  published row: a digest of those driver files taken when the run starts,
  the files it covers, the git commit, whether the driver files matched it,
  and whether they changed before the run ended
  (`gm_bench/agentic/provenance.py`, which also classifies every file in
  the package so a new one cannot be left out). A `panel` row now needs a
  driver that matched a commit for the whole run; a run without one redacts
  as `smoke`. A row played by an older driver than the checkout's gets a
  warning, not an error. Rows recorded before the block, like the committed
  smoke row, stay valid as `smoke` with a warning, so the format stays
  `gm-bench-agentic-summary-v1`.
  `scripts/run_bench_v2_panel_from_keychain.py` refuses to start a panel
  when a driver or contract file differs from `HEAD`. The contract
  fingerprint is unchanged.
- First five-season smoke rows on the paid harnesses, one container episode
  each on public seed 11 under `gm-bench-2.0`, with the driver block from a
  clean `main`: `results/agentic/codex-0.156.1-gpt-6-luna-smoke-1x5.json`
  (232.5, 10.7 min, $0.18 at API prices) and
  `results/agentic/claude-2.1.281-claude-sonnet-5-smoke-1x5.json` (248.0,
  19.8 min, $5.05 at API prices). Both closed 20/20 phases themselves with no nudges or
  provider stalls. They are `smoke` grade and the site does not show them.
- Repeat noise measured on the paid harnesses: seeds 1 to 4 run twice on
  Codex (`gpt-6-luna`) and Claude Code (`claude-sonnet-5`), committed as four
  `smoke` rows (`*-smoke-4x5-run-{a,b}.json`). Within-seed SD 21.4 for Codex
  and 11.3 for Claude, so a 32-seed panel resolves about 27 and 23 points.
  All 16 episodes closed every phase themselves on the same committed
  driver. Written up in the spec under "Repeat noise on the paid harnesses".
- First panel-grade 2.0 row: Codex 0.156.1 on `gpt-6-luna`, the frozen
  32-seed private panel at five seasons, container isolation, played from
  clean `main` at `4d742cc`
  (`results/agentic/codex-0.156.1-gpt-6-luna-panel-32x5.json`). Mean 227.4
  (SD 41.0), 640/640 phases closed by the agent, 0 failed decisions, 19
  penalized illegal moves, no nudges, provider stalls or quota pauses,
  10.3 min per episode, $4.54 at API prices, a lower bound: the row sets
  `api_equivalent_long_context_possible` (about 10M input tokens per
  episode, with turns growing past the 272K long-context threshold) and the
  estimate uses short-context rates. Against the predeclared
  `pick-trader` reference (249.18) the paired lift is -21.8, 95% interval
  -43.3 to +0.1, sign-flip p 0.062, winning 28% of seeds: not significant.
  The site's 2.0 section now renders, with this row flagged `unpinned`.
- Second panel-grade 2.0 row: Claude Code 2.1.281 on `claude-sonnet-5`, the
  same frozen 32-seed private panel at five seasons, container isolation,
  played from clean `main` at `4d742cc`
  (`results/agentic/claude-2.1.281-claude-sonnet-5-panel-32x5.json`). Mean
  227.4 (SD 54.3), 640/640 phases closed by the agent, 0 failed decisions,
  24 penalized illegal moves, no nudges, provider stalls or compactions,
  14.5 min per episode, $157 at API prices. Against `pick-trader` the paired
  lift is -21.8, 95% interval -47.2 to +3.5, sign-flip p 0.108, winning 41%
  of seeds: not significant. One episode recorded a 165/166 tool-call
  mismatch because the Claude event parser counted a call to the bare
  server name `mcp__gm-bench`, which Claude Code refused before any server
  saw it. The parser is fixed, and the row publishes the recount (165/165)
  with the recorded figure beside it.
- Post-hoc audit rule (2026-09-27, adopted after the `claude-haiku-4-5`
  panel had run): an accepted `draft` on a prospect id no
  tool reply exposed is now a `guessed_draft_pick`, reported as a warning,
  instead of a violation that blocks publication. Prospect ids are
  `1_000_000 + season * 10_000 + index` with the index independent of hidden
  potential, so a guessed pick is blind; a test pins that independence. Any
  other accepted move on an unseen id is still a violation. Prompted by the
  `claude-haiku-4-5` panel, which drafted six guessed ids in four episodes.
- Third panel-grade 2.0 row: Claude Code 2.1.281 on `claude-haiku-4-5`, the
  frozen 32-seed private panel at five seasons, container isolation, played
  from clean `main` at `21b71dc`
  (`results/agentic/claude-2.1.281-claude-haiku-4-5-panel-32x5.json`). Mean
  130.1 (SD 36.1), 640/640 phases closed by the agent, 0 failed decisions,
  56 penalized illegal moves, 3 nudges, no provider stalls or compactions,
  6.1 min per episode, $25 at API prices (re-derived as $27.71 on 2026-09-28, above). Against `pick-trader` the paired
  lift is -119.1, 95% interval -132.8 to -104.5, p < 0.001, winning no
  seed: significantly below the scripted bar. Six draft picks on guessed
  prospect ids are reported as warnings under the rule above.
- Documentation audit before release (2026-09-28): `docs/bench_v2_spec.md`
  now states what the freeze covers (the four fingerprinted files, the 1.0
  simulator contract, the seed panel) and what may change without a new
  version (driver, audit, validation and publication rules, disclosed here
  with their date and affected rows), records the guessed-draft-pick rule
  as post-hoc, adds the realized panel noise and a section on how 2.0
  differs from 1.0 beyond the interface (unlimited calls per phase,
  unpenalized schema rejections, draft class visibility, `inspect_player`
  on prospects), and marks plans that did not happen (a command-line
  wrapper, 8-seed private smoke rows, a 5 × 3 noise probe, the lowest
  reasoning variant, a free 1.0-versus-2.0 pairing). Deferred contract
  changes are listed in `docs/bench_v2_1_queue.md`. `docs/agentic_lane.md`
  gains the command behind the committed OpenCode smoke row, container
  isolation in the panel launcher example, a section on each harness's
  non-GM-Bench tools and the container's public egress, and corrections on
  Claude Code quota windows and the Codex long-context cost caveat. The
  site's 2.0 section gains per-row caveats, and a draft findings post is in
  `docs/blog/gm-bench-2.0-findings.md`. No row, driver or contract file
  changes.

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
