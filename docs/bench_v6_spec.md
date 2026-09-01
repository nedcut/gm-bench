# GM-Bench v6 specification

Frozen decisions for the v6 benchmark. Settled 2026-08-30 from the vision
contract (grilling session) and the feasibility study (token, route, and
budget checks against live OpenRouter data). Changes to this file after the
panel freeze create a new benchmark version.

## What v6 measures

Five-season hockey franchise management by language models under one fixed,
minimal API loop. Headline claim: dated model-plus-route performance under
these conditions. Adjacent frontier models are expected to tie; a tie is a
result, not a failure.

## Sensitivity target

- Minimum detectable difference (MDD): **30 points**. This is a design
  sensitivity figure from the calibration panel — how large a score gap the
  panel width can resolve — used to choose the seed count. It is not an
  inference plan: it says the panel is coarse enough that adjacent frontier
  models will not separate, and fine enough to be worth running.
- Anchor: MDD ~36 points at 16 seeds, and a projected 26 points at 29 paired
  seeds per model, so the 30-point target holds with margin. Measured on the
  48-seed residual panel in docs/scoring_calibration.md (paired-residual SD
  40.1, assumed within-seed model repeat noise 15.0); the projection holds for
  model rows whose within-seed SD is about 25 or below.
- The only supported inference is the predeclared contrast: each registered
  model against the pick-trader reference, exactly as frozen in
  config/sota_v5_publication_protocol.json. That plan is reference-only. No
  model-versus-model comparison, ordinal ranking, or capability tiering is
  planned, run, or published, and the MDD figure does not authorize one.
- The sensitivity ladder (scripted weak/mid/strong policies plus damaged
  agents) must demonstrate separation at this target before any paid model
  run. Its results are published, and the tie interpretation is written down
  before the panel starts.
- Variance reduction is an audit goal: if simulator fixes bring the
  within-seed score SD (currently ~15.0) down, re-run the power analysis and
  claim the finer resolution honestly.

## Panel

16 models, 29 paired seeds each, ~$75 base cost against a **$100 hard
ceiling** (2x completion-token overrun stays under $100). Prices are the
2026-08-30 preflight values; re-verify routes and prices at panel freeze.

| Model | Tier |
|---|---|
| x-ai/grok-4.6 | frontier |
| anthropic/claude-haiku-4.5 | flash |
| google/gemini-3.7-flash | mid |
| x-ai/grok-4.3 | mid |
| openai/gpt-5.4-mini | mid |
| z-ai/glm-5 | open-weight |
| moonshotai/kimi-k2.5 | open-weight |
| qwen/qwen3.5-397b-a17b | open-weight |
| minimax/minimax-m3 | open-weight |
| google/gemini-3.1-flash-lite | flash |
| openai/gpt-5.6-luna | flash |
| z-ai/glm-5.3-flash | flash |
| deepseek/deepseek-v4-flash-0731 | flash |
| qwen/qwen3.5-27b | local-runnable |
| nvidia/nemotron-3-nano-30b-a3b | local-runnable |
| openai/gpt-oss-20b | local-runnable |

Eligibility rule: a model joins only if a healthy route advertises
structured_outputs. Pin providers for models where few routes qualify
(minimax-m3, nemotron-3-nano). Run the zero-cost route preflight before any
paid call. Models added later run the same 29 scenario seeds.

Baselines (not budget-funded rows): one simple locally-reasonable policy and
one strong heuristic policy, both restricted to model-visible information.

## Execution rules

- One API call per decision phase (5 seasons x 4 phases = 20 calls per seed).
- Input: bounded observation, **target ~6,500 tokens** (hard ceiling 8,000).
  Today's serialization renders ~15,400; the v6 render must use tabular
  rosters, a ledger capped to roster-changing moves from the last ~2 seasons
  plus one-line season results, candidate lists of ~10 free agents / 8 draft
  / 6 trade, and a 2,000-character model-managed notebook.
- Output: 4,096-token ceiling including reasoning tokens.
- Reasoning: lowest supported setting; disable where possible. Mandatory-
  reasoning models run at minimum effort with reasoning tokens recorded.
- No paid retries. Deterministic local repair when intent is unambiguous;
  otherwise record a no-op. Malformed and unrecoverable output rates are
  reported beside the score, not inside it.

## Scoring

Weighted score, priority order:

1. Five-season competitive success
2. Championships and deep playoff runs
3. Consistent contention
4. Regular-season performance
5. Capped contribution from terminal roster, prospects, picks, and cap health

Weights are set from hockey judgment, hypothetical careers, and scripted
policies, then frozen before any candidate-model result is visible. A later
scoring change is a new benchmark version and does not rewrite old rows.

## Simulator boundary

ZenGM's strategic shape, not its feature set. A mechanic survives only if it
creates a real tradeoff, changes outcomes often enough to matter, is legible
from the observation, and measures something distinct. Measurement beats
realism when they conflict. Randomness stays bounded and paired across
models; no single event should dominate a five-season score.

v6 mechanic work (confirmed by audit):

- Draft lottery replaces deterministic draft order; traded picks carry team
  identity and uncertainty.
- Player willingness responds to winning, role, and money.
- Lineup construction rewards more than sorting by overall rating.
- Expiring contracts create real re-sign-or-lose pressure.
- Inert fields (morale, market, patience) are removed or made consequential.

## Maintenance

Freeze v6 (tag + contract fingerprint), then append model rows over time
under identical conditions. Old studies live in tags, releases, and
artifacts; historical runners do not stay operational on main. No
preregistration bureaucracy: the durable core is this spec, the runner, the
score, the scenario set, run manifests, results, and the site.
