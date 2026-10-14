# GM-Bench 2.0: a model in its own harness (DRAFT, not published)

> **Draft.** Updated 2026-10-14 for the owner to review before final
> publication. Ten panel rows are public under `results/agentic/`; a 2.0
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

Ten rows on the frozen 32-seed private panel, five seasons, each harness in
a firewalled Docker container:

| row | mean | vs `pick-trader` (95% interval) | tokens / decision | cost, whole panel |
|---|---|---|---|---|
| Codex 0.156.1 · `gpt-6-luna` | 227.4 | −21.8 (−43.3 to +0.1) | 518K | $4.54 est., lower bound |
| Claude Code 2.1.281 · `claude-sonnet-5` | 227.4 | −21.8 (−47.2 to +3.5) | 843K | $157.38 est. |
| Claude Code 2.1.281 · `claude-haiku-4-5` | 130.1 | −119.1 (−132.8 to −104.5) | 252K | $27.71 est. |
| Cursor 2026.09.26-dd393fe · `composer-2.5` | 230.6 | −18.6 (−35.6 to −1.4) | 255K | unmeasured |
| OpenCode 1.18.31 · `opencode-go/deepseek-v4.1-flash` | 247.1 | −2.0 (−22.4 to +18.0) | 618K | $3.69 (OpenCode's figure) |
| Codex 0.162.1 · `gpt-6.1-sol` | 273.2 | +24.0 (+1.6 to +45.8) | 137K | $17.38 est., lower bound |
| Claude Code 2.1.281 · `claude-haiku-5-5` | 202.7 | −46.5 (−66.7 to −26.7) | 393K | $4.89 est., lower bound |
| Codex 0.162.1 · `gpt-6-astra` | 288.4 | +39.2 (+15.6 to +63.1) | 123K | $115.04 est., lower bound |
| OpenCode 2.0.27 · `opencode-go/deepseek-v4.1-flash` | 244.6 | −4.6 (−25.8 to +17.0) | 661K | $4.91 (OpenCode's figure) |
| Claude Code 2.1.281 · `claude-sonnet-5-5` | 217.1 | −32.1 (−56.3 to −9.7) | 295K | $38.31 est. |

Every row is in the agentic execution lane, inside the harness it names. A
decision is one phase (20 per episode), and its tokens are everything the
harness sent and received in it, cached input included. "est." is an
API-equivalent estimate, not a bill (see Cost disclosures).

`pick-trader`, the scripted reference policy, averages 249.2 on these seeds.
All ten rows closed all 640 phases themselves. All ten are flagged
`unpinned`: the served model version is not pinned, so they may not be
reproducible. Under the frozen eligibility rule they are extra data points,
not headline results.

## What the numbers say

Haiku 4.5 is clearly below the scripted bar: it loses to `pick-trader` on
every seed. Haiku 5.5, on the same harness, is also clearly below it: a
paired lift of −46.5, 95% interval −66.7 to −26.7, sign-flip p 0.0002,
ahead on 9 of 32 seeds, beyond its realized minimum detectable difference
of about 29. Sonnet 5.5 is below it too: −32.1, 95% interval −56.3 to
−9.7, sign-flip p 0.012, ahead on 11 of 32 seeds. That lift is about the
size of its realized minimum detectable difference (about 33), and under
a Holm correction across the ten rows it is not significant (adjusted p
about 0.085), so the margin is thin. Its predecessor `claude-sonnet-5`
averaged 227.4 on the same harness, but 2.0 does not test rows against
each other. Sonnet 5.5 played fast and cheap by comparison: 2.9 minutes
and 107 tool calls per episode against 14.5 minutes for Sonnet 5, and
$38.31 for the panel against $157.38. For `gpt-6-luna` and `claude-sonnet-5` the panel cannot tell. Per-seed
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
difference of about 29 points, that is "cannot tell", not "on par". The same model
and OpenCode Go plan on OpenCode 2.0.27 gives the same answer: −4.6,
interval −25.8 to +17.0 (p = 0.67), ahead on 12 of 32 seeds, realized
minimum detectable difference about 30. The two harness versions are two
rows, and the 2.5-point gap between them is well inside either interval.
A first 2.0.27 panel was discarded, unpublished: OpenCode 2.0.27 sent the
first request of every invocation before the GM-Bench tools had
connected, and the agent spent its opening steps probing for them. The
driver fix (#193) played the published panel.

`gpt-6.1-sol` on Codex 0.162.1 is the first 2.0 row whose interval lies
above `pick-trader`: a paired lift of +24.0, 95% interval +1.6 to +45.8,
sign-flip p 0.046, ahead on 23 of 32 seeds. The evidence is marginal in
the same way as Cursor's, in the other direction: the lower bound is 1.6
points, the lift is below the row's realized minimum detectable difference
of about 32, and the row is one unpinned run on one panel. Each row's
p-value is its own, not adjusted for the ten rows; under a Holm correction
across them neither this 0.046 nor Cursor's 0.047 would be significant.
The agent made
36 `draft` calls across the 160 draft phases and 518 `trade` calls.

`gpt-6-astra`, on the same Codex 0.162.1 setup, has the highest 2.0 mean so
far and the clearest result above the scripted bar: a paired lift of
+39.2, 95% interval +15.6 to +63.1, sign-flip p 0.0036, ahead on 20 of 32
seeds. The lift is larger than its realized minimum detectable difference
of about 34, and it stays significant under a Holm correction across the
ten rows (adjusted p about 0.029). It is still one unpinned run on one
panel, and its interval overlaps `gpt-6.1-sol`'s. It used 123K tokens per
decision, the fewest of any row, and made 49 `draft` calls and 435
`trade` calls. These are separate contrasts against the scripted
reference, not tests between model or harness rows.

## Cost disclosures

Eight panel rows have `summary.usage.cost_usd: null` and zero decisions
with measured cost. The two OpenCode rows carry OpenCode's own cost figure.
Subscription quota use is not a per-token bill.

| row | API-equivalent estimate for the whole 32-episode panel |
|---|---|
| Codex · `gpt-6-luna` | $4.54, a lower bound at short-context list prices |
| Claude Code · `claude-sonnet-5` | $157.38 at API list prices |
| Claude Code · `claude-haiku-4-5` | $27.71 at API list prices, corrected from $25.14 |
| Cursor · `composer-2.5` | Unmeasured; no harness-reported cost or model list price |
| OpenCode · `deepseek-v4.1-flash` | $3.69 as OpenCode reports it, on an OpenCode Go subscription; no API-equivalent estimate |
| Codex · `gpt-6.1-sol` | $17.38, a lower bound at short-context list prices |
| Claude Code · `claude-haiku-5-5` | $4.89, a lower bound at the up-to-100K-token list prices; about $12 to $16 with the over-100K tier |
| Codex · `gpt-6-astra` | $115.04, a lower bound at short-context list prices; re-derived at redaction because the model had no price entry when the panel ran |
| OpenCode 2.0.27 · `deepseek-v4.1-flash` | $4.91 as OpenCode reports it, on an OpenCode Go subscription; no API-equivalent estimate |
| Claude Code · `claude-sonnet-5-5` | $38.31 at API list prices |

These estimates come from recorded token usage and the repository's dated
price entries; they do not measure the subscription's bill or establish
cost-efficiency comparisons. All three Codex artifacts flag possible long-context
requests, whose higher rates the estimate cannot reconstruct. The Haiku 5.5
artifact flags the same: Haiku 5.5 prices a request whose prompt is over
100,000 tokens at 5x on every category, 1,037 of the panel's 2,837
requests were, and repricing those from the per-request frames in the
retained event streams gives about $12 to $16 (a range, because Claude
Code's stream does not give output tokens per request). The Haiku 4.5
correction landed in #169: retained events identify 1-hour cache writes
that had been priced at the 5-minute rate. The artifact preserves the old
figure beside the recomputed estimate, and no score changed. Details are
in the [operator guide](../agentic_lane.md#publishing-a-row).

## What to keep in mind

- **A post-hoc audit rule admits the Haiku 4.5 row.** In 4 episodes Haiku drafted
  6 prospects by guessing their ids instead of listing the draft class. The
  audit originally counted that as a violation. After the panel ran, the rule
  was narrowed: prospect ids are assigned independently of hidden potential,
  so a guessed pick is blind. The change and its reason are in
  `docs/bench_v2_spec.md`.
- **A second post-hoc audit rule admits the Sonnet 5.5 row.** In one
  episode Sonnet 5.5 signed a free agent whose id the listing had not
  shown, at the minimum salary for one year, said it had used the wrong
  id, and released him on the next call. The audit counted the signing as
  a violation. After the panel ran, the rule was narrowed the same way:
  player ids are generation order, drawn independently of hidden
  potential, so a guessed signing is blind. The other option was to
  discard the panel and re-run it, which would have meant choosing a
  sample by the model's own behaviour.
- **Harness defaults.** Every row ran at the harness's default reasoning
  effort. Claude Code runs without web tools and loads each game tool's schema
  through ToolSearch; Codex and Cursor keep their built-in tools. The
  `gpt-6-luna` row ran with the ChatGPT account's connected apps and
  installed plugins available to the agent and recorded no call to them;
  the `gpt-6.1-sol` and `gpt-6-astra` rows ran with them turned off, on
  Codex 0.162.1 rather than 0.156.1, so `gpt-6-luna` does not share their
  harness setup. Cursor's
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
