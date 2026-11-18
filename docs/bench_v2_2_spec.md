# GM-Bench 2.2: specification (draft)

Status: **draft, not frozen.** Started 2026-11-17. No fingerprint is pinned and
no row can be published under it (`gm-bench-2.2-draft` has no lane, and
`agentic-redact` refuses a contract without one). Decisions are logged in
`docs/lab_notebook.html`; the evidence behind each queue item is in
[bench_v2_1_queue.md](bench_v2_1_queue.md).

2.1 fixed the simulator and the score and kept 2.0's tools and brief byte for
byte. 2.2 is the version that changes what the agent is told. Its aims:

1. The brief and the tool text state every mechanic a model was shown to
   misread under 2.1, so the board measures management, not guessing rules.
2. The end-of-run credit matches the winning that follows it, because the
   brief will now say when that credit is counted.
3. No part of the score depends on a constant the tools do not publish.

One rule holds for all agent-facing text: it states mechanics and never gives
strategy advice.

## Phases and gates

Each phase has a gate. Nothing paid runs before phase 4.

| Phase | Work | Gate | Status |
|---|---|---|---|
| 0 | Close 2.1 intake; fork the agent-facing surface as a no-op | Every 2.1 ledger replays identically under the 2.2 engine | **Done 2026-11-17** |
| 1 | Choose the end-of-run score (free, CPU only) | Criteria below | **Round 1 done, not passed**; round 2 open |
| 2 | Rules, published constants, brief and tool text | `validate-contract` and the new canaries pass | Not started |
| 3 | References: `pick-trader` plus a scripted contender, frozen before any model row | Planner and contender reruns find no exploit | Not started |
| 4 | Public-seed pilot with the behaviour diagnostic | Predicted behaviours move; no new misreading | Not started |
| 5 | Freeze, pre-register, smoke, first panel on the 32 private seeds | Prices checked first | Not started |
| 6 | Site: 2.1 moves to an archive page; spec and notebook entries | | Not started |

## Phase 0: the fork (done)

2.1 could subclass the frozen engine because it reused 2.0's tools and brief.
2.2 cannot: `gm_bench/agentic/episode.py` reads the 2.0 tool list as a module
global and `gm_bench/agentic/mcp_server.py` reads the 2.0 brief the same way.
Both files are frozen, so `gm_bench/v22/` carries its own copies of the two
data files and subclasses the rest:

- `tools.py`, `brief.py`: forked copies. Everything the agent sees is still
  2.0's, word for word, until phase 2.
- `episode.py`: `AgenticEpisode22`, the frozen engine with the two methods
  that read the tool list (`_execute`, `_legal_tools`) restated against the
  2.2 tools. `league_class` and `scoring` name the league and score; both are
  2.1's until phases 1 and 2 replace them.
- `mcp_server.py`: `McpServer22` and `SocketMcpServer22`, the frozen server
  bound to the 2.2 tools and instructions. There is no 2.2 stdio entry
  point, which makes queue item 8 moot.
- `contract.py`: version `gm-bench-2.2-draft` and a fingerprint over the 2.1
  fingerprint plus the four files above. Unpinned while in draft.
- `gm_bench/agentic/versions.py` (driver) now also names the brief module
  and the socket server for a contract, and `opencode.py` (the shared
  episode loop) asks it instead of importing 2.0's. The registry knows the
  draft as `2.2-draft`. The `gm-bench agentic --contract` flag does not
  offer it yet: `gm_bench/cli.py` is in the trajectory demo's pinned source
  manifest (`scripts/build_trajectory_demo.py`), so adding the choice means
  re-pinning that public provenance. That goes with phase 2, when there is
  something different to play.

No 1.0, 2.0 or 2.1 contract source was edited: fingerprints `a600b7da0c302231`,
`07de948a4f4afbae` and `282dbf382c4ee56c` are pinned in `tests/test_v22.py`.

**Gate result.** All 430 finished 2.1 ledgers on the operator's machine (the
twelve published panels and four partial runs) were replayed under both
`AgenticEpisode21` and `AgenticEpisode22`. Final score, score components,
wins, illegal actions, season summaries, transactions and per-tool call
counts are identical in all 430, and each matches its recorded `result.json`.
`tests/test_v22.py` keeps a small version of the same check and the
word-for-word check on the tools and brief; both are deleted by the change
that first forks the text or the rules on purpose.

**2.1 intake is closed.** `gmb-free-queue.service` was disabled on 2026-11-17
(it restarted free panels at boot). The two stalled panels are abandoned;
their run directories are kept.

## Phase 1: the end-of-run score

### Why it comes first

score-v2 takes its end-state terms after the final rollover, when expiring
contracts have just left. Two 2.1 findings pull against each other:

- Opus 5.5 and Sonnet 5.5 let contracts lapse and are scored on about 4.6
  players; the brief never says when the credit is counted (item 13).
- The 2026-10-26 planner's end state was 43 to 55 points above
  `pick-trader`'s, and over five more seasons it won no more.

Telling every model when the credit is counted (aim 1) pushes all of them
toward the behaviour the second finding says is over-paid. So the credit has
to be checked before the brief is written.

### Method

`scripts/score_v3_candidates.py`. A candidate replaces only the end-state
terms; the winning terms and the penalty stay score-v2's. The yardstick is
the notebook's continuation check: hand each final league to a scripted
manager for five more seasons, on the same dice as `pick-trader`'s final
league on that seed, and score the winning that follows with score-v2's
winning weights. A well-priced end state predicts that gap one for one.
Three managers play the later seasons (`pick-trader`, `strategic`,
`contend-1g`); the yardstick is their mean, and each is also reported alone.

- **Scripted sample.** 15 policies against `pick-trader` on public seeds
  101-172 (fit 101-124, check 125-172): the references, the four canaries,
  four win-now policies, and four built for this test. `extend-all:*` adds
  an extension for every eligible player in the final preseason.
  `rundown:*` makes no extension in the final season.
- **Held-out sample.** The final leagues of all 384 episodes behind the
  twelve published 2.1 rows, replayed with no model call. Reported as
  per-row means only.

### Gate criteria

Fixed before round 2 is read:

1. **Calibration.** Slope of later winning on end-state gap within 0.9 to
   1.1 on the check seeds and on the model rows, under the three-manager
   yardstick, and no worse than score-v2 under any single manager.
2. **Residuals.** Root mean square of the per-group residuals below
   score-v2's on both samples.
3. **Noise.** Mean paired SD of the lift no higher than score-v2's.
4. **No final-season cliff.** `extend-all:pick-trader` and
   `rundown:pick-trader` each within 5 points of what later seasons show.
5. **Contract checks.** `validate-contract` passes, including two new
   canaries (extend everything in the final preseason; run the roster down).
6. **No exploit.** The fair planner, given the candidate as its objective,
   finds none.

### Round 1 result (2026-11-17)

`results/diagnostics/score_v3/candidates.json`. Slope and residual are
against the three-manager yardstick; "residual" is the root mean square of
the per-group mean residuals.

| Candidate | Check seeds: slope | residual | lift SD | Model rows: slope | residual | lift SD |
|---|---|---|---|---|---|---|
| score-v2 (after the final rollover) | 0.86 | 13.6 | 21.4 | 0.75 | 8.8 | 33.3 |
| score-v2 plus the next draft's picks | 0.87 | 12.4 | 21.4 | 0.74 | 8.7 | 33.6 |
| Before contracts expire | 0.72 | 14.6 | 21.7 | 0.68 | 14.6 | 31.6 |
| Refill by `pick-trader`'s preseason, then score | 1.03 | 9.5 | 20.4 | 0.99 | 7.0 | 31.2 |
| Refill by the engine's opponent routine (to 21 players) | 1.14 | 14.2 | 20.9 | 1.11 | 9.5 | 31.2 |
| Refill by `contend-1g`'s preseason | 0.86 | 12.3 | 20.6 | 0.75 | 8.7 | 31.6 |
| Three more seasons played, as the score | 0.66 | 10.5 | 37.5 | 0.68 | 7.4 | 49.9 |
| Weights refitted on the fit seeds | 0.84 | 6.8 | 26.9 | 0.56 | 13.4 | 45.5 |

What it shows:

- **Rejected.** Scoring before expiry over-credits a run-down roster
  (`rundown:pick-trader` residual -24.8; the Claude rows -6.7 to -23.8). Playing more seasons as the score raises the lift SD from 33
  to 50 or more. Refitted weights fit the scripted policies and fail on the
  model rows (slope 0.56, lift SD 45.5), which is the over-fitting the
  held-out sample was there to catch.
- **Refill is the right direction but not settled.** Refilling with
  `pick-trader`'s preseason (at most eight signings) is the best calibrated
  candidate under the three-manager yardstick. It fails criterion 1's
  second half: judged by `contend-1g` alone on the model rows its residual
  is 18.4 against score-v2's 16.7, and it under-credits `gpt-6-astra` by
  16.6. `pick-trader` and `strategic` share a preseason routine, so two of
  the three judges agree with this candidate by construction. How deep the
  refill goes changes the answer (eight signings: slope 1.03; a full 21:
  1.14), and the yardstick cannot yet say which depth is right.
- **The board would move.** Under the `pick-trader` refill: `gpt-6-astra`
  +46.9 to +30.4, `gpt-6.1-sol` +19.1 to +4.3, `claude-opus-5-5` -29.5 to
  -21.9, `claude-sonnet-5-5` -46.8 to -38.3. Kendall tau against the 2.1
  order is 0.91 (0.85 for the full refill). The top row stays the top row
  and the Claude rows stay behind under every candidate.
- **The Claude run-down is a real cost, not a scoring artifact.** Over the
  next five seasons the three Claude rows trail `pick-trader` by 40.7 to
  53.6 points, against a score-v2 end-state gap of 49.1 to 61.8. score-v2
  overstates it by about 8 to 9 points; no candidate removes it. Queue item
  13 (say when the credit is counted) therefore matters more than the choice
  of score.
- **Final-season extensions are over-paid by about 7 to 9 points, not 25 to
  50.** `extend-all:pick-trader` gains 11.1 points of end state and 3.7 of
  later winning. The larger residual belongs to the win-now family whatever
  it does at the end: `rundown:contend-1g`, with no final-season extension,
  is over-credited by 18.2, as much as `contend-1g` (18.4). The 2026-10-26
  reading ("extending through the final rollover games the end-state
  terms") explains a third of that gap at most.
- **The next draft's picks are worth nothing at final scoring.** The final
  score is taken with the season counter already advanced, and the pick
  term starts one season after it, so picks for the draft straight after
  the episode are skipped (removing them leaves a `pick-trader` final score
  unchanged; removing the following draft's costs 1.5 points). They can be
  traded away in seasons 3 to 5 for value. Counting them lowers the residual
  slightly on both samples and closes the hole. **Adopt regardless of the
  rest.**

### Round 2 (next, free)

1. A win-now roster is over-valued independently of extensions. Test an
   age-aware or contract-aware asset term (the asset value of a player
   under contract, discounted by age over the years the contract runs).
2. Treat refill depth as one parameter (0 is score-v2, 8 is `pick-trader`'s
   preseason, 21 is the opponent routine), chosen on the fit seeds and
   judged on the check seeds and the model rows.
3. Add a judge that refills fully in one preseason, so the yardstick stops
   favouring the eight-signing routine.
4. Settle the second half of queue item 21 here: whether an extension
   starts next season or the quote drops its extra inflation year.
5. Run criteria 5 and 6 on whichever candidate passes 1 to 4.

**Fallback if no candidate passes:** score-v2 with the next draft's picks
counted, and the brief stating exactly when the credit is taken. The Claude
finding above says that alone removes the largest misreading.

## Phase 2: rules, constants and text

Every queue item on the agent-facing surface is either taken here or
rejected in writing, because the next fork costs another panel rerun.

| Queue item | Change in 2.2 | Where |
|---|---|---|
| 1 | Schema and simulator agree on ranges (`years` 2 to 5 for an extension, 1 to 5 for a signing). Schema failures stay unpenalized; say so in the brief | `tools.py`, `brief.py` |
| 2 | `list_draft_class` answers in every phase; `scout` on a prospect no longer needs a guessed id | `episode.py` |
| 3 | `inspect_player` finds prospects, as its description promises | league subclass |
| 4 | Log a non-object argument as not executed, so replay cannot diverge | `episode.py` |
| 5, 6 | Refuse a call that reaches the dispatch lock after `stop()`; review admission with it | `mcp_server.py` |
| 7 | Guard notice prints sub-second guards correctly | `episode.py` |
| 13 | Say when the end-of-run credit is counted and which part is capped; drop the bare word "capped" | `brief.py` |
| 14 | Name the tradable pick window in the argument description and beside the listed picks | `tools.py`, status payload |
| 19 | State the calendar: the rest of the season and the playoffs are played when the draft phase closes, with the roster and lineup in force then | `brief.py`, `end_phase` reply |
| 20 | Say that a stored lineup persists and new players dress only into empty slots | `tools.py`, `brief.py` |
| 21 | Document extension terms; start and pricing decided in phase 1 | `tools.py`, league subclass |
| 22 | `end_phase` reply lists the phase's rejected and penalized calls | `episode.py` |
| 23 | "not an available free agent" names the cause | league subclass |
| 24 | State the two-decline limit, the two-trades-per-partner limit and its penalty, and that a trade needs assets from both teams | `tools.py`, rules payload |
| 25 | Say that tool calls are reported, not scored | `brief.py` |
| 26 | Publish the strength formula (below) | rules payload |
| 27 | Clear deadline offers when the deadline closes | league subclass |
| new | Count the next draft's picks at final scoring | scoring |

Rules changes go in `League22(League21)` and the 2.2 episode; no frozen file
is edited.

**Published constants** (`get_rules`), all from `League._team_strength`:

- 2.5 strength for each dressed goalie, up to two. The rules currently say
  "1 G" and are silent on the second.
- Lineup slot weights by overall rank: 1.0 for the top six, 0.74 for the
  next six, 0.48 for the rest.
- 0.25 strength lost for each unit of payroll over the cap.
- The injury deduction used when a season is simulated, if it is not
  already published (check in phase 2).

The goalie bonus alone is worth 19 to 21 points to the scripted win-now
policies (notebook, 2026-10-26), more than the 13 points a 32-seed panel can
detect.

Not in 2.2:

- **9** (retry time off the phase clock for every harness) and **12** (record
  what the harness sends) are driver changes. Decide both before the panel;
  neither needs the contract.
- **10** and **11** are audit and publication changes. Take 11 (an audit
  version in each row) with the first 2.2 row.
- **17** is phase 1.

## Phase 3: references

- `pick-trader` stays the paired baseline, so the headline keeps its meaning
  across 2.1 and 2.2.
- A scripted contender, rebuilt under the 2.2 rules with the constants
  published, is a second, stronger line. 2.1 showed `pick-trader` is a weak
  bar: a fixed scripted mix reaches +66 without valuing the goalie bonus.
- Both are frozen and pinned in the lane config before any model row.
- `validate-contract --contract 2.2` runs the 2.0 orderings plus the two new
  canaries from phase 1.

## Phase 4: pilot

Before freezing, on **public seeds** so the text is not tuned against the
private panel:

- The planner and the contender, rerun under the 2.2 rules, as an exploit
  search.
- Three cheap models, one of them a Claude model: the largest 2.1 misreadings
  (roster run-down, skipped status reads, stale lineups) were Claude's.
- The behaviour diagnostic (`scripts/diagnose_v21_behavior.py`, ported) on
  the pilot ledgers.

The other agent's estimate for this was about $13 at API-equivalent prices.
It has not been checked; check `pricing.json` first.

## Phase 5: freeze and first panel

- **Seeds.** The same 32 private seeds, unless phase 1's chosen score raises
  the paired SD above 2.1's 26 to 29.
- **Rows first.** `gpt-6-astra`, `gpt-6.1-sol`, `claude-opus-5-5`,
  `claude-sonnet-5-5`, `mimo-v2.6-pro`, `deepseek-v4.1-flash`, on the same
  pinned harness versions as their 2.1 rows where those still run, so a
  change is attributable to the contract. Estimated by the other agent at
  about $310 API-equivalent, mostly subscription quota; unchecked.
- **Pre-registration.** 2.1 asked whether the order held. 2.2 expects it to
  move, so the registered predictions are behavioural, each with a
  threshold set from the pilot: roster at final scoring for the Claude
  rows, the share of penalized rejections caused by the pick window (45%
  under 2.1), draft-close lineup gap to the engine default, and phases
  closed straight after a penalized rejection. A no-go rule is registered
  with them.
- Serial within a provider, smoke first, as for 2.0 and 2.1.

## Decisions

Made 2026-11-17 (operator):

- Publish the hidden strength constants.
- 2.1 intake is closed; abandon the stalled panels, keep their directories.
- Start with phases 0 and 1.

Open:

- Which end-of-run score (phase 1, round 2), or the fallback.
- Queue item 1's other half: whether a schema failure on a move tool should
  be penalized as in 1.0. Draft answer: no, and say so.
- Whether to show the engine-default lineup's strength in `get_status`
  (item 20). Draft answer: no. The text will state the rule; showing the
  number does part of the manager's job.
