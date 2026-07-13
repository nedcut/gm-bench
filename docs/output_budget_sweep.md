# Output-budget sweep and lane freeze

The `sota-v2` contract fixes simulation and scoring. It does not by itself make
two model rows compute-comparable. The publication lane therefore remains
blocked until the planned 256 / 1,024 / 4,096 / uncapped sweep is complete for
at least two API models spanning the expected quality range.

## Run protocol

1. Select 2–3 models and commit their exact IDs to
   `config/output_budget_sweep.json` before seeing results.
2. Run `--preset smoke` serially at each cap to catch authentication,
   formatting, and usage failures. Never parallelize subscription CLIs.
3. Run the `leaderboard` preset with three repeats and the same `compact`
   observation profile. Set the provider-specific cap in config `env`
   (`OPENAI_MAX_TOKENS`, `ANTHROPIC_MAX_TOKENS`,
   `GEMINI_MAX_OUTPUT_TOKENS`, or `OPENROUTER_MAX_TOKENS`). An uncapped cell
   omits that variable.
4. Analyze locally without provider access:

   ```bash
   python scripts/analyze_output_budget.py /path/to/cells/*.json \
     --output results/analysis/output-budget-sweep.json
   ```

The analyzer accepts only `sota-v2` API transports, records each source
artifact hash, reports input and output tokens separately, and lists every
missing model-cap cell. It never promotes a complete matrix directly: a human
must inspect score-vs-output curves and freeze either a saturation cap or a
fixed-budget curve policy in `config/sota_v2_lane.json`.

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

## Artifact publication

Keep raw traces outside git as release assets. Run `gm-bench compact-result`
only after strict validation; it retains per-seed/repeat outcomes and aggregate
usage plus a canonical raw-artifact SHA-256. CI requires the compact format and
caps committed current rows at 1 MB.
