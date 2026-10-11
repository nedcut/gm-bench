# Experimental draft specialist baseline

This dependent extension to the [counterfactual lab](counterfactual_lab.md) fits a
small linear ranker from its simulated draft labels, compares it with the existing
public asset-value heuristic, and exposes an optional agent-callable ranking tool.
It is a bounded offline proof of concept, separate from frozen benchmark panels.
It does not train an LLM, invoke a provider or spend model/API quota.

## Walkthrough

```sh
python3 -m gm_bench.draft_specialist demo --out-dir /tmp/draft-specialist
```

The default generates four candidates × four downstream rollouts × two season
completions for each of training episode seeds 1–4 and test episode seeds 17–20.
Training rollout seeds start at 1001; test rollout seeds start at 1017. The output
directory must not exist. It receives eight inspectable comparison/label files,
`model.json` and `evaluation.json`. JSON contains source provenance and content
hashes, with no wall-clock nondeterminism. Same source and Python reproduce it.

Inspect `evaluation.json` → `score_delta_vs_heuristic`: a positive mean favors the
ranker on these episodes. Its `n` is four independent episode seeds, not sixteen
rollouts or eight seasons. The tiny public panel does not support a superiority
or generalization claim. Per-episode selections, heuristic choices and estimated
candidate gaps are included; “gap” means distance to the highest **estimated**
candidate value in that finite set, not regret against an optimal policy. Taking
a maximum over noisy labels is optimistic.

Train or evaluate existing lab exports separately:

```sh
python3 -m gm_bench.draft_specialist fit /tmp/draft-specialist/train-*.json \
  --horizon 2 --out /tmp/refit.json
python3 -m gm_bench.draft_specialist evaluate /tmp/refit.json \
  /tmp/draft-specialist/test-*.json --out /tmp/reevaluation.json
```

The loader checks the comparison hash, checkpoint replay, legality, unique and
complete candidate/rollout/horizon rows, finite labels and recomputed summaries.
These checks establish internal consistency, not authenticity of deliberately
forged labels. Use generated labels from trusted runs.

## Learning and separation

The heuristic chooses maximal `public_asset_value`, with prospect-ID tie-breaking.
The ranker uses ten public features: overall, published potential, age, injury
risk, salary, three position indicators, center indicator, and overall minus the
weakest roster player in that position. It never consumes true potential, hidden
league state, episode/rollout seed, rollout outcomes at inference, or test labels.

Training labels are mean frozen simulator state scores at one prespecified
horizon. Each checkpoint's features and labels are centered across candidates,
removing its shared intercept. Training-only RMS scales standardize the features.
A deterministic stdlib ridge solve (penalty 1, no fitted intercept) learns the
relative preference. Candidate rows have equal weight; custom exports with more
candidates give that checkpoint more weight. The CLI uses the same candidate count
for all episodes. Preference outputs are only for ranking within a decision and
are not calibrated absolute score predictions.

There is one checkpoint per episode seed in each split. Fit rejects duplicate
seed episodes; evaluation rejects duplicate test seeds or *any* training seed,
even at another checkpoint season. All checkpoints, actions, horizons and rollouts
from a seed stay in its split. The demo additionally uses disjoint downstream seed
panels. The horizon, candidate rule, features and ridge penalty are fixed before
evaluation; there is no test-set tuning, and users should not reuse these public
test seeds to tune and then claim untouched evaluation.

Evaluation is offline selection against generated labels for one draft
intervention followed by the lab's ValueAgent policy. It is not an on-policy test
of repeatedly deploying the learned specialist in a season. Simulator uncertainty,
fixed hidden state, non-event-matched randomness and candidate/policy relativity
remain exactly the lab's limitations. Uncertainty across the small held-out seed
panel includes noisy label estimates and is descriptive, not a benchmark claim.

## Optional tool adapter

Python callers can use:

```python
from gm_bench.draft_specialist import rank_candidates
ranked = rank_candidates(public_draft_observation, legal_draft_actions, model)
action = ranked[0]["action"]
```

Or pass three JSON files to the CLI:

```sh
python3 -m gm_bench.draft_specialist rank model.json observation.json candidates.json \
  --out ranked.json
```

The adapter checks model integrity/provenance, draft phase, remaining current-season
pick, unique candidate IDs and public prospect membership. It returns preference-
ranked actions with stable ID tie-breaking. It invokes no simulator, model API or
external process. An agent can choose whether to apply the suggestion; the adapter
does not alter any frozen agent/tool interface. Supply a fresh full public draft
observation before each use. Models require matching source and Python provenance.

## Bounds and artifacts

Fit/evaluate accept 2–16 unique seed episodes per split, 2–12 candidates per lab
comparison and one label horizon of 1–3 season completions. The demo caps downstream
rollouts at 16 per split and episode seeds at the public 1–32 allowlist. Maximum
demo work is 32 × 12 × 16 × 3 season completions plus bounded prefixes; the default
is 8 × 4 × 4 × 2. This upper bound can take minutes: use the default or the test smoke
(2 train seeds, 2 test seeds, 2 candidates, 1 rollout, horizon 1) for a quick check.
No season is counted as an independent uncertainty sample.

- `schemas/draft_specialist_model.schema.json`: weights, scales, feature order,
  label horizon/policy, source provenance, training seed panel and comparison IDs.
- `schemas/draft_specialist_evaluation.schema.json`: held-out episode selections,
  heuristic comparison, candidate gaps, uncertainty and scientific limitations.
- Foundation comparison files retain all labels and RNG audits for inspection.

Review/merge the counterfactual foundation before this dependent specialist PR.

## Recorded default smoke result

The default command on Python 3.12.14 (train 1–4, test 17–20, four candidates,
four rollouts, horizon 2) produced:

| Diagnostic | Result |
| --- | ---: |
| Held-out episode seeds | 4 |
| Mean estimated ranker score minus heuristic | -6.031 |
| Descriptive normal 95% interval | [-15.090, 3.028] |
| Ranker mean estimated candidate gap | 8.166 |
| Heuristic mean estimated candidate gap | 2.135 |

The learned baseline underperformed the heuristic on this smoke panel. This is
useful negative evidence that the pipeline works, not evidence of policy
improvement. No hyperparameters were retuned on these test outcomes. Full labels,
weights and per-episode choices are regenerated by the walkthrough command.
