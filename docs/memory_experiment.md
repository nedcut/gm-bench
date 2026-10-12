# Harness-design experiment: cross-phase context policy (experimental, not a leaderboard lane)

## The question

An agent harness decides what the model sees on each call. This experiment asks
one harness-design question: **with the model held fixed, does it change score
and cost if the harness carries a structured decision journal from one decision
phase into the next, instead of starting each phase with no memory?**

Only the harness's context policy changes. The model, tools, seeds and
resource ceilings stay the same. A difference between the two arms is
therefore an effect of how the harness manages context, not of which model ran.

The two arms (called *conditions* in the code and reports):

- `no_persistent_journal` (control): every phase starts with an empty
  conversation history and an empty journal.
- `structured_decision_journal` (treatment): every phase starts with an empty
  conversation history, plus the journal the model wrote in the previous phase.

This runner is separate from the frozen 1.0 and 2.0 benchmarks. It does not
change their engine, scoring, drivers, defaults, artifacts or panels. Nothing
imports it from the existing CLI; invoke `python -m gm_bench.memory_experiment`.
The experiment is public-seed-only. Do not supply private panel seeds: manifests,
ledgers and reports deliberately record the selected public seeds.

### What is held fixed

- **Model and request settings.** One provider, one requested model ID, one
  identity pin policy, and the same per-request settings for every cell
  (`temperature` 0 for OpenAI; a registered `effort` with adaptive thinking for
  Claude, see [Running with a Claude model](#running-with-a-claude-model)).
- **Tools.** The frozen 2.0 tools with unchanged semantics, except `write_memo`,
  which is removed from **both** arms so the control cannot keep its own note.
- **Seeds.** Each public simulator seed and repeat index is played once in each
  arm, from a fresh episode. The pair shares the seed, so league luck cancels.
- **Resource ceilings.** Calls per phase, request size, journal size, output
  tokens per request and socket timeout. Ceilings are equal; the amount actually
  used is an outcome (see below).
- **The prompt.** Same task brief, same experimental overrides, same tool
  schemas. Both arms are told to write a journal and both pay output tokens for
  it.

### What varies

Only whether the last journal of a phase is passed into the next phase. Within
a phase both arms keep their scratch journal and call history the same way.

### What the result can and cannot claim

It can estimate, for this one model and harness, the **total effect of
cross-phase journal retention** on score, completion, illegal actions, tool use,
tokens, latency and estimated cost, with seed-level uncertainty.

It cannot claim:

- That memory helps models in general. One model, one harness and a public-seed
  panel do not generalize.
- That planning helps. Both arms plan; only retention differs.
- That the task depends on memory. Past facts stay retrievable through the tools,
  so a benefit may be cheaper retrieval rather than knowledge the control lacks.
- Equal compute. The ceilings are equal, but the treatment reads longer requests
  and both arms may make different numbers of calls. These are consequences of
  the treatment and are reported, not equalized afterwards.
- Anything about 1.0 versus 2.0, or about a leaderboard ranking.

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
not estimates of LLM cost. The fixture proves the protocol runs and pairs
correctly. It does not show that memory improves model performance or predict an
effect size.

## Protocol details

Registration writes a SHA-256 manifest before the first outcome. It binds:

- Public simulator seeds, seasons, repeat count, both conditions and their order.
- One provider, requested model, identity pin policy, effort (Claude only),
  harness, temperature and sampling-seed support. Every episode has fresh
  simulator state and stateless provider calls; there is no shared
  conversation/session across episodes.
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

There is no shell, file tool, hidden simulator seed, prior episode state, or
previous-phase transcript in model requests. Public history, roster state,
scouting reports and transaction retrieval remain available equally. The wrapper
records every request, response, journal, tool result, reported usage and
observed model identity in local traces. Persistent simulator state can itself
carry information across phases in both arms. A task that truly depends on
memory would need a separately registered change to what the tools reveal; that
is outside this experiment.

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
total wall-clock deadline; an active streaming socket may take longer. The adapters
do not stream, but no strict end-to-end deadline or dollar cap is asserted.
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

## Running with a Claude model

Provider `anthropic-messages` sends one stateless request per tool decision to
the Anthropic Messages API (`https://api.anthropic.com/v1/messages`), using the
standard library only. It needs `ANTHROPIC_API_KEY` in the environment and
`--allow-paid` at run time; without either, the run stops before creating the
output directory.

Why a direct adapter rather than an OpenAI-compatible route such as OpenRouter:
the experiment's `openai-chat` adapter is fixed to `api.openai.com` and
`OPENAI_API_KEY`, so no existing route reached Claude. OpenRouter would also weaken
"the model is held fixed": it returns undated model slugs and can route one slug
to different upstream hosts unless the extra provider-pinning settings in
[api_provider_lanes.md](api_provider_lanes.md) are carried over. The direct API
has one upstream and returns the served model ID on every response.

What the adapter sends and records:

- `system` is the task brief; one `user` message holds the phase state as JSON.
- No `temperature`, `top_p` or `top_k`. Current Claude models reject sampling
  parameters, so the OpenAI adapter's `temperature=0` has no equivalent here.
- `thinking: {"type": "adaptive"}` and `output_config.effort` set to the value
  given by `--effort` at registration. Effort is required, written into the
  manifest and the same for every cell, so a model's default effort cannot vary
  silently. Thinking tokens count toward `max_tokens` and toward output usage.
- No server-side refusal fallback. A fallback would let a different model answer
  a request, which breaks the fixed-model design. A refusal or a response cut off
  at `max_tokens` has no valid JSON action, so the episode ends as
  `malformed_response`; `stop_reason` is kept in the trace to tell them apart.
- Only `text` blocks form the action. The JSON must be bare: a reply wrapped in a
  Markdown code fence is malformed. Run the pilot below before the panel to see
  how often that happens.
- Input tokens are `input_tokens` plus cache writes and cache reads. The adapter
  requests no prompt caching, so the cache counts should be zero; any cache reads
  would make the estimated cost slightly too high, not too low.

Identity: Claude model IDs such as `claude-sonnet-5-5` carry no date suffix.
With `--pin-status pinned` the runner checks that every response names exactly
the requested model, and stops the episode on a mismatch. It cannot prove that
the ID is a fixed snapshot rather than an alias; confirm that from Anthropic's
model documentation when you register.

## Sizing a real run

Nothing below has been run. The numbers are a plan for preregistration, built
from noise measured elsewhere in this repository. Run the pilot first and resize
from its own paired differences.

### Noise inputs

The primary outcome is the per-seed difference in `final_score` between the two
arms, with the model fixed. Its spread has two parts: run-to-run noise for one
model on one seed, and how much the journal's effect itself varies from seed to
seed. The repo has measurements for the first part and only a loose upper
reference for the second. All come from five-season episodes in the GM-Bench 2.0
agentic lane ([bench_v2_spec.md](bench_v2_spec.md)), which uses a different
harness (Claude Code and others over MCP), so they are borrowed, not measured
for this harness:

| Source in bench_v2_spec.md | Within-seed SD | SD of a paired difference |
|---|---:|---:|
| "Repeat noise on the paid harnesses": Claude Code, `claude-sonnet-5` | 11.3 | 16.0 (= √2 × 11.3) |
| "Repeat noise under current behaviour": free model, without seed 1 | 23.3 | 33.0 |
| Same, all eight seeds | 43.4 | 61.4 |
| "Realized panel noise": `claude-sonnet-5` lift against `pick-trader` | — | 73.4 |

The first three rows assume the journal effect is the same on every seed. The
last row is a model-versus-scripted-policy contrast; treat it as a pessimistic
reference, not an upper bound.

### Seeds needed

Two-sided alpha 0.05, 80% power, one repeat per arm per seed, so the number of
seed pairs is `((1.96 + 0.84) × SD / effect)²`, the formula the spec uses for
realized minimum detectable difference (MDD):

| SD of paired difference | Seeds for 10 points | for 20 points | for 30 points | MDD at 32 seeds |
|---:|---:|---:|---:|---:|
| 16.0 | 21 | 6 | 3 | 8 |
| 33.0 | 86 | 22 | 10 | 16 |
| 61.4 | 296 | 74 | 33 | 30 |
| 73.4 | 423 | 106 | 47 | 36 |

Five-season scores in the 2.0 panels sit around 200 to 260, so 10 to 30 points is
roughly a 4% to 14% change. There is no pilot yet, so a plausible effect size is
a guess. The proposal: **preregister 32 seed pairs, one repeat each (64 cells),
five seasons.** That resolves about 8 to 16 points if journal effects are fairly
stable across seeds, and about 30 to 36 points if they are as uneven as a
model-versus-policy contrast. Spend extra budget on more seeds, not repeats
(`scripts/panel_power.py` explains why).

### Token and cost estimate for one cell

One cell is one five-season episode (20 phases) in one arm. The estimate:

- **Calls.** The Claude Code `claude-sonnet-5` panel row
  (`results/agentic/claude-2.1.281-claude-sonnet-5-panel-32x5.json`) averaged
  156 GM-Bench tool calls per five-season episode (range 135 to 175). This
  harness makes one model request per tool call, so expect about 160 requests,
  with a ceiling of 240 at the default 12 per phase.
- **Input.** Measured on seed 701: the fixed part of each request (brief plus
  tool schemas) is about 11,000 characters; `get_status`, `get_team`,
  `list_free_agents` and `list_trade_market` results are 4,700 to 6,200
  characters each and stay in the history until the phase ends. At an assumed
  3.5 characters per token (not measured with Claude's tokenizer), that is about
  0.5M input tokens per cell at the low end, 1.1M typical, 2.5M high.
- **Output.** That panel row averaged 62,000 output tokens per episode. Here
  each request also rewrites the journal (up to 4,000 characters), so expect
  80,000 to 240,000.

| Model (list price per 1M input / output) | Low | Typical | High |
|---|---:|---:|---:|
| `claude-haiku-5-5` ($0.10 / $0.50) | $0.09 | $0.19 | $0.37 |
| `claude-sonnet-5-5` ($2 / $10) | $1.80 | $3.70 | $7.40 |
| `claude-opus-5-5` ($4 / $20) | $3.60 | $7.40 | $15 |

Prices are Anthropic list prices as of 2026-10-06; check them at registration and
pass them with `--input-usd-per-million` and `--output-usd-per-million`. With
`claude-sonnet-5-5`, the 64-cell panel is about $240 (range $115 to $475) and the
16-cell pilot about $60. Wall time is serial: at 5 to 30 seconds per request, a
cell takes roughly 15 to 80 minutes, so the panel takes days, not hours.

### Commands (do not run without separate spend authorization)

Pilot, 4 public seeds × 2 repeats × 2 arms = 16 cells. It measures the paired
spread, the malformed-response rate and real token use before the panel is
sized. `--max-output-tokens 8192` leaves room for thinking; it is a ceiling, not a
target, but it raises the worst case.

```sh
export ANTHROPIC_API_KEY=...   # existing authorized credential
.venv/bin/python -m gm_bench.memory_experiment register \
  --public-seeds 801 802 803 804 --repeats 2 --seasons 5 \
  --provider anthropic-messages --model claude-sonnet-5-5 --effort low \
  --pin-status pinned --max-output-tokens 8192 \
  --input-usd-per-million 2 --output-usd-per-million 10 \
  --out /tmp/context-policy-pilot-registration.json
.venv/bin/python -m gm_bench.memory_experiment run \
  /tmp/context-policy-pilot-registration.json \
  --out /tmp/context-policy-pilot --allow-paid
```

Panel, registered separately after the pilot, on seeds the pilot did not use:

```sh
.venv/bin/python -m gm_bench.memory_experiment register \
  --public-seeds $(seq 701 732) --repeats 1 --seasons 5 \
  --provider anthropic-messages --model claude-sonnet-5-5 --effort low \
  --pin-status pinned --max-output-tokens 8192 \
  --input-usd-per-million 2 --output-usd-per-million 10 \
  --out /tmp/context-policy-panel-registration.json
.venv/bin/python -m gm_bench.memory_experiment run \
  /tmp/context-policy-panel-registration.json \
  --out /tmp/context-policy-panel --allow-paid
```

If the pilot's SD of seed-level paired differences differs from the table above,
change the seed count before registering the panel, never after.

## Running with an OpenAI model

The `openai-chat` adapter sends one stateless request per tool decision to the
OpenAI Chat Completions JSON-object route. It fixes `temperature=0`,
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

A pinned OpenAI run rejects undated aliases at registration and verifies every
returned model ID before executing its action. Snapshot IDs are requested/response
assertions, not independent attestations of model weights. Returned backend
fingerprints are retained per invocation and summarized per cell (missing values
are explicit; the Anthropic API returns none). Sampling seed support is
`unsupported` for both adapters, and no sampling seed is sent. Simulator seed
pairing does not make provider inference deterministic. Where identity cannot be
pinned, explicitly register `--pin-status unpinned` or `unsupported`; it cannot
report verified identity. The existing four 2.0 rows remain unpinned exploratory
evidence. Neither this framework nor those rows support causal 1.0-versus-2.0
claims.

For known pricing, supply both `--input-usd-per-million` and
`--output-usd-per-million` at registration; otherwise cost is unavailable. Inspect
one separately registered small smoke before authorizing a larger panel, and
preregister the larger panel independently. No paid calls, credential changes,
private-seed publication, website changes or counterfactual branching are needed
to reproduce the offline example.
