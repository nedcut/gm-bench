# Withdrawn: the sota-v1 results

**These are not leaderboard rows. They are evidence of a defect.** The scores in
this directory have been withdrawn from the published leaderboard and are not a
valid ranking of the models in them — see [Comparability](#comparability).

The artifacts were produced under the `sota-v1` contract (`gm_bench.contract`:
`sota-v1` / `actions-v1` / `sim-v1`, frozen at fingerprint `cf2607e59dba0c7f`).
They are retained, unmodified, so the defect below stays independently auditable.

## Why archived

The `actions-v1` scaffold prompt told models to scout a prospect with
`{"type":"scout","prospect_id":1010001}`, but the `sim-v1` simulator only ever
read `action.get("player_id", -1)` and rejected `prospect_id`. A model that
followed the prompt's own documented example got back the unhelpful error "no
such player or prospect to scout" on every such call. In one 24-episode run
this happened 1,124 times. Because the failure was a non-penalized query
decline (`gm_bench/protocol.py` `QUERY_ACTION_TYPES`), it was also invisible:
it showed up nowhere in episode or run summaries, and that run's
`illegal_actions` count was 8.

**Every LLM candidate row in this directory was produced under that defect.**
Scripted baselines were not affected: `gm_bench/agents.py` always scouted with
`player_id`, so baseline scouting worked as intended in every row here. A model
that followed the prompt paid the full scouting decision budget and got no intel
back for it; the baselines it is scored against paid the same budget and got the
intel.

`sota-v2` fixes the contract so `scout` accepts either `player_id` or
`prospect_id` (schema, simulator, and prompt now agree), and adds
`failed_queries` as a first-class counter in episode results, run summaries,
and comparison blocks, so a run like this would no longer be silent.

## Comparability

**The defect did not fall evenly, so these rows are not comparable to each
other.** Whether a candidate was hit at all depended on which key it happened to
use — that is, on how closely it followed the prompt's own documented example.
Counting the rejection string in each artifact:

| artifact | silent scout rejections |
| --- | --- |
| `openrouter-gpt-5.6-luna.json` | 1124 |
| `cursor-composer-2.5.json` | 1060 |
| `cursor-grok-4.5-xhigh.json` | 824 |
| `ollama-qwen3-5-latest.json` | 8 |
| `ollama-gemma4-e4b.json` | 1 |
| `codex-gpt-5.6-luna-medium.json` | 0 |

Three candidates were penalized on the order of a thousand lookups; three were
effectively untouched. A handicap that lands on half the field and not the other
half does not preserve the ordering, so:

- These rows are **not** a valid ranking, and **not** internally comparable.
  An earlier version of this file claimed they were internally comparable. That
  claim was wrong and is retracted.
- They are **not** comparable with any `sota-v2` row either. The contract
  fingerprint changed, and a `sota-v1` score and a `sota-v2` score for the same
  model are not the same measurement.
- Do not merge, re-normalize, publish, or otherwise combine these rows with
  current `results/leaderboard/*.json` rows.
- They remain *verifiable* as authentic v1 artifacts —
  `python -m gm_bench validate-result <path> --policy archive-v1` — which
  asserts the frozen v1 contract and seed panel, and deliberately asserts
  nothing about eligibility. Two of these rows
  (`ollama-gemma4-e4b.json`, `ollama-qwen3-5-latest.json`) never cleared the
  strict `sota-v1` decision-failure-rate bar in the first place.
