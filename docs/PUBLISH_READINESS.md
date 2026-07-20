# GM-Bench Publication Readiness

> **This is a living document.** It is the working source of truth for taking
> GM-Bench from a strong benchmark codebase to a credible public release. Update
> it whenever an experiment changes the evidence, a publication decision is
> frozen, a blocker appears, or a checklist item is completed. The goal is not
> to preserve this first draft; the goal is to make it more accurate as the
> project develops.

**Last reviewed:** 2026-07-19
**Current target:** Publish a validated `sota-v2` leaderboard, accompanying blog
post, GitHub release, and public site.  
**Current state:** The frozen phase-one public panel is complete. Eight of ten
registered models produced route-matched, cost-complete `sota-v2` rows at the
shared 4,096-token native-minimum-reasoning cap, clearing the predeclared
minimum. Grok 4.5 and Mistral Medium 3.5 completed but remain diagnostic because
their artifacts lacked complete usage or cost coverage. The generated site now
exposes the eight eligible rows. All models overlap in one uncertainty tier,
and every eligible model trails `pick-trader`; the remaining release work is
claim review, raw public-trace packaging, presentation polish, and independent
reproduction rather than more phase-one model runs.
**Current weekly focus:** [#63 — Publication sprint: freeze and ship GM-Bench
`sota-v2`](https://github.com/nedcut/gm-bench/issues/63)  
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
baseline. A public release still needs raw trace assets, claim review,
presentation polish, and independent reproduction.

The strongest story is not merely that GM-Bench runs LLMs through a simulator.
It is that the project:

- built a deterministic, multi-season decision environment;
- created transparent baselines, adversarial canaries, and an oracle reference;
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
| Benchmark validity | Strong but scoped | Scripted references, exploit canaries, oracle headroom, calibration, and mechanic coverage exist. |
| Compute comparability | Frozen for phase one | The API lane has a common 4,096-token total-output ceiling, native-minimum reasoning, exact provider slugs and endpoint tags, a pre-full-panel 75% cap-pressure rule, and actual reasoning/token-efficiency reporting. All ten phase-one routes passed and were accepted; Kimi K3 and the unavailable Nemotron and DeepSeek routes are retained as exclusion evidence. |
| Current model evidence | Public panel complete | Eight registered, route-matched, cost-complete `sota-v2` rows clear the publication floor; Grok and Mistral are retained as diagnostics. |
| Statistical evidence | Ready but low-resolution | Seed-paired intervals, exact sign-flip tests, full-family Holm adjustment, and overlap tiers are generated. All eight rows share one tier and trail `pick-trader`. |
| External validation | Missing | No independent reproduction or third-party result has been recorded. |
| GitHub presentation | Needs polish | Repository metadata, release packaging, README framing, and final site still need work. |
| Blog | Scaffolded | The validated results now exist; the narrative still needs its final evidence-backed update. |

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
  under plausible perturbations.
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
- [ ] Create a tagged GitHub release for the frozen v2 study.
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
- The oracle is a diagnostic ceiling with privileged information, not a fair
  participant.
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

## Decision log

Add entries rather than rewriting history. If a decision changes, record the new
decision and why.

| Date | Decision | Evidence / rationale | Effect |
| --- | --- | --- | --- |
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
