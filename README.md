# GM-Bench MVP

GM-Bench is a small, deterministic sports general-manager benchmark inspired by
front-office dynasty games. Agents manage a fictional hockey-style league over
multiple seasons by making roster, trade, free-agency, draft, and lineup
decisions through a JSON-compatible API.

The MVP includes:

- A seeded league simulator with aging, development, injuries, contracts,
  salary-cap pressure, free agency, trades, drafts, playoffs, and team standings.
- Baseline agents: random, conservative, win-now, rebuild, and value-model.
- A scoring model that rewards wins, championships, future assets, prospects,
  and cap health while penalizing illegal or wasteful management.
- A CLI runner for single-agent runs and baseline comparisons.
- An external-process protocol for plugging in LLM agents.

## Quickstart

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
```

Invalid actions are ignored and penalized. Observations intentionally include
noisy public ratings, not hidden true potential, so agents must reason under
uncertainty.

## Evaluation

Use `evaluate` for benchmark-style scoring. It runs the candidate and a baseline
panel on the same seeds, then reports:

- `candidate_mean_score`: the raw objective score.
- `baseline_panel_mean_score`: the mean score of selected scripted baselines.
- `score_lift`: candidate score minus the baseline-panel score.
- `score_lift_pct`: percent lift over the baseline panel.
- illegal action counts.

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

See [docs/benchmark_spec.md](docs/benchmark_spec.md) for the MVP design,
landscape notes, and suggested next steps. See
[docs/scoring_calibration.md](docs/scoring_calibration.md) for how the objective
score is weighted and normalized.
