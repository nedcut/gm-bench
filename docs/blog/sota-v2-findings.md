# Frontier models versus long-horizon asset management

GM-Bench asks an agent to run the same procedurally generated hockey franchise
for five seasons: manage the cap, negotiate trades, scout and draft prospects,
and trade current wins against future asset value. In the frozen phase-one
study, eight publication-eligible frontier and open models all finished far
below a transparent scripted heuristic.

That result is more interesting than a model leaderboard. It says that fluent
model output, even from expensive frontier systems, did not reliably compound
good decisions across this particular synthetic environment. It does **not**
say that one model is generally better than another, or that LLMs cannot manage
real sports teams.

## Why the first ranking was withdrawn

The earlier `sota-v1` runs exposed two reasons to distrust an easy headline.
First, the documented prospect-scout action did not match the simulator,
harming models unevenly while leaving scripts untouched. Second, observed
output ranged from roughly 263 to 2,993 tokens per decision, and the same
nominal model behaved very differently through an API and a coding harness.
That table mixed model quality, output budget, and harness behavior, so it is
archived as evidence motivating the new protocol—not as a ranking.

The `sota-v2` protocol fixes scouting, separates API and coding-harness lanes,
reports input and output tokens, permits one measured JSON repair, and records
accepted and rejected actions by strategic mechanic. The phase-one API lane
was frozen before full scores were visible at a common 4,096-token total-output
safety ceiling with native-minimum reasoning: reasoning disabled where optional
and set to the lowest supported effort where mandatory. All ten exact routes
passed a real smoke audit without truncation or the predeclared 3,072-token
cap-pressure trigger.

## The result

Each registered model ran the same eight public seeds, five seasons, and three
candidate repeats: 24 episodes and 480 decision points. Repeats were averaged
within seed before comparison with that seed's deterministic `pick-trader`
score. The primary family contains all ten pre-registered models, including the
two technically ineligible rows.

| Model | Mean score | Lift vs `pick-trader` | Tokens / decision | Cost | Illegal actions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Muse Spark 1.1 | 231.851 | -179.768 | 10,084.2 | $7.5863 | 51 |
| GLM 5.2 | 217.539 | -194.080 | 10,764.4 | $1.2812 | 168 |
| Gemini 3.5 Flash | 215.624 | -195.995 | 8,770.7 | $6.3205 | 18 |
| Tencent HY3 | 195.841 | -215.778 | 7,743.3 | $0.0000 | 10 |
| Qwen 3.7 Plus | 175.520 | -236.099 | 8,039.6 | $1.2938 | 136 |
| GPT-5.6 Luna | 173.926 | -237.693 | 7,611.2 | $4.6802 | 126 |
| Claude Sonnet 5 | 142.143 | -269.475 | 9,944.4 | $11.0544 | 44 |
| MiniMax M3 | 129.880 | -281.739 | 8,728.2 | $1.2371 | 14 |

`pick-trader` scored 411.619; the full scripted-baseline panel averaged
273.794. Even the highest observed model mean, Muse Spark's 231.851, remained
below both references. The eight eligible rows consumed $33.4535 in artifact-
reported API cost. Across all ten completed cells, including diagnostics, the
artifact total was $48.9932.

The observed model means should not be read as ranks. Every eligible row lands
in one connected uncertainty tier because the seed-paired bootstrap intervals
overlap transitively. Each model's unadjusted exact sign-flip result is 0.0078,
reflecting a negative lift on every seed, but the predeclared Holm adjustment
uses the full ten-model family; every adjusted value is 0.078125. With only
eight public seeds, the study has limited resolution for model-versus-model
claims. “Muse had the highest observed mean” is supported. “Muse is the best
model” is not.

## Two completed cells were excluded

Grok 4.5 completed the simulator but recorded usage for 476/480 decisions and
cost for 474/480. Mistral Medium 3.5 recorded usage for 480/480 but cost for
479/480 after one adapter fallback. The frozen policy requires complete cost
and route telemetry for every headline decision, so neither row enters the
headline table and neither was rerun for a better result. Their raw evidence is
retained in the release archive; Mistral also has a compact diagnostic artifact.

This distinction matters. Eligibility means that a result is complete and
comparable under the frozen lane. It does not mean that the model performed
well. Conversely, an excluded row can remain useful operational evidence
without being silently promoted into the comparison.

## What appears to be hard

The model rows accumulated between 10 and 168 illegal actions. Several also
issued many failed information queries: Muse recorded 453, GLM 209, and Claude
137. Those counts do not prove a single causal failure mode, but the traces show
that plausible local actions did not reliably become legal, state-aware plans
across drafts, contracts, lineups, and trades. The benchmark's strongest
scripted policies benefit from explicit knowledge of its mechanics, so beating
them is intentionally a demanding bar rather than a fair imitation of a human
front office.

## Scope and limitations

- GM-Bench is a synthetic hockey-style environment, not a real organization.
- Its score is hand-designed and encodes explicit value judgments.
- Scripted baselines were written with direct knowledge of the environment.
- Eight public seeds provide limited statistical resolution and may be exposed
  to benchmark-specific adaptation.
- Native-minimum reasoning is operationally comparable, not identical compute:
  actual model token use still ranged from 7,611 to 10,764 tokens per decision.
- The result evaluates model-plus-standardized-scaffold systems on this task;
  it is not a claim about general intelligence or universal strategic ability.

## Audit and reproduce

The compact rows live in [`results/leaderboard/`](../../results/leaderboard/),
the seed-paired analysis in
[`results/analysis/publication-panel-analysis.json`](../../results/analysis/publication-panel-analysis.json),
and the release manifest in
[`releases/sota-v2-phase-one-2026-07-19/manifest.json`](../../releases/sota-v2-phase-one-2026-07-19/manifest.json).
The GitHub release attaches the exact raw public traces, frozen configs, final
run metadata, and checksums. See
[`docs/REPRODUCING_SOTA_V2_RELEASE.md`](../REPRODUCING_SOTA_V2_RELEASE.md)
for the clean-clone verification path.

The durable conclusion is deliberately narrow: under GM-Bench's frozen
phase-one public protocol, none of the eight eligible model systems beat the
transparent `pick-trader` heuristic, and the sample does not support an ordinal
ranking among the models themselves.
