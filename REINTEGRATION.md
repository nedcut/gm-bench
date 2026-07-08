# protocol-v2 → main re-integration (branch: protocol-v3)

Scratch design doc for the re-port. DELETE before opening the PR.

## Goal
Re-apply the protocol-v2 interaction layer (branch `origin/cursor/agent-environment-v2-02ca`,
tip `ede00b5`) onto the hardened `main`, which since the common base `f0bb2b3` gained the
SOTA-v1 benchmark hardening (contract.py, official.py, redaction), per-decision cost/latency
telemetry in runner.py, and a richer trade/scout model in simulator.py. A raw git merge is
impossible: both branches rewrote the same simulator/runner subsystems in incompatible ways.
We keep MAIN's mechanics and layer v2's protocol on top.

## Reference trees
- MAIN's version of any file (the base we build on): already checked out in this worktree.
- v2's version of any file: `git show origin/cursor/agent-environment-v2-02ca:<path>`.
  This v2 tip already contains 4 earlier review fixes (H1 baseline cache key, M2 midseason
  schedule, M3 negotiation-action gating, L4 multi-round test) — preserve their intent.

## Locked decisions
- D1 Trade model: keep MAIN's mechanics (`current_offers`, `_accept_offer`, `_decline_offer`,
  `_generate_incoming_offers`, `_trade` with pick-trading, `_walkaway`, `_trade_market_public`).
  Expose them through v2's action protocol.
- D2 Scouting: keep MAIN's (`scout_points_used`, `scout_reports`, `SCOUT_REPORT_NOISE`, `_scout`).
  Wire v2's `scout` query action to MAIN's `_scout`.
- D3 Midseason: KEEP it (v2's 4th phase). This changes total_decisions from seasons*3 to
  seasons*len(PHASES), bumps the env version, and changes the contract fingerprint — accepted.
- counter_trade_offer: PORT v2's counter mechanic, adapted to MAIN's `current_offers`.

## Naming
- Env/protocol version constant is `protocol.PROTOCOL_VERSION = "gm-bench-v2"` (already renamed;
  do NOT reintroduce a `BENCHMARK_VERSION` in protocol.py — contract.py owns `BENCHMARK_VERSION`).
- Canonical negotiation action names are v2's: `accept_trade_offer`, `reject_trade_offer`,
  `counter_trade_offer`. Keep `accept_offer`/`decline_offer` as accepted ALIASES so nothing
  that used MAIN's names breaks. Baselines emit only draft/noop/release/set_lineup/
  sign_free_agent/trade, so there is no baseline back-compat constraint.

## P1 — DONE (committed b84b1ca)
Added `gm_bench/protocol.py` and `gm_bench/session.py` from v2 (PROTOCOL_VERSION rename).
`protocol.EpisodeConfig` already carries the H1 `baseline_cache_fingerprint()`.

## P2 — action layer (assigned: grok-4.5) — IN PROGRESS
Rewrite `League.apply_actions` in gm_bench/simulator.py to return `list[ActionResult]` and
support v2's action set, WITHOUT rewriting MAIN's ~10 scoring handlers. Approach:
1. `_record(...)` (currently returns None): make it return an `ActionResult`, accept keyword
   `data: dict|None=None` and `penalize: bool|None=None`, and — when `team_id` is the user team
   — append the built `ActionResult` to `self._action_results`. Preserve MAIN's existing
   illegal_actions / rejected_offers accounting: still bump rejected_offers when
   `rejected_offer=True`; otherwise bump illegal_actions only when the action should be penalized
   (`penalize` if given, else `action_type not in NON_PENALIZED_TYPES`). Import ActionResult and
   NON_PENALIZED_TYPES from gm_bench.protocol (import already added).
2. Add field `_action_results: list[ActionResult] = field(default_factory=list)` to the League
   dataclass.
3. Rewrite `apply_actions(self, actions, phase) -> list[ActionResult]`: set
   `self.window_walkaways = {}`; `self._action_results = []`; validate list; for each of
   `actions[:24]`: object-check; if `type == "end_turn"` record accepted "turn ended"
   (penalize=False) and break (terminal); else dispatch. Return `self._action_results`.
4. Add a dispatch table method mapping types → handlers: core (memo/sign_free_agent/release/
   trade/draft/set_lineup, noop→accepted "no-op" penalize=False), scout, the three query
   handlers below, and negotiation: `accept_trade_offer`+alias `accept_offer` → `_accept_offer`;
   `reject_trade_offer`+alias `decline_offer` → `_decline_offer`; `counter_trade_offer` →
   new `_counter_offer`. Unknown type → record False "unknown action type". Route mutating
   handlers through MAIN's existing `_safe_apply` (it already records invalid-arg errors; those
   now collect + penalize by type automatically).
5. Add query handlers (read-only, always penalize=False), adapted to MAIN's helpers:
   - `_inspect_team`: team_id → `team.public_dict(self.players, self.cap)` + roster detail
     `[self.players[pid].public_dict() for pid in team.roster]`; unknown id → record False.
   - `_inspect_player`: player_id → `{"player": self.players[pid].public_dict()}`.
   - `_list_free_agents`: optional position/min_overall/limit filters over `self.free_agents`
     using `self._free_agent_public`. (See v2 versions for exact arg names/limits.)
6. Add `_counter_offer(self, action, phase) -> ActionResult` adapted from v2's
   `_counter_trade_offer`: look up `self.current_offers[offer_id]`; if missing, record False
   "no such active offer". Build a MAIN trade action:
   partner_team_id=offer["partner_id"],
   give_player_ids=action.get("give_player_ids", offer["they_receive"]),
   receive_player_ids=action.get("receive_player_ids", offer["you_receive"]),
   give_pick_seasons=action.get("give_pick_seasons", offer["they_receive_picks"]),
   receive_pick_seasons=action.get("receive_pick_seasons", offer["you_receive_picks"]).
   Call `self._trade(trade_action, phase)`; if the resulting ActionResult.accepted, delete the
   offer from current_offers and set its message to note the counter. (`_trade` already reads
   exactly these keys.)
7. Add `_available_actions(self, phase) -> list[str]` (from v2, using MAIN's fields): always
   list sign_free_agent/release/trade/set_lineup/memo/noop/inspect_team/inspect_player/
   list_free_agents/scout/end_turn; add "draft" in the draft phase; add "claim_waiver" only if
   midseason machinery exists yet (it does NOT until P4 — omit claim_waiver for now); advertise
   accept_trade_offer/reject_trade_offer/counter_trade_offer ONLY when `self.current_offers`
   is non-empty (the M3 fix, keyed on MAIN's field).
8. Do NOT change runner.py in P2 (still expects apply_actions side-effects — its return value
   was previously None and is now a list, which it ignores; that is fine until P3). Do NOT wire
   available_actions into observation yet (that is P5). Keep midseason out of scope (P4).

### P2 acceptance
- `uv run pytest -q` all green (existing tests must still pass; apply_actions returning a list
  instead of None must not break runner.py or any test).
- `uv run ruff check gm_bench` and `uv run ruff format --check gm_bench` clean.
- A quick REPL check: `League.new(seed=5)`, generate offers via one `observation("trade_deadline")`,
  then `apply_actions([{ "type": "list_free_agents", "limit": 3 }])` returns one ActionResult with
  `accepted=True` and a `data.free_agents` list; an `accept_trade_offer` with a real offer_id
  returns accepted True.

## P3+P5+P6 — runner + observation + cache fusion (assigned: grok-4.5) — NEXT
These are one coherent change (they are tightly coupled) and land together. After this the
DEFAULT episode is 4-phase (incl. midseason), multi-round, with telemetry. Only golden scores
should change — REGENERATE them (do not hand-edit to arbitrary values; run the code and paste
the new values, add a comment saying they moved because midseason is now in the default episode).

Context you already have: main's `run_episode` (3-phase, with per-decision telemetry
act_with_usage/usage_records/harness_latency_ms/decision_seconds/_decision_failed) is the
telemetry model to PRESERVE. v2's `run_episode` + `run_decision_point` + PersistentProcessAgent
(session.py, already present) is the multi-round/midseason structure to ADOPT. v2 observation
(tier/action_results/interaction_round/available_actions/summaries) is the shape to MERGE onto
main's richer observation.

### Observation (gm_bench/simulator.py `observation`)
- Add keyword-only params: `tier: ObservationTier = "full"`, `action_results=None`,
  `interaction_round: int = 0` (import ObservationTier from gm_bench.protocol).
- KEEP all of main's current fields (rules with pick_trading/scouting/fa_reservation, team,
  standings, free_agents, draft_class, draft_order, trade_market, scout_reports, history,
  recent_transactions, memo). ADD: `benchmark = PROTOCOL_VERSION`, `observation_tier`,
  `interaction_round`, `available_actions = self._available_actions(phase)`,
  `action_results` (only if truthy), and (from P4) waiver_wire.
- Tiering: full → full lists; summary → replace free_agents/draft_class/trade_market/waiver_wire
  with `*_summary` (use `_list_summary`) + a `hint` string. Add a `full_roster: bool = True` param
  to `Team.public_dict` in gm_bench/models.py and pass `full_roster=(tier=="full")`.
- OFFERS TIMING (correctness): observation must NOT regenerate offers every call (multi-round
  would resurrect an offer the agent just accepted). Split main's `_incoming_offers_public` into
  generation vs publishing: add `prepare_trade_deadline(self)` that sets
  `self.current_offers = self._generate_incoming_offers("trade_deadline")` ONCE; observation only
  PUBLISHES the current `self.current_offers` (no regeneration). The runner calls
  prepare_trade_deadline before the trade_deadline decision point (see below).
- If tests validate observations against schemas/gm_observation.schema.json, update that schema to
  match the merged observation.

### Runner (gm_bench/runner.py)
- `run_episode`: import EpisodeConfig + PHASES from gm_bench.protocol; add
  `config: EpisodeConfig | None = None` param (default EpisodeConfig()). Iterate phases from
  PHASES honoring config.include_midseason (drop "midseason" when disabled).
  `total_decisions = seasons * len(phases)`. Per phase, in order:
  `if phase=="midseason": league.prepare_midseason()`;
  `if phase=="trade_deadline": league.prepare_trade_deadline()`;
  `if phase=="draft": league.run_opponent_draft(before_user=True)`; then the decision point;
  `if phase=="draft": league.run_opponent_draft(before_user=False)`;
  `league.run_autopilot_opponents(phase)`. After phases: `league.simulate_season()`.
  Wrap in start/end_episode when `isinstance(agent, PersistentProcessAgent)`.
- `run_decision_point(league, agent, phase, config)`: adopt v2's multi-round loop (observation
  with tier/action_results/interaction_round; round 0 → agent.act_with_usage; later rounds →
  act_on_results for PersistentProcessAgent else act_with_usage on an observation carrying
  action_results; apply_actions returns list[ActionResult]; stop via
  session.should_continue_interaction). CRITICAL: preserve main's telemetry — use
  act_with_usage (NOT plain act) every round, time each call into harness latency, collect each
  usage into usage_records, and mark the decision failed if ANY round's actions fail
  (_decision_failed). Return the telemetry gathered (results + usage_records +
  harness_latency_ms + failed bool) so run_episode can aggregate exactly as today. Reuse main's
  _observation_tier_for_agent behavior if present, else tier=config.observation_tier with
  builtin_full_observation forcing "full" for AGENTS.
- P6: wire the H1 baseline cache fingerprint. In run_many_cached_baselines compute
  `config_fingerprint = (config or EpisodeConfig()).baseline_cache_fingerprint()` and pass it to
  cache_key(...) and put_cached_episode(..., config_fingerprint=...). (baseline_cache.py already
  accepts the param.) Thread `config` through run_many / evaluate_against_baselines to
  run_episode and the cached-baseline calls, matching v2.
- Keep run_many's ThreadPool/clone-for-parallel-seeds behavior; clone PersistentProcessAgent per
  seed.

### Acceptance (grok must run and paste results)
- `uv run pytest -q` → ALL green. Regenerate tests/test_golden_scores.py values from the code
  (they legitimately change: midseason is now in the default episode). If any other test hardcodes
  scores/decision counts (e.g. shrewd baseline, scoring, validity_fixes), update those snapshots
  the same way, each with a one-line comment. Do NOT weaken assertions or skip tests.
- `uv run ruff check gm_bench` and `uv run ruff format gm_bench` clean.
- Determinism: `run_episode(ValueAgent(), seed=1, seasons=2)` twice gives identical final_score.
- Shape: that result has `decisions == 2 * 4` and a non-empty transactions list.
- Report every file/function changed with line numbers, the new golden values, and the pytest line.
### P4 — midseason subsystem (assigned: grok-4.5) — NEXT
main has NO midseason machinery and, crucially, NO `_play_game` helper — its game engine is
INLINE in `simulate_season` (logistic on team-strength diff / 7.5, 3 games per pair). Port v2's
midseason onto MAIN's engine; do NOT import v2's game/scoring code (it would change every score).

CRITICAL INVARIANT: main's runner is still 3-phase until P3, so the midseason machinery you add
is DORMANT (nothing calls prepare_midseason yet). Therefore ALL 202 tests, including
tests/test_golden_scores.py, MUST STILL PASS unchanged after P4. If a golden score moves, your
_play_game extraction changed behavior — fix it. Do not edit golden values in P4.

Steps:
1. Refactor: extract main's inline per-game logic from `simulate_season` into
   `_play_game(self, home, away, ratings, rng)` that computes the logistic probability and
   updates wins/losses EXACTLY as today (same formula, same rng.random() call, same order).
   Replace the inline loop with `for _ in range(games_per_pair): self._play_game(home, away,
   ratings, rng)`. This must be score-preserving.
2. Add module const `REGULAR_SEASON_GAMES_PER_PAIR = 3` and replace the literal `3` /
   `games_per_pair = 3` in simulate_season with it.
3. Add League fields: `partial_season_played: bool = False`, `partial_games_per_pair: int = 0`,
   `waiver_wire: list[int] = field(default_factory=list)`.
4. Add `simulate_partial_season(self, fraction)` using MAIN's `_team_strength` + `_play_game`
   and a SEPARATE rng namespace `self._rng("partial_season")` (must NOT touch the "season"
   stream). M2 fix: `games_per_pair = max(1, min(REGULAR_SEASON_GAMES_PER_PAIR - 1,
   round(REGULAR_SEASON_GAMES_PER_PAIR * fraction)))`; store it in `self.partial_games_per_pair`;
   play that many per pair (do NOT reset wins/losses — the partial leg accumulates); then
   `self._update_morale_from_standings()`.
5. Make `simulate_season` partial-aware WITHOUT dropping any of main's season-boundary
   bookkeeping (playoffs, _age_and_contracts, draft-class regen, resets, summary, score_team):
   if `not self.partial_season_played`: reset wins/losses (as today) and
   `games_per_pair = REGULAR_SEASON_GAMES_PER_PAIR`; else DON'T reset and
   `games_per_pair = max(1, REGULAR_SEASON_GAMES_PER_PAIR - self.partial_games_per_pair)`
   (M2: legs sum to a full season). At the season boundary also reset
   `partial_season_played=False`, `partial_games_per_pair=0`, `waiver_wire=[]`.
6. Port from v2 (adapt to main's fields/helpers), preserving v2's "seed directly, never via
   _rng" discipline so these never perturb the scoring RNG stream:
   `prepare_midseason` (guard on partial_season_played; simulate_partial_season(
   PARTIAL_SEASON_FRACTION) — import PARTIAL_SEASON_FRACTION from gm_bench.protocol;
   generate injuries; populate waivers; set partial_season_played=True),
   `_generate_midseason_injuries`, `_populate_waiver_wire`, `_update_morale_from_standings`,
   `_waiver_player_public`, and `_claim_waiver(self, action, phase) -> ActionResult` (uses
   waiver_wire; returns via _record).
7. Wire claim_waiver into `_dispatch_action` and add "claim_waiver" to `_available_actions` only
   when `phase == "midseason"`.
Acceptance: `uv run pytest -q` -> 202 passed (goldens UNCHANGED), ruff check + format clean.
Also assert in a REPL that a fresh League.prepare_midseason() sets partial_games_per_pair to a
value in [1, REGULAR_SEASON_GAMES_PER_PAIR-1] and that after a subsequent simulate_season the two
legs summed to REGULAR_SEASON_GAMES_PER_PAIR.
- P5 observation + schemas: add tiered (summary/full) observation + available_actions + query
  surfaces to main's observation; reconcile schemas/gm_observation.schema.json and
  schemas/gm_action_list.schema.json.
- P6 baseline cache: wire EpisodeConfig.baseline_cache_fingerprint() into
  run_many_cached_baselines (H1).
- P7 contract/version + goldens: set contract benchmark_version/fingerprint for the new
  episode shape; regenerate tests/test_golden_scores.py; update validity canaries.
- P8 adapters: merge examples/gm_agent_common.py + openai_compatible_agent.py (v2 query/session
  handling + main usage reporting).
- P9 docs: README.md, docs/benchmark_spec.md.
- P10 verify: full pytest, ruff, `python -m gm_bench validate-contract`, web build, and a real
  `python -m gm_bench run` observing a 4-phase episode with telemetry.
