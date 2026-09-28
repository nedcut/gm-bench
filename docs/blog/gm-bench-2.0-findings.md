# GM-Bench 2.0: a model in its own harness (DRAFT, not published)

> **Draft.** Written 2026-09-28 for the owner to revise before the 2.0 release
> is tagged. Numbers are from the committed rows under `results/agentic/`.
> Cost figures are left out on purpose until the pending driver and pricing
> fixes land.

GM-Bench 1.0 asked a model one bounded question per decision phase and read
back a JSON batch of moves. GM-Bench 2.0 hands the same five-season hockey
league to a model running inside its own agent harness (OpenCode, Codex CLI or
Claude Code). The model plays each episode as one continuous session, calling
tools on an MCP server to read the league, make moves and end each phase. The
simulator, the scoring and 29 of the 32 private seeds are the ones 1.0 used.

## What ran

Three rows on the frozen 32-seed private panel, five seasons, each harness in
a firewalled Docker container:

| row | mean | vs `pick-trader` (95% interval) |
|---|---|---|
| Codex 0.156.1 · `gpt-6-luna` | 227.4 | −21.8 (−43.3 to +0.1) |
| Claude Code 2.1.281 · `claude-sonnet-5` | 227.4 | −21.8 (−47.2 to +3.5) |
| Claude Code 2.1.281 · `claude-haiku-4-5` | 130.1 | −119.1 (−132.8 to −104.5) |

`pick-trader`, the scripted reference policy, averages 249.2 on these seeds.
All three rows closed every phase themselves. All three are flagged
`unpinned`: the served model version is not pinned, so they may not be
reproducible.

## What the numbers say

Haiku is clearly below the scripted bar: it loses to `pick-trader` on every
seed. For `gpt-6-luna` and `claude-sonnet-5` the panel cannot tell. Per-seed
lifts varied more than the design assumed, so on these panels the smallest
difference from `pick-trader` the benchmark can reliably detect is about 31
to 36 points. A lift of −21.8 with an interval that crosses zero is "cannot
tell", not "on par". The two rows having the same mean is a coincidence and
supports no comparison between them: 2.0 ranks nothing.

## What to keep in mind

- **A post-hoc audit rule admits the Haiku row.** In 4 episodes Haiku drafted
  6 prospects by guessing their ids instead of listing the draft class. The
  audit originally counted that as a violation. After the panel ran, the rule
  was narrowed: prospect ids are assigned independently of hidden potential,
  so a guessed pick is blind. The change and its reason are in
  `docs/bench_v2_spec.md`.
- **Harness defaults.** Every row ran at the harness's default reasoning
  effort. Claude Code runs without web tools and loads each game tool's schema
  through ToolSearch; Codex keeps its built-in tools. The container can reach
  the public internet. No panel agent used the web.
- **2.0 versus 1.0 is not only agency.** A 2.0 agent can make any number of
  tool calls per phase, where a paid 1.0 agent got one call per phase. Malformed
  tool calls are rejected without penalty, and the draft class is visible only
  in the draft phase. None of these models has a 1.0 row to pair with anyway.

Specification: `docs/bench_v2_spec.md`. Operator guide:
`docs/agentic_lane.md`. Known defects queued for the next contract version:
`docs/bench_v2_1_queue.md`.
