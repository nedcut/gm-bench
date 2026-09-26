export interface SnapshotConfig {
  candidate: string;
  baselines: string[];
  seeds: number[];
  seasons: number;
}

export interface Normalized {
  candidate_mean_score: number;
  baseline_panel_mean_score: number;
  score_lift: number;
  score_lift_pct: number;
  candidate_illegal_actions: number;
  baseline_illegal_actions: number;
}

export interface PerSeed {
  seed: number;
  candidate_score: number;
  baseline_panel_score: number;
  lift: number;
}

export interface Paired {
  num_seeds: number;
  per_seed: PerSeed[];
  paired_lift_mean: number;
  paired_lift_stddev: number;
  paired_lift_ci95: number[];
  significant_at_95: boolean;
  candidate_seed_win_rate: number;
  best_baseline: {
    agent: string;
    mean_score: number;
    paired_lift_mean: number;
    seed_win_rate: number;
  } | null;
}

export interface StandingRow {
  agent: string;
  mean_score: number;
  score_stddev: number;
  mean_wins: number;
  titles: number;
  illegal_actions: number;
  episodes: number;
  best_score: number;
  worst_score: number;
}

export interface SeasonRow {
  season: number;
  wins: number;
  losses: number;
  playoff_rounds: number;
  champion: boolean;
  cap_room: number;
  score_after_season: number;
}

export interface SampleTransaction {
  season: number;
  phase: string;
  accepted: boolean;
  message: string;
  action: Record<string, unknown>;
}

export interface LeaderboardModel {
  id: string;
  model: string;
  provider: string;
  /**
   * `api` is the chat-lane headline; `cli-harness` a coding-agent product;
   * `decision-api` a decision model answering a host-written question set
   * (docs/typesafe_jev_lane.md), published beside the headline, never in it.
   */
  lane?: "api" | "cli-harness" | "decision-api";
  output_token_cap: number | null;
  mean_score: number;
  score_stddev: number;
  mean_strategy_score: number | null;
  protocol_penalty: number | null;
  /**
   * Primary contrast: paired lift versus pick-trader, as frozen in
   * config/publication_protocol.json. Present only on rows that cleared the
   * publication gate, which is why it is optional here and asserted in
   * benchmarkData.ts. Always publish this one, never `full_panel_*`.
   */
  primary_lift?: number | null;
  primary_ci95?: number[] | null;
  /**
   * Secondary contrast: lift versus the mean of the whole baseline panel
   * (which includes weak baselines like `random`). Descriptive only.
   * `full_panel_significant_at_95` is the panel bootstrap flag that the
   * statistical analysis plan explicitly forbids as a headline claim.
   */
  full_panel_lift: number | null;
  full_panel_ci95: number[] | null;
  full_panel_significant_at_95: boolean | null;
  seed_win_rate: number | null;
  lift_vs_best_baseline: number | null;
  /**
   * Legacy name for `decision_failure_rate`. Rows published before the field was
   * renamed carry this key and nothing else; it never measured an adapter
   * fallback path, only decisions whose call returned no usable turn.
   */
  fallback_rate?: number | null;
  illegal_actions: number;
  total_tokens: number;
  tokens_per_decision: number | null;
  input_tokens_per_decision: number | null;
  output_tokens_per_decision: number | null;
  protocol_repair_attempts: number;
  protocol_repairs_succeeded: number;
  mechanic_breakdown: Record<string, { accepted: number; rejected: number }>;
  failed_queries?: number;
  /**
   * v6 reliability fields, emitted by gm_bench.runner.summarize_episodes and
   * reported *beside* the score, never folded into it. Rows published before
   * v6 do not carry them, so every consumer must treat absence as "not
   * reported" rather than zero.
   */
  failed_decisions?: number | null;
  /** Share of decisions whose call never returned a usable turn. */
  decision_failure_rate?: number | null;
  malformed_decisions?: number | null;
  unrecoverable_decisions?: number | null;
  malformed_rate?: number | null;
  unrecoverable_rate?: number | null;
  /**
   * Mean per-seed score spread across repeats — the model's own run-to-run
   * noise, as distinct from `score_stddev` across seeds. Optional for the same
   * reason: pre-v6 rows never computed it.
   */
  within_seed_score_stddev?: number | null;
  /** Per-seed mean scores keyed by seed, when the row publishes them. */
  per_seed_scores?: Record<string, number> | null;
  /** Pinned provider route for the run, when one was pinned. */
  route?: string | null;
  cost_usd: number | null;
  cost_per_episode_usd: number | null;
  api_latency_s_per_decision: number | null;
  harness_latency_s_per_decision: number | null;
  decisions_with_usage: number;
  decision_points: number;
  seeds: number[] | null;
  /**
   * How wide this row's own seed panel was. Survives redaction, where `seeds`
   * does not: a private-panel row hides its seed values but still publishes
   * its count. Never substitute the public preset's panel width here.
   */
  seed_count: number | null;
  seasons: number | null;
  baseline_panel_mean_score: number | null;
  benchmark_version: string | null;
  contract_fingerprint: string | null;
  seed_panel: string | null;
  seed_panel_hash: string | null;
  sota_v2_eligible?: boolean;
  sota_v2_issues?: string[];
  publication_eligible?: boolean;
  publication_issues?: string[];
  artifact_sha256?: string;
  raw_artifact_sha256?: string;
}

export interface TieredLeaderboardModel extends LeaderboardModel {
  /**
   * Holm tier, present only when a study predeclares model-to-model contrasts.
   * sota-v5 predeclares only model-versus-pick-trader, so its rows carry no
   * tier and the site must not invent an ordering for them.
   */
  tier?: number;
  holm_adjusted_p_value: number;
  holm_reject_at_0_05: boolean | null;
}

/**
 * A row from the decision-model lane. Same contract, same private panel, same
 * scripted baselines as the headline, but the model answers typed questions
 * and the adapter composes the action batch, so the score measures the model
 * plus that scaffold. It is not in the Holm family and carries no
 * `primary_lift`; the comparison it supports is against the scripted
 * baselines, never against a headline row.
 */
export interface DecisionLaneModel extends LeaderboardModel {
  lane: "decision-api";
  /** Which endpoint served the run, e.g. the OpenRouter decisions endpoint. */
  route: string;
  /** Hash of the adapter, question set, and compaction rules the row was measured with. */
  scaffold_fingerprint: string | null;
  /** The lane's pinned knobs (route, yes-threshold, trades on/off), recorded on the run. */
  provider_options: Record<string, string>;
  /** Repo-relative path of the redacted artifact behind this row. */
  artifact_path: string;
  timestamp_utc: string | null;
}

/**
 * One GM-Bench 2.0 row (docs/bench_v2_spec.md): a model inside its own harness
 * driving the simulator through MCP tools, one session per episode. Row
 * identity is model + harness + harness version (+ variant). Only
 * panel-grade rows reach the site: the lane's frozen 32-seed private panel,
 * seeds redacted, harness isolated from the driver by user or container. It
 * is never a 1.0 row and carries nothing paired against one; its only paired
 * statistic is the pick-trader reference on its own seeds.
 */
export interface AgenticLaneRow {
  id: string;
  lane: "agentic";
  grade: "panel";
  agent: string;
  model: string;
  harness: { name: string; version: string; model: string; variant: string | null };
  /**
   * True unless config/bench_v2_lane.json pins this model's served version or
   * provider. An unpinned row may not be reproducible and is never a headline.
   */
  unpinned: boolean;
  /** The pin that makes the row reproducible; null when unpinned. */
  pin: string | null;
  isolation: "separate-user" | "container";
  panel: { distinct_seeds: number; episodes: number; sha256: string };
  seasons: number;
  phase_guard_seconds: number | null;
  max_nudges: number | null;
  /** Mean of per-seed means, and the population SD, min, and max of those means. */
  mean_score: number;
  score_stddev: number;
  seed_mean_min: number;
  seed_mean_max: number;
  illegal_actions: number | null;
  failed_decisions: number | null;
  /**
   * The spec's only supported inference: the predeclared pick-trader contrast
   * on this row's own seeds and seasons, computed at redaction from the raw
   * run. Lift is the row's per-seed score minus pick-trader's. Aggregates
   * only; per-seed values never reach the site.
   */
  reference: {
    agent: "pick-trader";
    mean_score: number;
    floor: { agent: "random"; mean_score: number };
    seasons: number;
    num_seeds: number;
    paired_lift_mean: number;
    paired_lift_stddev: number;
    paired_lift_ci95: number[];
    sign_flip_p_value: number;
    significant_at_95: boolean;
    candidate_seed_win_rate: number;
  };
  contract: {
    benchmark_version: string;
    agentic_fingerprint: string;
    base_benchmark_version: string;
    base_contract_fingerprint: string;
    tool_surface: string;
    brief: string;
    scoring_version: string;
    simulator_version: string;
  };
  /** Budgets are reported, not capped. Token and cost fields are null when unmeasured. */
  telemetry: {
    episodes: number;
    tool_calls: number;
    tool_calls_per_episode: number;
    tool_calls_by_tool: Record<string, number>;
    scout_points_used: number;
    phases_ended_by: Record<string, number>;
    nudges_used: number;
    nudges_per_episode: number;
    guard_kills: number;
    /** Harness runs that ended on a retryable provider error (e.g. a 429), and the backoff waited before resuming. */
    provider_stalls: number;
    provider_stall_wait_seconds: number;
    /** Of those stalls, harness runs stopped for printing nothing at all (OpenCode retries a 429 silently). */
    silent_harness_kills: number;
    /** Null when a harness in the row does not report compactions (Codex): unmeasured, not zero. */
    compactions: number | null;
    wall_seconds: number;
    wall_seconds_per_episode: number;
    /** Episodes whose harness reported token telemetry; token and cost totals cover only these. */
    telemetry_episodes: number;
    input_tokens: number | null;
    output_tokens: number | null;
    reasoning_tokens: number | null;
    cached_input_tokens: number | null;
    /** "inclusive-v1": input_tokens = uncached + cached + cache-write, output_tokens includes
     * reasoning (reasoning_tokens is a subset). "legacy": recorded before that shape, in the
     * harness's own convention. Null when no episode reported tokens. */
    token_shape?: "inclusive-v1" | "legacy" | "mixed" | null;
    uncached_input_tokens?: number | null;
    cache_write_input_tokens?: number | null;
    cost_usd: number | null;
    cost_per_episode_usd: number | null;
    /** What the reported tokens would cost at API list price (cached input at the cached
     * rate), for a harness that reports no billed cost (Codex). An estimate, never billed;
     * null when no episode carries one. Never folded into cost_usd. */
    api_equivalent_cost_usd?: number | null;
    api_equivalent_cost_per_episode_usd?: number | null;
    api_equivalent_cost_episodes?: number;
    /** Some turn's input grew past the model's long-context threshold, so a request may
     * have been billed at the higher tier and the short-context estimate may be low. */
    api_equivalent_long_context_possible?: boolean;
    /** A subscription harness's usage windows as it reported them (Codex), and the panel's
     * pauses for an exhausted window. Null or absent when no episode reported any. */
    quota?: {
      episodes_reporting: number;
      plan_types: string[];
      window_minutes: number[];
      max_used_percent: number | null;
      pauses: number;
      pause_seconds: number;
      episodes_ended_by_quota?: number;
    } | null;
  };
  /** Server ledger (authoritative) versus the harness's own tool-event count. */
  agreement: {
    episodes: number;
    episodes_agreeing: number;
    ledger_tool_calls: number;
    harness_tool_calls: number;
  };
  /** A 1.0 row on the same model, linked by id; the two are not paired here. */
  v1_row_id: string | null;
  artifact_path: string;
  raw_artifact_sha256: string;
  compacted_at_utc: string | null;
}

export interface LeaderboardBaseline {
  agent: string;
  mean_score: number;
  score_stddev: number;
}

export interface Leaderboard {
  updated: string;
  contract?: {
    benchmark_version: string;
    contract_fingerprint: string;
    scoring_version?: string;
    simulator_version?: string;
    action_protocol_version?: string;
    observation_version?: string;
    scoring_scale_fingerprint?: string;
  };
  preset: {
    name: string;
    /**
     * Seed values for a public panel, or a redaction sentinel string for a
     * private panel. Counts must come from `seed_count`, never from this.
     */
    seeds: number[] | string;
    /** Panel width, published even when the seed values are withheld. */
    seed_count?: number | null;
    sha256?: string;
    hiding_commitment_sha256?: string;
    seasons: number;
    decision_points_per_episode: number;
  };
  baselines: LeaderboardBaseline[];
  models: TieredLeaderboardModel[];
  cli_harness_models: LeaderboardModel[];
  /** Optional so the archived sota-v2 dataset, which predates the lane, still types. */
  decision_lane_models?: DecisionLaneModel[];
  /**
   * GM-Bench 2.0 rows, panel grade only. A different contract from every
   * array above; optional so the archived sota-v2 dataset still types.
   */
  agentic_lane?: AgenticLaneRow[];
  excluded_models: Array<{ id: string | null; issues: string[] }>;
  publication: {
    status: string;
    publishable_ranking: boolean;
    publishable_results: boolean;
    /* Gate prose and the per-cell cap plan are v2-era fields; a v5 dataset
       states its cap once, in frozen_output_token_cap. */
    reason?: string;
    planned_caps?: Array<number | null>;
    frozen_output_token_cap: number | null;
    output_policy_basis?: string;
    model_registry_frozen?: boolean;
    smoke_gate_issues?: string[] | null;
    panel_analysis_ready?: boolean;
    panel_analysis_issues?: string[];
    eligible_headline_models: number;
    minimum_headline_models: number;
    analysis_mode?: string;
    /** Every pre-registered model, published or not: the Holm family. */
    models?: Array<{ id: string; model: string; provider: string }>;
  };
  headroom: {
    /**
     * Partial-oracle reference score, or null for a study that ran no oracle
     * baseline. sota-v5 has none: pick-trader is the sole contrast.
     */
    oracle: number | null;
    pick_trader: number;
    best_model: number | null;
    random: number;
  };
}

export interface Snapshot {
  config: SnapshotConfig;
  normalized: Normalized;
  paired: Paired;
  standings: StandingRow[];
  season_trace: {
    agent: string;
    seed: number;
    seasons: SeasonRow[];
  };
  sample_transactions: SampleTransaction[];
}

/* ---------- replay fixture ----------
   public/replay/replay_fixture.json, written by
   scripts/build_web_replay_bundle.py --write-fixture. The same file the Pyodide
   verifier replays, so the browsable episode and the verified episode can never
   describe different runs. Everything the site reads beyond the schema and the
   decision list is optional: a fixture is a reproducibility artifact first. */

export interface ReplayPlayer {
  id: number;
  name?: string;
  position?: string;
  age?: number;
  overall?: number;
  potential?: number;
  salary?: number;
  contract_years?: number;
}

export interface ReplayObservation {
  season?: number;
  phase?: string;
  interaction_round?: number;
  memo?: string;
  hint?: string | null;
  action_results?: Array<{ accepted?: boolean; message?: string }> | null;
  team?: {
    id?: number;
    name?: string;
    /** v6 renders the record as a string; older observations carry counts. */
    record?: string;
    wins?: number;
    losses?: number;
    cap_room?: number;
    payroll?: number;
    championships?: number;
    /** v6 tabular roster: pipe-delimited rows described by `roster_columns`. */
    roster?: string[];
    roster_columns?: string;
    /** Pre-v6 roster shape, kept so old fixtures still render. */
    top_roster?: ReplayPlayer[];
  };
  free_agents?: unknown[];
  draft_class?: unknown[];
  trade_market?: unknown[];
  incoming_offers?: unknown[];
}

export interface ReplayRound {
  round: number;
  observation: ReplayObservation;
  actions: Array<Record<string, unknown>>;
}

export interface ReplayDecision {
  decision_index: number;
  season: number;
  phase: string;
  interaction_rounds: ReplayRound[];
}

export interface ReplayTransaction {
  season: number;
  phase: string;
  team_id: number;
  accepted: boolean;
  message: string;
  action: Record<string, unknown>;
}

export interface ReplaySeasonSummary {
  season: number;
  wins: number;
  losses: number;
  playoff_rounds: number;
  champion_team_id?: number | null;
  cap_room?: number;
  payroll?: number;
  score_after_season?: number;
}

export interface ReplayFixture {
  schema: string;
  agent: string;
  seed: number;
  user_team_id: number;
  provenance?: {
    contract_fingerprint?: string | null;
    recorder_version?: string | null;
    git_head?: string | null;
  };
  decisions: ReplayDecision[];
  expected: {
    state_digest: string;
    state?: {
      players?: Record<string, ReplayPlayer>;
      prospects?: Record<string, ReplayPlayer>;
      teams?: Record<string, { id?: number; name?: string }>;
      transactions?: ReplayTransaction[];
      summaries?: ReplaySeasonSummary[];
    };
  };
}

/* ---------- puzzles ----------
   Illustrative content built by scripts/build_puzzles.py. Every option is a
   real scripted policy's choice from the same observation, graded by the
   immediate change in score components. Not a benchmark artifact. */

/* Only what the card renders. The built deck carries more per-situation detail
   (payroll, championships, free-agent counts); it stays in the JSON. */
export interface PuzzleSituation {
  team: string;
  season: number;
  phase: string;
  record: string;
  cap_room: number;
  roster_size: number;
  offers_on_the_table: number;
}

export interface PuzzleOption {
  id: string;
  lines: string[];
  chosen_by: string[];
  immediate_score: number;
  summary: string;
  delta: Record<string, number>;
}

export type PuzzleOutcome = "subject_won" | "subject_missed";

export interface Puzzle {
  id: string;
  seed: number;
  season: number;
  phase: string;
  subject: string;
  situation: PuzzleSituation;
  options: PuzzleOption[];
  answer: string;
  /** Signed immediate-score margin for the recorded subject choice against the
   * best alternative recorded choice. */
  subject_margin?: number;
  /** Whether the recorded subject beat the reference policies on this card. */
  outcome?: PuzzleOutcome;
  /** Non-negative miss magnitude retained for older puzzle fixtures. */
  points_left_on_the_table?: number;
}

export interface PuzzleSet {
  note: string;
  puzzles: Puzzle[];
}
