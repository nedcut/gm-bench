# Sixteen models, one heuristic, twenty-nine hidden seeds

GM-Bench asks an agent to run the same procedurally generated hockey franchise
for five seasons: manage the cap, negotiate trades, scout and draft prospects,
and trade current wins against future asset value. The `sota-v5` study is the
first GM-Bench panel run on a private seed panel. Sixteen pre-registered
model-plus-scaffold systems were launched. Eleven produced complete,
route-matched, cost-complete rows. Every one of them trails the transparent
`pick-trader` heuristic. Ten of the eleven trail it by more than the panel
can attribute to chance; one, Gemini 3.7 Flash, does not.

That is the whole headline. The study was pre-registered to answer one
question per model, taken from the frozen protocol:

> Does each pre-registered model-plus-compact-scaffold system trail the named
> `pick-trader` reference under the frozen `actions-v3`, `sim-v4`,
> `observation-v3`, and `score-v1` mechanics?

It does not rank the models against each other, and nothing below should be
read as a ranking.

## What changed since phase one

The published [`sota-v2` phase-one study](sota-v2-findings.md) ran eight
models on eight public seeds with three repeats. Two weaknesses were obvious
at the time. Public seeds permit benchmark-specific adaptation, and eight seeds
give an exact sign-flip test a floor of one in 128, so nothing could reject
after multiple-comparison adjustment.

`sota-v5` fixes both. The seed panel is 29 seeds drawn privately, committed
before any model ran through an execution hash and a salted hiding commitment
recorded in `config/sota_v5_lane.json`. The seeds themselves are held outside
the repository and are not in the release archive. Each model ran every seed
once, with zero protocol repair attempts and a 4,096-token total output
ceiling that includes any reasoning tokens. Reasoning was disabled where the
route allowed it and set to the lowest supported effort where it was
mandatory. The simulator, action set, observation, and scoring contract are
frozen at fingerprint `a600b7da0c302231`; the OpenRouter scaffold at
`c582e126bbb6af10`. Any change to those files invalidates every row.

The cohort, routes, statistical design, exclusion rules, and analysis were
frozen in a pre-registration and a chain of dated amendments before the panel
started. One rule was amended after the data came in, and it is disclosed
below.

## The result

`pick-trader` scores 247.109 on this panel. The full eight-policy scripted
reference set averages 175.303, from `random` at 88.796 to `pick-trader`. Each
model's lift is its mean score minus `pick-trader`'s, paired by seed. The test
is an exact paired sign-flip test on those 29 differences, Holm-adjusted over
the family of all sixteen registered models. The five models that did not
produce a row still count in that family, so no p-value was eased by their
absence.

| Model | Route | Mean score | Lift vs `pick-trader` | 95% CI | Holm p | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Gemini 3.7 Flash | Google AI Studio | 223.7 | -23.4 | [-43.5, -2.8] | 0.221 | $1.88 |
| Grok 4.6 | xAI | 203.5 | -43.6 | [-61.6, -25.9] | 0.0003 | $9.18 |
| GPT-5.6 Luna | OpenAI | 171.3 | -75.8 | [-97.6, -54.2] | <0.0001 | $0.43 |
| GLM 5.3 Flash | Fireworks | 163.2 | -83.9 | [-100.7, -67.2] | <0.0001 | $0.60 |
| Kimi K2.5 | SiliconFlow | 149.2 | -97.9 | [-114.5, -81.2] | <0.0001 | $1.58 |
| Gemini 3.1 Flash Lite | Google AI Studio | 145.6 | -101.5 | [-117.4, -86.6] | <0.0001 | $0.46 |
| Grok 4.3 | xAI | 135.0 | -112.1 | [-127.9, -97.0] | <0.0001 | $3.52 |
| DeepSeek V4 Flash | Together | 124.9 | -122.2 | [-138.4, -106.7] | <0.0001 | $0.44 |
| GPT-5.4 Mini | OpenAI | 124.0 | -123.1 | [-140.8, -106.2] | <0.0001 | $2.45 |
| MiniMax M3 | ModelRun | 117.0 | -130.1 | [-146.2, -115.2] | <0.0001 | $2.10 |
| Qwen 3.5 27B | SiliconFlow | 113.7 | -133.4 | [-150.6, -117.0] | <0.0001 | $0.99 |

The table is sorted by mean score for readability, not as a ranking. The
confidence intervals are descriptive seed-paired bootstrap percentiles; the
inferential claim is the Holm-adjusted sign-flip test. The eleven headline
rows cost $23.62 in artifact-reported API spend.

Gemini 3.7 Flash lost to `pick-trader` on the panel mean and its bootstrap
interval excludes zero, but its unadjusted sign-flip p-value does not survive
adjustment over sixteen comparisons. The correct statement is that the panel
cannot distinguish its gap from noise at the pre-registered threshold. It is
not evidence that the model matched the heuristic.

## What the panel cannot say

**No within-seed noise was measured.** Each model ran each seed once. The
minimum detectable difference quoted in the analysis, about 30 points, rests
on the repeat noise measured on the earlier calibration panel, not on this
one. Every row in the analysis file says so. A future panel with repeats would
close this gap.

**No ordinal ranking.** The pre-registration declares only model-versus-
`pick-trader` contrasts. Model-versus-model tiers are marked unsupported in
the analysis artifact, and the site draws no such comparison.

**Reasoning policy is a confound, not a control.** Three routes required
reasoning to be on and were run at the lowest supported effort: Gemini 3.7
Flash, Grok 4.6, and GLM 5.3 Flash. The other eight ran with reasoning
disabled. Two of the three reasoning-on rows are the two closest to
`pick-trader`, and they also produced the most output per decision (481 and
742 output tokens against a range of 39 to 158 for the reasoning-off rows).
This study did not vary reasoning within a model, so it cannot separate the
model from the setting. The pattern is reported because it is visible, not
because it is explained.

## Five cells that are not in the table

All sixteen launched cells are accounted for under rules frozen before the
panel ran. Their statuses, attempts, decisions completed, cost, and checkpoint
hashes are in `config/sota_v5_panel_exclusions.json`.

Three cells are ineligible on model behavior. The protocol does not allow a
rerun for model behavior, so these rows were not retried for a better result.

- GPT-OSS 20B completed all 580 decisions with a decision failure rate of
  0.0207, over the frozen 0.020 gate.
- Claude Haiku 4.5 hit the fail-fast rule at seed 14 after two consecutive
  invalid-JSON replies, with 260 decisions retained.
- GLM 5 hit the same rule at seed 25, with 480 decisions retained.

Two cells were excluded at the two-attempt infrastructure limit with no
artifact. Qwen 3.8 Flash returned HTTP 429 on both attempts. GPT-5.6 Sol
returned billed responses with no choices on both attempts.

The three ineligible rows ship as redacted diagnostic artifacts in the
release. They are operational evidence and do not enter the comparison.

## One rule changed after the data was in

The pre-registration required eight headline rows and treated any missing row
as a partial family. When the panel finished with eleven headline rows and
five accounted-for exclusions, the owner amended the rule so that a row
excluded under a frozen, register-recorded reason counts as accounted for
rather than missing. The amendment is dated 2026-09-03T20:45Z in
[the route-and-cohort amendment log](../run_logs/sota-v5-v6-route-and-cohort-amendment-2026-09-01.md).

It is a post-data decision and it is labelled as one. Nothing about how any
row was run, scored, or gated changed, the Holm family stayed at sixteen, and
the eleven rows would have cleared the original floor of eight either way.
Readers who prefer the strict pre-registered reading can treat the family as
partial; the per-model numbers are the same under both readings.

## Protocol versus strategy

Each row's `strategy_score` is its score with invalid-action penalties
removed, so the distance between it and the final score prices protocol
failure exactly. On this panel that share is larger than in phase one for some
models and negligible for others.

| Model | Gap to `pick-trader` | Protocol cost / episode | Share of gap | Illegal actions |
| --- | ---: | ---: | ---: | ---: |
| Gemini 3.7 Flash | 23.4 | 1.0 | 4.4% | 12 |
| Grok 4.6 | 43.6 | 1.7 | 3.9% | 20 |
| GPT-5.6 Luna | 75.8 | 13.0 | 17.2% | 151 |
| GLM 5.3 Flash | 83.9 | 5.9 | 7.1% | 69 |
| Kimi K2.5 | 97.9 | 18.2 | 18.6% | 211 |
| Gemini 3.1 Flash Lite | 101.5 | 2.2 | 2.2% | 26 |
| Grok 4.3 | 112.1 | 0.3 | 0.3% | 4 |
| DeepSeek V4 Flash | 122.2 | 13.4 | 11.0% | 156 |
| GPT-5.4 Mini | 123.1 | 28.7 | 23.3% | 333 |
| MiniMax M3 | 130.1 | 3.0 | 2.3% | 35 |
| Qwen 3.5 27B | 133.4 | 23.9 | 17.9% | 277 |

Two things stand out. First, every model with perfectly legal output would
still trail `pick-trader` by at least 22 points, and most by more than 80.
Second, illegal actions and decision failures are different things. GPT-5.4
Mini and Qwen 3.5 27B logged 333 and 277 illegal actions with a decision
failure rate of zero: every reply parsed, and many of the parsed actions were
not legal in the game state. That is a state-tracking failure, not a
formatting one, and the benchmark scores it as such.

Grok 4.3 is the opposite case: four illegal actions, 39 output tokens per
decision, and a 112-point gap. Terse, legal, and poor.

## Cost and time

The eleven rows span a factor of about twenty in cost and sixteen in latency.
Grok 4.6 cost $9.18 and averaged 12.8 seconds per decision. GPT-5.6 Luna cost
$0.43 at 3.1 seconds. GLM 5.3 Flash was the slowest row at 15.0 seconds per
decision; Grok 4.3 the fastest at 0.9. Gemini 3.7 Flash, the closest row to
`pick-trader`, cost $1.88 at 2.3 seconds and was also the best score per
dollar. No row truncated a single reply against the 4,096-token ceiling. The
full efficiency table is in
[`results/analysis/sota-v5-robustness.md`](../../results/analysis/sota-v5-robustness.md).

## Robustness

Three checks were run after the panel closed, from the operator's raw
artifacts, and published as aggregates only. They are regenerable with
`scripts/sota_v5_robustness.py`, and the files carry no per-seed values,
because a per-fold vector would let a reader reconstruct the redacted
per-seed lifts.

**Detectable difference, observed.** Using each row's own paired-lift
standard deviation, the minimum detectable difference at alpha 0.05 and power
0.8 over 29 seeds runs from 22.4 to 31.5 points, median 24.4. The analysis
file's assumed figure of 30 is a within-seed noise threshold from the
calibration panel, a different quantity, and only GPT-5.6 Luna's row exceeds
it. Gaps of 40 points and more are comfortably above both.

**Leave-one-seed-out.** Dropping each of the 29 seeds in turn from every model
and recomputing the exact test on the remaining 28, with the Holm family held
at sixteen, moves no row's mean lift by more than 10 points and flips no
rejection except one. Gemini 3.7 Flash's Holm-adjusted p ranges from 0.028 to
0.424 across the 29 folds, and one fold crosses into rejection. Its
non-rejection therefore rests on a single seed. That does not change the
published decision, which is the full-panel one, but it should temper any
reading of Gemini 3.7 Flash as having matched the heuristic.

**Score-weight sensitivity.** Under 200 draws of independent plus or minus 30
percent perturbations to the score-component weights, the two rows nearest
`pick-trader` never change position relative to the scripted references, and
eight of eleven panels keep their full ordering in 95 percent of draws. The
rows that do move swap places with scripted neighbours in the lower half of
the reference set, never with each other's headline standing. Details are in
`results/analysis/sota-v5-weight-sensitivity.json`.

A season- or mechanic-held-out check is not possible from the retained
artifacts: the per-mechanic record is accepted and rejected action counts,
not a score decomposition.

## Scope and limitations

- GM-Bench is a synthetic hockey-style environment, not a real organization.
- Its score is hand-designed and encodes explicit value judgments. Scripted
  references were written with direct knowledge of the environment; beating
  them is a demanding bar by design.
- One repeat per seed means within-seed noise is unmeasured on this panel.
- Reasoning setting varies by route, as described above.
- The 4,096-token output ceiling applies to model rows and not to the scripted
  references, and its effect has not been measured.
- The result evaluates model-plus-standardized-scaffold systems on this task.
  It is not a claim about general intelligence, about real sports management,
  or about one model being better than another.
- Three items are recorded in the run log as known and unfixed: the Luna route
  billed about $0.125 per million prompt tokens against a $0.10 pricing
  snapshot; transient-retry counts live only in the spend guard ledger; and one
  reservation entry for Grok 4.6's first attempt is still marked active.

## Audit and reproduce

The redacted headline rows live in
[`results/leaderboard/sota-v5/`](../../results/leaderboard/sota-v5/), the
diagnostic rows in `results/diagnostics/sota-v5/`, the analysis in
[`results/analysis/publication-panel-analysis-v5.json`](../../results/analysis/publication-panel-analysis-v5.json),
and the release manifest and checksums in
[`releases/sota-v5-publication-2026-09-03/`](../../releases/sota-v5-publication-2026-09-03/).
The GitHub release `sota-v5-publication-2026-09-03` attaches the archive.
[`docs/REPRODUCING_SOTA_V5_RELEASE.md`](../REPRODUCING_SOTA_V5_RELEASE.md)
gives the verification path that needs no provider credentials. Private raw
traces and seed values are not published; the seed panel is verifiable
against its committed digests by anyone who later receives the escrow.

The durable conclusion is narrow. Under GM-Bench's frozen `sota-v5` protocol
on a 29-seed private panel, none of the eleven eligible model systems beat
the transparent `pick-trader` heuristic; ten trail it beyond what the panel
attributes to chance, and one, Gemini 3.7 Flash, cannot be separated from it
at the pre-registered threshold. The panel does not support an ordinal
ranking among the models.
