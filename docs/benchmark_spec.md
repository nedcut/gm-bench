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
- Preseason incumbent extensions for final-year players whose current deal
  predates the season. Quotes use next season's market, a 3% loyalty discount,
  and the same term premium. Same-season sign-and-extend is structurally barred.
  The discount must stay below the term premium it competes against, so that a
  five-year extension still costs more per year than a one-year free-agent deal
  (ratio 1.0895). Otherwise extending is both cheaper and longer, every
  incumbent is extended on sight, and contract length stops being a decision.
- Releases retain 25% of salary as dead cap for at most the next two guaranteed
  seasons. Each roster player publishes the exact by-season and total charge
  before release; the charge applies equally to the user and opponent teams.
- Competitive free agency: opponent front offices sign free agents after
  every phase and deterministically extend valuable expiring incumbents —
  filling roster needs and poaching standout players, waiving their least
  valuable player to make room when full — so the pool is never reserved for
  the user between decision points.
- Opponent-initiated trades: at the trade deadline, opponents make
  one-for-one swaps among themselves whenever both sides' hidden valuations
  agree, recorded in the transaction feed.
- Draft classes with noisy projections, drafted competitively: every team
  picks once per season in inverse-standings order around the user's slot.
- Trade acceptance based on asset value perturbed by hidden per-partner
  valuation noise (re-rolled each season), a per-partner trade limit per
  season, roster minimums on both sides, and cap constraints.
- Lineups that matter: `set_lineup` picks the 18 players who dress, which
  drives team strength; young players outside the lineup develop at half rate.
- Midseason phase: partial-season games (~35% of the schedule), standings and
  morale updates, random injuries, and a waiver wire with `claim_waiver`.
- Seasons, standings, playoffs, championships, aging, development, and expiring
  contracts.

## Decision Interface

The default episode uses protocol v3 (`gm-bench-v3`). At each season, agents
receive observations for four phases:

- `preseason`
- `midseason` — partial-season standings, injuries, and waiver wire
- `trade_deadline` — opponent trade proposals in `incoming_offers`
- `draft`

### Multi-round windows

Each phase is one decision window that may span up to five interaction rounds.
Round 0 delivers the phase observation; later rounds include `action_results`
from the prior round and an incremented `interaction_round`. Query actions
return same-turn feedback; send `end_turn` to stop gathering information.

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

During the draft phase, opponents with worse records pick before the user's
decision and opponents with better records pick after it, so the visible draft
class at the user's turn already reflects earlier selections. Every team's
pick is replenished each season, so episodes of any length keep a draft.

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

Introduced in v2 and retained in the default v3 episode:

- Four-phase seasons with midseason injuries and waiver wire
- Multi-round decision windows with query actions, `end_turn`, and
  `action_results`
- Trade negotiation: `accept_trade_offer`, `reject_trade_offer`,
  `counter_trade_offer` (plus legacy `accept_offer` / `decline_offer` aliases)
- Draft-pick trades on `trade` actions
- Tiered observations (`full` / `summary`)
- Persistent agent subprocess sessions (`GM_BENCH_SESSION=1`)
- Private evaluation seeds, leaderboard package, contract fingerprint, and
  versioned official-result validation. Current development uses `sota-v4`;
  `sota-v3` and `sota-v2` remain available for frozen historical evidence (see
  [production_benchmark.md](production_benchmark.md)).
