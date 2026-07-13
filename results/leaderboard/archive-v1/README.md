# Archive: sota-v1 leaderboard rows

These artifacts (`claude-sonnet-medium.json`, `codex-gpt-5.6-luna-medium.json`,
`cursor-composer-2.5.json`, `cursor-grok-4.5-xhigh.json`,
`ollama-gemma4-e4b.json`, `ollama-qwen3-5-latest.json`,
`openrouter-gpt-5.6-luna.json`) were produced under the
`sota-v1` contract (`gm_bench.contract`: `sota-v1` / `actions-v1` / `sim-v1`,
frozen at fingerprint `cf2607e59dba0c7f`). They were moved here when the
contract bumped to `sota-v2` and are no longer current leaderboard rows.

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
`player_id`, so baseline scouting worked as intended in every row here. The
practical effect is that each row's candidate-vs-baseline comparison
understates the candidate — the model paid the same scouting decision budget
but, when it used `prospect_id`, got no scouting intel back for it, while the
baselines it's compared against did.

`sota-v2` fixes the contract so `scout` accepts either `player_id` or
`prospect_id` (schema, simulator, and prompt now agree), and adds
`failed_queries` as a first-class counter in episode results, run summaries,
and comparison blocks, so a run like this would no longer be silent.

## Comparability

- Rows in this directory are internally comparable with each other: they
  share the `sota-v1` contract, baseline panel, and reference means.
- They are **not** comparable with any `sota-v2` row. The contract
  fingerprint changed, and the scout fix changes candidate behavior (and, for
  models that used `prospect_id`, candidate score) in a way that does not
  affect the baseline panel. A `sota-v1` score and a `sota-v2` score for the
  same model are not the same measurement.
- Do not merge, re-normalize, or otherwise combine these rows with current
  `results/leaderboard/*.json` rows on the live leaderboard.
- Archived rows remain structurally auditable with
  `python -m gm_bench validate-result <path> --policy sota-v1`.
