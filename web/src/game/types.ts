export interface Player {
  id: number;
  name: string;
  position: string;
  sub_position?: string;
  age: number;
  overall: number;
  potential: number;
  salary: number;
  contract_years: number;
  injury_risk: number;
  release_dead_cap?: { total: number; by_season: Record<string, number> };
  extension_quotes?: Record<string, number>;
  contract_quotes?: Record<string, number>;
  asking_salary?: number;
  resign_blocked?: boolean;
}
export interface Team {
  id: number;
  name: string;
  wins: number;
  losses: number;
  championships: number;
  payroll: number;
  cap_room: number;
  roster: Player[];
  lineup: number[];
  dead_cap: Record<string, number>;
  draft_picks: Record<string, number>;
  picks?: { season: number; from_team_name: string; projected_slot: number }[];
}
export interface Standing {
  team_id: number;
  team_name: string;
  wins: number;
  losses: number;
  public_strength: number;
  championships: number;
}
export interface History {
  season: number;
  wins: number;
  losses: number;
  champion_team_id: number;
  playoff_rounds: number;
  score_after_season: number;
}
export interface Offer {
  offer_id: string;
  team_id: number;
  team_name: string;
  you_receive_players: Player[];
  they_receive_players: Player[];
  you_receive_pick_seasons: number[];
  they_receive_pick_seasons: number[];
}
export interface Snapshot {
  season: number;
  seasons_total: number;
  phase: string;
  done: boolean;
  seed: number;
  team: Team;
  standings: Standing[];
  teams: Team[];
  history: History[];
  free_agents: Player[];
  draft_class: Player[];
  waiver_wire: Player[];
  incoming_offers: Offer[];
  scout_reports: Record<string, number>;
  memo: string;
  effective_lineup: number[];
  legal_tools: string[];
  actions_taken: number;
  score: Record<string, number>;
  score_terms: Record<string, number>;
  reference: {
    name: string;
    final_score: number;
    wins: number;
    championships: number;
  } | null;
  rules: {
    salary_cap: number;
    hard_cap_buffer: number;
    roster_min: number;
    lineup_size: number;
    lineup_min_positions: Record<string, number>;
    scouting: { points_remaining: number };
  };
  recent_transactions: {
    season: number;
    phase: string;
    team_id: number;
    message: string;
    accepted: boolean;
    action: Record<string, unknown>;
  }[];
}
export interface GameSave {
  schema: string;
  engine_version: string;
  seed: number;
  calls: { tool: string; arguments: Record<string, unknown>; ok: boolean }[];
}
export interface GameRequest {
  id: number;
  command: "new" | "restore" | "act";
  seed?: number;
  save?: unknown;
  tool?: string;
  arguments?: Record<string, unknown>;
}
export interface GameResponse {
  id: number;
  snapshot?: Snapshot;
  save?: GameSave;
  result?: {
    ok: boolean;
    message: string;
    penalized?: boolean;
    season_result?: History;
  };
  error?: string;
}
