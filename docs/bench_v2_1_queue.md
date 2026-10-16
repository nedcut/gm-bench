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
    **2.1 evidence, 2026-10-16** (`results/diagnostics/v21_behavior/behavior.json`): this is the largest
    single source of the OpenAI-Claude gap. Paired by seed, the three
    Codex rows lead `claude-opus-5-5` and `claude-sonnet-5-5` by 57.6
    points, and 45.5 of them come from the end-of-run roster terms
    (`family_gap.terms.end_roster`). Opus and Sonnet are scored on 4.56
    and 4.69 players, against 15.9-16.5 for the Codex rows
    (`end_of_run.roster_at_end`). 21 and 23 of their 32 episodes end
    with 5 or fewer players. In the season-5 preseason they make 2.91 and
    1.12 extensions per episode, against 11.06 for astra and 11.94 for
    sol. All 140 and 149 of their season-5 signings are one-year deals.
    Their final score is below the score after season 4 in 25 and 28 of
    32 episodes (`episodes_final_below_after_season_4`). Their own
    post-mortems give the reason: "the capped credit for future roster and
    picks will be low". The word "capped" is a candidate cause. In score-v2
    only cap room is clamped (-12 to +10). The total-asset, young-asset,
    pick, strength and depth terms are linear. Drop "capped", or say
    which part is capped, together with the timing.
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
    **2.1 evidence, 2026-10-16** (`results/diagnostics/v21_behavior/behavior.json`,
    `penalized_rejections`): across the six committed 2.1 rows the window
    causes 128 of the 285 penalized rejections (45%), in all six models.
    115 of those 128 offered the current season's pick, which the status
    lists among the team's picks (`rejections.pick_window_offering_current_season`).

Recorded 2026-10-16 from the 2.1 behaviour diagnostic
(`results/diagnostics/v21_behavior/behavior.json`, six committed 2.1 rows,
192 replayed episodes). Each item changes a fingerprinted file (`brief.py`,
`tools.py`, `episode.py`) unless it says otherwise. Counts are per row,
summed over its 32 episodes.

19. **The brief does not say when the season is played.** The rest of the
    regular season (about two thirds of it) and the playoffs are
    simulated when the **draft** phase closes (`AgenticEpisode._close_phase`
    calls `simulate_season`). The roster and lineup in force at that moment
    play them. The phase notes list the draft last, as "use your pick on a
    prospect", and the deadline as "last trades before the playoffs".
    They do not say that trades, signings and `set_lineup` stay open in
    the draft. Models act as if the season ended at the deadline:
    - Draftees left on the bench at draft close while outranking a dressed
      player at their position (`lineups.draftees_benched_outranking_a_dressed_player`):
      Sonnet 116 of 135, deepseek 103 of 141, luna 87 of 149, Opus 27 of
      77, against sol 3 of 39 and astra 0 of 48.
    - Sonnet set a lineup in none of its 160 draft phases
      (`drafts.set_lineup_in_draft`).
    - Across the six rows, models attempted 4 trades in the draft phase
      and 271 at the deadline, and signed no free agents in the draft.

    State the calendar in the brief and in the `end_phase` reply that
    opens the draft.
20. **A stored lineup persists, and new players dress only into empty
    slots.** `League._effective_lineup` keeps every stored id still on the
    roster and tops up with the best remaining players only to fill gaps.
    A signing, trade or draftee therefore stays on the bench until the
    agent calls `set_lineup` again. Neither the `set_lineup` description
    nor the brief says so. Strength with the stored lineup minus the
    engine's default lineup at draft close (`lineups.mean_gap_to_default_at_draft_close`):
    Sonnet -1.61, luna -1.11, Opus -0.89, deepseek -0.26, sol -0.11, astra
    -0.02. Draft closes more than 0.5 below the default: Sonnet 105, luna
    86, Opus 58, deepseek 48, sol 7, astra 1, out of 160 each. Document
    the persistence. Optionally show the default lineup's strength in
    `get_status`.
21. **Extension semantics are undocumented, and the price disagrees with
    them.** `years` counts from the current season, replaces the final
    contract year, and the new salary applies to this season's payroll at
    once (`League._extend_contract`). A 2-year extension in season 4 ends
    at the final rollover, so the player leaves before the end-of-run
    credit. Successful extensions ending at the final rollover
    (`end_of_run.extensions_ending_at_final_rollover`): Opus 315, astra
    256, sol 255, Sonnet 247, deepseek 218, luna 105. The schema allows
    `years: 1` and the simulator refuses it as a penalized move (3
    rejections, "extension years must be 2-5"; see item 1). The incumbent
    quote is priced as if the extension "begins next season"
    (`League._contract_quote` adds one more year of inflation), but the
    salary is charged now. Document the semantics in `extend_contract`.
    Then decide whether the simulator should start an extension next
    season or drop the extra inflation year. That half changes
    `gm_bench/simulator.py`, so it is a new contract on both lanes.
22. **The `end_phase` reply does not report the phase's rejected moves.**
    Models that batch calls close the phase without reading the last
    reply. Phases closed by an `end_phase` straight after a penalized
    rejection (`rejections.phases_closed_straight_after_a_penalized_rejection`):
    sol 22, astra 12, and 2 for each other row. List the phase's rejected
    and penalized calls in the `end_phase` reply (`episode.py`).
23. **"player is not an available free agent" does not say why.** 36
    penalized rejections across the six rows. At the time of the call, 31
    of the players were on another team (signed since the agent listed
    them) and 5 were on the waiver wire, where `claim_waiver` is the
    right tool (`rejections.not_an_available_free_agent`). Name the cause
    in the message (simulator message text, so also a simulator change).
24. **The trade rules are worded loosely.**
    - The brief says a counterparty stops talking "after a few declines".
      The code stops after 2 (`REJECTED_OFFER_LIMIT_PER_WINDOW`). Sonnet hit
      "broken off trade talks" 24 times (`rejections.partner_broke_off_talks`).
    - The per-partner limit of 2 completed trades a season
      (`TRADE_LIMIT_PER_PARTNER`) is penalized, although the brief says
      declines cost nothing. `get_rules` lists `trade_limit_per_partner: 2`
      with no unit and no penalty note. 10 penalized rejections ("partner
      has no appetite").
    - "trades must include assets from both teams" is in neither the brief
      nor the `trade` description. 13 penalized rejections.

    State all three in the `trade` description and `get_rules`.
25. **The brief pulls two ways on reading the status.** It says "Start
    each phase with `get_status`" and also that "calling everything every
    phase is a cost". Tool calls are reported, not scored. The Codex rows
    read the status in every phase. Opus and Sonnet end 61% and 71% of
    their phases without reading it (`status_habit.rate_ended_without_status_read`).
    82 of Opus's 88 and 81 of Sonnet's 97 empty phases have no status
    read (`empty_phases.without_status_read`). This difference, not missed
    decisions, drives most of the published empty-phase gap. 82 of Opus's
    88 empty phases are drafts with no pick to use, and one draft across
    the six rows was closed with a pick unused
    (`drafts.closed_holding_unused_pick`). Say whether calls count against
    the agent. The site should report drafts closed with an unused pick and
    phases ended without a status read beside the empty-phase count. That
    is a publication change and needs no contract.

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

Found 2026-10-16 by the 2.1 behaviour diagnostic
(`results/diagnostics/v21_behavior/behavior.json`). Both change
`gm_bench/simulator.py`.

26. **The second-goalie bonus is not published.** `League._team_strength`
    adds 2.5 per dressed goalie, up to two. `get_rules` publishes
    `lineup_center_bonus` and its size, and says only "1 G" for goalies.
    Phase closes with two healthy goalies on the roster and both dressed
    (`lineups.of_which_2_goalies_dressed` of
    `phase_closes_with_2_healthy_goalies`): deepseek 263 of 588, astra 132
    of 301, sol 77 of 268, luna 74 of 565, Opus 68 of 621, Sonnet 31 of 567.
    Publish it beside the center bonus, or decide that finding it is part
    of the test and say so in the spec.
27. **Trade-deadline offers stay listed in the draft phase.**
    `current_offers` is cleared only at the season rollover. Offers from
    the deadline are still listed in the draft phase, marked "expires:
    this decision point", and `legal_tools` advertises accept, reject and
    counter. Draft phases with live deadline offers
    (`drafts.with_live_deadline_offers`): 41 to 158 of 160 per row. Draft
    phases with at least one listed offer that can no longer go through,
    because a player in it has changed teams (`drafts.with_a_stale_listed_offer`):
    9 to 81. Accepting one is a penalized move ("offer is stale", 1 case,
    Opus). Clear the offers when the deadline closes, or drop stale ones
    from the listing.
