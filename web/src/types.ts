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
  lane?: "api" | "cli-harness";
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
  fallback_rate: number;
  illegal_actions: number;
  total_tokens: number;
  tokens_per_decision: number | null;
  input_tokens_per_decision: number | null;
  output_tokens_per_decision: number | null;
  protocol_repair_attempts: number;
  protocol_repairs_succeeded: number;
  mechanic_breakdown: Record<string, { accepted: number; rejected: number }>;
  failed_queries?: number;
  cost_usd: number | null;
  cost_per_episode_usd: number | null;
  api_latency_s_per_decision: number | null;
  harness_latency_s_per_decision: number | null;
  decisions_with_usage: number;
  decision_points: number;
  seeds: number[] | null;
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
  tier: number;
  holm_adjusted_p_value: number;
  holm_reject_at_0_05: boolean | null;
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
    seeds: number[];
    seasons: number;
    decision_points_per_episode: number;
  };
  baselines: LeaderboardBaseline[];
  models: TieredLeaderboardModel[];
  cli_harness_models: LeaderboardModel[];
  excluded_models: Array<{ id: string | null; issues: string[] }>;
  publication: {
    status: string;
    publishable_ranking: boolean;
    publishable_results: boolean;
    reason: string;
    planned_caps: Array<number | null>;
    frozen_output_token_cap: number | null;
    output_policy_basis?: string;
    model_registry_frozen?: boolean;
    smoke_gate_issues?: string[] | null;
    panel_analysis_ready?: boolean;
    panel_analysis_issues?: string[];
    eligible_headline_models: number;
    minimum_headline_models: number;
  };
  headroom: {
    oracle: number;
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

/* ---------- puzzles ----------
   Illustrative content built by scripts/build_puzzles.py. Every option is a
   real scripted policy's choice from the same observation, graded by the
   immediate change in score components. Not a benchmark artifact. */

export interface PuzzleSituation {
  team: string;
  season: number;
  phase: string;
  record: string;
  cap_room: number;
  payroll: number;
  roster_size: number;
  championships: number;
  free_agents_available: number;
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
  state_key: string;
  seed: number;
  season: number;
  phase: string;
  subject: string;
  mechanic?: "trade" | "draft" | "free_agency" | "contracts" | "roster";
  worthiness: number;
  situation: PuzzleSituation;
  options: PuzzleOption[];
  answer: string;
  /** Option letter used by the recorded subject after deterministic permutation. */
  subject_option?: string;
  /** Signed immediate-score margin for the recorded subject choice. */
  subject_margin?: number;
  /** Whether the recorded subject beat the reference policies on this card. */
  outcome?: PuzzleOutcome;
  /** Non-negative miss magnitude retained for older puzzle fixtures. */
  points_left_on_the_table?: number;
}

export interface PuzzleSet {
  schema: string;
  note: string;
  source_records: number;
  puzzles: Puzzle[];
}
