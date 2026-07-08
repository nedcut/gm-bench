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
- Baseline agents: random, conservative, win-now, rebuild, value, `shrewd`
  (cap hygiene plus development-aware lineups), and `strategic`, which also
  scouts, evaluates incoming offers, and persists a plan memo. The strongest
  `pick-trader` reference adds cap-aware future-pick acquisitions, while the
  red-team `exploit` canary replays known-degenerate strategies.
- A scoring model that rewards wins, championships, future assets, prospects,
  and cap health, reported as a strategy score with protocol (invalid-action)
  penalties broken out separately.
- A CLI runner for single-agent runs and baseline comparisons.
- An external-process protocol for plugging in LLM agents, including a
  persistent `memo` scratchpad for carrying multi-season plans between
  decision points.
- Protocol v2 (`gm-bench-v2`): four phases per season (including midseason
  injuries and waivers), multi-round decision windows with query actions and
  same-turn `action_results`, trade negotiation (`accept_trade_offer` /
  `reject_trade_offer` / `counter_trade_offer`), tiered observations
  (`full` / `summary`), and optional persistent subprocess sessions per
  episode.

## Leaderboard & Website

Official results use the `leaderboard` preset (8 held-back seeds × 5 seasons,
full baseline panel; `GM_BENCH_PRIVATE_SEEDS` swaps in a private panel). Every
run records usage telemetry — tokens, dollar cost (from `gm_bench/pricing.json`
or adapter-reported cost), and per-decision latency — alongside scores. Results
intended for serious frontier-model comparison should pass the stricter
`sota-v1` validator in [`docs/production_benchmark.md`](docs/production_benchmark.md).
Runs also stamp a seed-panel hash so private held-out panels can be verified
locally (integrity for a known panel, not secrecy). Use `redact-result` before
publishing private-panel artifacts so the seed list is not committed.

```bash
LLM_API_KEY=... python -m gm_bench model --provider openai --model gpt-5.4 \
  --preset leaderboard --repeats 3 --json > results/leaderboard/openai-gpt-5.4.json
python -m gm_bench validate-result results/leaderboard/openai-gpt-5.4.json \
  --policy sota-v1
python -m gm_bench validate-contract
python web/scripts/build_leaderboard.py   # refresh web/src/data/leaderboard.json
cd web && bun install && bun run dev      # local site
```

The site in `web/` deploys to GitHub Pages automatically on pushes to `main`
(`.github/workflows/pages.yml`).

## Quickstart

```bash
python -m gm_bench run --agent value --seeds 1 2 3 --seasons 5
python -m gm_bench compare --agents random conservative win-now rebuild value --seeds 1 2 3 --seasons 5
python -m gm_bench evaluate --agent value --seeds 1 2 3 4 5 --seasons 5
python -m gm_bench describe --seed 42
python -m gm_bench gui
```

## Model Benchmarking (Recommended)

The fastest way to score an LLM with objective simulator metrics is the `model`
command. It wires a built-in provider adapter, runs the candidate on your seed
panel, and compares against scripted baselines with paired lift statistics.

```bash
# Quick smoke test (1 seed, 1 season, 4 LLM calls)
LLM_API_KEY=... python -m gm_bench model \
  --provider openai \
  --model gpt-4.1-mini \
  --preset smoke

# Standard panel (3 seeds, 3 seasons)
python -m gm_bench model \
  --provider openai \
  --model gpt-4.1-mini \
  --preset standard \
  --json

# Local Ollama
python -m gm_bench model \
  --provider ollama \
  --model gemma4:e4b \
  --preset smoke \
  --profile tiny
```

Reproducible JSON configs live in `examples/` (the config supplies the provider,
so no extra flags are needed):

```bash
LLM_API_KEY=... python -m gm_bench model --config examples/benchmark.smoke.json
```

List supported providers:

```bash
python -m gm_bench providers
```

Precompute baseline scores so repeated model runs skip re-simulating scripted
agents:

```bash
python -m gm_bench cache-baselines --preset benchmark
```

Cached baseline episodes are keyed by a fingerprint of the simulator, scoring,
and agent source files, so any change to the simulation automatically
invalidates the cache — stale baselines can never bias lift statistics. Pass
`--no-baseline-cache` to force fresh baseline runs, or set
`GM_BENCH_BASELINE_CACHE=/path/to/cache.json` to relocate the cache file.

Presets:

| Preset | Seeds | Seasons | LLM calls per seed | Total LLM calls |
|--------|-------|---------|--------------------|-----------------|
| `smoke` | 1 | 1 | 4 | 4 |
| `standard` | 3 | 3 | 12 | 36 |
| `benchmark` | 5 | 5 | 20 | 100 |

Every preset pins the `compact` observation profile so scores from the same
preset are comparable across providers (provider defaults otherwise differ —
Ollama would see a `tiny` observation while OpenAI sees `compact`, which are
different questions). Pass `--profile tiny` explicitly for local models that
need the smaller observation, and treat those scores as their own track.

Result payloads from `run`, `evaluate`, and `model` include a `run_info`
provenance block recording the resolved provider, model, observation profile,
timeout, preset, benchmark version, and timestamp, so logged runs stay
attributable and comparable after the fact.

Use `--verbose` (or `GM_BENCH_VERBOSE=1`) to print per-decision progress while
model episodes run.

Add `--repeats N` (CLI or `"repeats"` in a config file) to run the candidate N
times per seed. The simulator is deterministic, so repeats isolate the model's
own sampling noise: paired lift statistics use the per-seed mean, and the
summary reports `within_seed_score_stddev` alongside the across-seed
`score_stddev`. `evaluate` also reports an exact sign-flip permutation p-value
on the paired lift (`sign_flip_p_value`), which is more trustworthy than the
bootstrap interval at 3-5 seeds — note the exact floor of `2 / 2^n` means a
3-seed run can never show p below 0.25.

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

The default episode uses protocol v2 (`benchmark: "gm-bench-v2"` in every
observation). Each season has four decision phases:

- `preseason`
- `midseason` — partial-season games, standings update, injuries, and a waiver
  wire (`claim_waiver`)
- `trade_deadline` — opponent trade proposals in `incoming_offers`
- `draft`

By default the runner launches external agents once per decision point: one
observation JSON object on stdin, a JSON action list (or `{"actions": [...],
"usage": {...}}` envelope) on stdout. For a persistent subprocess that stays
alive across the whole episode, use a session-capable adapter with
`GM_BENCH_SESSION=1` (see `examples/gm_agent_common.py`); the runner exchanges
line-delimited `start` / `observation` / `action_results` / `end` events and
records usage and latency for every interaction round.

```bash
python -m gm_bench run --agent-cmd "python examples/external_agent.py" --seeds 1 --seasons 3
python -m gm_bench run --agent-cmd "python examples/openai_compatible_agent.py" \
  --seeds 1 --seasons 1
```

### Multi-round decision windows

Within each phase the agent may take up to five interaction rounds. Query actions
return results in the same window; the runner echoes them as `action_results` on
the next round (with `interaction_round` incremented):

- `inspect_team` — roster and cap detail for one team
- `inspect_player` — full public card for one player
- `list_free_agents` — filtered free-agent list
- `scout` — spend a scouting point for a near-true `true_potential` reading
  (persisted in `scout_reports`)

Send `end_turn` to stop gathering information and close the window. Core roster
moves (`sign_free_agent`, `trade`, `draft`, etc.) apply immediately and also
end the multi-round loop unless followed by more query actions in the same
response. Review `action_results` before repeating failed moves.

### Observation tiers

Observations carry `observation_tier`: `full` (default for built-in scripted
agents) or `summary`. Summary tier replaces long lists with compact
`*_summary` blocks (`free_agents_summary`, `draft_class_summary`,
`waiver_wire_summary`, …) and a hint to use query actions. External agents
receive the tier configured for the run; use inspect/list/scout before
committing when on summary tier.

### Actions

Each action is an object. Core moves:

```json
{"type": "sign_free_agent", "player_id": 123, "years": 2, "salary": 4.2}
{"type": "trade", "partner_team_id": 3, "give_player_ids": [11], "receive_player_ids": [87], "give_pick_seasons": [], "receive_pick_seasons": [4]}
{"type": "draft", "prospect_id": 9001}
{"type": "set_lineup", "player_ids": [1, 2, 3, 4, 5, 6]}
{"type": "claim_waiver", "player_id": 55}
{"type": "memo", "text": "rebuild through season 3, then spend cap room"}
```

Trade negotiation (when `incoming_offers` is non-empty):

```json
{"type": "accept_trade_offer", "offer_id": "offer-3-1-trade_deadline-12-34"}
{"type": "reject_trade_offer", "offer_id": "offer-3-1-trade_deadline-12-34"}
{"type": "counter_trade_offer", "offer_id": "offer-3-1-trade_deadline-12-34", "give_player_ids": [2], "receive_player_ids": [9]}
```

`accept_offer` and `decline_offer` remain accepted aliases. Query and control:

```json
{"type": "inspect_team", "team_id": 3}
{"type": "scout", "player_id": 88}
{"type": "end_turn"}
```

Invalid actions are ignored and penalized. Observations intentionally include
noisy public ratings, not hidden true potential, so agents must reason under
uncertainty. Trade acceptance additionally uses hidden per-partner valuation
noise (re-rolled each season), so offers can only be estimated, not solved.

Rejections come in two kinds, and only one is penalized:

- **Protocol violations** (malformed actions, invented IDs, cap or roster
  violations) count as `illegal_actions` and cost score via
  `protocol_penalty`.
- **Rejected offers** — a trade the partner declines as too light, or a
  free-agent offer below the player's hidden reservation price — are
  legitimate negotiation under hidden information. They are counted and
  reported as `rejected_offers` but cost nothing. To keep free probing from
  solving the hidden values, a counterparty breaks off talks for the rest of
  the decision window after `rejected_offer_limit_per_window` declines.

Free agents accept salaries down to a hidden reservation fraction of their
asking price (uniform within `fa_reservation_range`, re-rolled each season),
so bidding is a real decision: offering the full ask always works, shading
below it saves cap but risks a decline.

Key mechanics agents should know:

- `set_lineup` chooses the 18 players who actually dress. It drives team
  strength directly, and players outside the lineup develop at half speed.
  Stale lineups (after trades or expiring contracts) are repaired
  automatically at simulation time.
- Midseason simulates roughly 35% of the regular season, updates standings
  and player morale, generates injuries, and populates `waiver_wire` with
  players opponents waived. `claim_waiver` is only legal in that phase.
- Each opponent accepts at most `trade_limit_per_partner` trades per season,
  and no trade may shrink a roster below `roster_min`. Opponents may send
  incoming trade offers at the deadline; judge them with public stats before
  accepting — every offer looks fair to the sender's hidden valuation.
- Opponents draft in inverse-standings order around your slot, so the draft
  class you see at your pick already reflects earlier selections.
- Opponent front offices act after every phase: they sign free agents (both
  to fill needs and to poach clear upgrades) and swap players among
  themselves at the trade deadline. A free agent visible now may be gone at
  the next decision point, and opponent trades appear in
  `recent_transactions` as market signal.
- `memo` stores up to 2000 characters that are echoed back in every future
  observation — the only cross-decision memory for stateless one-shot
  agents. Persistent-session adapters can also keep in-process state between
  rounds. `text` must be a JSON string; a null or missing `text` (allowed by
  the structured-output wrapper schema, where every field is nullable) is
  rejected as an invalid action.

### Adapter reliability accounting

When a model-backed adapter cannot use the model's output (timeout, crash,
unparseable JSON, missing API key), it substitutes fallback actions marked
with a `model_error` key (adapter-level failures from the runner carry an
`error` key). The runner counts each such decision as a *failed decision* and
reports `decisions`, `failed_decisions`, `decision_failure_rate`, and
`memo_writes` per episode and in run summaries, plus per-episode
`mean_decision_seconds` / `max_decision_seconds` wall-time latency. A model
that never produces usable output no longer silently scores like the fallback
policy — the failure rate is right next to the score.

By default the fallback still plays a safe turn (best-value draft pick plus a
legal lineup) so one flaky decision doesn't ruin an episode. Set
`GM_AGENT_STRICT=1` to make the fallback a pure `noop`, so the score reflects
only actions the model itself produced.

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
- `OLLAMA_THINK=0|1`: the adapter defaults to disabling Ollama thinking mode so
  thinking-first local models return JSON actions instead of reasoning prose.
  Set `OLLAMA_THINK=1` to opt a model back into thinking.

### OpenAI-Compatible APIs

Use the generic chat-completions adapter directly:

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

Or use the built-in provider shortcut:

```bash
LLM_API_KEY=... python -m gm_bench model --provider openai --model gpt-4.1-mini --preset standard
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
stateless between decision points by default: the `memo` action is the primary
channel for carrying a plan forward, so agents that form and follow multi-season
plans are distinguishable from agents that re-derive greedy moves each call.
Persistent-session adapters can additionally keep in-process memory across
rounds within an episode.

Model-backed scores are also attributed: adapters tag substituted actions
(`model_error`/`error`), and every result reports how many decision points the
model actually played versus how many fell back to the adapter's safety policy
(`fallback_decisions` and `fallback_decision_rate`). This keeps a weak model
from being silently carried by its fallback heuristics.

The `strategic` and `pick-trader` references ensure that scouting, offer
responses, pick trading, and memo persistence are exercised by accepted actions
across the official seed panel; `validate-contract` fails if that coverage or
their clean-play calibration disappears.

The `exploit` baseline exists to keep the benchmark honest. It replays the
degenerate strategies that used to dominate (trade value-pumping and free-agent
hoarding); a regression test asserts it stays below the honest `value`
baseline, so any rules change that re-opens an exploit fails CI instead of
silently inflating scores.

See [docs/benchmark_spec.md](docs/benchmark_spec.md) for the MVP design,
landscape notes, and suggested next steps. See
[docs/scoring_calibration.md](docs/scoring_calibration.md) for how the objective
score is weighted and normalized.
