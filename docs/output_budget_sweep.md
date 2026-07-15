# Output-budget sweep and lane freeze

The `sota-v2` contract fixes simulation and scoring. It does not by itself make
two model rows compute-comparable. The publication lane therefore remains
blocked until one output policy is explicitly re-frozen.

**Current status (2026-07-15): paused for policy review.** The first Luna cell
was superseded after a scaffold defect was found, and its 154 output
tokens/decision at a 1,024-token ceiling raised a second question: whether the
four-cap matrix measures a meaningful compute axis when reasoning is disabled,
or merely repeats a non-binding JSON response limit. The paid runner now blocks
the sweep while `config/output_budget_sweep.json` is `paused-policy-review`.
The project must choose and predeclare either the matrix below or one generous
safety ceiling with actual token and cost efficiency reported for every row.

## Run protocol

1. Select 2–3 models and commit their exact IDs to
   `config/output_budget_sweep.json` before seeing results.
2. Run one standardized `--preset smoke` per selected model at 1,024 tokens to
   catch authentication, formatting, routing, and usage failures. Then use the
   runner's endpoint preflight for the full cap matrix. Repeating a smoke at
   every cap adds cost without replacing the official sweep; low-cap protocol
   failures are expected measurements, not infrastructure blockers. Never
   parallelize subscription CLIs.
3. Run the `leaderboard` preset with three repeats and the same `compact`
   observation profile. Set the provider-specific cap in config `env`
   (`OPENAI_MAX_TOKENS`, `ANTHROPIC_MAX_TOKENS`,
   `GEMINI_MAX_OUTPUT_TOKENS`, or `OPENROUTER_MAX_TOKENS`) and set
   `GM_BENCH_OUTPUT_BUDGET_CELL` to the matching integer. Every cell is bounded
   at a common value. A provider-dependent “uncapped” cell was deliberately
   removed before official runs because different upstream maxima are neither
   financially safe nor compute-comparable.
4. Analyze locally without provider access:

   ```bash
   python scripts/analyze_output_budget.py /path/to/cells/*.json \
     --output results/analysis/output-budget-sweep.json
   ```

The analyzer accepts only frozen-contract API transports under the dedicated
failure-tolerant `output-budget-sweep` policy, records each source
artifact hash, reports input and output tokens separately, and lists every
missing model-cap cell. It never promotes a complete matrix directly: a human
must inspect score-vs-output curves and freeze either a saturation cap or a
fixed-budget curve policy in `config/sota_v2_lane.json`. A single-number
ranking requires `output_budget_status` to be `frozen-saturation` or
`frozen-fixed-budget` and `output_token_cap` to be the chosen positive integer.

The exact endpoint snapshots, retry/exclusion/stopping rule, primary endpoint,
and operator-approval requirement live in `config/publication_protocol.json`.
The reproducible planning and token-ceiling estimates live in
`results/analysis/output-budget-cost-estimate.json`. Paid runs require an
explicit `--max-spend-usd` argument. The runner reserves each cell's committed
output-ceiling estimate before launch and retains that reservation after a
failure; live account and artifact telemetry remain the final guard against
price or input-token drift.

The committed cost artifact still reproduces the superseded 12-cell plan for
auditability; it is not current spend guidance. Regenerate it only after the
policy is re-frozen, then recheck live pricing, endpoint health, and smoke
latency immediately before any official run.

## Frozen publication lanes

- The headline ranking is API-only, fresh-spawn, `compact`, with one bounded
  protocol-repair attempt. Every row reports input/decision,
  output/decision, repair attempts, failure rate, and cost.
- Codex, Claude Code, Cursor, and opencode are coding harnesses with
  uncontrolled context/tool loops and often no cost telemetry. Their rows are
  useful, but the site builder emits them separately as `cli_harness_models`.
- A failed first response repaired into valid JSON counts its full token and
  latency spend, but no longer becomes a strategy failure. Repair is bounded
  at one attempt, recorded in provenance and usage, and cannot loop.
- OpenRouter completion responses expose the observed upstream provider, not
  the endpoint snapshot name. The runner therefore validates the exact healthy
  endpoint snapshot and capabilities immediately before the cell, while the
  artifact independently attests the observed provider. This does not prove an
  endpoint identifier that OpenRouter does not return.

## Artifact publication

Keep raw traces outside git as release assets. Run `gm-bench compact-result`
only after strict validation; it retains per-seed/repeat outcomes and aggregate
usage plus a canonical raw-artifact SHA-256. CI requires the compact format and
caps committed current rows at 1 MB.
