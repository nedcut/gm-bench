# GM-Bench Results Snapshot

This snapshot records the benchmark results generated during the MVP build.

## Example SQLite Database

The example database path is:

```text
data/gm_bench.sqlite
```

Generate it locally by running any logged command, for example:

```bash
python -m gm_bench compare --agents random conservative win-now rebuild value --seeds 1 2 --seasons 2
```

A local run used to produce this snapshot contained:

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

Top episode rows from the snapshot run:

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

