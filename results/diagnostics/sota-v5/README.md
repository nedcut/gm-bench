# sota-v5 diagnostic artifacts

Redacted artifacts for the three sota-v5 panel rows the frozen exclusion
register (`config/sota_v5_panel_exclusions.json`) records as
`ineligible-model-behavior`. They are not leaderboard rows: the packager ships
them as diagnostics next to the register so every registered model is
accounted for. The two infrastructure-limit exclusions have no artifact here;
the manifest records them from the register alone.

## How each file was produced

`gm-bench redact-result` cannot write these rows: it refuses to write when the
sota-v5 publication policy fails, and ineligible rows fail by definition. It
also only reads result payloads, while two rows exist only as checkpoints. So
each file was written by `scripts/redact_sota_v5_diagnostic.py`, which reuses
`gm_bench.official.redact_leaderboard_payload` (the same helper the CLI uses)
and then stamps `publication.source_checkpoint_sha256` with the SHA-256 of the
retained checkpoint file's bytes, the digest the register binds to.

| Model | Source | Retained |
| --- | --- | --- |
| `openrouter-gpt-oss-20b-deepinfra` | full raw result `raw/<id>--4096.json` (29 seeds); decision failure rate 0.0207 over the 0.020 gate | 580 decisions |
| `openrouter-claude-haiku-4.5-anthropic` | checkpoint only; aborted at seed 14 of 29 on two consecutive invalid-JSON replies | 13 seeds, 260 decisions |
| `openrouter-glm-5-streamlake` | checkpoint only; aborted at seed 25 of 29 on two consecutive malformed replies | 24 seeds, 480 decisions |

For the checkpoint-only rows the script builds a result-shaped payload from the
completed episodes: candidate summary via `gm_bench.runner._episodes_payload`,
scripted baselines and paired analysis via
`gm_bench.model_runs.evaluate_resumable_candidate` (deterministic, served from
the baseline cache, no paid calls), and `run_info` from the checkpoint's stored
metadata and provenance. `run_info.seed_panel` describes the registered 29-seed
private panel (its hash matches the headline rows); the `diagnostic` block
records how many of those seeds completed.

The stored `validation_reports.sota-v5.errors` are the gate failures that make
the row ineligible. The seed-panel message is replaced with a sentinel because
the validator quotes the private seed lists in it.

## Fields

- `publication.raw_artifact_sha256`: canonical-JSON hash of the payload that
  was redacted (the raw result for gpt-oss-20b; the checkpoint-derived payload
  for the other two). This is not the register digest.
- `publication.source_checkpoint`: checkpoint path relative to the run
  directory `data/publication/sota-v5-panel`.
- `publication.source_checkpoint_sha256`: byte SHA-256 of that checkpoint,
  equal to the register entry's `evidence.checkpoint_sha256`.
- `diagnostic`: the register status, rule and reason, the checkpoint status and
  abort error, and completed versus registered seed counts.

Redaction shape is the same as a headline row: `redaction.applied` true,
`run_info.seed_panel.name` `private-env`, top-level, candidate and baseline
seeds `<redacted>`, candidate and baseline episodes empty, `paired.per_seed`
empty.
