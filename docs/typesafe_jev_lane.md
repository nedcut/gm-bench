# TypeSafe Jev lane (decision-api)

Status: exploratory one-off lane, added 2026-09-18. Not part of any
publication panel, not `sota-v5` eligible, and not comparable with the chat
lanes on the leaderboard. Read the "What a Jev row measures" section before
quoting a number from it.

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

Expected spend is small. A compact observation plus the question batch is
roughly 6-8k input tokens per decision, so at launch pricing a decision costs
about $0.0003, a five-season seed (20 decisions) about $0.006, and a 29-seed
panel under $0.20. The harness prices Jev usage from `gm_bench/pricing.json`
(`jev` prefix); the API returns token counts, not cost.

## Running it

```bash
GM_BENCH_WORKERS=1 python3 -m gm_bench model --config examples/typesafe.jev.smoke.json
# or
GM_BENCH_WORKERS=1 python3 -m gm_bench model --provider typesafe --model jev-latest \
  --preset smoke --verbose --json --no-log
```

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
| `TYPESAFE_API_KEY` | unset | Required credential |
| `TYPESAFE_MODEL` | `jev-latest` | Model route |
| `TYPESAFE_API_BASE` | `https://api.typesafe.ai` | Endpoint base (recorded in provenance) |
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
   - a signing or extension is priced at the published quote for the chosen
     term (offering the quote always succeeds, so the contract is exactly what
     Jev asked for);
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
   `output_tokens` (always 0), latency, and the response's request id as
   `generation_id`. Unanswered questions are noted in `telemetry_error` and
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
- **Own lane.** `run_info.transport` is `decision-api`. Keep it out of the
  `direct-api` and `gateway-api` tables, and do not put it on the site without
  a lane label; the leaderboard build currently groups anything that is not
  `coding-harness` as `api`.

Score it against the same scripted baselines as any other run and read the
paired lift; the comparison that is meaningful is Jev-plus-scaffold against the
scripted policies, not against the published model rows.
