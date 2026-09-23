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
  `reference_scores`, the frozen panel's pick-trader and random means, to be
  recorded from the first `--raw`-validated panel row; once recorded every
  panel row must carry them, and until then all panel rows must agree. The site's 2.0 section shows it as
  "vs pick-trader (same seeds)", and the results-data validator now requires
  that on-panel reference and rejects any other p-value on a 2.0 row.

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
