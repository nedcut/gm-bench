# Output policy and retired budget sweep

**Current policy (provisional revision 2026-07-16):** the `sota-v2` API headline
lane uses a common 4,096-total-output-token safety ceiling and native-minimum
reasoning. Reasoning is disabled where optional; models for which OpenRouter
marks reasoning mandatory use their lowest supported effort. Actual input,
output, and reasoning tokens, cost, and latency are secondary efficiency
metrics; they do not change the benchmark score.

The earlier 256 / 1,024 / 4,096 / 16,384 experiment was retired before any
replacement official cell ran. Its config, analyzer, and diagnostic artifacts
remain in the repository for auditability, but the matrix is neither runnable as
a paid phase nor required by the publication gate.

## Why the project changed course

The superseded GPT-5.6 Luna run made 601 successful API calls at a 1,024-token
ceiling. Per-call output usage was p50 121, p95 210, p99 264, and max 299; no
call reached the ceiling, and reasoning-token usage was zero. In this compact
JSON-action protocol, varying the maximum response length would therefore
mostly vary a non-binding safety limit rather than a clear inference-compute
treatment.

This evidence does **not** promote the old Luna score: that run used the
superseded prompt scaffold. It only supports the operational conclusion that
1,024 left substantial output headroom for reasoning-disabled models. It does
not establish a safe cap for Kimi K3 or the other mandatory-reasoning models in
the revised panel.

## Pre-full-panel cap-pressure rule

Before any full-panel result is run:

1. Smoke all ten phase-one models in `config/sota_v2_models.json` serially at 4,096.
2. Verify exact provider slug, endpoint tag and snapshot, required parameters,
   JSON behavior, the registered per-model reasoning policy, complete
   token/cost telemetry, and clean completion.
3. Inspect per-call output usage and truncation evidence.
4. If any call emits at least 3,072 total output tokens (75% of the cap), or provider or
   adapter telemetry indicates cap-induced truncation, raise the **entire** API
   lane to 8,192 and repeat affected smokes before any full result.
5. Do not change the common cap after any full-panel score is visible.

The 75% trigger is deliberately conservative: it detects meaningful cap
pressure before expensive evidence is generated without treating every model's
natural verbosity as benchmark compute.

Inspect the exact no-spend plan with:

```bash
python3 scripts/run_publication_matrix.py smoke --dry-run
```

Paid calls require an explicit `--max-spend-usd` ceiling and remain serial. The
operator should run one model at a time, inspect its artifact, and then approve
the next cell. A dry run or endpoint-only preflight does not contact a paid
model.

## Frozen publication lane

- Headline rows are API-only, fresh-spawn, `compact`, with one bounded protocol
  repair and exactly 4,096 maximum total output tokens per call.
- Reasoning is disabled with `reasoning.enabled=false` where optional. Gemini
  3.5 Flash and Muse Spark 1.1 use `minimal`, Grok 4.5 uses `low`, and Kimi K3
  uses its only supported effort, `max`.
- Every row reports score, failures, illegal actions, input/output tokens,
  latency, and cost. Token efficiency is interpretive evidence, not a hidden
  score adjustment.
- Codex, Claude Code, Cursor, and opencode remain a separate CLI-harness table
  because their context/tool loops and cost telemetry are not comparable to the
  API lane.
- The site still withholds the headline ranking until at least eight
  pre-registered, strictly eligible rows exist at the frozen common cap.

## Artifact publication

Keep raw traces outside git as release assets. Run `gm-bench compact-result`
only after strict validation; it retains per-seed/repeat outcomes and aggregate
usage plus a canonical raw-artifact SHA-256. CI requires the compact format and
caps committed current rows at 1 MB.

`config/output_budget_sweep.json` describes the retired four-cap design.
`results/analysis/output-budget-cost-estimate.json` must be regenerated from the
current ten-model registry and refreshed again after the route smokes provide
current latency and usage evidence.
