# Output policy and retired budget sweep

**Current policy (frozen 2026-07-15):** the `sota-v2` API headline lane uses a
common 1,024-output-token safety ceiling with reasoning disabled. Actual input
tokens, output tokens, cost, and latency are reported as secondary efficiency
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
1,024 left substantial output headroom.

## Pre-full-panel cap-pressure rule

Before any full-panel result is run:

1. Smoke all ten models in `config/sota_v2_models.json` serially at 1,024.
2. Verify exact route, required parameters, JSON behavior, reasoning disabled,
   complete token/cost telemetry, and clean completion.
3. Inspect per-call output usage and truncation evidence.
4. If any call emits at least 768 output tokens (75% of the cap), or provider or
   adapter telemetry indicates cap-induced truncation, raise the **entire** API
   lane to 2,048 and repeat affected smokes before any full result.
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
  repair and exactly 1,024 maximum output tokens per call.
- Reasoning is explicitly disabled with `reasoning.enabled=false`; reasoning
  effort and reasoning-token caps are absent.
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

`config/output_budget_sweep.json` and
`results/analysis/output-budget-cost-estimate.json` describe the retired design.
Do not use the old cost artifact as current spend guidance. Replace it with a
fixed-panel estimate after the ten route smokes provide current latency and
usage evidence.
