# GM-Bench Benchmark Spec

## Goal

GM-Bench tests whether an agent can manage a fictional sports franchise across
multi-season episodes. The benchmark is API-first and deterministic by seed, so
agents are evaluated on strategic decisions rather than UI automation.

## Existing Landscape

The closest product inspiration is ZenGM-style sports management, especially
hockey.zengm.com and Basketball GM. Those games demonstrate the shape of the
decision loop: roster building, contracts, drafts, trades, player development,
aging, and playoffs.

I did not find an obvious existing LLM benchmark where agents compete as sports
general managers over long-horizon franchise simulations. Adjacent benchmark
families include web-navigation agents, OS/computer-use agents, sports-control
simulators, prediction-market benchmarks, and fantasy-sports forecasting, but
those do not directly test front-office management.

## Benchmark Scope

The benchmark implements a compact hockey-style league:

- 12 fictional teams.
- 23-player initial rosters.
- Forwards, defense, and goalies.
- Public overall and potential ratings.
- Hidden true potential.
- Salary cap and strategic contract terms. The market and cap both inflate 4%
  per season; each guaranteed year after the first adds 2% to annual salary.
  Both inflate together on purpose: inflating salaries against a flat cap would
  squeeze all twelve teams identically, which is a difficulty knob rather than a
  decision. Inflating both isolates the actual mechanic — a long deal locks
  today's price against tomorrow's cap.
- Free agents with published 1-5 year quotes (free agents age and rust while
  unsigned).
- Free-agent willingness (v6): each free agent prices the signing team through
  one published multiplier, `signing_appeal.quote_multiplier = 1 - 0.08 *
  win_sensitivity * team_win_signal - 0.04 * role_appeal`. `team_win_signal` is
  the team's current record scaled to [-1, 1]; `role_appeal` is +1 when the
  player would crack the team's dressed lineup at his position and -1 when he
  would sit; `win_sensitivity` is 1.0 for veterans (age >= 28) and 0.5 for
  younger players. A contender offering a lineup spot pays up to 12% under the
  market rate; a rebuilder offering a bench seat pays up to 12% over, so
  rebuilding teams must overpay veterans while contenders sign at a discount.
  The multiplier and its components are published per free agent, quotes
  freeze for the length of a decision window, opponents price signings by the
  same rule against their own record and lineup, and incumbent extensions are
  exempt (they stay on the pure market quote that the loyalty-discount
  inequality is balanced against).
- Preseason incumbent extensions for final-year players whose current deal
  predates the season. Quotes use next season's market, a 3% loyalty discount,
  and the same term premium. Same-season sign-and-extend is structurally barred.
  The discount must stay below the term premium it competes against, so that a
  five-year extension still costs more per year than a one-year free-agent deal
  (ratio 1.0895). Otherwise extending is both cheaper and longer, every
  incumbent is extended on sight, and contract length stops being a decision.
- Expiring contracts create real re-sign-or-lose pressure (v6). A final-year
  incumbent publishes `extension_quotes` for exactly one preseason before his
  deal lapses; not extending him there is not a free wait-and-see option. He
  plays out the season, expires to free agency, and — before the user's next
  decision window, which is otherwise the user's first look at every FA pool —
  rival teams get one signing attempt at the best expiring players leaguewide
  (`expiry_scramble_candidates`, currently 6). A star left unextended can be
  gone entirely, not just re-signable next preseason at the same price.
  Scoped to the best expiring players only: a full season's ordinary short-deal
  churn runs into the dozens leaguewide, and scrambling all of it would drown
  the extend-or-lose decision in unrelated noise. Both the eligibility window
  and the scramble rule are published in `rules.contracts`.
- Releases retain 25% of salary as dead cap for at most the next two guaranteed
  seasons. Each roster player publishes the exact by-season and total charge
  before release; the charge applies equally to the user and opponent teams.
- Competitive free agency: opponent front offices sign free agents after
  every phase and deterministically extend valuable expiring incumbents —
  filling roster needs and poaching standout players, waiving their least
  valuable player to make room when full — so the pool is never reserved for
  the user between decision points. At the season boundary, opponents also
  get one scramble pass at the best players who just expired, before the
  user's next preseason (see expiring contracts, above).
- Opponent-initiated trades: at the trade deadline, opponents make
  one-for-one swaps among themselves whenever both sides' hidden valuations
  agree, recorded in the transaction feed.
- Draft classes with noisy projections, drafted competitively: slot order
  comes from a weighted lottery over the non-playoff teams (worst record
  favored, nothing guaranteed), with playoff teams following worst record
  first. Every pick carries its ORIGINAL team's identity and is exercised at
  that team's slot, so a pick acquired by trade is a bet on how the original
  team finishes.
- Trade acceptance based on asset value perturbed by hidden per-partner
  valuation noise (re-rolled each season), a per-partner trade limit per
  season, roster minimums on both sides, and cap constraints.
- Lineups that matter: `set_lineup` picks the 18 players who dress, which
  drives team strength; young players outside the lineup develop at half rate.
- Midseason phase: partial-season games (~35% of the schedule), standings
  updates, random injuries, and a waiver wire with `claim_waiver`.
- Seasons, standings, playoffs, championships, aging, development, and expiring
  contracts.

## Decision Interface

The default episode uses protocol v3 (`gm-bench-v3`). At each season, agents
receive observations for four phases:

- `preseason`
- `midseason` — partial-season standings, injuries, and waiver wire
- `trade_deadline` — opponent trade proposals in `incoming_offers`
- `draft`

### One paid call per phase

Under the v6 execution rules an agent that pays for its calls gets exactly one
per decision phase: five seasons of four phases is twenty calls per seed, and
no more. There is no paid retry — a malformed reply is repaired locally or
recorded as a structured no-op (see "Malformed output and local repair"). A
model cannot buy extra thinking by spending query rounds, and the per-seed cost
of a row is fixed before it starts.

Built-in scripted policies run in-process and make no API calls, so they keep
the multi-round query loop below and their episodes are unchanged. Operators
replaying the pre-v6 model lane can set
`EpisodeConfig(single_paid_call_per_phase=False)`.

### Multi-round windows

Each phase is one decision window that may span up to five interaction rounds
for an agent that makes no paid calls. Round 0 delivers the phase observation;
later rounds include `action_results` from the prior round and an incremented
`interaction_round`. Query actions return same-turn feedback; send `end_turn`
to stop gathering information.

Query actions:

- `inspect_team` — detailed roster/cap for one team
- `inspect_player` — full public card for one player
- `list_free_agents` — filtered free-agent list
- `scout` — spend one of three per-season scouting points for a near-true
  `true_potential` reading (echoed permanently in `scout_reports`)

Control:

- `end_turn` — close the information-gathering loop for this window

Core roster actions (apply immediately):

- `sign_free_agent`
- `extend_contract` (preseason only; 2-5 years, replacing the final contract
  year rather than adding to it)
- `release`
- `trade` (players and/or future draft picks via `give_pick_seasons` /
  `receive_pick_seasons`, up to 3 seasons ahead)
- `draft`
- `set_lineup`
- `claim_waiver` (midseason only)
- `memo`
- `noop`

Trade negotiation (when `incoming_offers` is non-empty):

- `accept_trade_offer` / `reject_trade_offer` / `counter_trade_offer`
- `accept_offer` / `decline_offer` remain accepted aliases

Incoming opponent offers look fair to the sender's hidden valuation, so some
are bargains and some are traps — offers expire each decision point and
ignoring them is free. `counter_trade_offer` rewrites the players/picks and
re-submits as a trade against the same partner.

### Observation tiers

Every observation includes `observation_tier`:

- `full` — complete `free_agents`, `draft_class`, `trade_market`, `waiver_wire`,
  and full roster cards (default for built-in scripted agents).
- `summary` — compact `*_summary` blocks plus a hint to use query actions;
  intended for external LLM agents that should inspect before committing.

The environment seed is runner-internal evaluation metadata, not model input.
It remains available for deterministic replay, pairing, and artifact provenance,
but is removed from compact/scaffold payloads, one-shot adapter stdin,
persistent-session events, and child-process environments. This prevents a
public adapter from reconstructing hidden potentials, reservation prices, or
trade biases from the private evaluation seed.

### The compact render models read

Scripted agents read the observation the simulator emits. Model adapters read
one compact render of it, built by `gm_bench/scaffold_view.py` and shared by
every adapter, so no model gets a private view. It exists to hold the whole
prompt inside the v6 budget — target ~6,500 tokens, hard ceiling 8,000 — which
the previous JSON view exceeded at roughly 11,600.

- Rosters, standings, free agents, prospects, the trade market, the waiver
  wire, incoming offers, season results, and the transaction ledger are
  pipe-delimited rows. Each table ships a `*_columns` line whose column names
  are the observation fields the values came from.
- Candidate lists are cut to the v6 budget: 26 roster players by overall, 10
  free agents, 8 prospects, and 6 trade listings by public asset value, 3
  incoming offers, 4 waiver players. The rule is the same for every agent and
  every list states how many of how many it is showing.
- The ledger carries accepted roster-changing moves from the current season and
  the one before it — up to 24 of the agent's own, plus a shorter rival tail —
  alongside one line per completed season.
- Echoed query answers in `action_results` are capped at a fixed number of rows
  and say when they were cut, so a batch of information actions cannot inflate
  the prompt past the ceiling.
- The rules block keeps the simulator's own descriptions of the center bonus,
  free-agent willingness, and extension expiry verbatim; only the numbers
  around them are flattened.

`compact_observation` renders those rows; `scaffold_view_observation` returns
the same selection as Python objects for the `scaffold-view` diagnostic. Both
come from one selection function, so neither shape can carry information the
other lacks.

### Persistent sessions

By default external agents are launched fresh at each decision point, so the
`memo` action is the only cross-decision memory channel — it is what makes
multi-season plan coherence observable rather than assumed.

Optional persistent sessions keep one subprocess alive for the entire episode.
The runner sends line-delimited JSON events (`start`, `observation`,
`action_results`, `end`); session-capable adapters set `GM_BENCH_SESSION=1` and
respond with actions after each event. This preserves in-process state across
rounds and phases while still reporting usage for every interaction round.

`python -m gm_bench model --session` runs a built-in provider in this mode as
an explicit **in-context condition**: the OpenAI-compatible adapter accumulates
the episode conversation (each observation and the model's reply) so the model
retains its full trajectory in context instead of externalizing plans through
`memo`. Session rows record `run_info.session: true`, are labeled on the
leaderboard, and are not `sota-v2` eligible — the frozen contract lane is
fresh-spawn/memo-only, and the delta between the two conditions is itself a
measurement: what explicit memory management costs a model versus free
continuity.

Actions are validated by the simulator. Invalid actions are ignored and counted
as penalties. Legal-but-declined offers are different: a trade rejected as too
light or a free-agent offer below the player's hidden reservation price is
counted separately as a `rejected_offer` with no protocol penalty, because
probing hidden valuations is legitimate negotiation, not a protocol failure.
After `rejected_offer_limit_per_window` declines in one decision window, the
counterparty breaks off talks until the next window, so unpenalized probing
cannot binary-search the hidden values.

Free agents accept salaries down to a hidden per-player reservation fraction
of the published term quote (uniform in `fa_reservation_range`, re-rolled each
season, seeded from stable keys like trade valuation bias). Offering the full
quote always succeeds; shading below it saves cap space but risks a decline.
The observation publishes `contract_quotes` on free agents,
`extension_quotes` on eligible incumbents, each roster player's exact
`release_dead_cap`, and the releasing team's season-keyed `team.dead_cap`.

Future draft picks are scored assets (discounted per season of distance, at
the same scale the trade market prices them) and every team is scored over the
same league-wide pick horizon, so pick churn cannot mint score.

### Adapter stdout protocol and usage telemetry

External adapters may print either of two shapes to stdout:

- A bare JSON action list (`[...]`) — the original protocol, still accepted so
  third-party adapters keep working.
- An envelope `{"actions": [...], "usage": {...}}` that also reports model
  usage for the decision.

Recognized `usage` keys (all optional; unknown keys are dropped):
`provider`, `model`, `api_calls`, `input_tokens`, `output_tokens`,
`total_tokens`, `api_latency_ms`, and `cost_usd` (adapter-reported cost, which
takes precedence over the pricing-table estimate). Adapters report only what
their backend actually returned — a missing token count means "unmeasured",
never zero.

The runner independently times every decision (`harness_latency_ms`), so the
gap between harness latency and adapter-reported `api_latency_ms` exposes
process-spawn/CLI overhead. Per-episode results carry an aggregated `usage`
block (tokens, api calls, latency, cost) plus the per-decision records; run
summaries and `evaluate` output aggregate it further. Costs are computed from
`gm_bench/pricing.json` (USD per million tokens, longest-prefix model match,
provider defaults such as `ollama` = $0). Unknown models yield
`cost_usd: null` rather than a guessed price; `GM_BENCH_PRICING=<path>` merges
a local override table. Episode usage is also logged to SQLite
(`episodes.total_tokens`, `episodes.cost_usd`, `episodes.usage_json`).

At the start of the draft phase the season's lottery is drawn once from the
seeded RNG: the non-playoff teams are drawn without replacement into the top
slots (the team ranked `i` from the bottom of a group of `n` carries weight
`n - i`, so with four lottery teams the first-slot odds are 40/30/20/10), and
playoff teams follow in inverse-standings order. Opponents holding slots ahead
of the user's earliest owned slot pick before the user's decision and the rest
pick after it, so the visible draft class at the user's turn already reflects
earlier selections. Each pick is exercised at its original team's slot by
whoever owns it now; the observation shows the rule, the drawn (or projected)
slot order in `draft_lottery`, and every owned pick's origin and projected
slot in `team.picks`. Trading a season's pick when several are held transfers
the one whose original team currently has the most wins — the giver keeps the
best-projected pick. Every team's own pick is replenished each season, so
episodes of any length keep a draft.

## Built-In Agents

The benchmark includes ten scripted references and diagnostics (`gm_bench.agents.AGENTS`):

- `random`: noisy but valid roster moves.
- `conservative`: value signings and best public prospects.
- `win-now`: prioritizes current overall and immediate wins.
- `rebuild`: prioritizes youth and potential.
- `value`: balances public overall, potential, age, and price.
- `shrewd`: a stronger-on-average honest reference — `value` plus retaining
  valuable young incumbents, releasing a contract only when the cap it frees
  net of the published dead-cap charge exceeds what the player still provides,
  and dressing high-upside youth. That release test is rare in practice (7
  releases across 120 team-seasons): dead cap deters, and paying it anyway is a
  deliberate choice. It fires at all only since #91 — the previous rule
  required a conjunction of conditions that never co-occurred, so it had never
  released anyone despite the description claiming otherwise.
- `strategic`: `shrewd` plus report-driven scouting, selective incoming-offer
  responses, and a persistent plan memo.
- `pick-trader`: `strategic` plus cap-aware sales of aging short-term contracts
  for future picks, avoiding dead cap. It is the pre-registered bar the
  `validate-contract` invariant is stated against, but it is no longer the
  highest-scoring reference: with releases priced and incumbents retainable,
  cap hygiene and retention now compete with pick accumulation, and the top
  four references sit within 10 points of each other against per-seed standard
  deviations near 50. Their relative order is not established and is not
  pinned.
- `scaffold-view`: the `pick-trader` policy restricted to the compacted payload
  model adapters receive — the same sorted-and-truncated free agents, draft
  prospects, trade-market slice, and incoming offers, plus the host-computed
  legal lineup the prompt injects. It is a diagnostic for the observation
  asymmetry between scripted and model agents, not part of the official
  baseline panel. The gap it measures is profile-specific, and the agent is
  pinned to the `compact` profile rather than inheriting `GM_AGENT_PROFILE`:
  it runs in the harness process, where that variable reflects the operator's
  shell rather than the lane the model ran under, so inheriting it would let an
  ambient value silently decide which view was measured — and the cached
  episode would carry no trace of which one produced it. To difference against
  a `tiny`-profile row, instantiate `ScaffoldViewAgent("tiny")` explicitly.
  On seeds 11–18 at five seasons it measured a +2.8 point paired gap versus
  `pick-trader` (paired *t* = 0.249; six seeds tied). The same-view diagnostic
  therefore does not explain the much larger historical model-to-reference
  gaps. It remains supporting evidence rather than a headline model result.
- `exploit`: a red-team canary that replays historically degenerate strategies
  (trade value-pumping, free-agent hoarding). A regression test pins it below
  `value`; if a rules change re-opens an exploit, the canary jumps and CI fails.

## Scoring

The objective score rewards:

- Recent wins.
- Playoff rounds.
- Championships.
- Total roster asset value.
- Young-player asset value.
- Cap flexibility, net of retained dead-cap charges.
- Current team strength.
- Roster depth.

The composite is deliberately biased toward sustainable asset accumulation
rather than win-now mortgaging. Wins and playoff rounds are counted only over
the trailing three seasons, while roster asset value, young-player value,
future picks, and cap room are read from end-of-episode state: trading youth
and picks for one strong year is credited once in the win terms and charged
against the stock terms for every season that follows. Championships are the
one permanent win reward, so genuine title contention still pays.

Illegal actions are penalized, but reported separately: every result carries a
`strategy_score` (roster management quality) and a `protocol_penalty`
(invalid-action cost), with `final_score = strategy_score - protocol_penalty`.
This keeps strategy skill from being conflated with JSON discipline when
comparing model-backed agents. The benchmark also supports normalized scoring
against a baseline panel on identical seeds:

```text
score_lift = candidate_mean_score - baseline_panel_mean_score
```

Results also attribute decisions: every episode reports `decisions` and
`failed_decisions`, counting the decision windows answered by an adapter's
fallback policy (actions tagged `model_error` by the example adapters, or
`error` by the external-process runner) instead of the model. A fallback is not
itself penalized — the score scale is unchanged — but the
`decision_failure_rate` in summaries and `evaluate` output shows how much of a
model-backed score the model actually earned, which matters most for small
local models with high parse-failure rates. Under the strict publication
default described below, a failed decision also stops contributing any roster
movement.

Because every agent plays the same seeds, `evaluate` additionally differences the
candidate against the baselines per seed and reports a deterministic bootstrap
95% confidence interval on that paired lift, a per-seed win rate, an exact
two-sided sign-flip permutation p-value (`sign_flip_p_value`), and the paired
lift against the strongest single baseline. Paired differencing cancels most of
the league-generation luck, which is what makes small-seed runs trustworthy.
The permutation test is exact at benchmark-sized panels, where the bootstrap
interval is coarse: with `n` seeds the smallest achievable p is `2 / 2^n`, so a
3-seed run can never look more certain than p=0.25.

The simulator is deterministic, but model-backed agents are not: one episode
per seed confounds model skill with sampling luck. `--repeats N` runs the
candidate N times per seed (baselines stay at one run — they are
deterministic). Paired statistics then use the per-seed mean across repeats,
and summaries report `within_seed_score_stddev` — the model's own run-to-run
noise — next to the across-seed `score_stddev`, so score differences between
models can be checked against both variance sources.

From `sota-v3` on, each episode row also persists a `score_components` block:
the nine raw end-of-episode metrics, the protocol penalty, and the nine
weighted contributions, each rounded to six decimals. It makes the composite
auditable term by term and lets a published row be re-weighted without a
re-run. `sota-v3` validation requires the block and checks that its
contributions still sum to the row's `strategy_score`; `sota-v2` and the v1
archive predate the field and validate without it.

See [scoring_calibration.md](scoring_calibration.md) for term definitions and
weight rationale.

## Adapter Reliability Metrics

Model-backed adapters mark substituted output: fallback actions carry a
`model_error` key and runner-level failures (timeout, crash, invalid JSON)
carry an `error` key. The episode loop counts any decision containing such a
marker as a failed decision and reports `decisions`, `failed_decisions`,
`decision_failure_rate`, and `memo_writes` alongside the score, plus
per-episode decision wall-time latency. This keeps the benchmark honest: a
model that never produces usable output is visibly failing rather than
silently scoring like the fallback policy.

### Malformed output and local repair

Because v6 buys no second call, the harness repairs malformed output itself,
for free, and only where the intent is unambiguous. The rules are fixed and
published in `gm_bench/repair.py`:

| Rule | Repaired | Left alone |
|---|---|---|
| `strip_code_fence` | exactly one Markdown fence around the payload | two or more fenced blocks |
| `strip_surrounding_prose` | one balanced JSON value inside chatter | a second bracketed value after it |
| `strip_trailing_comma` | a comma directly before `]` or `}` | a *missing* comma between items |
| `wrap_single_action` | a lone action object where a list was required | an object with no `type` |
| `normalize_action_type` | a spelling that case-folds onto exactly one canonical type (`"SET-LINEUP"`) | a near-miss that matches nothing (`"sign"`) |
| `coerce_numeric_string` | a plain decimal literal in a numeric field (`"player_id": "42"`) | anything else (`"42nd"`, `"1e3"`) |

Repair never changes which actions were requested, only how they were spelled,
so it cannot lift a score. Whatever the rules cannot settle becomes a
structured no-op for the whole phase.

Every episode reports `malformed_decisions` and `unrecoverable_decisions` (the
subset repair could not save), and every run summary adds `malformed_rate` and
`unrecoverable_rate`. These sit beside the score and are never folded into it:
a model that formats badly should read as visibly unreliable, not as quietly
worse at hockey. A transport failure (timeout, crashed adapter) carries `error`
alone and is counted as a failed decision but not as malformed output — it says
nothing about the model's formatting.

### Output budget and reasoning

The output ceiling is 4,096 tokens including reasoning tokens, pinned per
provider in `gm_bench/providers.py` and recorded in
`run_info.provider_options`. Reasoning is disabled where the route allows it;
models that cannot turn it off run at their minimum effort, set per model in
the panel config. Reasoning tokens are recorded per call in
`usage.per_decision` and summarized as `mean_reasoning_tokens_per_decision`.

Failure handling is itself a measurement condition, so the harness resolves it
rather than inheriting it from the operator's shell, and records the effective
value as `run_info.strict_fallback` plus `provider_options.GM_AGENT_STRICT`.
From `sota-v3` on, publication lanes default to strict — the fallback is a pure
noop, and no roster movement is ever credited to a model that produced nothing.
`--no-strict-fallback` keeps the soft policy; such a row is recorded as
non-strict and is ineligible for `sota-v3`. The frozen `sota-v1`/`sota-v2` rows
predate the flag and were measured under the soft fallback.

## Reproducibility

The simulator is deterministic for a given seed, agent, and season count. Public
observations do not expose hidden `true_potential`, so agents must handle noisy
information rather than optimize directly against ground truth. Trade
acceptance uses hidden per-partner valuation noise seeded from stable keys
(`seed:season:partner:player`), so it is deterministic across identical runs
while remaining uncomputable from the observation alone — agents can estimate
whether an offer will land, but cannot solve for it.

## Commands

```bash
python -m gm_bench describe --seed 42
python -m gm_bench run --agent value --seeds 1 2 3 --seasons 5
python -m gm_bench compare --agents random conservative win-now rebuild value --seeds 1 2 3 --seasons 5
python -m gm_bench evaluate --agent value --seeds 1 2 3 4 5 --seasons 5
python -m gm_bench run --agent-cmd "python examples/external_agent.py" --seeds 1 --seasons 3
python -m gm_bench run --agent-cmd "python examples/ollama_agent.py" --agent-timeout 240 --seeds 1 --seasons 1 --json
LLM_API_KEY=... LLM_MODEL=gpt-4.1-mini python -m gm_bench evaluate --agent-cmd "python examples/openai_compatible_agent.py" --agent-timeout 120 --seeds 1 2 3 --seasons 3
OPENCODE_MODEL=opencode/deepseek-v4-flash-free python -m gm_bench run --agent-cmd "python examples/opencode_agent.py" --agent-timeout 240 --seeds 1 --seasons 1
CODEX_MODEL=gpt-5-mini python -m gm_bench run --agent-cmd "python examples/codex_agent.py" --agent-timeout 180 --seeds 1 --seasons 1
CODEX_OSS=1 CODEX_LOCAL_PROVIDER=ollama CODEX_MODEL=gemma4:e4b python -m gm_bench run --agent-cmd "python examples/codex_agent.py" --agent-timeout 240 --seeds 1 --seasons 1
CLAUDE_MODEL=sonnet python -m gm_bench run --agent-cmd "python examples/claude_agent.py" --agent-timeout 180 --seeds 1 --seasons 1
```

The Ollama adapter defaults to a tiny prompt profile because local models are
much more sensitive to long roster/draft observations. API-backed models can use
`GM_AGENT_PROFILE=compact` for a richer observation. It also defaults to
disabling Ollama thinking mode; set `OLLAMA_THINK=1` when you explicitly want a
local model to reason before producing actions.

Codex CLI and Claude Code are treated like any other external process. The
benchmark sends them one JSON observation per decision point and accepts only
typed GM action objects in response. Codex can be run against local Ollama via
OSS mode; Claude Code and provider-backed Codex/opencode runs may call external
model services.

## Official Leaderboard Runs

The `leaderboard` preset (8 seeds × 5 seasons, full baseline panel) is the
official configuration for published results. Its public seed panel (11-18)
deliberately avoids the dev seeds (1-5) used across docs and examples; setting
`GM_BENCH_PRIVATE_SEEDS` (e.g. `"101,102,110-115"`) replaces the panel with a
held-out one that is never committed, guarding against seed overfitting.

## Next Steps

- Add a multi-agent arena mode where agents negotiate with each other.
- Add sport variants with different roster and cap constraints.

Introduced in v2 and retained in the default v5 episode:

- Four-phase seasons with midseason injuries and waiver wire
- Multi-round decision windows with query actions, `end_turn`, and
  `action_results`
- Trade negotiation: `accept_trade_offer`, `reject_trade_offer`,
  `counter_trade_offer` (plus legacy `accept_offer` / `decline_offer` aliases)
- Draft-pick trades on `trade` actions
- Tiered observations (`full` / `summary`)
- Persistent agent subprocess sessions (`GM_BENCH_SESSION=1`)
- Private evaluation seeds, leaderboard package, contract fingerprint, and
  versioned official-result validation. Current development uses `sota-v5`;
  `sota-v4`, `sota-v3`, and `sota-v2` remain available for frozen historical evidence (see
  [production_benchmark.md](production_benchmark.md)).
