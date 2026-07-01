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
- Free agents with asking prices.
- Draft classes with noisy projections.
- Simple trade acceptance based on hidden asset value and cap constraints.
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
- `noop`

Actions are validated by the simulator. Invalid actions are ignored and counted
as penalties.

## Built-In Agents

The MVP includes five scripted baselines:

- `random`: noisy but valid roster moves.
- `conservative`: value signings and best public prospects.
- `win-now`: prioritizes current overall and immediate wins.
- `rebuild`: prioritizes youth and potential.
- `value`: balances public overall, potential, age, and price.

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

It penalizes illegal actions. The benchmark also supports normalized scoring
against a baseline panel on identical seeds:

```text
score_lift = candidate_mean_score - baseline_panel_mean_score
```

Because every agent plays the same seeds, `evaluate` additionally differences the
candidate against the baselines per seed and reports a deterministic bootstrap
95% confidence interval on that paired lift, a per-seed win rate, and the paired
lift against the strongest single baseline. Paired differencing cancels most of
the league-generation luck, which is what makes small-seed runs trustworthy.

## Reproducibility

The simulator is deterministic for a given seed, agent, and season count. Public
observations do not expose hidden `true_potential`, so agents must handle noisy
information rather than optimize directly against ground truth.

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
`GM_AGENT_PROFILE=compact` for a richer observation.

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
