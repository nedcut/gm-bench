# Deferred changes for the next 2.0-lane contract version

GM-Bench 2.0 is frozen at agentic fingerprint `07de948a4f4afbae`
(`docs/bench_v2_spec.md`). Everything below was found after the freeze. Each
item either changes a fingerprinted file (`gm_bench/agentic/tools.py`,
`brief.py`, `episode.py`, `mcp_server.py`), so fixing it is a new benchmark
version, changes a post-hoc rule that a published row relied on, or is a
driver change that can alter future measurements without a version bump
(disclosed per the spec's freeze rules). None of them is fixed in 2.0. The spec reserves 2.1 for simulator mechanics; these
items ride on whichever contract version comes next.

Recorded 2026-09-28 from the pre-release audit. Line references are to
`main` at `c19a1b7`.

## Contract behaviour that differs from 1.0 without a reason

These also appear in the spec under "How 2.0 differs from 1.0 beyond the
interface", because they affect any 1.0-versus-2.0 comparison.

1. **Penalty parity for malformed calls.** A tool call that fails the input
   schema is rejected before the simulator and not penalized
   (`episode.py` `_execute`, `tools.py` `validate_arguments`). The same
   mistake in 1.0 is a protocol violation. Decide whether schema failures on
   move tools should count as illegal actions, as in 1.0, or stay free, and
   make the schema and the simulator agree on ranges (`years` has
   `minimum: 1` and no maximum in the schema; the simulator allows 1 to 5).
2. **Draft class visibility and scouting.** `list_draft_class` answers only
   in the draft phase, while 1.0 shows a draft class summary in every phase.
   `scout` accepts a prospect id in any phase, so the only way to scout
   prospects before the draft is to guess their ids, which the audit then
   reports as `guessed_read`. Either list the class (or its summary) in
   every phase, or restrict prospect scouting to the draft phase.
3. **`inspect_player` promises prospects.** Its description says "any team,
   free agent, or prospect", but `League._inspect_player` looks the id up in
   signed players only and answers "unknown player id" for a prospect. Fix
   the lookup or the description.

## Engine and server defects

4. **Non-object arguments are logged as `{}`.** `episode.py` `_log_call`
   (about line 289) writes `arguments` as `{}` when the call's arguments were
   not an object. Live, such a call fails with "arguments must be an
   object"; on replay it runs with `{}`, which is valid for tools with no
   required arguments (`end_phase`, the read tools). Replay can then diverge
   from the live episode. Log the raw value, or log the call as not executed.
5. **A call queued on the dispatch lock can run after `stop()`.**
   `SocketMcpServer.stop()` sets `_stop`, hangs up on every connection and
   joins their threads, but a request already read and waiting on
   `dispatch_lock` in `_LockedMcpServer._dispatch` still executes when it
   gets the lock. Check `_stop` inside the lock and refuse the call.
6. **Accept-loop admission.** A deferred review nit on the atomicity of
   connection admission against `stop()` in `SocketMcpServer._accept_loop`.
   The current code registers a connection under `_live_lock` and re-checks
   `_stop` there; review it again together with item 5.
7. **Guard notice rounding.** The phase-guard notice formats the guard with
   `:.0f`, so a sub-second guard (tests only) prints as `0s`. Cosmetic, but
   the text is a contract source.
8. **The stdio entry point resets the guard clock.** `AgenticEpisode.from_ledger`
   restores recorded phase durations but starts the open phase's guard
   clock from the reload, so a restarted stdio server gives the open phase a
   fresh guard period. The socket path the driver uses keeps one engine for
   the whole episode and is not affected.

## Driver behaviour to settle before the next panel

These are driver files, so they can change without a version bump, but a
change alters what a new row measures against the existing ones.

9. **Retry time off the phase clock only for OpenCode.** The driver takes a
   provider stall's backoff off the guard clock when the harness exits on a
   retryable error, and OpenCode's silent in-process 429 retries are caught
   by the silent-harness stop. Claude Code's in-process `api_retry` waits and
   Codex's stream reconnects happen inside a running invocation, so they
   count against the phase guard. No panel phase came near the guard, but
   the treatment is unequal across harnesses.

## Audit and publication

10. **Id-based audit failures can be sidestepped.** A successful read on a
    guessed id (`scout`, `inspect_player`, `inspect_team`) marks the id as
    seen, so an agent with leaked ids could read each one before moving on
    it and pass as clean. The audit also cannot catch a leak of values
    rather than ids (for example true potential). Consider a
    publication-time check that ranks the players an agent drafted or
    signed by true potential against the public prediction: an agent that
    systematically beats the public estimate without scouting is using
    hidden information.
11. **Rows do not record which audit rules admitted them.** `audit.py` is
    post-hoc and not fingerprinted, and the guessed-draft-pick exception
    (#163) was added after a panel had run. Record an audit version or
    digest in each row (or fingerprint `audit.py`), so a row says which
    rules it passed.
12. **What the harness sends the model is not fingerprinted.** The
    fingerprint covers the tool surface and brief the server offers, not
    the harness's own system prompt, tool list or deferral (Claude Code
    shows MCP tools by name and loads schemas through ToolSearch). The
    prompt check proposed in #166 (merged 2026-09-28) records what
    each harness sends; decide whether a row should carry it.

## Brief and tool-schema clarity

Recorded 2026-10-14 from the `claude-opus-5-5` panel. Both would change a
fingerprinted file (`brief.py`, `tools.py`), so they are candidate
clarifications for the next contract, not 2.0 changes.

13. **The end-of-episode credit does not say when it is counted.** The
    brief describes the term only as "a capped credit for the roster,
    prospects, picks and cap health you leave behind". Nothing in it says
    that contracts expiring at the end of the final season leave the
    roster before that credit is taken (`get_rules` says an unextended
    player expires to free agency at season end, but not that this
    applies before final scoring). Opus 5.5 played the last season to win
    now, let contracts run out, and three of its 32 episodes ended with
    zero total assets and zero roster depth. State the timing in the
    brief.
14. **The tradable pick-season window is not in the tool schema.** The
    `give_pick_seasons` and `receive_pick_seasons` arguments of `trade`
    and `counter_trade_offer` are described only as "draft seasons, e.g.
    [4, 5]". The window shifts each season (the next
    `PICK_TRADE_MAX_SEASONS_AHEAD` seasons); `get_rules` shows it for the
    current season only. A pick season outside it is an illegal move: 33
    of `claude-opus-5-5`'s 59 and 24 of `claude-sonnet-5-5`'s 37 illegal
    moves. The picks the status lists include the current season's,
    which cannot be traded. Name the window in the argument description or
    beside the listed picks.

## Simulator and scoring

Found 2026-10-14 while estimating the score ceiling
([score_ceiling.md](score_ceiling.md)). Both change `gm_bench/simulator.py`
or `gm_bench/scoring.py`, which the 1.0 contract fingerprints and 2.0 plays
unchanged, so either fix is a new contract version on both lanes. Neither is
fixed in 1.0 or 2.0. **Items 15, 16 and 18 are fixed in 2.1**
([bench_v2_1_spec.md](bench_v2_1_spec.md)), built on top of both contracts
without editing either.

15. **Team records never reset between seasons.** `League.simulate_season`
    zeroes `wins` and `losses` only when no partial season was played, and
    `simulate_partial_season` never zeroes them. Every episode plays the
    midseason leg (`EpisodeConfig.include_midseason` is on, and the agentic
    episode calls `prepare_midseason` too), so records accumulate over the
    whole episode: a `pick-trader` season summary on seed 101 reads 17-16,
    40-26, 58-41, 78-54, 94-71. The bug came in with the midseason port
    (`afab3cd`). What it touches:
    - `score_components` sums `summaries[-3:]` wins, which is cumulative
      wins after seasons 3, 4 and 5, so per-season wins are weighted
      3, 3, 3, 2, 1 instead of 0, 0, 1, 1, 1. The term meant to reward
      recent results rewards early ones most, and is about 88 of
      `pick-trader`'s ~238 points.
    - Playoff qualification and seeding (top eight by `wins`), the draft
      lottery group and slot order (`_inverse_standings`), and the
      free-agent win signal (`_team_win_signal`, whose docstring promises
      the current season's record) all read the running total.
    - The public standings show the running total as the season record.
    Fix: zero records at the start of each season (in
    `simulate_partial_season` when it opens a season, or at the rollover in
    `simulate_season`), then rescale `recent_win` if the term should keep
    its share of the score.
16. **Single-game playoffs dominate the score's variance.** The bracket is
    one game per tie, and `playoff_rounds` plus `championships` are worth up
    to 81 + 175 points. Replacing each season's realized playoff result with
    its exact expectation given the playoff ratings (the "luck-neutral"
    score in `scripts/ceiling_search.py`) leaves the `pick-trader` mean
    unchanged (245.4 realized, 249.2 luck-neutral, difference -3.9 +/- 4.2
    over seeds 101-160) and cuts its across-seed SD from 42.3 to 25.5:
    about 64% of the score variance is playoff dice. A clairvoyant search
    that sees those dice gains about 130 points over `pick-trader`, almost
    all in playoff terms. Options for the next contract: best-of series,
    scoring expected playoff value from the bracket (as the diagnostic
    does), or lowering the playoff weights. Replaying all eleven published 2.0
    panel rows under the luck-neutral score (no model calls) cut their mean
    minimum detectable difference from 30.8 to 18.1 points and changed no
    row's direction (`docs/score_ceiling.md`). Scoring expected playoff
    value changes no simulation, so existing ledgers can be rescored
    exactly; best-of series would need new runs. A concrete scoring rule
    covering this item and the scoring half of item 15 is drafted in
    [score_v2_proposal.md](score_v2_proposal.md).
17. **The end-state terms miss part of the future value `pick-trader`
    leaves.** Handing every final league to one scripted manager for five
    more seasons ([score_deep_dive.md](score_deep_dive.md) section 2), one
    point of end-state score predicts about one point of later winning
    value, but at equal end-state score every other team did about 35
    points worse over five seasons than `pick-trader`'s. **Explained,
    2026-10-15: mostly item 18.** Under the 2.1 rules the per-policy
    residual roughly halves with the draft fixed (`strategic` -9.6 to -5.0,
    `value` -12.8 to -7.7, seeds 11-58; `score_deep_dive.py continuation21`);
    what remains is mostly the picks `pick-trader` takes from opponents,
    which is legitimate and not scored (section 8 there).
18. **Opponents skip draft slots behind an unused user pick.**
    `League.run_opponent_draft(before_user=False)` finds the user's window
    again from the user's earliest *unexercised* slot. When the user holds
    two picks in one draft and uses one, that is the unused later pick, so
    every opponent slot between the two is never exercised. Scripted
    policies draft once, so `pick-trader` (which acquires picks) triggers it
    in 29 of 32 private-panel episodes, about 17 skipped opponent picks per
    episode; on public seeds 11-22 opponents make 43 picks per episode
    behind `pick-trader` against 55 behind `strategic`. No published model
    episode triggered it (every owned opponent slot was used in all 384).
    Inside the five-season episode it is worth about 2 points to
    `pick-trader` under score-v1 (not significant) and about 4 under 2.1;
    it compounds afterwards, because the opponents stay weaker. It is also
    an exploit open to a model: acquire a second pick, leave it unused.
    Fixed in 2.1 (`League21.run_opponent_draft`, which records where the
    user's window opened).
