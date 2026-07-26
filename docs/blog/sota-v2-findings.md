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

## Protocol discipline, the references' memory advantage, and memo use do not explain the gap (added 2026-07-26)

A 180-to-282-point gap invites two cheap explanations: that the models were
really being scored on JSON discipline, or that they ran through a scaffold the
scripted references never faced. Both are testable without spending anything,
and both fail. The three measurements below are drawn from the frozen v2
artifacts and from the v2 contract itself (`558e8f35ea1d66b9`); the fourth
(observation truncation) is a `sota-v3` measurement and is labelled inline where
it appears. None of them adds a paid run or changes a published number.

**Protocol discipline accounts for 0.5–9.0% of the gap.** `strategy_score` is
the score with invalid-action penalties removed, so its distance from
`final_score` prices protocol failure exactly:

| Model | Gap to `pick-trader` | Protocol cost / episode | Share of gap |
| --- | ---: | ---: | ---: |
| Muse Spark 1.1 | 179.8 | 5.31 | 3.0% |
| GLM 5.2 | 194.1 | 17.50 | 9.0% |
| Gemini 3.5 Flash | 196.0 | 1.88 | 1.0% |
| Tencent HY3 | 215.8 | 1.04 | 0.5% |
| Qwen 3.7 Plus | 236.1 | 14.17 | 6.0% |
| GPT-5.6 Luna | 237.7 | 13.12 | 5.5% |
| Claude Sonnet 5 | 269.5 | 4.58 | 1.7% |
| MiniMax M3 | 281.7 | 1.46 | 0.5% |

A model that emitted perfectly legal JSON on every decision would still trail
`pick-trader` by 174–280 points. Adapter reliability is not the explanation
either: `failed_decisions` totalled 0–8 out of 480 per model, so no row was
carried or sunk by the fallback policy.

**Cross-decision continuity is worth nothing to the references.** Model rows run
fresh-spawned, carrying only a 2,000-character memo between decision points,
while the scripted references are ordinary long-lived objects. If they had been
accumulating state across an episode, part of the gap would be "the reference
remembered what the model was forbidden to remember." Re-instantiating every
scripted agent before every single decision, on the v2 contract, reproduces
episode scores bit-identically for all nine agents registered at that tag — they
hold no mutable state and rebuild their plan from the observation each turn.
There was no memory advantage to strip. (The run log's §2 table reports ten
agents and different absolute scores, because it measures current HEAD under the
`sota-v3` contract — `pick-trader` on seed 11 is 455.725 under v2 and 261.148
under v3, and `scaffold-view` did not exist under v2. The v2-contract run
supporting this paragraph is recorded separately as §2a of that log.)

**Memo volume does not predict score.** If carrying a plan forward were the
binding constraint, heavier memo use should buy score. It does not. Gemini wrote
**3** memos across 480 decisions and scored 215.624; GLM wrote **568** — a 190×
difference in memo volume — and scored 217.539. Two points apart, and both about
195 points below `pick-trader`. Claude Sonnet 5 wrote 361 and scored 142.143,
below both. (Stated in scores rather than placements deliberately: this study
does not support an ordinal ranking, so an argument resting on who "placed third"
would be resting on something the same document disclaims.) Taken with the point
above — the references reach 411.619 using no cross-decision memory at all —
memory does not look like the bottleneck here.

A fourth factor, the truncated observation model adapters receive, was measured
at +2.8 points (paired *t* = 0.249) on the same public seed panel, under
successor contract fingerprint `4f6ddddd6a6dd81c`. The source log requires that
fingerprint to travel with the number, since any contract-source change
invalidates the comparison. Because it is a `sota-v3` measurement it is
supporting evidence for interpreting this study rather than part of it, and it is
reported separately for that reason.

What these do not establish is a positive mechanism. They do not show *why* the
decisions were worse, and nothing here licenses a claim about reasoning ability
in general. Nor do they close the harness question entirely: **the 4,096-token
output cap applies to model rows and not to the scripted references, and it has
not been measured.** The protocol-repair budget is only partly bounded, via the
penalty accounting above.

The continuity result is also one-sided, and worth stating precisely. It shows
that the *references* gained nothing from persistence, which rules out "the
reference remembered what the model could not." It does not show that models
would have gained nothing from persistent state they were denied. If they would
have, continuity contributes to the gap even though the references take no
advantage from it — that half is not measured here.

So the correct reading is narrow. Three specific explanations that would have
made the gap a measurement artefact—protocol discipline, cross-decision
continuity, and memo usage—do not account for it, and a fourth, observation
truncation, does not account for it under the successor contract. The residual
is not thereby shown to be decision quality alone; it is whatever is left after
those four, which still includes at least one uncontrolled harness factor.
Full working is in
[`docs/run_logs/gap-decomposition-and-panel-power-2026-07-26.md`](../run_logs/gap-decomposition-and-panel-power-2026-07-26.md).

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
- The published panel and scripted references are committed and public. That
  makes replay easy, but it also permits benchmark-specific adaptation; future
  generalization claims need a private or prospective panel.
- Opponents are scripted front-office policies, not autonomous learning GMs.
  Morale is shown as decorative state but does not currently affect strength,
  development, or score; readers should not treat it as a decision-relevant mechanic.

## Decision history

The protocol was frozen through an iterative process, not discovered whole.
The public [publish-readiness decision log](../PUBLISH_READINESS.md) records
panel reshuffles, cap-policy changes, route substitutions, and evidence resets.
“Frozen” describes the released protocol and artifact set; it does not erase
those pre-freeze researcher decisions.

## Post-release integrity note (2026-07-24)

A post-release code audit found three defects: non-finite numeric action inputs
could bypass comparison-based validation; negotiation walk-away counters reset
between interaction rounds instead of lasting for the full decision window; and
the routine compact-artifact validator trusted several derived statistics
instead of recomputing them from retained episode rows. The tagged release
manifest and checksums still bind the published files, and the committed compact
rows contain finite values. The compact rows do not preserve enough action-level
detail to prove retrospectively that no model benefited from the negotiation
reset.

The repair therefore does not rewrite or silently “re-certify” `sota-v2`.
Released v2 artifacts remain frozen historical evidence under their literal
contract and the narrow claim below. Corrected simulator/action behavior and
the stronger artifact validator begin at `sota-v3`; a future v3 model panel
would require a new pre-registered lane and fresh evidence. No paid reruns are
part of this repair.

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
ranking among the models themselves. The 2026-07-26 decomposition sharpens the
first half without widening the second: protocol discipline, the references'
memory advantage, and memo usage do not account for the gap. It does not follow
that the gap is decision quality alone. The 4,096-token output cap remains
uncontrolled, and the continuity result is one-sided — it rules out a reference
advantage, not a cost to models denied persistent state. The absence of an
ordinal ranking is unchanged, and remains the more important caveat of the two.
