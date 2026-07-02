# GM-Bench MVP

GM-Bench is a small, deterministic sports general-manager benchmark inspired by
front-office dynasty games. Agents manage a fictional hockey-style league over
multiple seasons by making roster, trade, free-agency, draft, and lineup
decisions through a JSON-compatible API.

The MVP includes:

- A seeded league simulator with aging, development, injuries, contracts,
  salary-cap pressure, free agency, trades, drafts, playoffs, and team standings.
- Lineups that matter: the players you dress set team strength, and only
  dressed young players develop at full speed.
- A competitive draft: opponents pick in inverse-standings order, so top
  prospects are gone before a strong team's turn.
- Competitive free agency: opponent front offices act after every phase, fill
  roster needs, and grab standout free agents (waiving their weakest player
  to make room), so waiting on a signing carries real risk.
- A realistic trade market: partners privately re-value players each season,
  accept a limited number of trades, and rosters cannot be stripped below the
  league minimum. At the trade deadline, opponents also make one-for-one
  trades among themselves, visible in the transaction feed.
- Baseline agents: random, conservative, win-now, rebuild, value, and a
  red-team `exploit` canary that replays known-degenerate strategies.
- A scoring model that rewards wins, championships, future assets, prospects,
  and cap health, reported as a strategy score with protocol (invalid-action)
  penalties broken out separately.
- A CLI runner for single-agent runs and baseline comparisons.
- An external-process protocol for plugging in LLM agents, including a
  persistent `memo` scratchpad for carrying multi-season plans between
  decision points.

## Protocol v2 (gm-bench-v2)

GM-Bench v2 expands how agents interact with the environment:

- **4 phases per season**: `preseason`, `midseason` (partial games, injuries, waiver wire), `trade_deadline`, `draft`
- **Tiered observations**: summary by default for external agents; use query actions for detail
- **Query actions**: `inspect_team`, `inspect_player`, `list_free_agents`, `scout` (reveals true-potential band)
- **Trade negotiation**: incoming opponent offers with `accept_trade_offer`, `reject_trade_offer`, `counter_trade_offer`
- **Draft-pick trades**: `give_pick_seasons` / `receive_pick_seasons` on `trade` actions
- **Same-turn feedback**: multi-round decisions return `action_results` until `end_turn`
- **Persistent sessions**: `--persistent-session` keeps one subprocess alive per episode
- **Strict mode**: `--strict` disables heuristic fallback actions for model evaluation
- **Morale & injuries**: morale affects performance; midseason injuries reduce effective overall

```bash
python -m gm_bench run --agent-cmd "python examples/openai_compatible_agent.py" \
  --observation-tier summary --persistent-session --strict \
  --seeds 1 --seasons 1
```


```bash
python -m gm_bench run --agent value --seeds 1 2 3 --seasons 5
python -m gm_bench compare --agents random conservative win-now rebuild value --seeds 1 2 3 --seasons 5
python -m gm_bench evaluate --agent value --seeds 1 2 3 4 5 --seasons 5
python -m gm_bench describe --seed 42
python -m gm_bench gui
```

## Local GUI

Start the browser GUI:

```bash
python -m gm_bench gui --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

The GUI can:

- Run built-in agents in `run`, `compare`, and `evaluate` modes.
- Automatically log those runs into the SQLite database.
- Show KPI totals for runs, episodes, best score, mean score, and rejected-action rate.
- Explain the latest run with candidate-vs-baseline lift, score, wins, titles, and illegal-action totals.
- Compare aggregate agent standings by mean score, best score, score range, wins, titles, and legality.
- Browse score history, the episode leaderboard, recent runs, and transaction audit feed.

The GUI intentionally does not launch external model-backed agents yet; use the
CLI for Codex, Claude, opencode, Ollama, and API-backed agents where cost and
provider behavior should be explicit.

## Public Web Site

A forward-facing landing site (Vite + React + TypeScript, managed with Bun)
lives in [`web/`](web/README.md). It renders reference baseline results,
the decision-loop and protocol overview, and a quickstart from a committed
snapshot of real benchmark output, and builds to a fully static bundle:

```bash
cd web
bun install
bun dev        # local development
bun run build  # static production build in web/dist/
```

## External Agent Protocol

External agents are launched once per decision point. The runner writes an
observation JSON object to stdin and expects a JSON array of actions on stdout.

```bash
python -m gm_bench run --agent-cmd "python examples/external_agent.py" --seeds 1 --seasons 3
```

Each action is an object:

```json
{"type": "sign_free_agent", "player_id": 123, "years": 2, "salary": 4.2}
{"type": "trade", "partner_team_id": 3, "give_player_ids": [11], "receive_player_ids": [87]}
{"type": "draft", "prospect_id": 9001}
{"type": "set_lineup", "player_ids": [1, 2, 3, 4, 5, 6]}
{"type": "memo", "text": "rebuild through season 3, then spend cap room"}
```

Invalid actions are ignored and penalized. Observations intentionally include
noisy public ratings, not hidden true potential, so agents must reason under
uncertainty. Trade acceptance additionally uses hidden per-partner valuation
noise (re-rolled each season), so offers can only be estimated, not solved.

Key mechanics agents should know:

- `set_lineup` chooses the 18 players who actually dress. It drives team
  strength directly, and players outside the lineup develop at half speed.
  Stale lineups (after trades or expiring contracts) are repaired
  automatically at simulation time.
- Each opponent accepts at most `trade_limit_per_partner` trades per season,
  and no trade may shrink a roster below `roster_min`.
- Opponents draft in inverse-standings order around your slot, so the draft
  class you see at your pick already reflects earlier selections.
- Opponent front offices act after every phase: they sign free agents (both
  to fill needs and to poach clear upgrades) and swap players among
  themselves at the trade deadline. A free agent visible now may be gone at
  the next decision point, and opponent trades appear in
  `recent_transactions` as market signal.
- `memo` stores up to 2000 characters that are echoed back in every future
  observation — the only state that persists across decision points for
  stateless external agents. `text` must be a JSON string; a null or missing
  `text` (allowed by the structured-output wrapper schema, where every field
  is nullable) is rejected as an invalid action.

JSON Schema definitions for the protocol live in `schemas/`:

- `gm_observation.schema.json` — observation sent to agents
- `gm_action_list.schema.json` — action array on stdout
- `gm_actions.schema.json` — structured wrapper for Codex/Claude adapters

## Evaluation

Use `evaluate` for benchmark-style scoring. It runs the candidate and a baseline
panel on the same seeds, then reports:

- `candidate_mean_score`: the raw objective score.
- `candidate_mean_strategy_score` / `candidate_protocol_penalty`: the score
  split into roster-management quality and invalid-action penalties, so
  strategy skill is not conflated with JSON discipline.
- `baseline_panel_mean_score`: the mean score of selected scripted baselines.
- `score_lift`: candidate score minus the baseline-panel score.
- `score_lift_pct`: percent lift over the baseline panel.
- illegal action counts.

Because every agent plays identical seeds, the report also includes a `paired`
block that differences the candidate against the baselines *per seed*. On a
handful of seeds this cancels most of the league-generation luck and gives a
far lower-variance read on skill than comparing unpaired means:

- `per_seed`: candidate score, baseline-panel score, and lift for each seed.
- `paired_lift_mean`: mean of the per-seed lifts (equals `score_lift`, but with
  a variance you can now quantify).
- `paired_lift_ci95`: a deterministic bootstrap 95% confidence interval on the
  paired lift.
- `significant_at_95`: whether that interval excludes zero.
- `candidate_seed_win_rate`: fraction of seeds where the candidate beat the panel.
- `best_baseline`: the strongest single baseline (by mean score) with the
  candidate's paired lift and seed win rate against it — an honest bar to clear,
  since the panel average is dragged down by weak baselines like `random`.

This keeps league-seed luck from dominating a small benchmark run.

## Run Database

`run`, `compare`, and `evaluate` automatically log to SQLite at:

```text
data/gm_bench.sqlite
```

Override the path:

```bash
GM_BENCH_DB=/tmp/gm-bench.sqlite python -m gm_bench run --agent value --seeds 1 --seasons 1
```

Disable logging:

```bash
python -m gm_bench run --agent value --seeds 1 --seasons 1 --no-log
```

Useful queries:

```bash
sqlite3 data/gm_bench.sqlite 'select created_at, command, agent, summary_json from runs order by created_at desc;'
sqlite3 data/gm_bench.sqlite 'select agent, seed, final_score, wins, championships, illegal_actions from episodes order by final_score desc;'
sqlite3 data/gm_bench.sqlite 'select phase, accepted, message, action_json from transactions where accepted = 0;'
```

## Running Model-Backed Agents

### Local Ollama

The Ollama adapter reads the benchmark observation from stdin, prompts a local
model, parses JSON actions, and falls back to legal value-style moves if parsing
fails.

Installed local models can be checked with:

```bash
ollama list
```

Example:

```bash
python -m gm_bench run \
  --agent-cmd "python examples/ollama_agent.py" \
  --agent-timeout 240 \
  --seeds 1 \
  --seasons 1 \
  --json
```

Choose a model explicitly:

```bash
OLLAMA_MODEL=gemma4:e4b python -m gm_bench run \
  --agent-cmd "python examples/ollama_agent.py" \
  --agent-timeout 240 \
  --seeds 1 \
  --seasons 1
```

Useful knobs:

- `OLLAMA_MODEL`: local model name. In this workspace, `gemma4:e4b` and
  `qwen3.5:latest` were installed.
- `GM_AGENT_PROFILE=tiny|compact`: smaller prompts are better for local models.
  The Ollama adapter defaults to `tiny`.
- `OLLAMA_TRANSPORT=cli|http`: defaults to `cli`; `http` uses the Ollama REST
  API.

### OpenAI-Compatible APIs

Use the generic chat-completions adapter:

```bash
LLM_API_KEY=... \
LLM_MODEL=gpt-4.1-mini \
python -m gm_bench evaluate \
  --agent-cmd "python examples/openai_compatible_agent.py" \
  --agent-timeout 120 \
  --baselines random conservative win-now rebuild \
  --seeds 1 2 3 \
  --seasons 3
```

For non-OpenAI-compatible providers, set:

```bash
LLM_API_BASE=https://provider.example/v1
LLM_API_KEY=...
LLM_MODEL=provider-model-name
```

### opencode

The opencode adapter uses `opencode run` and whatever provider/model opencode is
configured to use:

```bash
OPENCODE_MODEL=opencode/deepseek-v4-flash-free python -m gm_bench run \
  --agent-cmd "python examples/opencode_agent.py" \
  --agent-timeout 240 \
  --seeds 1 \
  --seasons 1 \
  --json
```

In this workspace, `opencode models` reported:

- `opencode/big-pickle`
- `opencode/deepseek-v4-flash-free`
- `opencode/mimo-v2.5-free`
- `opencode/nemotron-3-ultra-free`
- `opencode/north-mini-code-free`

Note: opencode-backed runs may send benchmark observations/prompts to an
external model provider, depending on your opencode configuration.

### Codex CLI

The Codex adapter uses `codex exec` with a read-only sandbox, no approvals,
ephemeral sessions, and the shared GM action JSON schema:

```bash
python -m gm_bench run \
  --agent-cmd "python examples/codex_agent.py" \
  --agent-timeout 180 \
  --seeds 1 \
  --seasons 1 \
  --json
```

Pick a Codex model:

```bash
CODEX_MODEL=gpt-5-mini python -m gm_bench evaluate \
  --agent-cmd "python examples/codex_agent.py" \
  --agent-timeout 180 \
  --baselines random conservative win-now rebuild \
  --seeds 1 2 3 \
  --seasons 3
```

Use Codex in local Ollama/OSS mode:

```bash
CODEX_OSS=1 CODEX_LOCAL_PROVIDER=ollama CODEX_MODEL=gemma4:e4b python -m gm_bench run \
  --agent-cmd "python examples/codex_agent.py" \
  --agent-timeout 240 \
  --seeds 1 \
  --seasons 1
```

### Claude Code

The Claude adapter uses `claude -p` with no tools, no session persistence, and
the shared GM action JSON schema:

```bash
CLAUDE_MODEL=sonnet python -m gm_bench run \
  --agent-cmd "python examples/claude_agent.py" \
  --agent-timeout 180 \
  --seeds 1 \
  --seasons 1 \
  --json
```

For a more controlled spend during early tests:

```bash
CLAUDE_MODEL=sonnet CLAUDE_MAX_BUDGET_USD=0.25 python -m gm_bench evaluate \
  --agent-cmd "python examples/claude_agent.py" \
  --agent-timeout 180 \
  --baselines random conservative win-now rebuild \
  --seeds 1 2 3 \
  --seasons 3
```

Note: Codex cloud/API mode, Claude Code, and opencode-backed runs may send
benchmark observations/prompts to external model providers. Local Codex OSS mode
with Ollama stays local.

## Benchmark Philosophy

This MVP is designed to test long-horizon strategic planning, resource
allocation, numeric reasoning, uncertainty management, and coherent memory over
multi-season episodes. It avoids GUI automation and avoids real player names so
evaluation focuses on decision quality rather than browser-control reliability
or memorized sports data.

Multi-season coherence is testable in practice because external agents are
stateless between decision points: the `memo` action is the only channel for
carrying a plan forward, so agents that form and follow multi-season plans are
distinguishable from agents that re-derive greedy moves each call.

The `exploit` baseline exists to keep the benchmark honest. It replays the
degenerate strategies that used to dominate (trade value-pumping and free-agent
hoarding); a regression test asserts it stays below the honest `value`
baseline, so any rules change that re-opens an exploit fails CI instead of
silently inflating scores.

See [docs/benchmark_spec.md](docs/benchmark_spec.md) for the MVP design,
landscape notes, and suggested next steps. See
[docs/scoring_calibration.md](docs/scoring_calibration.md) for how the objective
score is weighted and normalized.
