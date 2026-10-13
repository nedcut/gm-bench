# GM-Bench 2.0: a model in its own harness (DRAFT, not published)

> **Draft.** Updated 2026-10-13 for the owner to review before final
> publication. Six panel rows are public under `results/agentic/`; a 2.0
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

Six rows on the frozen 32-seed private panel, five seasons, each harness in
a firewalled Docker container:

| row | mean | vs `pick-trader` (95% interval) |
|---|---|---|
| Codex 0.156.1 · `gpt-6-luna` | 227.4 | −21.8 (−43.3 to +0.1) |
| Claude Code 2.1.281 · `claude-sonnet-5` | 227.4 | −21.8 (−47.2 to +3.5) |
| Claude Code 2.1.281 · `claude-haiku-4-5` | 130.1 | −119.1 (−132.8 to −104.5) |
| Cursor 2026.09.26-dd393fe · `composer-2.5` | 230.6 | −18.6 (−35.6 to −1.4) |
| OpenCode 1.18.31 · `opencode-go/deepseek-v4.1-flash` | 247.1 | −2.0 (−22.4 to +18.0) |
| Codex 0.162.1 · `gpt-6.1-sol` | 273.2 | +24.0 (+1.6 to +45.8) |

`pick-trader`, the scripted reference policy, averages 249.2 on these seeds.
All six rows closed all 640 phases themselves. All six are flagged
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
0.0469, so the evidence is marginal. It beats `pick-trader` on 12 of 32 seeds. Its realized minimum
detectable difference is about 25 points.

DeepSeek V4.1 Flash on OpenCode lands closest to the scripted bar: a
paired lift of −2.0 with an interval from −22.4 to +18.0 (p = 0.84), ahead
of `pick-trader` on 15 of 32 seeds. With a realized minimum detectable
difference of about 29 points, that is "cannot tell", not "on par".

`gpt-6.1-sol` on Codex 0.162.1 is the first 2.0 row whose interval lies
above `pick-trader`: a paired lift of +24.0, 95% interval +1.6 to +45.8,
sign-flip p 0.046, ahead on 23 of 32 seeds. The evidence is marginal in
the same way as Cursor's, in the other direction: the lower bound is 1.6
points, the lift is below the row's realized minimum detectable difference
of about 32, and the row is one unpinned run on one panel. Each row's
p-value is its own, not adjusted for the six rows; under a Holm correction
across them neither this 0.046 nor Cursor's 0.047 would be significant.
The agent made
36 `draft` calls across the 160 draft phases and 518 `trade` calls. These
are separate contrasts against the scripted reference, not tests between
model or harness rows.

## Cost disclosures

Five panel rows have `summary.usage.cost_usd: null` and zero decisions
with measured cost. The OpenCode row carries OpenCode's own cost figure.
Subscription quota use is not a per-token bill.

| row | API-equivalent estimate for the whole 32-episode panel |
|---|---|
| Codex · `gpt-6-luna` | $4.54, a lower bound at short-context list prices |
| Claude Code · `claude-sonnet-5` | $157.38 at API list prices |
| Claude Code · `claude-haiku-4-5` | $27.71 at API list prices, corrected from $25.14 |
| Cursor · `composer-2.5` | Unmeasured; no harness-reported cost or model list price |
| OpenCode · `deepseek-v4.1-flash` | $3.69 as OpenCode reports it, on an OpenCode Go subscription; no API-equivalent estimate |
| Codex · `gpt-6.1-sol` | $17.38, a lower bound at short-context list prices |

These estimates come from recorded token usage and the repository's dated
price entries; they do not measure the subscription's bill or establish
cost-efficiency comparisons. Both Codex artifacts flag possible long-context
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
  through ToolSearch; Codex and Cursor keep their built-in tools. The
  `gpt-6-luna` row ran with the ChatGPT account's connected apps and
  installed plugins available to the agent and recorded no call to them;
  the `gpt-6.1-sol` row ran with them turned off, on Codex 0.162.1 rather
  than 0.156.1, so the two Codex rows do not share a harness setup. Cursor's
  servers add seven default User Rules; the prompt audit found only those
  on every panel episode. Cursor's reasoning effort and compactions are
  unmeasured. The container can reach the public internet. The committed
  harness tool counts record no web-search or fetch tool use; they do not
  prove an absence of network access through shell commands.
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
