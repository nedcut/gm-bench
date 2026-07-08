# GM-Bench Results Snapshot

This snapshot records the benchmark results generated during the MVP build.

> **Note (2026-07-08, protocol v2 / contract `cf2607e59dba`):** Midseason,
> multi-round interaction, functional injuries, and the full v1 baseline panel
> (`strategic`, `pick-trader`) are now on `main`. SOTA-v1 claims must use this
> contract fingerprint. Older model rows and pre-v2 leaderboard means are not
> comparable. Re-run model candidates with
> `python -m gm_bench model --preset leaderboard --repeats 3` and validate with
> `--policy sota-v1`. Scripted reference means on the public panel (seeds 11–18,
> 5 seasons): `pick-trader` 411.619, `strategic` 402.025, `shrewd` 371.769,
> `value` 354.619, `win-now` 275.834, `conservative` 139.030, `rebuild` 138.745,
> `random` 96.715. See `docs/scoring_calibration.md` and
> `python -m gm_bench validate-contract` / `calibrate-score --json`.

> **Note (2026-07-04):** Draft-pick trading, opponent-initiated trade offers,
> and scouting landed together with usage/cost telemetry. Scoring now counts
> future picks as assets, shifting every score by a flat +3.748 versus the
> post-validity-fixes numbers below without reordering any baseline. All older
> numbers remain historical records on the previous scale.

## Rules Update Baselines (pick trading + offers + scouting, 2026-07-04)

```bash
python -m gm_bench compare --agents random conservative win-now rebuild value exploit --seeds 1 2 3 --seasons 5 --no-log
```

| Agent | Mean Score | Stddev | Mean Wins | Titles | Illegal |
| --- | ---: | ---: | ---: | ---: | ---: |
| value | 243.85 | 12.16 | 98.67 | 0 | 0 |
| win-now | 201.41 | 18.86 | 98.00 | 2 | 0 |
| rebuild | 99.84 | 23.49 | 50.00 | 1 | 0 |
| conservative | 78.27 | 6.77 | 49.33 | 0 | 0 |
| random | 50.66 | 3.51 | 32.00 | 0 | 0 |
| exploit | -132.09 | 8.44 | 48.33 | 0 | 261 |

The exploit canary stays far below every honest baseline, so the new
mechanics (including far-future pick churn, which is provably score-neutral)
did not reopen degenerate strategies. Scripted baselines ignore incoming
offers and never scout, and both features are RNG-stream-isolated, so their
scores moved only by the flat pick-asset term.

Leaderboard preset baselines (seeds 11-18, 5 seasons):

| Agent | Mean Score |
| --- | ---: |
| value | 282.22 |
| win-now | 217.43 |
| rebuild | 79.49 |
| conservative | 76.08 |
| random | 51.39 |

> **Note:** All results below the "Post-Validity-Fixes Baselines" section were
> produced by the original MVP rules and are retained as a historical record.
> The validity fixes (real lineups, competitive draft and free agency,
> opponent-initiated trades, trade limits with hidden partner valuations,
> roster minimums, memo scratchpad, and the strategy/protocol score split)
> changed the score scale, so old and new numbers are not comparable.

## Post-Validity-Fixes Baselines

Command:

```bash
python -m gm_bench compare --agents random conservative win-now rebuild value exploit --seeds 1 2 3 --seasons 5 --no-log
```

Result:

| Agent | Mean Score | Stddev | Mean Wins | Titles | Illegal |
| --- | ---: | ---: | ---: | ---: | ---: |
| value | 240.11 | 12.16 | 98.67 | 0 | 0 |
| win-now | 197.66 | 18.86 | 98.00 | 2 | 0 |
| rebuild | 96.09 | 23.49 | 50.00 | 1 | 0 |
| conservative | 74.52 | 6.77 | 49.33 | 0 | 0 |
| random | 46.91 | 3.51 | 32.00 | 0 | 0 |
| exploit | -135.84 | 8.44 | 48.33 | 0 | 261 |

The `exploit` red-team canary (trade value-pumping plus free-agent hoarding)
now finishes far below every honest baseline — 261 of its trade attempts are
rejected. Before the fixes, its strategies were score-dominant. Baseline
lifts are also tighter than under the original rules because opponents now
compete for free agents in every phase and trade among themselves, so easy
value is scarcer for everyone.

Normalized evaluation:

```bash
python -m gm_bench evaluate --agent value --baselines random conservative win-now rebuild --seeds 1 2 3 --seasons 3 --no-log
```

```text
candidate_mean=148.364 strategy=148.364 protocol_penalty=0.0
baseline_panel_mean=100.406 lift=47.958 lift_pct=47.76%
paired_lift=47.958 ci95=[27.24, 66.304] (significant) candidate_seed_win_rate=1.0
vs strongest baseline 'win-now': paired_lift=4.567 seed_win_rate=0.667
```

## Local Ollama Models (current rules)

First model-backed results under the post-validity-fixes rules, run with the
fixed Ollama adapter (thinking disabled by default — see below). Protocol:

```bash
GM_BENCH_WORKERS=1 OLLAMA_MODEL=<model> python -m gm_bench evaluate \
  --agent-cmd "python examples/ollama_agent.py" --agent-timeout 300 \
  --baselines random conservative win-now rebuild value \
  --seeds 1 2 --seasons 3 --no-log --json
```

| Model | Mean Score | Strategy | Penalty | Fallback | Paired Lift vs Panel | CI95 | vs `value` |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| qwen3.5:latest | 65.93 | 80.93 | 30.0 | 1/18 | −36.17 (sig) | [−43.93, −28.40] | −82.82 |
| gemma4:e4b | 69.77 | 81.02 | 22.5 | 2/18 | −32.32 (sig) | [−46.35, −18.29] | −78.98 |

Baseline panel mean on these seeds: 102.09; `value` mean: 148.75.

Observations:

- Both models played nearly every decision point themselves (fallback rates
  0.056 and 0.111), so these scores are genuinely model-earned — the first
  model-backed numbers under the current rules where that is verifiable.
- Their strategy scores are nearly identical (80.9 vs 81.0); they differ
  mainly in protocol discipline (qwen 12 illegal actions, gemma 9).
- qwen plays a reckless win-now style: 41 mean wins (more than any baseline
  archetype except win-now itself) but weak asset/cap terms. gemma is more
  conservative (30 mean wins) with a similar overall result.
- Neither model used the `memo` action once across 6 seasons of decisions —
  no multi-season planning was even attempted. The benchmark's headroom story
  holds: both finish significantly below the scripted baseline panel and
  ~80 points below the `value` heuristic, so there is ample room above small
  local models before the `value` ceiling is even in question.

### Adapter validity fix: thinking models

Earlier runs of both models produced fallback rates of 83–89%: qwen3.5 and
gemma4 both emit reasoning prose ("Thinking...") that never reaches JSON,
because the adapter's `/no_think` prompt prefix is a qwen3-era soft switch
newer models ignore. Those scores measured the adapter's deterministic
fallback policy, not the model — exactly the failure mode the
`fallback_decisions` attribution was added to expose (a tainted qwen run
scored **87.2 with 16/18 fallbacks**, i.e. *higher* than the model plays on
its own).

The adapter now passes Ollama's real think switch (`--think=false` on the
CLI, `"think": false` over HTTP) for every model by default, retrying without
the switch for models or CLI versions that reject it. `OLLAMA_THINK=1` opts
back in.

## Historical MVP Results (pre-fix rules)

## Committed SQLite Database

The committed database is:

```text
data/gm_bench.sqlite
```

It currently contains:

- 3 logged CLI runs.
- 11 episode rows.
- Transaction traces for each logged episode.

Logged runs:

| Command | Agent(s) | Seasons | Seeds |
| --- | --- | ---: | --- |
| `run` | `value` | 1 | `[1]` |
| `compare` | `random, conservative, win-now, rebuild, value` | 2 | `[1, 2]` |
| `evaluate` | `value` against `random, conservative, win-now, rebuild` | 3 | `[1, 2, 3]` |

Useful DB queries:

```bash
sqlite3 data/gm_bench.sqlite 'select count(*) from runs;'
sqlite3 data/gm_bench.sqlite 'select count(*) from episodes;'
sqlite3 data/gm_bench.sqlite 'select agent, seed, final_score, wins, championships, illegal_actions from episodes order by final_score desc limit 8;'
```

Top committed episode rows:

| Agent | Seed | Final Score | Wins | Championships | Illegal Actions |
| --- | ---: | ---: | ---: | ---: | ---: |
| value | 2 | 222.552 | 44 | 1 | 0 |
| win-now | 1 | 176.620 | 36 | 1 | 0 |
| value | 1 | 162.443 | 35 | 0 | 0 |
| rebuild | 2 | 137.550 | 38 | 0 | 0 |
| conservative | 2 | 136.673 | 38 | 0 | 0 |
| value | 1 | 135.466 | 16 | 0 | 0 |
| win-now | 2 | 133.637 | 41 | 0 | 0 |
| rebuild | 1 | 105.363 | 30 | 0 | 0 |

## Built-In Baseline Comparison

Command:

```bash
python -m gm_bench compare --agents random conservative win-now rebuild value --seeds 1 2 --seasons 2
```

Result:

| Agent | Mean Score | Stddev | Mean Wins | Titles | Illegal |
| --- | ---: | ---: | ---: | ---: | ---: |
| value | 192.50 | 30.05 | 39.50 | 1 | 0 |
| win-now | 155.13 | 21.49 | 38.50 | 1 | 0 |
| rebuild | 121.46 | 16.09 | 34.00 | 0 | 0 |
| conservative | 119.87 | 16.80 | 34.00 | 0 | 0 |
| random | 85.13 | 2.06 | 31.50 | 0 | 0 |

## Baseline-Normalized Value Agent

Command:

```bash
python -m gm_bench evaluate --agent value --baselines random conservative win-now rebuild --seeds 1 2 3 --seasons 3
```

Result:

```text
candidate_mean=190.682
baseline_panel_mean=113.177
lift=77.505
lift_pct=68.48%
illegal=0
```

## Model-Backed Smoke Results

These were run during development and summarized here rather than re-running
paid/external providers while creating the repository.

| Agent path | Model setting | Seasons | Seed | Final Score | Wins | Championships | Illegal Actions | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Codex CLI | `CODEX_MODEL=gpt-5.5 CODEX_EFFORT=high` | 1 | 1 | 166.149 | 17 | 1 | 3 | Real model run after schema/config fixes. |
| Claude Code | `CLAUDE_MODEL=opus CLAUDE_EFFORT=high` | 1 | 1 | 94.428 | 16 | 0 | 13 | Real model run using Claude CLI `opus` alias. |
| Claude Code | `CLAUDE_MODEL=claude-opus-4.8 CLAUDE_EFFORT=high` | 1 | 1 | 110.534 | 14 | 0 | 0 | Did not reach model; Claude reported Opus 4 retired on 2026-06-15. |
| Ollama | `OLLAMA_MODEL=gemma4:e4b` | 1 | 1 | 105.534 | 14 | 0 | 2 | Local model run, slow but model-driven. |

