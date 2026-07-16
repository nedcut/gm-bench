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
  paired_lift: number | null;
  ci95: number[] | null;
  significant: boolean | null;
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
  /** Display tier from CI-overlap grouping — the frozen plan publishes tiers, not ordinal ranks. */
  tier?: number;
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
  models: LeaderboardModel[];
  cli_harness_models: LeaderboardModel[];
  excluded_models: Array<{ id: string | null; issues: string[] }>;
  publication: {
    status: string;
    publishable_ranking: boolean;
    reason: string;
    planned_caps: Array<number | null>;
    frozen_output_token_cap: number | null;
    output_policy_basis?: string;
    model_registry_frozen?: boolean;
    smoke_gate_issues?: string[] | null;
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
