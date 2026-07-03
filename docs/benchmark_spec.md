# GM-Bench MVP Spec

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

## MVP Scope

The MVP implements a compact hockey-style league:

- 12 fictional teams.
- 23-player initial rosters.
- Forwards, defense, and goalies.
- Public overall and potential ratings.
- Hidden true potential.
- Salary cap and contract years.
- Free agents with asking prices (free agents age and rust while unsigned).
- Competitive free agency: opponent front offices sign free agents after
  every phase — filling roster needs and poaching standout players, waiving
  their least valuable player to make room when full — so the pool is never
  reserved for the user between decision points.
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
- Seasons, standings, playoffs, championships, aging, development, and expiring
  contracts.

## Decision Interface

At each season, agents receive observations for three phases:

- `preseason`
- `trade_deadline`
- `draft`

Agents return a JSON array of actions:

- `sign_free_agent`
- `release`
- `trade`
- `draft`
- `set_lineup`
- `memo`
- `noop`

Actions are validated by the simulator. Invalid actions are ignored and counted
as penalties.

`memo` stores a persistent scratchpad (up to 2000 characters) echoed back in
every subsequent observation. External agents are launched fresh at each
decision point, so the memo is the only cross-decision memory channel — it is
what makes multi-season plan coherence observable rather than assumed.

During the draft phase, opponents with worse records pick before the user's
decision and opponents with better records pick after it, so the visible draft
class at the user's turn already reflects earlier selections. Every team's
pick is replenished each season, so episodes of any length keep a draft.

## Built-In Agents

The MVP includes six scripted baselines:

- `random`: noisy but valid roster moves.
- `conservative`: value signings and best public prospects.
- `win-now`: prioritizes current overall and immediate wins.
- `rebuild`: prioritizes youth and potential.
- `value`: balances public overall, potential, age, and price.
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
- Cap flexibility.
- Current team strength.
- Roster depth.

Illegal actions are penalized, but reported separately: every result carries a
`strategy_score` (roster management quality) and a `protocol_penalty`
(invalid-action cost), with `final_score = strategy_score - protocol_penalty`.
This keeps strategy skill from being conflated with JSON discipline when
comparing model-backed agents. The benchmark also supports normalized scoring
against a baseline panel on identical seeds:

```text
score_lift = candidate_mean_score - baseline_panel_mean_score
```

Results also attribute decisions: every episode reports `decision_points` and
`fallback_decisions`, counting the decision windows answered by an adapter's
fallback policy (actions tagged `model_error` by the example adapters, or
`error` by the external-process runner) instead of the model. Fallbacks are not
penalized — the score scale is unchanged — but the `fallback_decision_rate` in
summaries and `evaluate` output shows how much of a model-backed score the
model actually earned, which matters most for small local models with high
parse-failure rates.

Because every agent plays the same seeds, `evaluate` additionally differences the
candidate against the baselines per seed and reports a deterministic bootstrap
95% confidence interval on that paired lift, a per-seed win rate, and the paired
lift against the strongest single baseline. Paired differencing cancels most of
the league-generation luck, which is what makes small-seed runs trustworthy.

See [scoring_calibration.md](scoring_calibration.md) for term definitions and
weight rationale.

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

## Next Steps

- Add a richer trade market with draft-pick trades.
- Add private scouting actions that improve noisy projections.
- Add a multi-agent arena mode where agents negotiate with each other.
- Add private evaluation seeds and a leaderboard package.
- Add sport variants with different roster and cap constraints.
- Let opponents propose trades directly to the user, adding a negotiation
  surface on top of the existing opponent-to-opponent deadline trades.
