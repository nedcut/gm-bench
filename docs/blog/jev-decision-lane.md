# A model that answers questions instead of writing the batch (2026-09-18)

TypeSafe's Jev is not a chat model. You send it a state and a list of typed
questions, and it returns one typed answer per question: a probability for a
yes/no, one option from a list, a position on a scale. It never produces text.
Every other GM-Bench adapter forwards the model's JSON action batch verbatim;
Jev cannot produce one. So the harness gained a second kind of lane, and this
post explains what was run, what the number means, and why it is published
beside the sota-v5 headline rather than in it.

## What ran

The adapter (`examples/typesafe_jev_agent.py`) sends the exact compact
observation every chat lane is prompted with as Jev's state, asks one fixed
batch of 25 to 40 questions per decision phase (which free agent and for how
long, whom to release, whom to dress, whom to draft or scout, accept or reject
each incoming offer, which trade to propose), and composes the action batch
from the answers under published rules. Every choice is Jev's; the host only
enforces legality.

The run used the sota-v5 contract (`a600b7da0c302231`), the same 29-seed
private panel as the published headline rows, five seasons, one episode per
seed, one paid call per decision, and the same eight scripted baselines. Route:
OpenRouter's decisions endpoint, upstream TypeSafe, served model
`jev-1.13-20260917`.

| | |
| --- | --- |
| Decisions | 580 of 580, 0 failed, every question answered |
| Mean score | 229.0 (sd 41.1) |
| vs baseline-panel mean (175.3) | +53.7, 95% CI 37.5 to 69.5, won 25 of 29 seeds |
| vs pick-trader (247.1) | -18.1, won 9 of 29 seeds, unadjusted sign-flip p 0.081 |
| Illegal actions | 8 |
| Cost | $0.33, 0.42 s per call |

Jev beat random, conservative, and rebuild on every seed, win-now and value on
25 of 29, split evenly with shrewd, and trailed strategic and pick-trader.
Leave-one-seed-out on the pick-trader contrast changes the unadjusted verdict
in 2 of 29 folds, so "does not reject against pick-trader" is not a stable
finding either way. The full aggregate-only analysis is in
`results/analysis/decision-lane-typesafe-jev-1.13-openrouter.md`.

## What the number is not

- **It is not a Jev score.** A chat model decides which actions to take and
  how many; Jev answers a list the host wrote. The row measures Jev plus this
  question set, and a different question set would be a different row. The
  scaffold fingerprint (`e1fc1e298283f465`) attests which set this was.
- **It is not a twelfth headline row.** The sota-v5 family of sixteen was
  pre-registered and frozen before the panel ran. This row was neither, so it
  carries no Holm-adjusted p-value and does not change any headline count.
- **It is not comparable with the chat rows.** Same contract, same panel, same
  baselines, different system. The comparison it supports is against the
  scripted policies, which is why the table above is built from those.
- **Zero malformed output means nothing here.** There is no text to misformat.

## Where it lives

The redacted artifact is `results/leaderboard/decision-lane/typesafe-jev-1.13-openrouter.json`.
It sits in its own directory so that everything which reads
`results/leaderboard/sota-v5/` as "the registered eleven" keeps meaning that.
It validates under the `sota-v5` policy with its own scaffold fingerprint, and
the site renders it in a separate "Decision-model lane" section; the web build
fails if the row ever reaches the headline array, the eligible-headline count,
or the shot chart. Lane notes, wire format, composition rules, and caveats:
`docs/typesafe_jev_lane.md`.
