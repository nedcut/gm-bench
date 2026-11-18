# GM-Bench 2.2: specification (draft)

Status: **release candidate, not frozen.** Started 2026-11-17; phases 0 to 3
done 2026-11-18. What remains needs paid model runs (phase 4 onward). No
fingerprint is pinned and no row can be published under it (`gm-bench-2.2-draft` has no lane, and
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
| 1 | Choose the end-of-run score (free, CPU only) | Criteria below | **Done 2026-11-18: no candidate passed, fallback taken** |
| 2 | Rules, published constants, brief and tool text | `validate-contract` and the new canaries pass | **Done 2026-11-18** |
| 3 | References and a free exploit check | No scripted policy gains under 2.2; real ledgers replay | **Done 2026-11-18** (lane pins wait for the freeze) |
| 4 | Public-seed pilot with the behaviour diagnostic | Predicted behaviours move; no new misreading | Not started (paid) |
| 5 | Freeze, pre-register, smoke, first panel on the 32 private seeds | Prices checked first | Not started (paid) |
| 6 | Site: 2.1 moves to an archive page; spec and notebook entries | | Not started |

## Phase 0: the fork (done)

2.1 could subclass the frozen engine because it reused 2.0's tools and brief.
2.2 cannot: `gm_bench/agentic/episode.py` reads the 2.0 tool list as a module
global and `gm_bench/agentic/mcp_server.py` reads the 2.0 brief the same way.
Both files are frozen, so `gm_bench/v22/` carries its own copies of the two
data files and subclasses the rest:

- `tools.py`, `brief.py`: forked copies. In phase 0 everything the agent saw
  was still 2.0's, word for word; phase 2 changed them.
- `episode.py`: `AgenticEpisode22`, the frozen engine with the two methods
  that read the tool list (`_execute`, `_legal_tools`) restated against the
  2.2 tools. `league_class` and `scoring` name the league and score; in
  phase 0 both were 2.1's.
- `mcp_server.py`: `McpServer22` and `SocketMcpServer22`, the frozen server
  bound to the 2.2 tools and instructions. There is no 2.2 stdio entry
  point, which makes queue item 8 moot.
- `contract.py`: version `gm-bench-2.2-draft` and a fingerprint over the 2.1
  fingerprint plus every 2.2 source (these four, and from phase 2
  `rules.py`, `scoring.py` and `runner.py`). Unpinned while in draft.
- `gm_bench/agentic/versions.py` (driver) now also names the brief module
  and the socket server for a contract, and `opencode.py` (the shared
  episode loop) asks it instead of importing 2.0's. The registry knows the
  draft as `2.2-draft`. The prompt check (`prompt_check.py`) takes the
  contract too, so it captures what a 2.2 panel's harness would be sent.
  `gm-bench agentic --contract 2.2-draft` and `gm-bench validate-contract
  --contract 2.2-draft` came with phase 2. `gm_bench/cli.py` is in the
  trajectory demo's pinned source manifest, so that change re-pinned the
  demo's source digest (`scripts/build_trajectory_demo.py`), as the 2.1
  build did.

No 1.0, 2.0 or 2.1 contract source was edited: fingerprints `a600b7da0c302231`,
`07de948a4f4afbae` and `282dbf382c4ee56c` are pinned in `tests/test_v22.py`.

**Gate result.** All 430 finished 2.1 ledgers on the operator's machine (the
twelve published panels and four partial runs) were replayed under both
`AgenticEpisode21` and `AgenticEpisode22`. Final score, score components,
wins, illegal actions, season summaries, transactions and per-tool call
counts are identical in all 430, and each matches its recorded `result.json`.
`tests/test_v22.py` kept a small version of the same check and a
word-for-word check on the tools and brief until phase 2 forked the text and
the rules on purpose.

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

Fixed on 2026-11-17, before round 2 was read:

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

### Round 2 result (2026-11-18)

Three additions, same file:

- **Engine fill.** The engine fills the user's roster to a set size with the
  best free agents by overall, at the published one-year quote, within the
  cap plus 4 (the first loop of `League._opponent_signings`, without its
  dice), then score-v2's terms. Sizes 8 to 21.
- **Contract-length discount.** score-v2 plus the next draft's picks, with a
  player on a one-year contract counted at a fraction of his asset value.
  The fraction is one parameter (0.4 to 0.9), chosen on the fit seeds only
  as the one whose slope is nearest 1. It came out 0.7.
- **A fourth judge**, `filled:pick-trader`: the engine fills the roster to 21
  and then `pick-trader` manages. Reported alone, never in the yardstick,
  which stays the three managers the gate named.

| Candidate | Check seeds: slope | residual | lift SD | Model rows: slope | residual | lift SD |
|---|---|---|---|---|---|---|
| score-v2 (for reference) | 0.86 | 13.6 | 21.4 | 0.75 | 8.8 | 33.3 |
| **score-v2 plus the next draft's picks (adopted)** | 0.87 | 12.4 | 21.4 | 0.74 | 8.7 | 33.6 |
| Engine fill to 8 players | 1.05 | 14.8 | 21.5 | 0.95 | 8.8 | 30.9 |
| Engine fill to 21 players | 1.15 | 14.5 | 20.9 | 1.12 | 9.5 | 31.4 |
| One-year contracts counted at 0.7 | 1.06 | 8.8 | 20.2 | 0.87 | 6.9 | 32.0 |
| One-year contracts counted at 0.5 | 1.13 | 9.3 | 19.5 | 0.92 | 7.3 | 31.6 |

Against the gate:

- **Engine fill fails criterion 2.** To 8 players the slope is inside 0.9 to
  1.1 on both samples, but the residual on the check seeds is 14.8 against
  score-v2's 13.6. Deeper fills overshoot the slope (1.13 to 1.24).
- **The contract-length discount fails criterion 1, narrowly, twice.** At 0.7
  the model-row slope is 0.87 against a floor of 0.9, and judged by
  `contend-1g` alone on the model rows its residual is 16.9 against
  score-v2's 16.7. It passes criteria 2, 3 and 4: `extend-all:pick-trader`
  is over-paid by 4.5 points instead of 7.4. No fraction passes both
  samples (0.6: 1.11 and 0.90).
- **The fourth judge agrees on direction.** With the roster filled first,
  score-v2's slope is 0.64 and 0.52; the 0.7 discount's is 0.90 and 0.66.
  score-v2 over-pays end state under every judge.

### Decision: the fallback

No candidate passes, so 2.2 takes the fallback the gate named:
**score-v3 is score-v2 plus the next draft's picks** (`gm_bench/v22/scoring.py`),
and the brief says exactly when the credit is taken.

Every replayed model episode is checked against its recorded score before it
is used (all 384 match), and the replay runs under the 2.1 engine.

- At final scoring the season counter has advanced, so the picks a team
  holds for that season's draft are counted at the value of a
  current-season pick. While a season is open its draft has been held and
  nothing is added, so `score_after_season` is score-v2's.
- On the 2.1 ledgers the board barely moves: `gpt-6-astra` +46.9 to +44.5,
  `gpt-6.1-sol` +19.1 to +16.7, `claude-opus-5-5` -29.5 to -31.6,
  `claude-sonnet-5-5` -46.8 to -48.1. Kendall tau against the 2.1 order is
  0.97. `pick-trader` holds more next-draft picks than the model rows do.
- **Known and accepted.** Extending every eligible player in the final
  preseason gains about 11 points of which later seasons confirm about 4.
  That is under the 13 points a 32-seed panel can detect, and it is now a
  contract check (below). A win-now roster stays over-credited whatever
  it does in the final season (`contend-1g` by 16.0 points, and
  `rundown:contend-1g` by 15.6).
- **Criteria 5 and 6 for the fallback.** `validate-contract --contract
  2.2-draft` passes with the two new canaries
  (`results/diagnostics/v22_references/validate_contract.json`):
  `extend-everything` gains 11.2 points over `pick-trader` on the canary
  seeds against a bound of 13, and `run-down` loses 16.6. The fair planner
  was not rerun. Against 2.1 the game changes only by withdrawing deadline
  offers after the deadline, and the objective by a linear pick term priced
  as trades price it; the scripted-policy comparison in phase 3 stands in
  for it.
- **Queue item 21, simulator half: rejected.** An extension keeps starting
  at once, and its quote keeps the extra inflation year. The quote the agent
  is shown is the price charged, the tool text now says what an extension
  does, and a price change would break the comparison of `pick-trader`
  across 2.1 and 2.2.

**Open to the operator before the freeze.** The 0.7 contract-length discount
is the better-calibrated score and the closest miss. Taking it means
overriding the gate, and the brief would have to state it, so it must be
chosen before the first 2.2 row. This spec does not take it.

## Phase 2: rules, constants and text

Every queue item on the agent-facing surface is either taken here or
rejected in writing, because the next fork costs another panel rerun.

| Queue item | What 2.2 does | Where |
|---|---|---|
| 1 | Schema ranges are the simulator's: `years` 2 to 5 for an extension, 1 to 5 for a signing. A schema failure stays unpenalized, and the brief says so | `tools.py`, `brief.py` |
| 2 | `list_draft_class` answers in every phase, so a prospect can be scouted before the draft without a guessed id | `episode.py`, `tools.py` |
| 3 | `inspect_player` finds prospects, as its description says | `rules.py` |
| 4 | A call whose arguments are not an object is logged as not executed, so replay skips it | `episode.py` |
| 5 | A `tools/call` that reaches the dispatch lock after `stop()` began is refused | `mcp_server.py` |
| 6 | Reviewed with item 5: admission already registers a connection and re-checks `stop()` under one lock. No change | |
| 7 | **Rejected.** The sub-second guard notice only prints wrongly in tests; fixing it means restating `call_tool` | |
| 13 | The brief says the credit is counted after the final season's contracts expire, that the next draft's picks count, and that only cap room and roster depth (at 24 players) are capped | `brief.py` |
| 14 | The pick-season arguments name the window; `get_rules` lists `tradable_seasons`; each listed pick carries `tradable_now` | `tools.py`, `rules.py` |
| 19 | The brief says games are played when the preseason closes (a third) and when the draft closes (the rest and the playoffs), and that moves stay open in the draft; the `end_phase` reply that opens the draft repeats it | `brief.py`, `episode.py` |
| 20 | `set_lineup` and the brief say a lineup persists and new players dress only into empty slots | `tools.py`, `brief.py` |
| 21 | `extend_contract` and `get_rules` say what an extension does. The simulator half is rejected (phase 1) | `tools.py`, `rules.py` |
| 22 | The `end_phase` reply lists every call the phase refused (illegal moves, declines, schema failures, refused reads) and counts the penalized ones | `episode.py` |
| 23 | A signing refused because the player is not a free agent says where he is (another team, the waiver wire, the draft class). Still an illegal move | `rules.py` |
| 24 | `trade` and `get_rules` state the two-decline limit, the two-trades-per-partner limit and its penalty, and that both teams must give something | `tools.py`, `rules.py`, `brief.py` |
| 25 | The brief says tool calls are reported and do not change the score; "calling everything every phase is a cost" is gone | `brief.py` |
| 26 | `get_rules` publishes the strength formula (below) | `rules.py` |
| 27 | Deadline offers are withdrawn when the deadline closes | `rules.py` |
| new | The next draft's picks count at final scoring (score-v3) | `scoring.py` |
| new | Roster cards in `get_team` carry `injured_games`. An injured player does not dress, and nothing showed which players were injured | `rules.py` |
| new | Three inherited `get_rules` descriptions are restated as mechanics: the center bonus and expiry texts gave advice, and the free-agent text said a quote "always succeeds" (the hard cap, the re-sign block and a walk-away can still refuse it) | `rules.py`, `tools.py` |

The surface versions are `gm-bench-agentic-v2` and
`gm-bench-agentic-brief-v2`. Tool names and the tool-to-action mapping are
unchanged.

Rules changes are in `League22(League21)` (`gm_bench/v22/rules.py`) and the
2.2 episode; no frozen file is edited. Item 27 is the only change to how the
game plays.

**Published constants** (`get_rules`, `team_strength`), all from
`League._team_strength`; a test checks that the published formula reproduces
the engine's strength for every team:

- 2.5 strength for each dressed goalie, up to two. The rules currently say
  "1 G" and are silent on the second.
- Lineup slot weights by overall rank: 1.0 for the top six, 0.74 for the
  next six, 0.48 for the rest.
- 0.25 strength lost for each unit of payroll over the cap.
- Each time games are simulated, every dressed player plays 5 to 18 overall
  points below his rating with probability equal to his `injury_risk`. This
  was not published either.

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

## Phase 3: references and the free exploit check

`scripts/v22_reference_check.py`, no model call.

- **No scripted policy gains under 2.2.** Fifteen policies (the references,
  the four canaries, the win-now family, the two end-of-run policies) on
  public seeds 101-172, each against `pick-trader` under the same rules
  (`results/diagnostics/v22_references/policies.json`). Lifts change by
  -2.6 to +2.3 from 2.1 to 2.2. The +2.3 is `accept-everything`, whose
  illegal moves fall from 3.76 to 2.51 an episode because stale deadline
  offers are no longer listed in the draft.
- **Real traffic.** All 430 finished 2.1 ledgers replay through
  `AgenticEpisode22` to a finished, scored episode with no engine error. The
  rules differ, so those games diverge and their scores mean nothing; the
  check is that every recorded call is answered.
- **`pick-trader` stays the paired baseline**, so the headline keeps its
  meaning across 2.1 and 2.2.
- **A scripted contender is the second line.** `contend-preseason-1g`
  (`scripts/ceiling_planner.py`), which values the now-published goalie
  bonus, is +82.7 over `pick-trader` under 2.2 on seeds 101-172 (+84.4
  under 2.1). `pick-trader` is a weak bar, and the top published 2.1 row is
  about half of that.
- **Left for the freeze.** Both reference means on the 32 private seeds, the
  lane config that pins them, and moving the contender policy into the
  package. They need the escrowed seeds and a frozen fingerprint.
- `validate-contract --contract 2.2-draft` runs the 2.0 orderings under
  `League22` and score-v3 plus the two end-of-run canaries
  (`gm_bench/v22/validity.py`).

## Phase 4: pilot

Before freezing, on **public seeds** so the text is not tuned against the
private panel:

- Three cheap models, one of them a Claude model: the largest 2.1 misreadings
  (roster run-down, skipped status reads, stale lineups) were Claude's.
- The behaviour diagnostic (`scripts/diagnose_v21_behavior.py`, ported) on
  the pilot ledgers. The port is not written; it has nothing to read until
  the pilot runs.

The text can still change after the pilot, which is why the contract is not
frozen yet. A harness smoke on one episode comes first, as for 2.0 and 2.1.

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
- Start with phases 0 and 1; then (2026-11-18) build the rest up to the paid
  steps.

Made 2026-11-18 (by the gate and in the build; each is in the notebook):

- The end-of-run score is the fallback, score-v3.
- A schema failure on a move tool stays unpenalized, and the brief says so.
- `get_status` does not show the engine-default lineup's strength. The text
  states the rule; showing the number does part of the manager's job.
- Queue items 7 and the simulator half of 21 are rejected.

Open, for the operator:

- Whether to override the gate and take the 0.7 contract-length discount
  (phase 1).
- The pilot's models and budget, after a price check (phase 4).
- Driver items 9 and 12 and audit item 11, before the first panel.
