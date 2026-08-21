# GM-Bench Publication Readiness

> **This is a living document.** It is the working source of truth for taking
> GM-Bench from a strong benchmark codebase to a credible public release. Update
> it whenever an experiment changes the evidence, a publication decision is
> frozen, a blocker appears, or a checklist item is completed. The goal is not
> to preserve this first draft; the goal is to make it more accurate as the
> project develops.

**Last reviewed:** 2026-08-21
**Current target:** Preserve the published `sota-v2` study and terminal
`sota-v3`/`sota-v4` execution records while preparing the prospective
`sota-v5` successor. Its authenticated zero-completion route, privacy, pricing,
seed-free command, and final-preflight evidence were accepted on the prior
contract. The hardening change relocks final preflight until equivalent
zero-completion evidence is refreshed on the merged head. V5 spend, smoke,
panel, and publication remain false.
**Current state:** The frozen phase-one public panel, blog, GitHub release, and
results-first site are published. Eight of ten
`sota-v2`-registered models produced route-matched, cost-complete `sota-v2`
rows at the shared 4,096-token native-minimum-reasoning cap, clearing the
predeclared minimum. Grok 4.5 and Mistral Medium 3.5 completed but remain diagnostic because
their artifacts lacked complete usage or cost coverage. The generated site now
exposes the eight eligible rows. All models overlap in one uncertainty tier,
and every eligible model trails `pick-trader`.

### Historical SOTA-v3 execution record

The following state is terminal history. It does not authorize current spend
or describe the active v5 lane.

The three P0 correctness and
artifact-integrity fixes landed in #85 as an explicit `sota-v3` contract. The
v3 candidate also closed the contract-economics, same-view,
gap-diagnostic, site-framing, statistical-tiering, and version-dispatched CI
items.

Pre-data
design amendment 3 (2026-08-06,
`docs/run_logs/sota-v3-design-amendment-2026-08-06.md`) withdrew Gemini 3.6
Flash and Grok 4.5 — the only two mandatory-reasoning routes — leaving an
eight-model, uniformly reasoning-disabled cohort (2 frontier-proprietary / 6
open-weight) at Holm family size 8. The current candidate contains that
cohort, a frozen 16-seed x 1-repeat statistical design (sensitivity power
0.8727, Wilson lower 0.8660), a frozen 4,096-token smoke ceiling, an in-progress
smoke manifest with five accepted entries, explicit runner dispatch, and a zero-spend synthetic
rehearsal. Exact-route and synthetic-data privacy acceptance are recorded for
all eight routes, and the private 16-seed commitment is frozen with its secret
in macOS Keychain. Final-fingerprint Keychain-backed dry-run and authenticated
route-plus-price preflight evidence passed for all eight routes with zero
completion calls. Route health and pricing remain ephemeral, so rerun the
zero-completion preflight immediately before paid smoke execution. Private
seeds are now stripped from every model-facing payload and child environment
while remaining runner-internal for pairing and replay. Spend and strict-smoke
execution are authorized under a committed $100 ceiling. The generated cost
artifact is authoritative for both the one-response-per-window planning
forecast and the protocol-maximum estimate; the runner separately enforces the
ceiling before every provider call. The strict-smoke run is now terminal under
the frozen retry policy: Luna, Claude, Mistral, DeepSeek, and HY3 passed; GLM
completed with one model-behavior protocol failure and cannot be rerun; MiniMax
exhausted two HTTP 429 attempts; Qwen exhausted two HTTP 400 attempts. Panel
authorization therefore remains blocked.

### Historical SOTA-v4 execution record

The v4 record is terminal and remains locked against further paid execution. It retains the exact
unused 16-seed v3 commitment with explicit lineage, replaces the terminal GLM
slot with `upstage/solar-pro4`, returns MiniMax M3 to the recovered
policy-selected `minimax/fp8` route, and records Qwen/Alibaba as terminally
incompatible with the uniform reasoning-disabled lane. Fresh
authenticated route/privacy evidence, Keychain-backed command construction,
and route-plus-live-price preflight passed for all eight routes with zero
completion calls; no v3 execution artifact is accepted as v4 evidence. The generated cost
artifact records a `$6.67548672` protocol-maximum smoke estimate under a `$10`
operator ceiling. The owner authorized the eight serial strict smokes on
2026-08-14, but the first Qwen attempt stopped the sequence. The adapter now
preserves only bounded, allowlisted provider error detail and reconciliation
records a contemporaneous aggregate account delta without treating it as
per-call settlement. The unresolved call bound was conservatively charged as
spent after a live `$0.00` aggregate account delta, and fresh Keychain-backed
command construction plus authenticated route-and-price preflight passed at
OpenRouter scaffold fingerprint `f04724717cc09caf` with zero completion calls.
On 2026-08-16 the owner authorized only Qwen's second and final infrastructure
attempt. Qwen's exact route and live price preflight passed immediately before
launch, then its one provider request returned HTTP 400: `Reasoning is mandatory
for this endpoint and cannot be disabled.` No generation, episode, decision, or
raw artifact was produced, and no other model launched. The attempt ledger is
terminal at 2/2. A live credits read still showed `$0.00` aggregate run delta;
the guard nevertheless charged the full second `$0.1832184` unknown-call bound,
bringing conservative reported spend to `$0.3664368`. The separate all-route
zero-call probe also found DeepSeek live prices above the frozen snapshot; no
DeepSeek completion call was made. SOTA-v4 cannot complete its registered
eight-model smoke family without an outcome-driven cohort or reasoning-policy
change, so spend and smoke are re-locked. Panel and publication remain
unauthorized.

### Current SOTA-v5 readiness

The next contract is the outcome-independent `sota-v5` successor, frozen in
the five `config/sota_v5_*.json` files and recorded in
`docs/run_logs/sota-v5-preregistration-2026-08-16.md`. It retains the seven
non-Qwen v4 identities and replaces the terminal Qwen slot with
`google/gemini-3.7-flash` on the accepted `google-ai-studio` route,
selected from public OpenRouter metadata before any v5 data. V5 carries the
unused hidden 16-seed commitment through the explicit lineage
`sota-v3 -> sota-v4 -> sota-v5`, but requires an owner attestation before seed
access. It freezes a uniform reasoning-disabled policy, a 4,096-token ceiling,
one repair, serial execution, two infrastructure attempts per cell, and the
same exact paired sign-flip/Holm plan over eight contrasts. Fresh authenticated
route/privacy evidence and the seed-free command plus live-price final preflight
passed for all eight routes with zero completion calls on contract fingerprint
`247e12fe5a7d4f5b` and OpenRouter scaffold fingerprint `f04724717cc09caf`.
The subsequent fail-closed API and canonical-host hardening moved those
fingerprints to `519bf6db27320d8b` and `ec8ede1bcf7774ce`, so final preflight
is pending again. Route preflight remains the only enabled phase; all v5 spend,
smoke, panel, and publication authorizations are false. The regenerated
protocol-maximum smoke estimate is `$6.17324032` (`$7.407888384` with
contingency), below the `$10` owner ceiling; the panel remains separately
unauthorized.

V5 smoke readiness is intentionally seed-free: its smoke-command dry run does
not read Keychain or set `GM_BENCH_PRIVATE_SEEDS`, because strict smokes use the
public smoke seed. The hidden commitment is verified only after the owner
attestation and immediately before the separately authorized private panel.

Pre-data amendment 4 (2026-08-09) makes the cap-pressure rule terminal on its
first trigger: any truncation or call
reaching 3,072 output tokens invalidates all v3 smokes, aborts this contract,
and requires a new preregistration before another run. No in-place cap
amendment is allowed. The registered 8,192-token value is only a planning
comparison, not an authorized fallback branch. The reasoning-policy ambiguity
is resolved by construction, since all eight retained routes are registered
with reasoning disabled. Panel execution and publication remain false until
every required strict smoke is accepted. Real v3 smoke artifacts now exist,
but there is no v3 panel or leaderboard artifact.
**Current weekly focus:** Land the v5 hardening, refresh zero-completion evidence
on the merged head, and stop before paid smokes for explicit owner approval.
Panel and publication remain separate decisions.
**Broader roadmap:** [#60 — Roadmap to a publishable leaderboard + blog
post](https://github.com/nedcut/gm-bench/issues/60)

## Executive assessment

GM-Bench is viable as a focused benchmark for comparing models and agent
scaffolds on synthetic, long-horizon resource allocation in a frozen sports
management environment. It is already strong enough to be a flagship AI/ML
portfolio project. The public `sota-v2` evidence gate is now satisfied with
eight eligible rows under the frozen 4,096-token native-minimum-reasoning lane.
The evidence does not support an ordinal model ranking: all eight rows occupy
one overlapping uncertainty tier, and none beats the transparent `pick-trader`
baseline. A future `sota-v5` release still needs accepted smoke and panel
evidence, raw trace assets, claim review, presentation polish, and independent
reproduction.

The strongest story is not merely that GM-Bench runs LLMs through a simulator.
It is that the project:

- built a deterministic, multi-season decision environment;
- created transparent baselines, adversarial canaries, and a privileged
  hidden-information diagnostic;
- discovered that its first model comparison was confounded by a scout protocol
  bug, unequal output budgets, and mixed execution lanes;
- withdrew the affected ranking instead of defending it;
- versioned and froze the corrected benchmark contract;
- archived historical evidence without presenting it as current evidence; and
- added machine-enforced publication gates so invalid or incomparable rows
  cannot silently become headline results.

That combination demonstrates benchmark design, simulation, agent evaluation,
statistical reasoning, reliability engineering, and scientific judgment. The
remaining work is to package, independently verify, and present the frozen
experiment clearly.

## What “publish-ready” means

Publication readiness has four independent gates. Passing tests alone is not
enough.

1. **Benchmark gate:** the simulator, scoring, schemas, baselines, seed panel,
   and validation policy are frozen and machine-checkable.
2. **Evidence gate:** the fixed-cap model panel is complete, comparable,
   statistically reported, and validated.
3. **Claim gate:** every public statement is supported by the evidence and stays
   within the benchmark's actual scope.
4. **Presentation gate:** a new reader can understand, run, audit, and cite the
   project without reconstructing its history from pull requests.

The project is publish-ready only when all four gates pass.

## Current readiness snapshot

| Area | Status | Assessment |
| --- | --- | --- |
| Core engineering | Strong | Deterministic simulator, adapters, CLI, GUI, site, tests, and CI are substantial. |
| Reproducibility | Strong | Contract fingerprints, seed provenance, compact artifacts, and validators are in place. |
| Benchmark validity | Strong but scoped | Scripted references, exploit canaries, a partial hidden-information diagnostic, calibration, and mechanic coverage exist. |
| Compute comparability | Frozen for phase one | The API lane has a common 4,096-token total-output ceiling, native-minimum reasoning, exact provider slugs and endpoint tags, a pre-full-panel 75% cap-pressure rule, and actual reasoning/token-efficiency reporting. All ten phase-one routes passed and were accepted; Kimi K3 and the unavailable Nemotron and DeepSeek routes are retained as exclusion evidence. |
| Current model evidence | Public panel complete | Eight registered, route-matched, cost-complete `sota-v2` rows clear the publication floor; Grok and Mistral are retained as diagnostics. |
| Statistical evidence | Ready but low-resolution | Seed-paired intervals, exact sign-flip tests, full-family Holm adjustment, and overlap tiers are generated. All eight rows share one tier and trail `pick-trader`. |
| External validation | Missing | No independent reproduction or third-party result has been recorded. |
| GitHub presentation | Strong | The results-first site, README, tagged evidence release, and clean-clone guide are public; the remaining work is consistency and disclosure polish. |
| Blog | Published, living | The evidence-backed phase-one findings are public and must retain post-release integrity notes as the implementation evolves. |

## Critical path

Do these in order. Do not allow attractive v3 work or site polish to move ahead
of the frozen v2 evidence package.

### Phase 0 — stabilize the v2 base

- [x] Merge [#58 — GM-Bench v2](https://github.com/nedcut/gm-bench/pull/58)
  after a final live review of its head SHA, checks, and mergeability. Merged as
  `7ee1c920e6b86434b6e71a0ae055e0b47443f5d2` on 2026-07-14.
- [x] Merge [#59 — model-run hardening](https://github.com/nedcut/gm-bench/pull/59)
  after the same live verification. Merged as
  `3b7a14fc9a4d573fe09e87575a255034e5e1ba9a` on 2026-07-14.
- [x] Merge the #58/#59 state into the publication branch; retarget #61 to
  `main` before final review.
- [x] Confirm the frozen `sota-v2` contract fingerprint and score fingerprint
  match the published documentation and generated artifacts.
- [x] Run the complete local release gate on the merged state:

  ```bash
  python3 -m pytest -q
  python3 -m ruff format --check gm_bench examples tests
  python3 -m ruff check gm_bench examples tests
  python3 -m gm_bench validate-contract
  python3 -m gm_bench calibrate-score --json
  cd web && ~/.bun/bin/bun run lint && ~/.bun/bin/bun run build
  ```

- [x] Verify every archived v1 artifact with the historical `archive-v1`
  authenticity policy; strict `sota-v1` remains an eligibility question.
- [x] Confirm the current v2 leaderboard is empty rather than populated with
  invalid, diagnostic, or historical rows.
- [x] Confirm `results/diagnostics/`, `results/leaderboard/`, and archived result
  directories have distinct, documented meanings in
  `docs/production_benchmark.md`, `docs/submitting_results.md`, and the archive
  README.

**Exit condition:** `main` contains a stable, frozen, fully green v2 benchmark
and the safe execution path needed for expensive model panels.

### Phase 1 — validate and freeze the fixed-cap panel

This phase proves that the common safety ceiling and registered routes work
before any full-panel score is visible.

- [x] Land or finalize the infrastructure in [#61 — publishable leaderboard
  pipeline](https://github.com/nedcut/gm-bench/pull/61).
- [x] Obtain an independent review of #61 after it leaves draft; resolve or
  explicitly disposition every substantive finding before expensive runs begin.
- [x] Retain the earlier three-model/four-cap design and analyzer as auditable
  history without treating it as an active publication prerequisite.
- [x] Freeze common scaffold conditions: temperature omitted, hardened
  scaffold, compact profile, one repair, and fresh-spawn execution.
- [x] Freeze exact model routes and the registry only after all ten phase-one smokes are
  accepted.
- [x] Validate the provisional common 4,096-token safety ceiling with
  native-minimum reasoning.
- [x] Predeclare exact provider slugs/tags and the 75% cap-pressure rule: raise
  the entire lane to 8,192 before full results if any smoke call reaches 3,072
  total output tokens or shows cap-induced truncation.
- [x] Freeze the permitted retry conditions, exclusion rules, and stopping rule
  in `config/publication_protocol.json` before seeing sweep outcomes.
- [x] Distinguish infrastructure/provider failures that permit a resumed run from
  poor model behavior that must remain part of the measured result.
- [x] Smoke all ten provisional phase-one models serially at 4,096 using the hardened
  scaffold. Start with dry-run and endpoint preflight; then run one paid model,
  inspect it, and approve the next rather than launching the set blindly.
- [x] Verify each smoke's exact route, JSON behavior, registered reasoning provenance,
  repair/failure telemetry, cost coverage, per-call output distribution, and
  absence of truncation. Then record it with `run_publication_matrix.py
  record-smoke` so the machine-enforced manifest accepts it; the panel phase
  refuses to run until every registered model has an accepted entry.
- [x] Apply the cap-pressure rule before full results. It did not fire: the
  maximum smoke output was 1,432 tokens, below the 3,072-token trigger, so the
  lane remained at 4,096.
- [x] Freeze the provisional model registry only after all ten phase-one routes pass.
- [x] Re-estimate and record expected full-panel cost, runtime, serial
  concurrency, and quota after the smokes. Final raw artifact cost was
  $48.993235 across all ten completed cells; measured account spend was
  approximately $49.06.
- [x] Preserve raw artifacts and final run metadata outside git; package them as
  hash-linked release assets without discarding diagnostic cells.
- [x] Confirm in automated tests that the retired analyzer still rejects
  missing, duplicate, mixed-provenance, wrong-route, wrong-lane, wrong-repeat,
  incomplete-telemetry, and invalid-contract cells.
- [x] Update `config/sota_v2_lane.json` to `frozen-native-reasoning-cap` only
  after the ten phase-one smokes clear the cap-pressure audit.
- [x] Record the rationale, decision date, pre-full-panel trigger, and known
  limitations in the decision log below.
- [x] Regenerate the site and confirm it still refuses to publish a ranking if
  any publication prerequisite is missing.

**Exit condition:** the official API lane has a documented fixed-cap policy,
all ten phase-one registered-model smokes pass without a cap-pressure trigger, the model
registry is frozen, and the full-panel cost plan is refreshed.

#### Safe execution workflow

All model calls are serial. Inspect all ten phase-one smoke commands and their non-secret
provider options first.

```bash
python3 scripts/run_publication_matrix.py smoke --dry-run
```

Source credentials locally, then run endpoint/parameter preflight without a
model request:

```bash
python3 scripts/run_publication_matrix.py smoke --preflight-only
```

Run the cheapest pre-registered smoke first. Before a cell launches, the spend
guard reserves its output-ceiling cost from the committed price snapshot; it
also uses the larger of completed-artifact telemetry and the OpenRouter account
delta. Reservations survive failed cells. Price drift or input growth can still
make actual cost exceed an estimate, so keep smoke caps small and inspect account
usage and cap pressure after every cell:

```bash
python3 scripts/run_publication_matrix.py smoke \
  --model-id openrouter-qwen3.7-plus-alibaba \
  --run-dir data/publication-runs/smoke-native-4096-2026-07-16 \
  --max-spend-usd 5
```

In a second terminal, use the read-only monitor for live episode progress,
active/interrupted state, accepted-smoke state, artifact-reported cost, and
reserved spend. The runner checkpoints after every seed/repeat episode, so the
display updates at that durable boundary:

```bash
python3 scripts/run_publication_matrix.py status \
  --run-dir data/publication-runs/smoke-native-4096-2026-07-16 \
  --watch
```

Omit `--watch` for a one-shot status table, or add `--json` for machine-readable
status suitable for logs and other wrappers.

After each smoke passes inspection, record it so the machine-enforced manifest
accepts the route. The command validates route, options, fingerprints, zero
failures, complete finish-reason coverage, absence of truncation, and peak
total output tokens below 3,072 before writing an accepted entry to
`config/sota_v2_smoke_manifest.json`:

```bash
python3 scripts/run_publication_matrix.py record-smoke \
  --model-id openrouter-qwen3.7-plus-alibaba \
  --artifact data/publication-runs/smoke-native-4096-2026-07-16/raw/openrouter-qwen3.7-plus-alibaba--4096.json
```

Repeat one registered model at a time. Only after all ten phase-one standardized smokes,
the cap-pressure audit, and the refreshed cost estimate are acceptable should
the model registry be frozen and the full panel begin. The `panel` phase now
refuses to run unless every registered model has an accepted manifest entry;
editing `selection_status` to "frozen" is no longer sufficient. The driver creates
atomic raw artifacts and per-cell checkpoints, uses validated resume when a
checkpoint already exists, and refuses to fan out workers:

```bash
python3 scripts/run_publication_matrix.py panel \
  --run-dir data/publication-runs/sota-v2-native-4096 \
  --max-spend-usd <approved-panel-budget>
```

Do not run `panel` until `config/sota_v2_models.json` records a frozen registry.
The driver enforces that lock.

### Phase 2 — run the publishable model panel

- [x] Freeze the revised 10-model phase-one provider/model/route registry in
  `config/sota_v2_models.json` after changed-route smokes pass.
- [x] Pre-register the full-panel rerun and exclusion policy. A disappointing
  valid result is not a reason to rerun a model.
- [x] Target 8–12 models covering frontier, mid-tier, smaller, and open-weight
  models where technically and financially practical.

The provisional restarted headline panel is:

| Model | Pinned upstream | Panel role |
| --- | --- | --- |
| GPT-5.6 Luna | OpenAI | Frontier OpenAI anchor |
| Claude Sonnet 5 | Amazon Bedrock global | Anthropic frontier anchor; direct Anthropic route was unhealthy at revision time |
| Gemini 3.5 Flash | Google AI Studio | Google fast frontier anchor; mandatory `minimal` reasoning |
| Grok 4.5 | xAI | xAI frontier anchor; mandatory `low` reasoning |
| Muse Spark 1.1 | Meta | Meta frontier anchor; mandatory `minimal` reasoning |
| GLM 5.2 | Novita FP8 | Open-weight anchor; replacement for the unhealthy first-party Z.AI route |
| MiniMax M3 | MiniMax FP8 | First-party open-weight anchor |
| Qwen 3.7 Plus | Alibaba | Qwen frontier open-weight anchor |
| Mistral Medium 3.5 | Mistral | European open-weight anchor |
| Tencent HY3 | Novita free | Temporary free route expiring July 21; prompt-only JSON because the endpoint does not advertise `response_format` |

The mixed reasoning policy is explicit rather than hidden: reasoning is off for
the seven optional-reasoning models and set to the lowest catalog-supported
effort for the three mandatory-reasoning models. Scores remain comparable as
model-plus-native-inference systems, while reasoning tokens, cost, and latency
must be reported beside score.

- [x] Record exact model identifiers, endpoint snapshot names, and upstream routes;
  never collapse distinct snapshots
  under a generic family name.
- [x] Keep the headline lane API-only, fresh-spawn, `compact`, and under the
  frozen output policy.
- [x] Keep coding-agent CLI harnesses in a separate diagnostic table.
- [x] Never parallelize Claude or another subscription/rate-limited CLI; the
  phase-one API cells ran serially with one worker.
- [x] Verify all 10 provisional phase-one provider/model routes can accept the common
  privacy, parameter, JSON, registered reasoning, and bounded-output policy.
- [x] Run a benchmark-level smoke for every provider/model combination at the
  shared frozen cap immediately before the full panel.
- [x] Use serial execution, fail-fast behavior, atomic checkpoints, and validated
  resume rather than restarting completed episodes.
- [x] Run all eight official seeds, five seasons, and three candidate repeats.
- [x] Use the full official baseline panel.
- [x] Require complete input/output token, latency, failure, repair, route, and
  cost telemetry for every headline API decision; quarantine rows that fail.
- [x] Reject or quarantine any row that does not pass strict `sota-v2` validation.
- [ ] Put interesting but ineligible rows in `results/diagnostics/`, never in the
  headline table. Mistral's compact diagnostic is committed; Grok's
  non-compactable raw diagnostic still needs release-asset packaging.
- [x] Compact only after strict validation and preserve the raw-artifact hash.
- [x] Keep committed result artifacts under the CI size limit.
- [ ] Publish raw public-panel traces as release assets so results are auditable.
- [x] Preserve provider errors and incomplete attempts as diagnostic evidence.
- [x] Regenerate the leaderboard from source artifacts; do not hand-copy scores.
- [x] Require at least eight eligible, registered, route-matched, cost-complete
  headline rows before the generated JSON can expose a ranking.

For every headline model, report at least:

- [x] mean score and score standard deviation;
- [x] an uncertainty interval for the mean or paired lift, with its method;
- [x] lift versus the full baseline-panel mean;
- [x] lift versus `pick-trader`;
- [x] per-seed win rate and paired sign-flip p-value;
- [x] input tokens per decision and output tokens per decision;
- [x] total cost and cost per episode;
- [x] illegal actions, failed queries, adapter failures, and repair attempts;
- [x] execution lane, provider route, model snapshot, and scaffold fingerprint;
- [x] result contract and seed-panel identity; and
- [x] per-mechanic outcomes for drafting, trades, free agency, cap management,
  scouting, and lineup decisions where supported.

- [x] State how multiple model comparisons are handled. If adjusted inferential
  claims are not justified at this sample size, label per-model p-values as
  descriptive and emphasize effect sizes and uncertainty instead.

**Exit condition:** the generated current leaderboard contains a meaningful set
of strictly eligible and compute-comparable v2 model rows.

### Phase 3 — private-panel and robustness evidence

The public panel is for reproducibility. The private panel is needed for the
strongest contamination-resistant claim.

- [ ] Select a private seed panel with at least the official minimum count.
- [ ] Create and publish a salted pre-commitment before running models.
- [ ] Keep private seeds, raw traces, and salt outside the repository.
- [ ] Run at least the headline models under the same frozen lane and contract.
- [ ] Validate locally with `GM_BENCH_PRIVATE_SEEDS` set.
- [ ] Publish only validated, redacted private-panel artifacts.
- [ ] Compare public and private conclusions and disclose meaningful divergence.
- [ ] Document the panel-rotation schedule and future reveal procedure.
- [ ] Run the power analysis using final model residuals.
- [ ] Report the minimum detectable difference and the limited p-value resolution
  of an eight-seed panel.
- [ ] Run score-weight sensitivity and report whether important rankings change
  under plausible perturbations. The scripted-panel sensitivity is reported in
  `docs/scoring_calibration.md`; model rows become reweightable only from
  `sota-v3` artifacts, which carry `score_components`.
- [ ] Check whether conclusions depend on a single seed, season, mechanic, or
  extreme episode.
- [ ] Confirm the oracle-to-`pick-trader` gap still leaves meaningful headroom.

**Exit condition:** the main conclusion survives an appropriately held-out panel
or is narrowed to reflect any discrepancy.

### Phase 4 — claims and interpretation

- [ ] Write the primary research question in one sentence before drafting the
  conclusion.
- [ ] Keep the claim scoped to this synthetic environment and frozen condition.
- [ ] Say whether the benchmark compares base models, models plus a standardized
  scaffold, or full agent harnesses. Do not blur these units of evaluation.
- [ ] State that scripted policies were designed with knowledge of the simulator
  and are transparent environment-specific references, not general AI systems.
- [ ] Separate protocol competence from strategic competence.
- [ ] Treat JSON failures, query failures, and repair behavior as measurements,
  not invisible noise.
- [ ] Discuss the fixed output-safety policy and observed token efficiency before
  presenting a ranking.
- [ ] Describe the hand-designed scoring function and its construct-validity
  limits.
- [ ] Explain why score components were chosen and show calibration/sensitivity.
- [ ] Report null, negative, or mixed findings without replacing the frozen panel
  post hoc.
- [ ] Clearly label archived v1 data as withdrawn historical evidence.
- [ ] Include the scout-contract failure and unequal-budget discovery in the
  methodology story.
- [ ] Distinguish reproducible public-panel evidence from contamination-resistant
  private-panel evidence.
- [ ] Avoid claims about real-world sports management, general intelligence, or
  model superiority outside GM-Bench.

Recommended framing:

> Which current model-plus-standardized-scaffold systems can beat a transparent
> heuristic at long-horizon asset management under one fixed response budget?

Claims that may be supportable after the study:

- At a stated output budget, model X did or did not outperform transparent
  scripted references on the frozen GM-Bench v2 environment.
- Models differed in observed token, cost, and latency efficiency under the same
  output safety ceiling.
- Models showed specific strengths or weaknesses across measured mechanics.
- API and coding-harness conditions produced materially different results and
  should be treated as different evaluation lanes.

Claims to avoid:

- “LLMs cannot manage sports teams.”
- “Model X is generally more strategic than model Y.”
- “GM-Bench measures general intelligence.”
- “A `sota-v2`-eligible result is state of the art” without the comparative
  evidence and compute context.

### Phase 5 — blog, site, and durable artifacts

- [x] Generate all tables and headline numbers from validated artifacts.
- [x] Keep a visible “last updated” date and contract version on the site.
- [ ] Lead the blog with the research question and the measurement problem, not
  with implementation history.
- [ ] Explain the simulator and decision loop with one compact diagram.
- [ ] Explain the provisional 4,096-token native-reasoning policy and cap-pressure audit before
  the final model ranking.
- [ ] Show Oracle → `pick-trader` → best eligible model → `random` headroom.
- [ ] Include cost and compute beside score in every model table.
- [ ] Include uncertainty and failure telemetry, not only means.
- [ ] Include a concise limitations and threats-to-validity section.
- [ ] Link each row to its compact artifact and raw release asset.
- [ ] Link the exact contract fingerprint, score fingerprint, commit, and model
  identifiers used for the release.
- [ ] Keep CLI-harness rows visually separate from the API headline lane.
- [ ] Confirm the site remains legible on mobile and without JavaScript errors.
- [ ] Check basic accessibility: keyboard navigation, focus visibility, semantic
  headings/tables, color contrast, and meaningful chart alternatives.
- [ ] Check every command and internal link from a clean clone.
- [ ] Have at least one person unfamiliar with the project read the draft and
  describe what they think the benchmark proves.
- [ ] Revise any section they interpret more broadly than intended.

**Exit condition:** a reader can move from claim to table to validated artifact
to raw evidence without relying on trust in the author.

### Phase 6 — GitHub and portfolio presentation

- [x] Replace “GM-Bench MVP” with a confident, accurate project name and one-line
  description.
- [ ] Add a concise GitHub repository description.
- [ ] Add the deployed site as the repository homepage.
- [ ] Add relevant topics such as `llm-evaluation`, `agents`, `benchmark`,
  `simulation`, `sports-analytics`, and `reproducible-research`.
- [x] Put the primary result or honest “results pending” state near the top of the
  README.
- [x] Add a five-minute release-verification path that works from a clean clone without provider
  credentials.
- [ ] Add a separate provider-backed quickstart with explicit cost expectations.
- [ ] Add an architecture or evaluation-flow diagram.
- [ ] Add a “What this measures / What this does not measure” section.
- [ ] Link benchmark specification, production standard, result submission guide,
  blog, site, and release from the README.
- [ ] Remove or ignore accidental local artifacts and document where run outputs
  belong.
- [ ] Make sure a clean clone contains no credentials, private seeds, raw private
  traces, or machine-specific paths.
- [x] Create a tagged GitHub release for the frozen v2 study.
- [ ] Add concise release notes and a changelog entry explaining what is frozen,
  what was withdrawn, and what remains diagnostic.
- [ ] Attach raw public traces, generated analysis, checksums, and a compact
  reproducibility manifest to the release.
- [ ] Add citation metadata (`CITATION.cff`) even though this is not a paper.
- [ ] Add contribution and result-submission instructions.
- [ ] Add an issue template for third-party result submissions or reproductions.
- [ ] Ask for one independent clean-clone reproduction.
- [ ] Record successful external reproduction in the README or release notes.
- [ ] Obtain an independent final review of the result-generation and publication
  PR, not only automated CI/review-bot approval.
- [ ] Decide whether to publish the package to PyPI; if not, document the
  supported install path clearly.
- [ ] Park or close stale/superseded PRs so the public queue tells a coherent
  story.

**Exit condition:** the repository looks like a maintained public benchmark,
not a private experiment whose best context lives in its PR history.

### Phase 7 — release decision

Before pressing publish, answer each question with evidence:

- [ ] Is the benchmark contract frozen and identified by fingerprint?
- [ ] Can a clean clone reproduce the scripted calibration and validity suite?
- [ ] Was the fixed output-safety policy validated across every registered model
  before full-panel scores were generated?
- [ ] Is every headline model row strictly eligible and compute-comparable?
- [ ] Are raw public traces and compact artifacts available and hash-linked?
- [ ] Are private-panel claims properly committed, redacted, and scoped?
- [ ] Are statistical uncertainty and practical effect sizes both reported?
- [ ] Are all important failures and exclusions visible?
- [ ] Does the blog say exactly what the evidence supports—and no more?
- [ ] Can an outsider follow the quickstart and understand the result?
- [ ] Are CI, the site build, artifact validation, and link checks green?
- [ ] Has v3 work remained separate from the frozen v2 publication lane?

If any answer is “no,” either finish the work or narrow the release claim until
the answer becomes “yes.”

## Known limitations to preserve in the final writeup

These should be refined, not quietly removed:

- GM-Bench is a synthetic hockey-style environment, not a real front office.
- The scoring function is hand-designed and inevitably encodes value judgments.
- Scripted baselines were written with direct knowledge of the environment.
- The partial oracle is a privileged hidden-information diagnostic, not a fair
  participant, optimization ceiling, or valid model submission.
- Eight public seeds provide limited environmental and statistical resolution.
- Candidate repeats measure model sampling variation, not new environments.
- Prompt scaffolds, repair policies, provider routing, and output budgets affect
  results.
- A model-plus-scaffold result is not a pure measurement of model weights.
- Coding-agent harnesses add uncontrolled context and tool-loop behavior.
- Public deterministic seeds are reproducible but contamination-exposed.
- Private evaluation reduces contamination risk but still depends on operator
  discipline.
- Benchmark version churn prevents results from accumulating unless a contract
  remains frozen long enough to build a meaningful panel.
- Performance inside the benchmark may not transfer to other strategic domains.

## Post-publication contract hardening

- [x] Publish and tag the frozen `sota-v2` evidence before changing simulator
  semantics.
- [x] Merge [#85](https://github.com/nedcut/gm-bench/pull/85) only after the
  complete test, lint, contract, historical-artifact, analyzer, and site gates
  pass on its exact head. Merged as
  `1e5cd449b1d2504aa464e54bb58e6dcdc9641e21` on 2026-07-24.
- [x] Reject non-finite action inputs and forbid non-finite publication JSON.
- [x] Make negotiation walk-aways persist for the full decision window.
- [x] Recompute compact-artifact statistics and verify raw-artifact hashes when
  raw evidence is supplied.
- [x] Preserve a literal historical `sota-v2` validation contract rather than
  reinterpreting released rows against current source.
- [x] Start corrected development at `sota-v3`; do not re-record old smokes,
  silently unlock the old publication runner, or spend on a new panel without a
  new pre-registered registry and lane.
- [ ] Add the post-release integrity disclosure to every public surface where a
  reader might confuse the frozen v2 study with current development behavior.
- [x] Complete Issue #84's landed evidence/claim items in order of scientific
  impact: scoring decomposition, same-view/scaffold comparison, power/no-ranking
  framing, and memo-volume association. Scoring decomposition landed as the
  `sota-v3` `score_components` block plus `weight_sensitivity.py --result`. The
  same-view/scaffold **measurement** is recorded under `4f6ddddd6a6dd81c` (see
  [`docs/run_logs/scaffold-view-official-panel-2026-07-25.md`](run_logs/scaffold-view-official-panel-2026-07-25.md));
  the power/no-ranking and memo conclusions are recorded in
  [`docs/run_logs/gap-decomposition-and-panel-power-2026-07-26.md`](run_logs/gap-decomposition-and-panel-power-2026-07-26.md)
  and surfaced by #99/#101. This is not a causal memo intervention: a
  controlled memo ablation remains open but does not block preregistration or
  offline rehearsal. Additional realism polish is deferred by the v3
  mechanics-freeze decision below.
- [x] **Run `scaffold-view` under the current candidate contract fingerprint
  before a paid panel.** First measured 2026-07-25 on seeds 11–18 at 5 seasons
  under fingerprint `4f6ddddd6a6dd81c`, and **revalidated 2026-08-03 under the
  `sota-v3` candidate fingerprint `a523bdfcebe47bbd`** at
  `88ab7df191ef4d8e3ec4921a3e374e51d7fcc91c`, where every headline mean,
  per-seed score, and the paired *t* reproduce exactly. Paired mean gap versus
  `pick-trader` is +2.8 points.
  See [`docs/run_logs/scaffold-view-official-panel-2026-07-25.md`](run_logs/scaffold-view-official-panel-2026-07-25.md).
  The baseline remains outside `PRESETS["leaderboard"]` (2026-07-24 entry); the
  gap is diagnostic only and does not re-rank models.
- [ ] Obtain and link an independent clean-clone reproduction. A closed issue
  without a report is not evidence of reproduction.

### Consultant audit critical path ([#93](https://github.com/nedcut/gm-bench/issues/93))

Full P0/P1 backlog lives in Issue #93, but backlog membership is not the same as
a pre-spend blocker. The finite critical path is below; the verified 2026-07-27
snapshot is in
[`docs/run_logs/sota-v3-preflight-2026-07-27.md`](run_logs/sota-v3-preflight-2026-07-27.md).

- [x] Merge [#92 — contract economics](https://github.com/nedcut/gm-bench/pull/92)
  after confirming no live checkpoints under `data/model_checkpoints/`. Merged
  2026-07-26; the contract fingerprint is now `4f6ddddd6a6dd81c`, so any
  checkpoint keyed to an earlier fingerprint is invalid and must not be resumed.
- [x] **Run `scaffold-view` on seeds 11–18 at 5 seasons** under the frozen
  contract fingerprint with no contract-source change before or after (Issue #84
  item above). Completed under `4f6ddddd6a6dd81c` in
  [#98](https://github.com/nedcut/gm-bench/pull/98); paired gap +2.8, diagnostic
  only.
- [x] Fix site claim integrity while the public page still sells v2: tiered or
  CI-backed baseline ladder in `Analysis.tsx`, `tokens_per_decision` on score
  surfaces, relabel partial-oracle reference, and a public-panel adaptation /
  contamination caveat mirroring the blog. Landed in
  [#95](https://github.com/nedcut/gm-bench/pull/95), which also named the stored
  `ci95` field as a *lift* interval so it is not read as an interval on score.
- [x] Finish pre-registering the v3 publication lane (`config/sota_v3_lane.json`,
  registry, and initially empty smoke manifest) before authorizing spend. Freeze the
  research question, model/route selection, public or private seed-panel
  identity, seeds-versus-repeats allocation, reasoning/output limits, strict
  fallback, exclusions, multiplicity family, cost model, and operator ceiling.
  The focused v3 analysis supports only model-versus-`pick-trader` contrasts,
  with Holm correction across the final registered model family; it does not
  assign model tiers or support all-pairs ranking. Before power simulation,
  require enough independent seeds for the exact two-sided sign-flip minimum
  p-value (`2 / 2**seeds`) to clear Holm step one (`0.05 / models`).
  The statistical design is frozen. Spend and strict-smoke execution are
  separately authorized; panel execution and publication remain locked.
  Corrected 10,000-trial production-procedure simulations include the historical
  residual lift seed variance (`3770.4784`) as a draw shared across all eight
  model contrasts. The original +40 superiority design was abandoned: no
  allocation in the 9–20 seed x 1–3 repeat grid reached the 0.80 target, and the
  20-seed ceiling caps sensitivity power near 0.36 even at unbounded repeats, so
  the block was structural rather than a budget shortfall. Design amendment 1
  restates the primary claim in the direction the frozen `sota-v2` evidence
  actually shows — every eligible model *trailed* `pick-trader` by 180–282
  points at a 0.0 seed win rate — and powers a −100 planning effect. The
  selected allocation is **15 seeds x 1 repeat (15 episodes/model)**, base power
  0.9461 and sensitivity power 0.8357 (Wilson 95% CI 0.8283–0.8428), clearing
  the target on its lower bound. Repeats moved 3 → 1 because a
  candidate-minus-reference lift keeps its full seed component, so at fixed
  budget seeds dominate repeats for discrimination. Evidence, covariance
  assumptions, and the amendment are recorded in
  [`docs/run_logs/sota-v3-design-amendment-2026-07-28.md`](run_logs/sota-v3-design-amendment-2026-07-28.md),
  superseding
  [`docs/run_logs/sota-v3-statistical-design-audit-2026-07-28.md`](run_logs/sota-v3-statistical-design-audit-2026-07-28.md).
  The owner-authorized private seed panel is now frozen: the audited unbiased
  generator produced 16 high-entropy ordered seeds, only the salted hiding
  commitment plus ordered execution hash are committed, and the secret values
  and salt are escrowed in macOS Keychain. Exact-route and synthetic-data
  privacy evidence are accepted, so the overall preregistration, registry,
  protocol, pricing, output budget, spend, and strict-smoke gates are frozen.
  Panel execution and publication remain locked. Design amendment 2 (2026-08-03,
  [`docs/run_logs/sota-v3-design-amendment-2026-08-03.md`](run_logs/sota-v3-design-amendment-2026-08-03.md))
  is a pre-data cohort update: the OpenAI anchor moves from GPT-5.6 Luna Pro to
  plain GPT-5.6 Luna, and DeepSeek V4 Flash 0731 plus Tencent Hy3 join as
  open-weight anchors on first-party FP8 routes (Thinking Machines Inkling
  Small was evaluated and recorded ineligible: no healthy route advertises
  `response_format` under the lane's frozen JSON-mode and require-parameters
  options). The Holm family is now ten, and the allocation reselected with the
  identical frozen machinery is **16 seeds x 1 repeat (16 episodes/model)** —
  base power 0.9527, sensitivity 0.8488 (Wilson 95% lower bound 0.8416); the
  prior 15x1 allocation fails the lower-bound rule at family ten (0.8020,
  lower bound 0.7941). The contract fingerprint is unchanged. The reproducible
  conservative pre-smoke reservation is recorded in
  `results/analysis/sota-v3-pre-smoke-cost-estimate.json`: 3,240 calls,
  $106.073183 before contingency and $127.287820 at the committed 1.2x reserve.
  Runtime remains pending accepted smoke telemetry. Those ten-model figures
  are historical inputs to the next amendment, not the active plan. Design
  amendment 3 (2026-08-06,
  [`docs/run_logs/sota-v3-design-amendment-2026-08-06.md`](run_logs/sota-v3-design-amendment-2026-08-06.md))
  removes the two mandatory-reasoning routes before any v3 model evidence,
  leaving eight uniformly reasoning-disabled routes at Holm family size 8.
  The frozen seed allocation remains 16x1, with sensitivity power 0.8727
  (Wilson lower bound 0.8660), and the operator ceiling is now $100. The
  generated cost artifact, rather than a duplicated prose amount, is the
  authoritative planning forecast; the runner enforces the ceiling before each
  provider call. Pre-data amendment 4 (2026-08-09) records that separation and
  makes cap pressure abort this contract on its first trigger; it does not
  authorize an in-place cap or ceiling amendment. A
  runtime private panel can change without changing the contract fingerprint;
  editing the canonical public leaderboard preset in
  `gm_bench/benchmark_config.py` does change it and would require one pre-data
  lane amendment plus a free re-run of fingerprint-bound diagnostics.
- [x] CI validates each committed leaderboard artifact against the policy matching
  its own declared `benchmark_version` (unknown versions fail loudly), so the
  first `sota-v3` row is covered without a hardcoded `sota-v2` step. Landed with
  [#99](https://github.com/nedcut/gm-bench/pull/99); no real committed v3
  artifact exists yet, so the dispatch path is implemented but has not validated
  a real committed v3 row. The smoke-coverage half was already done:
  `require_strict_fallback` and the CapHoard seed-level assertion in
  [#96](https://github.com/nedcut/gm-bench/pull/96), and `extend_contract` prompt
  conformance in #92.
- [x] Re-run the integrated, no-provider-call v3 rehearsal after the current
  contract/config hardening:
  generate a disposable result, apply the registered policy, compact it, verify
  raw/compact hashes, run the actual publication analyzer on a nondegenerate
  paired synthetic panel, exercise site ingestion and the web build in an
  isolated staging copy without replacing the public v2 study, and prove stale
  fingerprints, wrong routes/policies, broken hashes, and unknown versions fail
  closed. On 2026-08-09, `python3 scripts/sota_v3_rehearsal.py` passed on the
  integrated candidate with zero spend, no cross-file coherence issues, seven
  rejected mutations, a finite nonzero paired-lift interval, shared row
  ingestion, a generated dataset matching the checked-in frozen-v2 site data,
  the synthetic v3 row excluded, and a successful staged web build. The
  synthetic output is diagnostic, not panel evidence.
- [x] After these changes are committed, rerun the rehearsal from a clean
  checkout at the exact candidate SHA and record that SHA before any spend.
  **Verified unassisted 2026-08-09 at candidate SHA
  `17d5f3c77f7c96b1223cd6688242e91d65833202`.** A fresh clone from the GitHub
  remote with no `web/node_modules` completed the full rehearsal with status
  `passed`, spend `0.0`, all seven mutations rejected, `sota_v2` rejected /
  `sota_v3` accepted, frozen-v2 site data byte-matching the checked-in dataset,
  the synthetic v3 row excluded, 42 packages installed under the frozen Bun
  lockfile, and a successful production web build. The same clean clone passed
  all 783 tests. Panel execution and publication remain locked; this authorizes
  no paid panel. The authenticated exact-route/price refresh and eight strict
  paid smokes remain the next execution gate.

  Previous clean-clone record: **2026-08-03 at candidate SHA
  `02a069937d167810b261c21928c85cd3730f5461`.** A fresh clone from the GitHub
  remote with no `web/node_modules` runs `python3 scripts/sota_v3_rehearsal.py`
  to completion with no manual preparation: status `passed`, `spend_usd` 0.0,
  `evidence_class` `synthetic-non-evidence`, all seven mutations rejected,
  policy selection `sota_v2` rejected / `sota_v3` accepted, generated site
  data byte-matching the checked-in frozen v2 dataset with the synthetic v3
  row excluded, dependencies `installed` via `bun install --frozen-lockfile`
  (40 packages), and a successful staged build. The full suite passes in the
  same clone (742 tests). No contract source was touched, so the fingerprint
  remains `a523bdfcebe47bbd`, matching `config/sota_v3_lane.json`. This
  authorized no spend at that SHA and is superseded by the 2026-08-09 record.

  **When this record goes stale.** The rehearsal stages `config/`,
  `results/leaderboard/`, `results/analysis/`, and `web/`, so a commit
  touching any of those — or any `_CONTRACT_SOURCES` file — invalidates this
  verification and requires a rerun before spend. Commits confined to `docs/`
  or `tests/` do not, since neither is staged nor fingerprinted. State the
  rule rather than chasing the SHA: re-verify when a staged input changes, and
  once more immediately before the first authorized spend.

  Earlier runs, superseded: `3be9432e10dd0f81c9e58f89bbaae1e0c5a7465f`
  (2026-08-03, before the registry moved to `route-preflight-ready`) and
  `63f28e6897383fe73394c1e4354005dd404fb30b` (2026-08-01, before the
  cohort-ten amendment). Both recorded the same result, and both predate edits
  to `config/sota_v3_models.json`, which the rehearsal validates against.

  The first attempt, at `a0fdec5493eaf5f702e71c519910e03f39e727f5`, **failed**
  — recorded here because the failure mode is the point. `_run_web_build`
  aborted with an unhandled `CalledProcessError` (exit 127, `vite` absent)
  because `_stage_site_inputs` symlinks `web/node_modules` only when it
  already exists in `ROOT`, which is never true on a clean checkout. The
  2026-07-27 run had passed only by inheriting `node_modules` from the tree it
  ran in: the gate was passing for the wrong reason, and the single dependency
  it never checked was the one a clean-checkout rerun exists to rule out. No
  test caught it because every case in `tests/test_sota_v3_rehearsal.py`
  passed `run_web_build=False`, leaving the build path uncovered.
  `_ensure_web_dependencies` now resolves the dependency explicitly and
  records under `web_build.dependencies` which path ran; three regression
  tests cover install, reuse, and failure.

  Those three tests shipped incomplete, and the gap is worth recording because
  it repeats the pattern above. All three call `_ensure_web_dependencies`
  directly, so none of them touches the call site inside `_run_web_build` —
  the single line that makes a clean checkout work. Stubbing that line out
  left the suite fully green, meaning the fix could be deleted without any
  signal. Two tests added 2026-08-03 drive `_run_web_build` itself and assert
  the install precedes the build; the same sabotage now fails 2 of 11 tests.
  A regression test that passes with the code removed is not coverage, and the
  only way to learn which case you are in is to break the code on purpose.
- [x] Select exact routes, grant the separate zero-completion-call
  `route_preflight_authorized` gate, then run
  `python3 scripts/run_publication_matrix.py route-preflight --contract sota-v3`.
  This phase checks endpoint identity and parameters but cannot launch a model
  subprocess, reserve spend, or create run state.
  **Ran 2026-08-03 at $0.00; all ten routes in the then-current registry passed
  at that instant.** See
  [`docs/run_logs/sota-v3-route-preflight-2026-08-03.md`](run_logs/sota-v3-route-preflight-2026-08-03.md).

  **This box records that the probe ran and that its findings were acted on.
  It is not a standing claim that the routes are reachable now, and it must
  not be read as one before authorizing spend.** A passing route check has a
  shelf life measured in hours: the first-party `deepseek/deepseek-v4-flash-0731`
  route passed this very run and was deranked to status `-5` the same evening,
  serving 78% of requests, while its 24h availability figure still read 99.24%.
  Re-run the probe immediately before any paid phase and treat a stale pass as
  no pass.

  Nine of ten pins were correct on first contact. `qwen/qwen3.7-plus` failed
  because its Alibaba endpoint tag had moved from `alibaba` to `alibaba/fp8`;
  the route itself is healthy and its provider name, endpoint name, and every
  price are unchanged, so this was a stale label rather than a lost model. The
  tag was corrected in the registry and the bound pricing slug, the cost
  artifact regenerates byte-identically, and **the cohort stays at ten with
  the 16x1 allocation and $107.81 reservation intact.** Running this before
  the seed panel was the point: a genuinely dead route would have forced a
  cohort amendment, and cohort size drives the Holm family size, the
  allocation, and the reservation.

  Design amendment 3 later retained eight of those accepted routes and removed
  Gemini 3.6 Flash and Grok 4.5. The registry's August 6 acceptance records are
  the active eight-route evidence, but route availability and prices must still
  be refreshed immediately before paid smoke execution.
- [x] After explicit owner authorization, use
  `scripts/seed_panel_commitment.py generate --lane config/sota_v3_lane.json
  --secret-file <recoverable-private-escrow-outside-the-checkout>` to draw the ordered 16-seed panel
  uniformly with `secrets.randbelow`, excluding duplicates and committed public
  preset seeds. Independently verify the salted hiding commitment and ordered
  execution hash; commit commitments only, never seed values. The legacy
  `commit --seeds-env` path is for verifying or adopting an independently
  generated escrowed panel, not the registered generation procedure. Complete:
  the public lane contains only the salted hiding commitment and ordered hash;
  the 16 seed values and salt remain escrowed in macOS Keychain.
- [x] Review the preregistration, route-preflight, and rehearsal records; freeze
  the seed-panel identity and execution policies; then make a separate explicit
  spend-authorization decision for serial route smokes. Spend and strict-smoke
  execution are authorized; panel execution is still separately locked.
- [ ] Decide v3 site strategy (historical v2 page vs current v3 page) and
  propagate Holm / tier caveats before a v3 headline refresh. This need not
  block offline rehearsal.
- [ ] Report weight sensitivity and an outcome-only secondary view (titles /
  playoff rounds / wins) for future v3 model rows via `score_components`. This
  requires real v3 rows and is not a reason to delay preregistration/rehearsal.
- [ ] Fix multi-year dead-cap projection in shrewd/strategic release accounting
  and drop or accept 1-year `extension_quotes` consistently. Deferred by the
  mechanics freeze below unless a reproducible claim-threatening defect is
  demonstrated before the first accepted v3 smoke.

### `sota-v3` freeze decision — 2026-07-27

The score-affecting simulator, action/observation schemas, scoring, scripted
policy logic, and model-view compaction are **semantically frozen** at the
fingerprint recorded in `config/sota_v3_lane.json`. Do not accept another
realism or mechanics batch before the v3 rehearsal/panel merely because it
might improve the benchmark.
Reopen mechanics only for a reproducible defect that threatens the registered
claim; doing so requires an explicit decision-log entry, a new fingerprint,
invalidation of v3 preregistration evidence tied to the prior fingerprint, and
free diagnostic re-runs before any spend.

The earlier `scaffold-view` diagnostic was measured under
`4f6ddddd6a6dd81c` and was revalidated 2026-08-03 under the then-current v3
fingerprint with every figure reproducing exactly. Any later contract-source
change reopens this gate, so the final candidate fingerprint must be revalidated
before spend. The publication-lane parameters are now registered separately:
authenticated route/privacy acceptance, disabled reasoning, private seed-panel
identity, exclusions, and operator ceiling. Public site treatment remains a
post-panel publication decision. The output policy
is a 4,096-token fixed safety ceiling with a 3,072 cap-pressure trigger. The
registered 8,192-token value is a planning comparison, not an authorized
fallback. Any accepted-smoke truncation or trigger crossing invalidates all v3
smokes and aborts this contract; a later run requires a new preregistration and
full-family smoke. Observed score never influences the cap. Runtime
private-panel selection does
not alter the contract fingerprint. A change to the canonical public
leaderboard preset does; if chosen for power, treat it as a bounded pre-data
lane amendment rather than an invitation to revisit simulator mechanics.

The frozen `sota-v2` study remains a separate historical evidence lane at
fingerprint `558e8f35ea1d66b9`. No v3 rehearsal, preregistration, validator
change, or future result may rewrite or silently revalidate those artifacts.

## What should wait until after publication

- [ ] Keep [#62 — strategic contract mechanics](https://github.com/nedcut/gm-bench/pull/62)
  in the separate `sota-v3` lane until the v2 study is published.
- [ ] Do not change frozen v2 simulator, scoring, preset, or schemas to improve
  realism after model runs begin.
- [ ] Do not rerun only disappointing models with more favorable settings unless
  the full comparison policy requires the same treatment for every row.
- [ ] Do not let the landing-page rewrite become the source of truth before real
  v2 results exist.
- [ ] Capture good v3 ideas in issues without interrupting the v2 critical path.

After the v2 publication, v3 can pursue stronger contract mechanics, richer
strategic decisions, improved external validity, and lessons learned from model
failure traces without invalidating the published v2 evidence.

## Consultant audit (2026-07-25)

Independent consulting review on Issue
[#93](https://github.com/nedcut/gm-bench/issues/93) (HEAD around PR #92):

- **`sota-v3` is ready to freeze as a contract, not to launch as a public panel
  or headline refresh.** Keep the live site, blog, and release locked to the
  frozen `sota-v2` study until a pre-registered v3 panel exists.
- **Merge #92 first.** Contract economics closes a real validity hole; confirm
  no in-flight model checkpoints before merge.
- **Run `scaffold-view` before any paid v3 panel.** The observation-asymmetry gap
  is free and fingerprint-sensitive; it must land under the same contract as the
  panel contrast.
- **Site claim gaps remain P0** while v2 is the public face: ranked baseline
  ladder without CIs, missing token-efficiency surfaces, “oracle ceiling”
  overstatement, and no contamination caveat on the landing page.
- **No ordinal ranking** among models or among the new reference ladder
  (`shrewd` / `strategic` / `scaffold-view` / `pick-trader` sit within ~10
  points on the official 8-seed panel). That spread was observed under
  fingerprint `0a5f0434dca31ac5` at audit time; #92 merged as
  `4f6ddddd6a6dd81c` and #98 re-measured the panel there with scores unchanged,
  so the conclusion carries over to the current contract. The durable public
  claim stays: all eight eligible v2 systems trailed `pick-trader`; no model
  ordering is justified.

## Decision log

Add entries rather than rewriting history. If a decision changes, record the new
decision and why.

| Date | Decision | Evidence / rationale | Effect |
| --- | --- | --- | --- |
| 2026-08-16 | Accept the merged-head SOTA-v5 seed-free command and final live-price preflight evidence without authorizing spend. | After route/pricing PR #126 merged at `49f2b0577f08664c66917074ae983bf7be558452`, authenticated route/privacy evidence was refreshed for all eight exact routes, the wrapper constructed all eight serial smoke commands while `GM_BENCH_PRIVATE_SEEDS` was absent and without Keychain access, and live route-plus-price preflight passed. The route and final artifacts record `completion_calls: 0`, current contract fingerprint `247e12fe5a7d4f5b`, and OpenRouter scaffold fingerprint `f04724717cc09caf`; the final validator and route validator report no issues. | Mark final preflight accepted. Keep the smoke gate blocked only by the four explicit spend/smoke authorization flags. Require separate owner approval before changing those flags or making a completion call; keep owner attestation, panel, analysis, release, site publication, and public v2 data untouched. |
| 2026-08-16 | Accept all eight SOTA-v5 exact routes and conservatively amend DeepSeek pricing before final preflight. | Authenticated credits, provider, privacy, zero-data-retention, and exact-endpoint metadata passed for all eight routes with `completion_calls: 0`; two routes are zero-data-retention. The subsequent live-price gate found only DeepSeek above its planning snapshot: prompt `$0.00000044/token` and completion `$0.00000132/token`, versus `$0.00000014/$0.00000028`. The collector wrote the route artifact and no provider model call, Keychain, or private-seed read occurred. | Freeze the accepted zero-call route evidence, raise only DeepSeek's conservative planning rates, and regenerate the smoke budget to `$6.17324032` protocol maximum / `$7.407888384` with contingency under the unchanged `$10` ceiling. Keep spend, smoke, panel, analysis, release, and publication false pending merged-head final preflight and owner approval. |
| 2026-08-16 | Amend the pre-data SOTA-v5 Gemini route to Google AI Studio. | Authenticated zero-completion endpoint metadata showed `google-ai-studio` at `99.6568375762854%` 24-hour uptime versus `99.46602224161464%` for `google-vertex/global`; the frozen route rule selects the highest 24-hour uptime and excludes price. The exact route is `Google AI Studio | google/gemini-3.7-flash-20260813`, status `0`, 65,536-token maximum, unknown quantization, 30-minute uptime `99.31597947938438%`, prompt `$0.00000075/token`, completion/internal-reasoning `$0.00000375/token`, discount `0`. The all-route collector stopped before writing acceptance evidence. No v5 completion, smoke, panel, Keychain, private-seed, or provider model call occurred. | Update only the pre-data model/route identity, planning price, required smoke IDs, and replacement lineage. Keep exact-route acceptance pending; spend, smoke, panel, analysis, release, and publication remain false. The regenerated protocol-maximum smoke estimate is recorded in `results/analysis/sota-v5-pre-smoke-cost-estimate.json`. See [`sota-v5-route-amendment-2026-08-16.md`](run_logs/sota-v5-route-amendment-2026-08-16.md). |
| 2026-08-16 | Freeze SOTA-v5 as the prospective outcome-independent successor to terminal SOTA-v4. | Before any v5 authenticated route evidence or completion call, retain the seven non-Qwen v4 model identities and select `google/gemini-3.7-flash` on provisional `google-vertex/global` from public catalog metadata to fill the terminal Qwen slot. Preserve the uniform reasoning-disabled 4,096-token policy, family size eight, exact sign-flip/Holm plan, and still-unused 16-seed commitment with explicit lineage and an owner-attestation requirement. The initial protocol-maximum smoke estimate was `$5.47964672` (`$6.575576064` with contingency); the later pre-data route amendment supersedes that planning figure. | Make v5 the current strict contract while freezing v4 literally as historical. Authorize only authenticated zero-completion route/privacy/live-price and final-preflight work. Keep spend, smoke, panel, analysis, release, and publication locked until their separate evidence and owner decisions. See [`sota-v5-preregistration-2026-08-16.md`](run_logs/sota-v5-preregistration-2026-08-16.md). |
| 2026-08-16 | Mark Qwen/Alibaba terminally incompatible and re-lock all SOTA-v4 paid execution after its final attempt. | The machine-scoped gate admitted only `openrouter-qwen3.8-max-alibaba` at attempt 2/2. Its immediate exact-route/live-price preflight passed, then one provider request returned HTTP 400 with sanitized detail: `Reasoning is mandatory for this endpoint and cannot be disabled.` No generation, episode, decision, raw artifact, or later-model launch occurred. The cell ledger is `excluded` at 2/2. A live credits read observed `$0.00` aggregate run delta; reconciliation still charged the full `$0.1832184` unknown-call bound, hash-linked to the first reconciliation, for `$0.3664368` conservative reported spend. | Consume the one-shot authorization, set its remaining attempts to zero, and re-lock spend/smoke across every frozen record. Keep the manifest `in-progress` with zero accepted entries and `accepted_for_panel: false`. Qwen cannot be rerun or substituted in place; SOTA-v4 panel/publication remain impossible without a separately preregistered successor decision. The same free preflight found unrelated DeepSeek price drift, so DeepSeek also remains unlaunched. |
| 2026-08-16 | Authorize only Qwen/Alibaba's second and final SOTA-v4 infrastructure attempt. | The owner explicitly approved the retry after the first HTTP 400 was preserved as infrastructure-only evidence, its full `$0.1832184` unknown-call bound was conservatively charged, the active guard block was cleared, and the refreshed zero-call handoff passed at contract fingerprint `247e12fe5a7d4f5b` and OpenRouter scaffold fingerprint `f04724717cc09caf`. | Reopen spend and smoke execution only long enough to run `openrouter-qwen3.8-max-alibaba` alone, serially, under the `$10` ceiling after an immediate zero-completion route-and-price preflight. Stop after its outcome. Do not run another model; panel and publication remain false. |
| 2026-08-14 | Complete the fail-closed Qwen reconciliation and refresh the zero-call handoff without authorizing a retry. | A live credits read observed total account usage `$61.234034455` and `$0.00` run delta. The reconciliation did not treat that aggregate delta as per-call settlement; it charged the full unresolved `$0.1832184` call bound as spent, cleared the active call reservation, and retained the cell's attempt/reservation ledger. Keychain-backed command construction and authenticated route-plus-price preflight then passed for all eight routes at contract fingerprint `247e12fe5a7d4f5b` and OpenRouter scaffold fingerprint `f04724717cc09caf`, recording zero completion calls. | The adapter can capture bounded provider detail on a future failure and the guard is internally reconciled, but the original HTTP 400 detail remains unrecoverable. Spend and smoke remain false pending a separate owner decision on Qwen's second and final infrastructure attempt; panel and publication remain false. |
| 2026-08-14 | Stop SOTA-v4 after the first Qwen/Alibaba strict-smoke attempt and re-lock paid execution. | One provider request returned HTTP 400 with no generation or authoritative per-call cost. The guard retained a `$0.1832184` call reservation, the cell ledger retained `$0.38953`, the checkpoint contains zero episodes and decisions, and two account reads showed `$0.00` run delta. The second reported model failure was the local fail-closed guard, not another provider call. No later model launched. | Preserve attempt 1 as infrastructure-only evidence. Add sanitized HTTP error diagnostics and aggregate-delta reconciliation evidence, refresh the OpenRouter scaffold and final preflight, then require a separate owner decision before using Qwen's final infrastructure attempt. Spend and smoke are false again; panel and publication remain false. |
| 2026-08-14 | Authorize only the eight serial SOTA-v4 strict smokes under a $10 operator ceiling. | The owner explicitly authorized the proposed smoke sequence. Fresh authenticated route/privacy evidence, Keychain-backed command construction, and live route-plus-price preflight passed for all eight routes with zero completion calls at contract fingerprint `247e12fe5a7d4f5b` and OpenRouter scaffold fingerprint `2462b25854c1298b`. The generated $6.67548672 protocol-maximum smoke estimate fits below the reduced ceiling. | Spend and strict-smoke flags are true only for the frozen eight-model smoke lane. The runner remains serial, canonical-host pinned, dynamically spend-guarded, and process-locked. Stop on the first failed cell; do not consume a second attempt without diagnosis and reconciliation. Panel execution and publication remain false and require a separate owner decision. |
| 2026-08-12 | Accept the fresh SOTA-v4 zero-completion route/privacy and final-preflight evidence. | Authenticated metadata covered all eight exact routes, the Keychain-backed dry run constructed all eight commands without exposing the carried private panel, and live route-plus-price preflight passed at contract fingerprint `247e12fe5a7d4f5b` and OpenRouter scaffold fingerprint `2462b25854c1298b`. Both evidence artifacts record zero completion calls. Luna and Solar live prices moved downward, so the frozen reservation remains conservative. | Route and final-preflight evidence are accepted. Spend, strict smoke, panel, and publication remain false; Qwen request compatibility and Mistral request-cap behavior remain strict-smoke questions. |
| 2026-08-12 | Open an initial fail-closed SOTA-v4 preregistration after the terminal v3 smoke phase. | Preserve an eight-model family and the exact unused 16-seed v3 commitment without reading its secret. Replace the terminal GLM model-behavior slot with `upstage/solar-pro4` under the documented external-selection rule; select the recovered first-party `minimax/fp8` route mechanically under the route policy; retain Qwen/Alibaba only as an unresolved candidate after two v3 HTTP 400 attempts. Public endpoint metadata was read without authentication or completion calls. | Every v4 route/privacy/final-evidence state is unresolved, the smoke manifest is empty, and only authenticated zero-completion route preflight is authorized. Spend, smoke, panel, and publication remain false. No v3 execution artifact carries forward. See [`sota-v4-preregistration-2026-08-12.md`](run_logs/sota-v4-preregistration-2026-08-12.md). |
| 2026-08-12 | Complete the frozen eight-route v3 strict-smoke phase without selective model reruns. | Luna, Claude Sonnet 5, Mistral Medium 3.5, DeepSeek V4 Flash, and HY3 passed every strict gate (20/20 decision windows total, zero failed decisions, zero illegal actions, zero fallback, complete route/cost telemetry). GLM completed with one malformed-action fallback and is ineligible because model behavior never authorizes a rerun. MiniMax returned HTTP 429 on both permitted attempts; Qwen returned HTTP 400 on both permitted attempts; both are infrastructure-excluded. Accepted raw artifacts report `$0.182942`; including GLM diagnostic telemetry, all completed artifacts report `$0.217734`. The dynamic guard conservatively reports `$0.66528688` after charging five unresolved call bounds as spent in an append-only five-record reconciliation chain. | The smoke manifest is `in-progress` with five accepted entries and remains `accepted_for_panel: false`. No retries remain for the three terminal cells. Panel execution, publication, and any v3 leaderboard claim remain locked pending an explicit, predeclared next-contract decision; no panel was run. |
| 2026-08-12 | Recover fail-closed from the first Luna smoke attempt and re-authorize its one remaining infrastructure attempt at OpenRouter scaffold fingerprint `2462b25854c1298b`. | One paid call reported `$0.001168`; a later response omitted authoritative inline cost, so the call guard retained its `$0.02203344` upper bound and stopped before any other model. The recovery polls OpenRouter's generation record for authoritative `total_cost`, persists sanitized telemetry failure context, and can clear an unknown-cost block only by charging its full conservative reservation as spent. The scripted scaffold diagnostic reproduced exactly and the final Keychain/route-price evidence is regenerated before retry. | The failed partial attempt is accounting-only and cannot enter the smoke manifest. Luna has one infrastructure attempt remaining; all other models remain untouched. The runner archives that empty stale checkpoint before reserving the retry, stays serial under the same $100 ceiling, and keeps panel/publication locked. |
| 2026-08-11 | Re-authorize only the eight serial SOTA-v3 smokes at final contract fingerprint `247e12fe5a7d4f5b` and OpenRouter scaffold fingerprint `d451b0e38cdee0fb`. | The final free gate reproduced the scaffold-view diagnostic exactly, regenerated authenticated exact-route/privacy evidence for all eight routes, constructed all eight Keychain-backed smoke commands without exposing private seeds, and executed authenticated route plus live-price preflight with zero completion calls. The digested record is `results/analysis/sota-v3-final-preflight-evidence.json`. Full Python 3.13 and 3.14 suites, Ruff, contract canaries, synthetic rehearsal, cost regeneration, web lint/build, dependency audit, and wheel build passed. | `spend_authorized` and `smoke_execution_authorized` are true under the $100 operator ceiling. The runner remains serial, canonical-host pinned, dynamically spend-guarded, and process-locked. Panel execution and publication remain false until every strict smoke is independently accepted. |
| 2026-08-04 | Adopt `qwen/qwen3.8-max` in place of `qwen/qwen3.7-plus`, and adopt a written [route substitution policy](ROUTE_SUBSTITUTION_POLICY.md). | Qwen 3.8 Max shipped 2026-08-03 and the benchmark is intended to track new releases rather than freeze once. Three substitutions in two days had each been decided ad hoc, which is how a benchmark quietly starts measuring whichever host is cheapest this week. | Cohort stays at ten, so the Holm family, the 16x1 allocation, and the power selection are untouched. The Max tier bills 6.25x/4.69x the Plus tier per token. The policy fixes eligibility, forbids price/throughput/first-party status as substitution criteria, and requires re-establishing route and privacy acceptance for any new counterparty. |
| 2026-08-04 | Substitute `deepseek/fp8` -> `cloudflare/fp8` and `minimax/fp8` -> `deepinfra/fp8`. | Both first-party routes were deranked the same day (status `-5` at 78% availability, and `-2`). Both replacements are the same model at the same FP8 quantization, chosen on highest 24h availability, at identical published rates. | No cost or cohort-size effect. The DeepSeek route recovered on its own within the day, so in hindsight that substitution was not strictly necessary; it is kept because Cloudflare holds the better 24h record. Route and privacy acceptance do **not** carry over — Cloudflare and DeepInfra are counterparties this project has never reviewed. |
| 2026-08-11 | Refresh the Cloudflare endpoint tag from `cloudflare/fp8` to `cloudflare` after the final authenticated zero-call check found the old tag absent. | The live route still reports the same Cloudflare provider, canonical endpoint name, healthy status, required parameters, 384k maximum completion tokens, and committed prompt/completion prices. This is an endpoint-tag refresh, not a provider or model substitution. | Cohort, Holm family, seed allocation, output cap, and cost are unchanged. Prior route acceptance is invalidated and must be regenerated before smoke. |
| 2026-08-04 | Pin undiscounted list rates instead of promotional rates, and enforce `operator_ceiling_usd` in the runner. | `openai/gpt-5.6-luna` and `z-ai/glm-5.2` were both pinned at 50%-off promos; the GLM discount moved 55.1% -> 50% within hours of being recorded. A reservation computed from a promo is wrong the moment it ends. Separately, `operator_ceiling_usd` had sat in config unread, so nothing enforced the committed cap. | Reservation $119.76 -> **$127.29**, which exceeded the then-committed $120.00 ceiling — the plan only ever appeared to fit because of the discounts. **Ceiling raised to $150.00 on 2026-08-04** to clear the reservation with headroom for a further substitution or list-price move. The reservation and the ceiling are now compared by `test_the_committed_plan_fits_under_the_committed_ceiling`, and the committed cost artifact is checked against the configs it claims to describe, so neither can drift silently again. Projected actual spend is ~$35-45 from July smoke telemetry, so the ceiling is a backstop rather than the expected bill. Logged in [`docs/run_logs/sota-v3-lineup-refresh-2026-08-04.md`](run_logs/sota-v3-lineup-refresh-2026-08-04.md). |
| 2026-07-13 | Treat v1 model rows as archived historical evidence, not a current ranking. | Scout-key mismatch affected models unevenly; failed queries were invisible. | Current claims require `sota-v2`; v1 remains auditable under `sota-v1`. |
| 2026-07-13 | Separate API and coding-harness lanes. | Archived rows mixed provider API behavior with uncontrolled CLI harness context and very different output usage. | API becomes the headline lane; CLI harnesses remain diagnostic. |
| 2026-07-13 | Withhold the v2 ranking pending an output-budget sweep. | Archived scores tracked output allowance strongly enough to confound model comparison. | Run the planned cap matrix and freeze a compute policy before the full panel. |
| 2026-07-13 | Keep strategic contract mechanics in v3. | Making contract length meaningful changes simulator behavior and reference scores. | Publish frozen v2 evidence before merging v3 behavior changes. |
| 2026-07-14 | Pre-register a three-model output-budget sweep and an 11-model headline panel. | The selected panel spans a small open model, mid-tier models, and frontier families while preserving exact OpenRouter upstream routing. | Do not substitute models or routes after results are visible; record any unavoidable provider withdrawal as an exclusion. |
| 2026-07-14 | Require eight publication-eligible headline rows before emitting a ranking. | A tiny or partially successful panel would invite selection bias and overstate coverage. | The generated public JSON contains no model ranking until the frozen compute lane and minimum panel both pass. |
| 2026-07-14 | Replace the provider-dependent uncapped sweep cell with a common 16,384-token ceiling. | Upstreams expose different maxima, so “uncapped” was neither compute-comparable nor financially bounded. No official sweep cell had run. | Every sweep cell now has a common explicit cap and the runner requires a spend ceiling. |
| 2026-07-14 | Standardize JSON mode on and reasoning off, and replace four incompatible headline routes before results. | Live route probes found mandatory reasoning on Grok, Gemini, and Kimi, and an incompatible data-retention policy on DeepSeek. Replacements were selected on route compatibility and panel coverage, not score. | All 11 registered routes can accept one common protocol; exact endpoint names remain pinned and checked before calls. |
| 2026-07-14 | Freeze the output-budget decision, rerun, exclusion, stopping, and budget rules in `config/publication_protocol.json`. | Post-result discretion would create researcher degrees of freedom and selection bias. | The analyzer emits the predeclared cap recommendation; valid poor behavior cannot be rerun away. |
| 2026-07-15 | Finalize the 11-model panel and make GPT-5.6 Luna the frontier sweep model. | No official sweep cell existed. The live preflight found the pinned SiliconFlow Qwen and DeepInfra Nemotron endpoints unavailable; healthy DeepInfra Qwen and Together Nemotron endpoints support the common lane. Luna replaced GPT-5.4 Mini in the sweep so the requested first full run contributes to the predeclared compute study instead of becoming a disposable diagnostic. | The headline model identities remain unchanged; two exact routes change, and the sweep now spans small open, capable low-cost, and frontier models. Re-smoke changed routes before their official cells. |
| 2026-07-15 | Reset publication evidence after the first Luna forensic audit. | All 890 Luna penalties were attributable, but 688 came from draft attempts encouraged by global prompt examples that appeared even when `draft` was absent from `available_actions`; the smoke had shown the same signal. | Preserve the prior artifact as diagnostic evidence, harden the shared scaffold, invalidate its old scaffold fingerprint, and restart every publication row symmetrically. |
| 2026-07-15 | Reopen model selection and express reasoning-off as `reasoning.enabled=false`. | The current OpenRouter catalog exposes non-mandatory reasoning for Kimi and DeepSeek but mandatory reasoning for Gemini 3.1 Pro and Grok 4.5. A boolean off switch is more portable than provider-specific `effort=none`. | The panel becomes a provisional 10-model, nine-lab set; Kimi, DeepSeek, and Nemotron Nano enter pending route smokes, while mandatory-reasoning Gemini and Grok remain explicit exclusions. |
| 2026-07-15 | Pause the four-cap output sweep for policy review. | Luna averaged only 154 output tokens per decision at a 1,024-token ceiling with reasoning disabled, so the existing 12-cell matrix may spend more to study a mostly non-binding response limit rather than strategic compute. | The runner blocks paid sweep cells until the project chooses between a cap experiment and one generous safety ceiling with token-efficiency reporting. |
| 2026-07-15 | Retire the four-cap sweep and freeze a 1,024-token safety ceiling. | In 601 superseded Luna API calls, output-token usage was p50 121, p95 210, p99 264, max 299, with zero calls at 1,024 and zero reasoning tokens. The cap was operationally non-binding even though the old score remains invalid under the new scaffold. | Smoke all ten registered models at 1,024. If any call reaches 768 tokens or shows cap-induced truncation, raise the entire lane to 2,048 before any full-panel result. Report actual token efficiency as a secondary metric. |
| 2026-07-15 | Machine-enforce the pre-panel smoke gate and unique-row counting. | Review found the panel and ranking were unlockable by editing status strings and by row aliasing: `selection_status` "frozen" was accepted as smoke completion, and duplicate aliases for one model could satisfy the eight-row floor. | Panel and `publishable_ranking` now require recorded, accepted smoke-manifest entries per registered model, count by unique registered model identity, and can never require fewer rows than the protocol's pre-registered minimum floor. |
| 2026-07-15 | Re-fingerprint the v2 contract and OpenRouter scaffold before any accepted evidence. | `failed_queries` narrowed to unresolved lookups plus ambiguous-scout rejection changed the contract (`a65a4359ca3c6e64` → `558e8f35ea1d66b9`), and per-call `finish_reason`/`native_finish_reason` recording made cap-induced truncation auditable (scaffold `317371cf66b436fe` → `d7321ad9d0a739b4`). No accepted smoke or eligible row existed, so nothing was invalidated. | All ten route smokes must run under the new fingerprints, and the statistical analysis plan is frozen pre-data in `config/publication_protocol.json`. |
| 2026-07-16 | Amend the headline contrast to paired lift versus pick-trader. | The full baseline-panel mean includes random and other weak references, so clearing it would not show that a model-plus-scaffold system beats the transparent competent heuristic bar. No accepted `sota-v2` smoke manifest, eligible panel row, or observed full-panel score existed when this was amended. | Pick-trader is the Holm-adjusted primary contrast; full-panel lift remains a secondary descriptive endpoint, and publication still uses tiers rather than ordinal ranks. |
| 2026-07-16 | Replace the stale ten-model panel with the user-curated twelve-model frontier panel. | No full-panel score existed. Live OpenRouter catalog and endpoint checks confirmed all requested models, but Gemini 3.5 Flash, Grok 4.5, Muse Spark 1.1, and newly released Kimi K3 require reasoning. | Reset the smoke manifest; pin provider slugs plus endpoint tags; use native-minimum reasoning and a provisional common 4,096-token cap; require all twelve fresh smokes before freezing. |
| 2026-07-17 | Add Tencent HY3 on OpenRouter's free Novita route before smoke execution. | The live catalog exposed `tencent/hy3:free` at zero input and output cost with one exact healthy Novita endpoint, optional reasoning, and a July 21 catalog expiration. The route advertises structured outputs but not the `response_format` parameter used by the other routes. No revised-panel smoke or full-panel score existed. | Expand the provisional registry and multiplicity family to thirteen, keep reasoning and JSON response mode disabled for HY3, rely on the same explicit JSON-only prompt plus clean-smoke gate, and retain the pinned dated free endpoint rather than silently falling back after it expires. |
| 2026-07-17 | Park Kimi K3 for the under-$100 phase-one panel after its first clean-gate smoke. | At mandatory `max` reasoning, two of four calls hit the 4,096-token ceiling and were truncated; the episode had two failed decisions, 13,275 reasoning tokens, 100.264 seconds per decision, and $0.301296 cost. Raising the common lane to 8,192 would invalidate the six clean 4,096-token smokes and push the conservative one-repeat plan beyond the phase-one budget. | Preserve the raw Kimi artifact as diagnostic evidence, prohibit a phase-one rerun, return the registry and Holm family to twelve models, and continue the untouched routes at 4,096. |
| 2026-07-17 | Switch Nemotron 3 Ultra from paid Together to the exact free Nvidia route before its first smoke. | OpenRouter's live catalog exposed `nvidia/nemotron-3-ultra-550b-a55b:free` at zero input/output cost on one healthy first-party Nvidia endpoint with no listed expiration. It supports optional reasoning but does not advertise `response_format`. | Pin the dated Nvidia free endpoint with fallbacks and reasoning disabled, use prompt-only JSON plus the clean-smoke gate, and regenerate the cost plan before continuing. |
| 2026-07-17 | Park the listed-free Nemotron 3 Ultra route after bounded infrastructure failure. | The exact Nvidia endpoint passed live catalog and authentication preflight, then both permitted real chat-completion attempts returned `HTTP 404 Not Found`. Fail-fast stopped before a complete episode and OpenRouter reported no incremental spend. | Preserve the checkpoint as infrastructure evidence, do not retry or silently substitute the paid Together route, reduce the phase-one registry and Holm family to eleven, and continue the untouched models. |
| 2026-07-17 | Park DeepSeek V4 Pro after the same bounded infrastructure failure. | The exact first-party DeepSeek route passed live catalog and authentication preflight, then both permitted real chat-completion attempts returned `HTTP 404 Not Found`. Fail-fast stopped before a complete episode and OpenRouter reported no incremental spend. | Preserve the checkpoint, do not retry or substitute a different route, reduce the phase-one registry and Holm family to ten, and continue Mistral and HY3. |
| 2026-07-17 | Freeze the ten-model phase-one registry and 4,096-token lane after the accepted smoke gate. | All ten registered models completed four decisions with zero failed decisions and zero truncations. Peak per-call output was 1,432 tokens, below the 3,072 cap-pressure trigger. Accepted-route artifact spend was $0.427613; total campaign spend was $0.728909 including the excluded Kimi diagnostic. | Record all ten manifest entries, freeze the registry and native-reasoning cap, retain excluded-model diagnostics, regenerate the cost plan, and unlock panel dry-runs without starting paid panel cells. |
| 2026-07-18 | Settle successful serial-cell reservations against measured spend. | The runner retained every historical worst-case reservation, so a healthy panel could stop against cumulative hypothetical spend even after completed artifacts and the OpenRouter account established a much lower real cost. | Mark successful-cell reservations settled after post-cell spend measurement, keep failed/interrupted reservations active, and evaluate each next cell against measured spend plus only unresolved liabilities. |
| 2026-07-18 | Amend GLM 5.2 from the unhealthy first-party Z.AI FP8 endpoint to Novita FP8. | The frozen `z-ai/fp8` endpoint remained at OpenRouter status `-2` across repeated launch preflights, while the exact dated Novita FP8 endpoint was healthy and advertised the common lane parameters. No full-panel GLM result existed. | Pin `novita/fp8`, replace rather than reuse the Z.AI smoke entry, refresh route pricing/runtime evidence, and require a clean exact-route smoke before restoring panel unlock. The replacement smoke completed 4/4 decisions with zero failures or truncations for $0.009225. |
| 2026-07-19 | Publish eight eligible phase-one rows without an ordinal winner claim. | Eight of ten registered cells passed exact-route and complete-cost gates. Grok recorded usage for 476/480 decisions and cost for 474/480; Mistral recorded cost for 479/480 after one fallback. All eight eligible seed-paired intervals form one connected tier, and every Holm-adjusted primary contrast is 0.078125. | Publish the eight eligible rows as one uncertainty tier, retain Grok and Mistral as diagnostics, do not rerun completed cells, and attach exact raw evidence plus checksums to the tagged release. |
| 2026-07-18 | Reconcile the frozen publication protocol and reserve repair-call contingency before launch. | Independent Fable 5 review found that the runner and lane correctly enforced 4,096/3,072/8,192 native-minimum reasoning, but `publication_protocol.json` still described the retired 1,024/768/2,048 policy. It also noted that the prior reservation covered only primary calls even though one bounded repair is configured. No full-panel result existed. | Record the current lane as an explicit pre-data protocol amendment. Reserve one full-price call for every configured repair attempt and apply the committed 1.2x cost contingency before admitting each serial cell. Use a sub-$100 operator ceiling and monitor measured spend after every cell. |
| 2026-07-24 | Make strict failure handling the resolved-and-recorded publication default, and persist per-episode `score_components`, in `sota-v3` only. | Under the soft fallback a decision the model never produced still moved roster state, and the effective policy came from the operator's shell and was never written into an artifact. Separately, no released row could be reweighted post hoc because components were discarded after scoring. Both are measurement conditions, so they belong in the contract rather than in run habits. | `SOTA_V3_POLICY` requires `run_info.strict_fallback` plus a matching `provider_options.GM_AGENT_STRICT`, and a complete finite `score_components` block per episode whose contributions rebuild `strategy_score`. Frozen v1/v2 policies keep the default off and validate unchanged. The contract fingerprint moved; no v3 artifact or smoke manifest existed, so nothing was invalidated. |
| 2026-07-24 | Register the `scaffold-view` diagnostic without running it and without adding it to the official baseline panel. | The scripted references read the untruncated observation while model adapters read a sorted, truncated payload, so the published model-versus-`pick-trader` gap mixes policy quality with observation asymmetry. Measuring that needs one shared compaction implementation, not a second copy that can drift. | `gm_bench/scaffold_view.py` is imported by both `examples/gm_agent_common.py` and the new baseline, and is a contract-fingerprint source. The agent is registered but has not been run on any panel; no scaffold-gap number exists or may be quoted. Adding it to the official panel would break the exact-order baseline match on every existing artifact, so it stays opt-in. |
| 2026-07-25 | Run `scaffold-view` on the official 8-seed panel under fingerprint `4f6ddddd6a6dd81c`. | Issue #93 P0: bound observation asymmetry before any paid panel on the contract-economics lane. Re-measured after PR #92 polish (`0a5f0434dca31ac5` → `4f6ddddd6a6dd81c`); panel scores unchanged. | Scripted compare on seeds 11–18 × 5 seasons: `scaffold-view` mean 270.675, `pick-trader` mean 267.875, paired gap +2.8 (six seeds tied; seeds 17–18 diverge). Logged in `docs/run_logs/scaffold-view-official-panel-2026-07-25.md`. Diagnostic only — does not re-rank models or alter leaderboard JSON. |
| 2026-07-24 | Preserve the released `sota-v2` study and open `sota-v3` for the Issue #84 P0 fixes. | Non-finite input rejection and decision-window walk-away persistence change simulator/action semantics; compact-artifact recomputation strengthens the validator. Quietly changing the v2 fingerprint or re-recording old smokes would make the released contract mutable after results were known. | Pin the historical v2 contract and validator, identify current corrected runs as v3, block paid publication execution until a v3 registry and lane are pre-registered, retain the tagged v2 evidence and its narrow claim, and require no paid reruns for this repair. |
| 2026-07-25 | Treat `sota-v3` as contract-ready and panel-blocked per consultant audit #93. | Independent review graded reproducibility A− but model discrimination D; one overlapping v2 tier; PR #92 contract economics still unmerged; scaffold-view unrun; site surfaces overclaim. | Merge #92, run scaffold-view at the frozen fingerprint, fix v2-site claim gaps, pre-register the v3 lane, and defer paid v3 panel spend until those gates pass. Do not publish ordinal model or baseline rankings. |
| 2026-07-27 | Freeze v3 mechanics and reduce the pre-spend path to preregistration plus offline rehearsal. | PRs #92, #95, #98, #99, and #101 closed the mechanics, site-framing, same-view, version-dispatch, and claim-decomposition blockers. Continuing to add plausible realism changes now creates more schedule and evidence risk than it removes. The base SHA had no v3 lane/registry/manifest or v3 artifact; the working tree now has provisional fail-closed config files but still no selected model family or real/committed artifact. | Freeze score-affecting mechanics at `4f6ddddd6a6dd81c`; permit only one bounded, pre-data publication-parameter amendment if panel design requires it; preserve v2 literally; complete preregistration and a clean-checkout no-provider-call rehearsal; authorize no paid smoke or panel by this decision. |
| 2026-07-30 | Reconcile the v3 pre-spend design across configs, policy, cost planning, seed commitment, and rehearsal. | The exact registered power procedure supports 15 independent seeds x 1 stochastic trajectory per model: base power 0.9461 and sensitivity power 0.8357 with Wilson lower bound 0.8283. One repeat is the registered estimand, not a dropped replicate. The prior configs disagreed on repeats and treated a live-readiness mismatch as non-fatal. No private seed was generated and no provider was called during reconciliation. | Bind the current lane to fingerprint `a523bdfcebe47bbd`, freeze the 15 x 1 statistical design, use a provisional 4,096/3,072/8,192 cap rule with whole-cohort invalidation and re-smoke on pressure, provide an unbiased private-seed generator, and make preregistration coherence a hard rehearsal gate. Keep every route, spend, execution, and publication authorization false. |
| 2026-08-03 | Move the ten-model registry from `provisional-blocked` to `route-preflight-ready` while `evidence_state` is still pre-data. | Everything registered about the ten routes comes from the public OpenRouter catalog, which by the registry's own admission "does not prove authenticated exact-route access or provider privacy and retention behavior." The v2 lane already lost Nemotron 3 Ultra and DeepSeek V4 Pro to bounded HTTP 404s on routes that looked healthy publicly, so a failed authenticated probe is a live possibility, not a hypothetical. Route preflight is the cheapest test of that assumption: it makes zero completion calls and cannot launch a model subprocess, reserve spend, or create run state. Discovering a dead route now costs a JSON regeneration; discovering it after the seed panel is committed means a committed panel attached to a design that then changed, because cohort size drives the Holm family size, which drives the allocation and the reservation. | Registry `selection_status` becomes `route-preflight-ready`; `selection_frozen_at_utc` stays `null`. This is strictly weaker than `frozen` and unlocks nothing that costs money: measured against the live configs, route-preflight readiness goes from two blockers to one — the owner's separate `route_preflight_authorized` grant — while the smoke and panel phases stay at an identical 60 blockers, still including "provider execution is locked until the model registry is frozen." Asserted by `test_route_preflight_readiness_unlocks_nothing_that_costs_money`. Cohort identity is **not** frozen by this decision; freezing it remains a separate later decision informed by preflight results. Every lane authorization remains false. |
| 2026-08-03 | Grant `route_preflight_authorized`, run the authenticated zero-call route preflight, and correct the stale `qwen/qwen3.7-plus` endpoint tag. | The registered route metadata came from the public catalog, which cannot prove authenticated access. The probe makes zero completion calls, cannot launch a model subprocess, and cannot write run state — verified empirically, since the aborted first run left no files behind. It found exactly one defect in ten: the Alibaba endpoint tag for `qwen/qwen3.7-plus` had moved from `alibaba` to `alibaba/fp8`, while `provider_name`, `name`, status, and every published price stayed identical. | All ten routes now pass at $0.00 spend. `endpoint_tag` and `upstream_provider_slug` corrected in the registry, and the bound `provider_slug` in the pricing snapshot; the cost artifact regenerates byte-identically, so the reservation holds at $89.845094 / $107.814113. **The cohort stays at ten and the 16x1 allocation is unaffected** — a dead route would have forced a family-of-nine amendment and a power re-selection. `exact_route_acceptance` remains `unresolved`; smoke is still blocked by 60 issues, the same count as before the probe. `spend_authorized`, `smoke_execution_authorized`, `panel_execution_authorized`, and `publication_authorized` all remain false. Logged in [`docs/run_logs/sota-v3-route-preflight-2026-08-03.md`](run_logs/sota-v3-route-preflight-2026-08-03.md). |
| 2026-08-04 | Freeze the SOTA-v3 lane and authorize only the strict-smoke phase. | PR #110 is merged; the refreshed exact routes pass authenticated metadata checks. The private 16-seed panel was owner-authorized and generated before any v3 model result. OpenRouter's current policy distinguishes data-collection denial from ZDR: all routes run with `data_collection=deny`, while 5/10 exact routes are listed as ZDR. Grok and Mistral advertise `max_tokens` but omit a numeric `max_completion_tokens`, and no same-model alternative fixes that metadata gap. | Commit only the salted hiding commitment and ordered seed hash; escrow secret values in macOS Keychain. Accept retention for synthetic non-confidential benchmark inputs, prohibit provider training use, and record ZDR per route rather than claiming it universally. Permit the two null-cap routes only as `request-cap-pending-strict-smoke`; complete smoke telemetry remains mandatory before panel authorization. Set the lane, registry, protocol, and pricing to frozen; authorize spend and strict smokes under the $150 ceiling; leave panel and publication authorization false. Logged in [`docs/run_logs/sota-v3-smoke-readiness-freeze-2026-08-04.md`](run_logs/sota-v3-smoke-readiness-freeze-2026-08-04.md). |
| 2026-08-09 | Amendment 4: make cap pressure terminal on its first trigger and bind duplicated v3 planning facts in the rehearsal. | The prior one-amendment policy existed only in JSON, tests, and prose; the runner did not persist or enforce amendment count. The configs had also drifted between eight and ten routes, disabled and pending reasoning, and two forecast amounts. No v3 smoke or panel result exists. | Permit zero in-place cap amendments. Any truncation or 3,072-token trigger invalidates all smokes, aborts this contract, and requires a new preregistration. Make the generated forecast authoritative, enforce the operator ceiling before every provider call, and have the zero-spend rehearsal cross-check the model count, Holm family, required smokes, routes, reasoning mode, allocation, cap action, and cost facts. |

## Experiment and release log

Use this section for concise operational status. Link to durable artifacts rather
than pasting large outputs.

| Date | Item | Status | Artifact / PR | Notes |
| --- | --- | --- | --- | --- |
| 2026-07-14 | `sota-v2` contract transition | Merged | [#58](https://github.com/nedcut/gm-bench/pull/58) | Corrected scout behavior, surfaced failed queries, archived v1 evidence. |
| 2026-07-14 | Model-run recovery hardening | Merged | [#59](https://github.com/nedcut/gm-bench/pull/59) | Serial safety, fail-fast, locking, checkpoint validation, atomic merge. |
| 2026-07-14 | Publication pipeline | Merged | [#61](https://github.com/nedcut/gm-bench/pull/61) | Independent review complete; all findings addressed or dispositioned. Paid sweep and model panel remain. |
| 2026-07-13 | Strategic contract mechanics | Deferred v3 draft | [#62](https://github.com/nedcut/gm-bench/pull/62) | Keep separate until v2 publication is complete. |
| 2026-07-14 | Initial OpenRouter smoke | Superseded diagnostic | Qwen 1,024/4,096; GPT-5.4 mini 4,096 | Provider-default reasoning made Qwen consume its output allowance without usable content. This exposed the need to standardize reasoning and JSON settings; these scores are not benchmark evidence. |
| 2026-07-14 | Standardized sweep smoke | Partly superseded | Qwen 3.5 9B, GPT-5.4 mini, MiniMax M3 at 1,024 | The Qwen smoke used the now-unavailable SiliconFlow route and GPT-5.4 Mini left the sweep before official results. MiniMax remains current. Refresh Luna and DeepInfra Qwen before their first official cells. Do not treat smoke scores as benchmark evidence. |
| 2026-07-14 | Full-panel route compatibility | Superseded | `config/sota_v2_models.json` | Applied to the previous 11-model registry. The revised 10-model registry is provisional pending changed-route smokes. |
| 2026-07-15 | GPT-5.6 Luna standardized smoke | Superseded diagnostic | raw SHA-256 `e8f83c6516cb3cc8105b173c826c1b5d91314a487b729f9b06b8fc6beda2bc8f` | Exact OpenAI route and complete telemetry remain useful, but all four illegal actions were preseason draft attempts primed by the old global action catalog. |
| 2026-07-15 | GPT-5.6 Luna 1,024-token sweep cell | Superseded diagnostic | canonical SHA-256 `b681bdc56f3d176d194c9c1e20cc688be4ef4b58f7669862fb2268af99a0e37a`; byte SHA-256 `74d342c5d4c799524dadd6f668350eede67b8b74e5522833723e25ab4f50480b` | The run remains operationally valid and auditable, but its scaffold fingerprint is intentionally invalidated. It cannot count toward the restarted sweep or headline panel. |
| 2026-07-15 | Sweep cost/runtime plan | Superseded by fixed-cap policy | `results/analysis/output-budget-cost-estimate.json` | The prior figures describe the retired 12-cell matrix. Replace with a full-panel estimate after all ten route smokes. |
| 2026-07-16 | First fixed-1,024 smoke series | Superseded by deliberate panel revision | `docs/run_logs/sota-v2-smokes-2026-07-16.md` | Six routes were accepted, two completed with protocol failures, Nemotron Nano exhausted infrastructure retries, and Claude direct remained unhealthy. The evidence remains auditable but cannot unlock the revised 4,096-token native-reasoning panel. |
| 2026-07-15 | Statistical analysis plan | Frozen | `config/publication_protocol.json` | Pre-registered pre-data: unit of inference, primary paired contrast, Holm-Bonferroni multiplicity, descriptive inference labels, tiered ranking, power disclosure, temperature policy, and registry exclusion criteria. |
| 2026-07-18 | Final Fable 5 launch audit | Conditions resolved pre-data | `docs/run_logs/sota-v2-final-launch-audit-2026-07-18.md` | No P0 blocker. Reconciled the stale output-policy text, strengthened reservations for repairs plus contingency, selected a $95 operator ceiling, and retained Tencent timing and per-cell spend monitoring as launch conditions. |
| 2026-07-24 | P0 integrity hardening and v3 boundary | Merged | [#85](https://github.com/nedcut/gm-bench/pull/85) | Fixes non-finite actions, negotiation-window resets, and compact-artifact integrity without mutating the frozen v2 release contract. Merged as `1e5cd44`. |
| 2026-07-24 | #84 P1: score decomposition, strict publication fallback, same-view reference | Merged | [#88](https://github.com/nedcut/gm-bench/pull/88) | Persists `score_components` on every episode row, makes strict failure handling the resolved-and-recorded publication default, and registers the `scaffold-view` diagnostic. All three are `sota-v3`-only; no v2 artifact is touched. The scaffold-view diagnostic panel ran 2026-07-25 (see run log); no paid v3 model panel has run. |
| 2026-07-25 | scaffold-view official panel measurement | Complete | [`docs/run_logs/scaffold-view-official-panel-2026-07-25.md`](run_logs/scaffold-view-official-panel-2026-07-25.md) / [#98](https://github.com/nedcut/gm-bench/pull/98) | Deterministic compare vs `pick-trader` on seeds 11–18 × 5 seasons under fingerprint `4f6ddddd6a6dd81c` (re-measured after PR #92 polish; scores unchanged). Paired mean gap +2.8 (six seeds tied; only seeds 17–18 diverge). Revalidated 2026-08-03 under the `sota-v3` candidate fingerprint `a523bdfcebe47bbd`; every per-seed score and the paired *t* reproduce exactly. Diagnostic only. |
| 2026-07-26 | Gap decomposition and panel power | Complete | [`docs/run_logs/gap-decomposition-and-panel-power-2026-07-26.md`](run_logs/gap-decomposition-and-panel-power-2026-07-26.md) | Protocol friction bounds at 0.5–9.0% of the model-vs-`pick-trader` gap; fresh-spawn/memo-only continuity costs the scripted references exactly zero (now enforced by `tests/test_reference_statelessness.py`); memo-write volume is not meaningfully associated with score (not a causal ablation). Variance decomposition: within-seed noise sd 53.4 vs seed difficulty sd 13.45, model×seed interaction indistinguishable from zero. For the published eight-model family, the Holm illustration (matching `model_tiers.py`) needs ~96 episodes/model for 0.95 power at Δ=40, not 48; rerun after the v3 family is selected. No contract source touched; no spend authorised. |
| 2026-07-27 | v3 readiness reconciliation and mechanics freeze | Ready for review | [`docs/run_logs/sota-v3-preflight-2026-07-27.md`](run_logs/sota-v3-preflight-2026-07-27.md) | Confirms PR #99 CI dispatch is present; records the provisional, fail-closed v3 config/runner package and passing zero-spend rehearsal; keeps v2 as the public evidence lane; freezes mechanics; and authorizes no paid spend. A post-commit clean-checkout rerun remains required. |
| 2026-07-24 | Results-first public site | Merged | [#87](https://github.com/nedcut/gm-bench/pull/87) | Reframes the public result around one unresolved model tier, the scripted-reference gap, compute, and auditability. |

## Living-document maintenance checklist

Update this file when any of the following happens:

- [ ] A relevant PR merges, closes, rebases, or changes scope.
- [ ] The frozen contract, scaffold, provider route, or publication lane changes.
- [ ] A registered-model smoke or model-panel cell completes or fails.
- [ ] A result becomes eligible, diagnostic, withdrawn, or superseded.
- [ ] Cost, runtime, quota, or provider limitations change the execution plan.
- [ ] An external reviewer or reproducer finds a problem.
- [ ] A publication claim becomes stronger, weaker, or differently scoped.
- [ ] A checklist item is completed—mark it and link its evidence.
- [ ] A new blocker appears—add it to the relevant phase and critical path.
- [ ] A release is published—record its tag, commit, contract fingerprint,
  artifact manifest, and final claim.

During active experiment periods, review this document at the beginning and end
of each work session. Before release, read it once as an engineer, once as a
skeptical benchmark reviewer, and once as a portfolio visitor seeing GM-Bench
for the first time.
