# TypeSafe Jev lane (decision-api)

Status: decision-model lane, added 2026-09-18 and run on the full sota-v5
private panel the same day (see "Published run" at the end). Its row validates
under the `sota-v5` result policy and is published beside, never inside, the
chat-lane headline: it is not in the pre-registered family and is not
comparable with the chat lanes on the leaderboard. Read the "What a Jev row
measures" section before quoting a number from it.

## What Jev is

[TypeSafe AI](https://typesafe.ai) came out of stealth on 2026-09-15 with Jev,
which it calls a "System One" model. Jev does not generate text. A request
carries a `state` (a string, JSON object, or array) and a map of typed
questions; the response carries one typed answer per question:

| Question type | You send | Jev returns |
| --- | --- | --- |
| `noul` | a yes/no question | `noul`: probability of yes |
| `choice` | a question plus `criteria`, a map of option label to description (up to 255 options) | `choice`: one label, `probabilities` per label, `confidence` |
| `score` | a question plus `criteria`, an ordered list of 2-10 level descriptions | `score`, `legend`, `probabilities`, `confidence` |

Questions in one request are evaluated independently and adding questions adds
little latency. Launch pricing is $0.042 per million input tokens and $0 for
output (there is no token generation phase); TypeSafe describes the price as
possibly subsidized. The documented limits are roughly 32k tokens for the state
plus the longest single question and roughly 64k tokens for the state plus all
questions. Launch coverage reports 70-500 ms end-to-end latency.

Wire format used by `examples/typesafe_jev_agent.py`:

```text
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer $TYPESAFE_API_KEY
Content-Type: application/json

{"model": "jev-latest", "state": {...}, "questions": {"<key>": {"type": "choice", "instructions": "...", "criteria": {...}}, ...}}
```

```json
{"model": "jev-1.13.0",
 "answers": {"<key>": {"type": "choice", "choice": "280", "probabilities": {"280": 0.61, "none": 0.39}, "confidence": 0.42},
             "dress_4": {"type": "noul", "noul": 0.92}},
 "usage": {"input_tokens": 3120, "output_tokens": 0}}
```

The adapter uses the raw HTTP API with the standard library, like every other
GM-Bench adapter, so no SDK is installed. The official Python package is
`typesafe-sdk` (`from typesafe_sdk import TypeSafeClient, Choice, Noul, Score`)
if you want to poke at the API by hand. The shape above was reconciled from the
official quickstart and two independent client libraries; the docs site itself
was not reachable from the environment this lane was written in, so verify the
first live smoke's request log against https://docs.typesafe.ai/api before
trusting a full run.

## Getting access

1. Join the waitlist at https://typesafe.ai. Early access was opening within a
   day or two of signing up in the launch week.
2. Create an API key in the console at https://console.typesafe.ai and attach
   billing there.
3. Put it in the shell or in `.env.local` (ignored by git):

```dotenv
TYPESAFE_API_KEY=apikey_...
```

Expected spend is small. Budget from the published OpenRouter panel: about
13,700 input tokens per decision and $0.33 for 580 calls (output billed at
zero). Launch coverage's 6-8k figure was low. The harness prices Jev usage
from `gm_bench/pricing.json` (`jev` prefix); the API returns token counts,
not cost.

## Running it

```bash
GM_BENCH_WORKERS=1 python3 -m gm_bench model --config examples/typesafe.jev.smoke.json
# or
GM_BENCH_WORKERS=1 python3 -m gm_bench model --provider typesafe --model jev-latest \
  --preset smoke --verbose --json --no-log
```

### Through OpenRouter, while the direct API is waitlisted

OpenRouter resells Jev as `typesafe/jev-1.13` at the same launch price, but
not on chat completions: that endpoint rejects the slug with HTTP 400. It
answers on `POST https://openrouter.ai/api/alpha/decisions`, which takes the
same `{model, state, questions}` body and returns the same `answers` map. With
`JEV_ROUTE=openrouter` the adapter posts there under `OPENROUTER_API_KEY`,
adds the usual OpenRouter referer headers, records the upstream provider,
generation id and any reported cost, and translates a bare pinned id such as
`jev-1.13` into the `typesafe/jev-1.13` slug (`jev-latest` becomes OpenRouter's
moving alias `~typesafe/jev-latest`):

```bash
OPENROUTER_API_KEY=... GM_BENCH_WORKERS=1 python3 -m gm_bench model \
  --config examples/typesafe.jev.openrouter.smoke.json
```

The route is a provider pin like the other v6 call conditions: the spec pins
`JEV_ROUTE=typesafe`, and a pin beats an inherited shell value, so exporting
`JEV_ROUTE=openrouter` in a terminal does nothing for a `--provider typesafe`
run. Switching routes takes a config `env` entry, as the OpenRouter smoke
config above does, and the credential preflight checks the key for that same
resolved route in the environment the child will get (the shell overlaid with
the config `env` block). The route is stamped into
`run_info.provider_options.JEV_ROUTE`. The path has
`alpha` in its name, so pin `typesafe/jev-1.13` rather than an alias, and keep
OpenRouter rows and direct-API rows apart: they are different transports of
the same model. OpenRouter also validates that every `instructions` and
`criteria` value is a string, which the adapter's question builder already
guarantees.

Keep the first run at `--preset smoke` (four decisions) and set
`JEV_DECISION_LOG=/tmp/jev.jsonl` so every request, answer set, and composed
action batch is written out for inspection. For a longer look use
`--preset standard` (36 decisions) or `--preset benchmark` (100 decisions);
`--preset leaderboard` also runs, but see the caveats below before treating the
output as a leaderboard row. Pin an exact model version instead of
`jev-latest` for anything you intend to keep; the returned model id is recorded
in `usage.model`.

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `JEV_ROUTE` | `typesafe` | `typesafe` (direct API) or `openrouter` (decisions endpoint); a provider pin, switched through a config `env` block; recorded |
| `TYPESAFE_API_KEY` | unset | Credential for the direct route |
| `OPENROUTER_API_KEY` | unset | Credential for the OpenRouter route |
| `TYPESAFE_MODEL` | `jev-latest` (`typesafe/jev-1.13` on OpenRouter) | Model id or slug |
| `TYPESAFE_API_BASE` | per route | Endpoint base override for the selected route (recorded); must be `https://`, with plain `http://` allowed only on loopback for a local stand-in. Redirects are never followed: a 3xx ends the call as an HTTP error, so the bearer key stays on the configured origin |
| `TYPESAFE_TIMEOUT` | derived from the decision budget | Per-call HTTP timeout |
| `JEV_NOUL_THRESHOLD` | `0.5` | Probability at which a yes/no answer counts as yes (recorded) |
| `JEV_ENABLE_TRADES` | `1` | Ask the trade questions and emit trade proposals (recorded) |
| `JEV_DECISION_LOG` | unset | JSONL audit log of questions, answers, and actions |

## How the harness was adapted

Every other GM-Bench adapter sends one prompt and forwards the model's reply
verbatim for `gm_bench/repair.py` to parse. Jev cannot reply with JSON actions,
so the adapter does the following instead, still within one paid call per
decision phase:

1. **State.** The `state` is a short briefing plus the exact
   `compact_observation` every chat adapter is prompted with. Jev reads the
   same rows, truncated by the same rules, as every other model.
2. **Questions.** One fixed batch per phase, built from `available_actions`:
   - `sign_free_agent` (choice over the listed free agents plus `none`) and
     `sign_years` (choice over 1-5 years);
   - `release` (choice over the roster plus `none`);
   - `dress_<player_id>` (one noul per roster row) for the lineup;
   - `extend_<player_id>` (noul per expiring contract) and `extend_years`
     (choice over 2-5 years) in preseason;
   - `claim_waiver` (choice plus `none`) in midseason;
   - `scout` (choice over unscouted prospects plus `none`) while scouting
     points remain;
   - `draft` (choice over the listed prospects) in the draft;
   - `offer_<n>` (accept / reject / ignore) per incoming offer;
   - `trade_target` (choice over the trade market plus `none`) and
     `trade_give` (choice over the roster and tradeable own picks plus `none`).
   Around 25-40 questions per decision, all `choice` or `noul`; `score` is not
   used because its numeric answer scale was the one part of the format the
   available sources disagreed on.
3. **Composition.** `compose_actions` turns the answers into an action batch by
   fixed rules. Every choice is Jev's. The host contributes only legality:
   - a signing or extension needs Jev's term answer as well as its pick, and
     is priced at the published quote for that term (offering the quote always
     succeeds, so the contract is exactly what Jev asked for); no answered
     term, or a term with no quote, means no contract;
   - the lineup is `position_aware_lineup` run over Jev's own dress
     probabilities, which fills the 10F/4D/1G minimums and the 18 slots in
     Jev's order; if Jev answered no dress question there is no lineup action;
   - the draft takes prospects in Jev's probability order, at most as many as
     picks owned;
   - a noul counts as yes at `JEV_NOUL_THRESHOLD`;
   - because answers are independent, a player named twice in one batch (given
     in a trade and also sent in an accepted offer) is settled in batch order:
     the first action keeps him and the later one is dropped. The lineup leads
     the batch and is legal on the roster Jev was asked about; a player Jev is
     sending away is left out of it when a legal lineup exists without him,
     and the simulator drops him from it once he leaves otherwise.
   A missing or malformed answer means no action for that question; the host
   never substitutes a choice.
4. **Telemetry.** One `api_calls`, the returned `model`, `input_tokens`,
   `output_tokens`, latency, and the response's request id as
   `generation_id`. The direct API documents no token generation phase, but
   OpenRouter's decisions endpoint reports around 1,300 output tokens per call
   for the answer payload and bills them at zero: the gateway-reported cost of
   the published run reproduces from input tokens alone at $0.042 per million.
   The adapter records what the gateway reports rather than zeroing it, so an
   output-token figure on a Jev row is an answer-size count, not spend. Unanswered questions are noted in `telemetry_error` and
   the decision still counts. Transport failures fall back to a strict noop
   with `model_error`, like every other lane.

The lane is declared in `gm_bench/decision_providers.py` rather than in
`gm_bench/providers.py`: the latter is hashed into every provider's scaffold
fingerprint and `benchmark_config.py` into the contract fingerprint, so adding
a spec to either would move the recorded fingerprints of every frozen sota-v5
row. The decision module registers into the live registry when the package is
imported, and the Jev scaffold fingerprint hashes that module in addition.

The adapter does not use `memo` (Jev writes no text), does not counter offers,
proposes at most one trade per window, and never asks the information queries
whose answers a one-call lane never sees.

## What a Jev row measures

- **The scaffold is part of the system.** A chat model decides *which* actions
  to take and *how many*; Jev answers a question list the host wrote. A Jev
  score is "Jev plus this question set", and a different question set is a
  different row. The scaffold fingerprint covers the adapter file, so the
  question set is attested, but the number is not evidence about Jev alone.
- **Malformed rate is zero by construction.** There is no text to misformat.
  Do not read a 0.0 malformed rate as a protocol-quality result.
- **Illegal actions are shared blame.** A trade the partner refuses is Jev's
  call, but the fact that a trade was proposable at all, and with one asset
  each way, is the scaffold's. Read `illegal_actions` beside the decision log.
- **No continuity.** Jev is stateless per call and writes no memo. It sees the
  observation's history rows and the ledger, nothing else, every decision.
- **Own lane.** `run_info.transport` is `decision-api`. The site builder maps
  that to its own lane and publishes the row in `decision_lane_models`, never
  in the headline `models` array. Do not fold it into the chat-lane `api`
  table.

Score it against the same scripted baselines as any other run and read the
paired lift; the comparison that is meaningful is Jev-plus-scaffold against the
scripted policies, not against the published model rows.

## Published run (2026-09-18)

The full private panel ran once over the OpenRouter route with
`examples/typesafe.jev.openrouter.smoke.json`'s knobs at `--preset leaderboard`
(`JEV_ROUTE=openrouter`, `JEV_NOUL_THRESHOLD=0.5`, `JEV_ENABLE_TRADES=1`),
serially, one paid call per decision, `require_clean` on.

| | |
| --- | --- |
| Model | `typesafe/jev-1.13`, served as `jev-1.13-20260917` |
| Route | OpenRouter `/api/alpha/decisions`, upstream TypeSafe |
| Contract / scaffold | `a600b7da0c302231` / `e1fc1e298283f465` |
| Panel | sota-v5 private panel, 29 seeds, 5 seasons, one episode per seed |
| Decisions | 580 of 580, 0 failed, every question answered |
| Illegal actions | 8 (54 refused trade proposals are counted separately) |
| Mean score | 229.0 (sd 41.1) |
| vs baseline-panel mean (175.3) | +53.7, 95% CI 37.5 to 69.5, seed win rate 0.862 |
| vs pick-trader (247.1) | -18.1, 9 of 29 seeds, unadjusted sign-flip p 0.081 |
| Cost | $0.33 gateway-billed; 0.42 s per call |

Artifact: `results/leaderboard/decision-lane/typesafe-jev-1.13-openrouter.json`
(redacted like every private-panel row; raw artifact and the
`JEV_DECISION_LOG` audit log stay with the operator). Analysis, including
leave-one-seed-out, observed minimum detectable difference, per-baseline seed
wins, weight sensitivity, and efficiency:
`results/analysis/decision-lane-typesafe-jev-1.13-openrouter.md`, regenerated
by `scripts/decision_lane_analysis.py --check`.

How it is published, and why this shape:

- The artifact lives in `results/leaderboard/decision-lane/`, not
  `results/leaderboard/sota-v5/`. The sota-v5 directory is what the
  robustness script, the reproduction guide, and the site's headline builder
  read as "the registered eleven", and this row must not change their count.
- The `sota-v5` result policy carries the lane's scaffold fingerprint so the
  row validates in CI like every other committed artifact. That entry attests
  the adapter and question set; it does not make the row a member of the
  pre-registered family.
- The site serves the row in its own "Decision-model lane" section built from
  `decision_lane_models` in `web/src/data/leaderboard.json`. The headline
  `models` array, the eligible-headline count, the shot chart, and the Holm
  counts do not see it, and `web/scripts/validate_results_data.ts` fails the
  build if they ever do.
- The comparison the row supports is against the scripted baselines. It is
  not a pre-registered cell, it has no Holm-adjusted p-value, and a
  side-by-side with a chat-lane row would compare two different systems.

