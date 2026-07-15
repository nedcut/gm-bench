# GM-Bench Publication Readiness

> **This is a living document.** It is the working source of truth for taking
> GM-Bench from a strong benchmark codebase to a credible public release. Update
> it whenever an experiment changes the evidence, a publication decision is
> frozen, a blocker appears, or a checklist item is completed. The goal is not
> to preserve this first draft; the goal is to make it more accurate as the
> project develops.

**Last reviewed:** 2026-07-14
**Current target:** Publish a validated `sota-v2` leaderboard, accompanying blog
post, GitHub release, and public site.  
**Current state:** Publication runner and gates are merged to `main`; the
definitive `sota-v2` experiment has not yet started.
**Current weekly focus:** [#63 — Publication sprint: freeze and ship GM-Bench
`sota-v2`](https://github.com/nedcut/gm-bench/issues/63)  
**Broader roadmap:** [#60 — Roadmap to a publishable leaderboard + blog
post](https://github.com/nedcut/gm-bench/issues/60)

## Executive assessment

GM-Bench is viable as a focused benchmark for comparing models and agent
scaffolds on synthetic, long-horizon resource allocation in a frozen sports
management environment. It is already strong enough to be a flagship AI/ML
portfolio project. It is not yet ready for a headline model-ranking claim
because the current `sota-v2` leaderboard has no eligible model rows and the
output-budget confound has not been resolved.

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
remaining work is to finish one frozen experiment and present it clearly.

## What “publish-ready” means

Publication readiness has four independent gates. Passing tests alone is not
enough.

1. **Benchmark gate:** the simulator, scoring, schemas, baselines, seed panel,
   and validation policy are frozen and machine-checkable.
2. **Evidence gate:** the output-budget study and model panel are complete,
   comparable, statistically reported, and validated.
3. **Claim gate:** every public statement is supported by the evidence and stays
   within the benchmark's actual scope.
4. **Presentation gate:** a new reader can understand, run, audit, and cite the
   project without reconstructing its history from pull requests.

The project is publish-ready only when all four gates pass.

## Current readiness snapshot

| Area | Status | Assessment |
| --- | --- | --- |
| Core engineering | Strong | Deterministic simulator, adapters, CLI, GUI, site, tests, and CI are substantial. |
| Reproducibility | Strong | Contract fingerprints, seed provenance, compact artifacts, and validators are in place or staged. |
| Benchmark validity | Strong but scoped | Scripted references, exploit canaries, oracle headroom, calibration, and mechanic coverage exist. |
| Compute comparability | Ready to measure | Three sweep models, four bounded cap cells, exact routes, fixed protocol, and a deterministic decision rule are pre-registered; all three standardized smokes passed, but no official sweep cells are complete. |
| Current model evidence | Blocked | The active `sota-v2` leaderboard has no eligible model rows. |
| Statistical evidence | Partially ready | Paired analysis and power tooling exist; final model results do not. |
| External validation | Missing | No independent reproduction or third-party result has been recorded. |
| GitHub presentation | Needs polish | Repository metadata, release packaging, README framing, and final site still need work. |
| Blog | Scaffolded | The honest narrative exists, but results must be generated from validated data. |

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

### Phase 1 — finish the output-budget study

This phase decides whether a single-number ranking is scientifically coherent.
It must happen before the larger model panel.

- [x] Land or finalize the infrastructure in [#61 — publishable leaderboard
  pipeline](https://github.com/nedcut/gm-bench/pull/61).
- [x] Obtain an independent review of #61 after it leaves draft; resolve or
  explicitly disposition every substantive finding before expensive runs begin.
- [x] Select three API models before seeing sweep results.
- [x] Record exact provider/model IDs in `config/output_budget_sweep.json`.
- [x] Choose models that span expected capability rather than only frontier
  models likely to behave similarly.
- [x] Freeze provider routing, reasoning-effort settings, temperature, scaffold,
  observation profile, repair policy, and fresh-spawn condition.
- [x] Predeclare the primary endpoint and deterministic saturation decision rule.
- [x] Freeze the permitted retry conditions, exclusion rules, and stopping rule
  in `config/publication_protocol.json` before seeing sweep outcomes.
- [x] Distinguish infrastructure/provider failures that permit a resumed run from
  poor model behavior that must remain part of the measured result.
- [x] Estimate and record expected cost, runtime, serial concurrency, and quota
  in `results/analysis/output-budget-cost-estimate.json`: $33.25 planning,
  $39.90 with cost contingency, $98.28 token-ceiling reservation ($117.94 with
  contingency), 8.60 provisional serial API-hours, and 12.90 hours with
  runtime contingency. Refresh the runtime portion after current-route smokes.
- [ ] Refresh the standardized 1,024-token serial smoke for the changed
  DeepInfra Qwen route before its first official cell. Luna and MiniMax are
  current; the previous Qwen smoke used the now-unavailable SiliconFlow route.
  Keep live metadata preflight for the full cap matrix.
- [ ] Run the complete 256 / 1,024 / 4,096 / 16,384 matrix with three repeats
  on the official panel.
- [x] Remove the provider-dependent uncapped cell before official runs; use the
  same bounded 16,384-token high cell for all selected models.
- [ ] Preserve raw artifacts and logs outside git; do not discard failed cells.
- [ ] Analyze completed cells with `scripts/analyze_output_budget.py`.
- [x] Confirm in automated tests that the analyzer rejects missing, duplicate,
  mixed-provenance, wrong-route, wrong-lane, wrong-repeat,
  incomplete-telemetry, and invalid-contract cells.
- [ ] Inspect score versus actual output tokens, not just configured caps.
- [ ] Inspect protocol failure and repair rates at each cap.
- [ ] Record the interpretation in this document before running the full panel.

Then freeze exactly one publication policy:

- [ ] **Saturation outcome:** freeze the lowest defensible cap at which further
  compute produces no material score improvement; or
- [ ] **Compute-elastic outcome:** freeze a common budget for the headline table
  and publish score-versus-budget curves as the primary result.

- [ ] Update `config/sota_v2_lane.json` from `pending-sweep` to the frozen policy.
- [ ] Record the rationale, decision date, evidence artifact hash, and known
  limitations in the decision log below.
- [ ] Regenerate the site and confirm it still refuses to publish a ranking if
  any publication prerequisite is missing.

**Exit condition:** the official API lane has a documented and frozen compute
policy supported by completed sweep evidence.

#### Safe execution workflow

All model calls are serial. Inspect the exact commands and non-secret provider
options first:

```bash
python3 scripts/run_publication_matrix.py sweep --dry-run
```

Source credentials locally, then run authentication preflight without a model
request:

```bash
python3 scripts/run_publication_matrix.py sweep --preflight-only
```

Run the cheapest pre-registered smoke first. Before a cell launches, the spend
guard reserves its output-ceiling cost from the committed price snapshot; it
also uses the larger of completed-artifact telemetry and the OpenRouter account
delta. Reservations survive failed cells. Price drift or input growth can still
make actual cost exceed an estimate, so keep smoke caps small and inspect account
usage after every cell:

```bash
python3 scripts/run_publication_matrix.py smoke \
  --model-id openrouter-qwen3.5-9b-deepinfra \
  --cap 256 \
  --run-dir data/publication-runs/smoke-2026-07-14 \
  --max-spend-usd 5
```

Only after every standardized smoke and the recorded cost estimate are
acceptable, run the
pre-registered sweep into a new run directory. The driver creates atomic raw
artifacts and per-cell checkpoints, uses validated resume when a checkpoint
already exists, and refuses to fan out workers:

```bash
python3 scripts/run_publication_matrix.py sweep \
  --run-dir data/publication-runs/output-budget-v2 \
  --max-spend-usd <approved-sweep-budget>
```

Do not run `panel` until `config/sota_v2_lane.json` records a positive frozen
cap and a frozen policy status. The driver enforces that lock.

### Phase 2 — run the publishable model panel

- [x] Pre-register 11 exact provider/model/route identities in
  `config/sota_v2_models.json` before full results are visible.
- [x] Pre-register the full-panel rerun and exclusion policy. A disappointing
  valid result is not a reason to rerun a model.
- [x] Target 8–12 models covering frontier, mid-tier, smaller, and open-weight
  models where technically and financially practical.

The finalized headline panel is:

| Model | Pinned upstream | Panel role |
| --- | --- | --- |
| GPT-5.6 Luna | OpenAI | Frontier OpenAI anchor and frontier sweep model |
| GPT-5.4 Mini | OpenAI | Smaller, more economical OpenAI comparison |
| GLM 5.2 | StreamLake | Large non-US frontier-family comparison |
| Claude Sonnet 5 | Anthropic | Frontier Anthropic anchor |
| Nemotron 3 Ultra 550B | Together | Large open-weight-family comparison |
| Qwen 3.7 Plus | Alibaba | Large Qwen-family comparison |
| Claude Haiku 4.5 | Anthropic | Efficient Anthropic comparison |
| Mistral Medium 3.5 | Mistral | Mid-tier European-family comparison |
| Mistral Small 4 (`2603`) | Mistral | Small/efficient Mistral comparison |
| MiniMax M3 | MiniMax | Capable low-cost model and sweep anchor |
| Qwen 3.5 9B | DeepInfra | Small open model and sweep floor |

Gemini, Grok, Kimi, and DeepSeek are not silent omissions: the live pre-result
compatibility probes could not put their candidate routes into the same
reasoning-off, JSON, privacy, and pinned-provider lane. They may appear later in
a separately specified lane, but they must not be mixed into this ranking with
different execution conditions.

- [x] Record exact model identifiers, endpoint snapshot names, and upstream routes;
  never collapse distinct snapshots
  under a generic family name.
- [x] Keep the headline lane API-only, fresh-spawn, `compact`, and under the
  frozen output policy.
- [x] Keep coding-agent CLI harnesses in a separate diagnostic table.
- [ ] Never parallelize Claude or another subscription/rate-limited CLI.
- [x] Verify all 11 pre-registered provider/model routes can accept the common
  privacy, parameter, JSON, reasoning-off, and bounded-output policy. Replace
  incompatible routes before any official sweep result existed.
- [ ] Run a benchmark-level smoke for every provider/model combination after the
  sweep freezes the shared cap and immediately before the full panel.
- [ ] Use serial execution, fail-fast behavior, atomic checkpoints, and validated
  resume rather than restarting completed episodes.
- [ ] Run all eight official seeds, five seasons, and three candidate repeats.
- [ ] Use the full official baseline panel.
- [ ] Require complete input/output token, latency, failure, repair, route, and
  cost telemetry for every API decision.
- [ ] Reject or quarantine any row that does not pass strict `sota-v2` validation.
- [ ] Put interesting but ineligible rows in `results/diagnostics/`, never in the
  headline table.
- [ ] Compact only after strict validation and preserve the raw-artifact hash.
- [ ] Keep committed result artifacts under the CI size limit.
- [ ] Publish raw public-panel traces as release assets so results are auditable.
- [ ] Preserve provider errors and incomplete attempts as diagnostic evidence.
- [ ] Regenerate the leaderboard from source artifacts; do not hand-copy scores.
- [x] Require at least eight eligible, registered, route-matched, cost-complete
  headline rows before the generated JSON can expose a ranking.

For every headline model, report at least:

- [ ] mean score and score standard deviation;
- [ ] an uncertainty interval for the mean or paired lift, with its method;
- [ ] lift versus the full baseline-panel mean;
- [ ] lift versus `pick-trader`;
- [ ] per-seed win rate and paired sign-flip p-value;
- [ ] input tokens per decision and output tokens per decision;
- [ ] total cost and cost per episode;
- [ ] illegal actions, failed queries, adapter failures, and repair attempts;
- [ ] execution lane, provider route, model snapshot, and scaffold fingerprint;
- [ ] result contract and seed-panel identity; and
- [ ] per-mechanic outcomes for drafting, trades, free agency, cap management,
  scouting, and lineup decisions where supported.

- [ ] State how multiple model comparisons are handled. If adjusted inferential
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
- [ ] Discuss compute elasticity before presenting a ranking.
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

> How much inference compute does an LLM need to beat a transparent heuristic at
> long-horizon asset management?

Claims that may be supportable after the study:

- At a stated output budget, model X did or did not outperform transparent
  scripted references on the frozen GM-Bench v2 environment.
- Performance did or did not saturate over the tested output-budget range.
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

- [ ] Generate all tables and headline numbers from validated artifacts.
- [ ] Keep a visible “last updated” date and contract version on the site.
- [ ] Lead the blog with the research question and the measurement problem, not
  with implementation history.
- [ ] Explain the simulator and decision loop with one compact diagram.
- [ ] Show the output-budget result before the final model ranking.
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

- [ ] Replace “GM-Bench MVP” with a confident, accurate project name and one-line
  description.
- [ ] Add a concise GitHub repository description.
- [ ] Add the deployed site as the repository homepage.
- [ ] Add relevant topics such as `llm-evaluation`, `agents`, `benchmark`,
  `simulation`, `sports-analytics`, and `reproducible-research`.
- [ ] Put the primary result or honest “results pending” state near the top of the
  README.
- [ ] Add a five-minute quickstart that works from a clean clone without provider
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
- [ ] Did the output-budget study determine the presentation policy?
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
| 2026-07-14 | Full-panel route compatibility | Complete for current snapshot | `config/sota_v2_models.json` | All 11 exact routes accepted the common privacy/parameter policy; four incompatible original choices were replaced before official results. Endpoint health is rechecked by the runner because provider state can drift. |
| 2026-07-15 | GPT-5.6 Luna standardized smoke | Complete | raw SHA-256 `e8f83c6516cb3cc8105b173c826c1b5d91314a487b729f9b06b8fc6beda2bc8f` | Exact OpenAI route, reasoning off, 4/4 decisions with complete telemetry, zero repairs or failed decisions, 593 output tokens, $0.0494 cost, and 7.9 seconds API time. Four illegal actions and the resulting 10-point penalty are retained as measured model behavior. |
| 2026-07-15 | GPT-5.6 Luna 1,024-token sweep cell | Accepted | canonical SHA-256 `b681bdc56f3d176d194c9c1e20cc688be4ef4b58f7669862fb2268af99a0e37a`; byte SHA-256 `74d342c5d4c799524dadd6f668350eede67b8b74e5522833723e25ab4f50480b` | Strict `output-budget-sweep` validation passes. Mean score 200.799; strategy score 293.508; 2,225 protocol penalty from 890 illegal actions; 84 failed queries; zero failed decisions or repairs; 154 output tokens/decision; $5.6377 total cost. This is one accepted compute-study cell, not yet a headline row or cap decision. |
| 2026-07-15 | Sweep cost/runtime plan | Provisional pending refreshed Qwen smoke | `results/analysis/output-budget-cost-estimate.json` | With Luna replacing GPT-5.4 Mini: planning estimate $33.25; cost contingency $39.90; token-ceiling reservation $98.28 ($117.94 with contingency). Luna runtime is current; refresh the total runtime estimate after the changed Qwen route smoke. |

## Living-document maintenance checklist

Update this file when any of the following happens:

- [ ] A relevant PR merges, closes, rebases, or changes scope.
- [ ] The frozen contract, scaffold, provider route, or publication lane changes.
- [ ] A sweep cell or model panel completes or fails.
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
