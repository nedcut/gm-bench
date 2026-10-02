# GM-Bench 2.0: a model in its own harness (DRAFT, not published)

> **Draft.** Updated 2026-10-02 for the owner to review before final
> publication. Four panel rows are public under `results/agentic/`; a 2.0
> tag and GitHub release have not been cut. Numbers and cost disclosures
> below reflect the committed artifacts, including the merged release fixes.

GM-Bench 1.0 asked a model one bounded question per decision phase and read
back a JSON batch of moves. GM-Bench 2.0 hands the same five-season hockey
league to a model running inside its own agent harness (OpenCode, Codex CLI,
Claude Code or the Cursor CLI). The model plays each episode as one continuous
session, calling tools on an MCP server to read the league, make moves and
end each phase. The simulator, the scoring and 29 of the 32 private seeds
are the ones 1.0 used.

## What ran

Four rows on the frozen 32-seed private panel, five seasons, each harness in
a firewalled Docker container:

| row | mean | vs `pick-trader` (95% interval) |
|---|---|---|
| Codex 0.156.1 · `gpt-6-luna` | 227.4 | −21.8 (−43.3 to +0.1) |
| Claude Code 2.1.281 · `claude-sonnet-5` | 227.4 | −21.8 (−47.2 to +3.5) |
| Claude Code 2.1.281 · `claude-haiku-4-5` | 130.1 | −119.1 (−132.8 to −104.5) |
| Cursor 2026.09.26-dd393fe · `composer-2.5` | 230.6 | −18.6 (−35.6 to −1.4) |

`pick-trader`, the scripted reference policy, averages 249.2 on these seeds.
All four rows closed all 640 phases themselves. All four are flagged
`unpinned`: the served model version is not pinned, so they may not be
reproducible. Under the frozen eligibility rule they are extra data points,
not headline results.

## What the numbers say

Haiku is clearly below the scripted bar: it loses to `pick-trader` on every
seed. For `gpt-6-luna` and `claude-sonnet-5` the panel cannot tell. Per-seed
lifts varied more than the design assumed, so on these panels the smallest
difference from `pick-trader` the benchmark can reliably detect is about 31
to 36 points. A lift of −21.8 with an interval that crosses zero is "cannot
tell", not "on par". The two rows having the same mean is a coincidence and
supports no comparison between them: 2.0 ranks nothing.

Cursor is also below the scripted bar, with a smaller margin: its paired
lift is −18.6, the interval excludes zero, and the sign-flip p-value is
0.0469. It beats `pick-trader` on 12 of 32 seeds. Its realized minimum
detectable difference is about 25 points. These are separate contrasts
against the scripted reference, not tests between model or harness rows.

## Cost disclosures

All four panel rows have `summary.usage.cost_usd: null` and zero decisions
with measured cost. Subscription quota use is not a per-token bill.

| row | API-equivalent estimate for the whole 32-episode panel |
|---|---|
| Codex · `gpt-6-luna` | $4.54, a lower bound at short-context list prices |
| Claude Code · `claude-sonnet-5` | $157.38 at API list prices |
| Claude Code · `claude-haiku-4-5` | $27.71 at API list prices, corrected from $25.14 |
| Cursor · `composer-2.5` | Unmeasured; no harness-reported cost or model list price |

These estimates come from recorded token usage and the repository's dated
price entries; they do not measure the subscription's bill or establish
cost-efficiency comparisons. Codex's artifact flags possible long-context
requests, whose higher rates the estimate cannot reconstruct. The Haiku
correction landed in #169: retained events identify 1-hour cache writes
that had been priced at the 5-minute rate. The artifact preserves the old
figure beside the recomputed estimate, and no score changed. Details are
in the [operator guide](../agentic_lane.md#publishing-a-row).

## What to keep in mind

- **A post-hoc audit rule admits the Haiku row.** In 4 episodes Haiku drafted
  6 prospects by guessing their ids instead of listing the draft class. The
  audit originally counted that as a violation. After the panel ran, the rule
  was narrowed: prospect ids are assigned independently of hidden potential,
  so a guessed pick is blind. The change and its reason are in
  `docs/bench_v2_spec.md`.
- **Harness defaults.** Every row ran at the harness's default reasoning
  effort. Claude Code runs without web tools and loads each game tool's schema
  through ToolSearch; Codex and Cursor keep their built-in tools. Cursor's
  servers add seven default User Rules; the prompt audit found only those
  on every panel episode. Cursor's reasoning effort and compactions are
  unmeasured. The container can reach the public internet. No panel agent
  used the web.
- **2.0 versus 1.0 is not only agency.** A 2.0 agent can make any number of
  tool calls per phase, where a paid 1.0 agent got one call per phase. Malformed
  tool calls are rejected without penalty, and the draft class is visible only
  in the draft phase. None of these models has a 1.0 row to pair with anyway.

Specification: [bench_v2_spec.md](../bench_v2_spec.md). Operator guide:
[agentic_lane.md](../agentic_lane.md). The [clean-clone verification
guide](../REPRODUCING_GM_BENCH_2_0.md) validates the public compact rows;
withheld private seeds and raw event streams are needed to recompute the
original panel and audit. Known defects remain queued for a version
decision in [bench_v2_1_queue.md](../bench_v2_1_queue.md).
