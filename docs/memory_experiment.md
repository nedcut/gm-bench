# Controlled journal experiment (experimental, not a leaderboard lane)

This separate runner compares **no persistent journal** with a **structured
decision journal**, using one fixed model and harness for all cells. It does not
change the frozen 1.0 or 2.0 engine, scoring, drivers, defaults, artifacts or panels.
Nothing imports it from the existing CLI; invoke `python -m gm_bench.memory_experiment`.
The experiment is public-seed-only. Do not supply private panel seeds: manifests,
ledgers and reports deliberately record the selected public seeds.

## Reproduce the offline example

From a repository environment with the project installed (for example,
`uv sync --extra dev`), run:

```sh
.venv/bin/python -m gm_bench.memory_experiment register \
  --public-seeds 701 702 --repeats 2 --seasons 1 \
  --out /tmp/journal-registration.json
.venv/bin/python -m gm_bench.memory_experiment run \
  /tmp/journal-registration.json --out /tmp/journal-smoke
cat /tmp/journal-smoke/report.md
.venv/bin/python -m gm_bench.memory_experiment report /tmp/journal-smoke
```

Use fresh paths each time: registration and collection refuse overwrite. The
[illustrative report](../examples/memory_experiment/report.md) and companion
manifest, cell summaries and analysis are committed outside the original results
directories. Raw traces are generated locally, not committed. Timestamps, git
provenance, manifest hashes and measured latency vary across reproductions;
scripted scores, action counts and paired differences are deterministic.

The scripted agent reads status at each phase, reads rules when its journal lacks
the fact “rules reviewed,” then ends the phase. It intentionally does not optimize
the team. Both conditions therefore have identical scores, while retained journals
save three reads (and three provider-function invocations) over four phases. Zero
model tokens and zero provider cost are measured facts about the **offline fixture**,
not estimates of LLM cost. These fixtures do not prove that memory improves LLM
performance or predict an effect size.

## What is held fixed

Registration writes a SHA-256 manifest before the first outcome. It binds:

- Public simulator seeds, seasons, repeat count, both conditions and their order.
- One provider, requested model, identity pin policy, harness, temperature and
  sampling-seed support. Every episode has fresh simulator state and stateless
  provider calls; there is no shared conversation/session across episodes.
- The frozen simulator/2.0 contract fingerprints and experimental source digest,
  git commit, dirty state and Python version. Source drift requires registration
  of a new panel. Keep the exact checkout to regenerate historical reports.
- The tool schemas, prompt/observation policy, journal schema and all limits.
- Primary score difference, secondary diagnostics, pairing, repeat aggregation,
  failure handling and descriptive uncertainty, before collecting outcomes.

Every phase starts with empty call/reply history. Both arms receive the same task
brief with explicit experimental overrides, tool schemas, current phase coordinates
and a journal with `facts`, `plan`, `decisions` (arrays of strings). The model emits
one `{tool, arguments, journal}` JSON object per invocation. Journal updates cost
output tokens in **both** arms. Scratch journals persist within a phase in both
arms; only the treatment retains the last journal across a phase boundary.

All frozen tools keep their semantics except `write_memo`, which is unavailable
in both arms and removed from both schemas and status tool listings. This prevents
the control writing an alternative persistent note. There is no shell, file tool,
hidden simulator seed, prior episode state, or previous-phase transcript in model
requests. Public history, roster state, scouting reports and transaction retrieval
remain available equally. The wrapper records every request, response, journal,
tool result, reported usage and observed model identity in local traces.

This tests the **total effect of cross-phase journal retention under fixed
resource ceilings**, conditional on both arms being instructed to plan. It does
not separately identify a planning benefit. Journal input length, realized tool
use and later decisions may differ as consequences of treatment; they are not
equalized post hoc. Persistent simulator state can itself carry information.
Because historical facts remain freely retrievable, a result may reflect retrieval
efficiency rather than memory dependence. A memory-dependent task would need a
separately registered observation intervention; that is outside this experiment.

## Limits and failure accounting

Defaults per condition are 12 invocations per phase, a 120,000-character canonical
JSON request ceiling, a 4,000-character canonical journal ceiling, 2,048 maximum
completion tokens per provider request, and 60 seconds of socket inactivity.
CLI registration flags can change these **before** outcomes. Limits include
rejections and the `end_phase` call. An episode stops on the first limit violation,
malformed response, provider failure or identity mismatch; no truncation, retry,
selective resume or model fallback occurs. Remaining phases are finalized as
`harness_exit`, scored and retained. A failed cell is not silently dropped.

The character budget is precisely `len(canonical_json(request))`, **not** tokenizer
length, wire bytes or a billed-input ceiling. urllib's socket timeout is not a
total wall-clock deadline; an active streaming socket may take longer. The adapter
does not stream, but no strict end-to-end deadline or dollar cap is asserted.
Maximum attempted requests per cell are `seasons × 4 × max_calls_per_phase`;
maximum requested completion-token allowances multiply that by
`max_output_tokens`. Input tokens, pricing and actual bills are separate concerns.
The frozen engine wall-clock guard is disabled only in this new runner; the
existing 2.0 guard and all other default entrypoints remain unchanged.

Reports separate completion, failed decisions, simulator-illegal actions, rejected
tool calls, score, strategy score, protocol penalty, tools and model invocations.
Schema/unknown-tool rejections do not necessarily incur a simulator penalty.
Token usage is provider-reported (`measured`) or `unavailable`; any missing call's
usage makes the episode total unavailable. Latency is client-measured, including
failed requests. Optional preregistered input/output prices produce `estimated`
cost only if usage is complete; cache discounts and billing adjustments are not
modeled. Actual billed cost is `unavailable`. No missing quantity becomes zero.

## Pairing and analysis

Each public seed × repeat runs both conditions from a fresh episode. Order alternates
by seed index plus repeat index, serially. The analysis computes journal-minus-control
differences within each pair, averages repeat differences within each seed, then
averages equally across seeds. Descriptive standard errors use these seed means;
repeats are not falsely treated as independent league samples. One seed has no
standard-error estimate. There is no significance test, post-hoc sample selection
or automatic causal headline.

All preregistered cells must appear exactly once for a complete-panel estimate.
Interrupted panels can be reported with `report`; missing cells are named and
pooled estimates withheld. A whole-panel rerun requires a new directory and must
retain/disclose the interrupted run. Do not select the best rerun. Provider failures
with a recorded cell remain in the primary analysis; their separate completion
rate makes interpretation possible. Inspect identity verification and source-drift
status before interpreting any numerical estimate. Unpinned/unsupported identities
are explicitly exploratory, even with a complete panel.

`manifest.json` and `run-start.json` precede collection. Each `cell-NNNN` contains
`ledger.jsonl` (replayable simulator actions), `trace.jsonl` (full experimental
inputs/outputs), and `cell.json` (outcomes). `run-end.json` hashes all cell evidence
and records code drift; report regeneration rejects altered evidence. `analysis.json`
and `report.md` are derived. Hashes detect accidental modification; they are not
an external timestamped preregistration authority or a cryptographic authenticity
claim. Do not publish raw model traces without reviewing their content.

## Future real run (not executed for this PR)

The bundled stdlib adapter supports the OpenAI Chat Completions JSON-object route,
one stateless request per tool decision. It fixes `temperature=0`,
`max_completion_tokens`, `store=false`, and disables redirects and retries.
The [official API reference](https://developers.openai.com/api/reference/resources/chat)
documents this interface. Use a model supporting these parameters; incompatible
models produce retained provider failures, never a silently different route.

First select and verify an available **dated snapshot ID** using provider
documentation/account access. The command below uses an operator-provided
`MODEL_SNAPSHOT`, not a promise that any particular model remains available:

```sh
# MODEL_SNAPSHOT must be an available dated ID, e.g. ending -YYYY-MM-DD.
# Existing authorized credentials must already be available as OPENAI_API_KEY.
.venv/bin/python -m gm_bench.memory_experiment register \
  --public-seeds 701 702 --repeats 2 --seasons 1 \
  --provider openai-chat --model "$MODEL_SNAPSHOT" --pin-status pinned \
  --out /tmp/journal-real-registration.json

# Run only after separate authorization of provider spend:
.venv/bin/python -m gm_bench.memory_experiment run \
  /tmp/journal-real-registration.json --out /tmp/journal-real --allow-paid
```

A pinned run rejects aliases at registration and verifies every returned model ID
before executing its action. Snapshot IDs are requested/response assertions, not
independent attestations of model weights. Returned backend fingerprints are retained
per invocation and summarized per cell (missing values are explicit). Sampling seed
support is `unsupported` for this adapter, and no sampling seed is sent. Simulator
seed pairing does not make provider inference deterministic. Where identity cannot
be pinned, explicitly register `--pin-status unpinned` or `unsupported`; it cannot
report verified identity. The existing four 2.0 rows remain unpinned exploratory
evidence. Neither this framework nor those rows support causal 1.0-versus-2.0 claims.

For known pricing, supply both `--input-usd-per-million` and
`--output-usd-per-million` at registration; otherwise cost is unavailable. Inspect
one separately registered small smoke before authorizing a larger panel, and
preregister the larger panel independently. No paid calls, credential changes,
private-seed publication, website changes or counterfactual branching are needed
to reproduce the offline example.
