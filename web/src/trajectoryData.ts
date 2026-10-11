import type { ReplayFixture, ReplayPlayer } from "./types";

export interface Observation {
  team?: { name?: string; cap_room?: number; payroll?: number; wins?: number; losses?: number; roster?: ReplayPlayer[] };
  scout_reports?: unknown;
  [key: string]: unknown;
}
export interface Decision {
  decision_index: number;
  season: number;
  phase: string;
  interaction_rounds: { round: number; observation?: Observation; actions: Record<string, unknown>[] }[];
  results: { accepted: boolean; message: string; action: Record<string, unknown> }[];
  delta: Record<string, number>;
}
export interface Episode {
  kind: "scripted-demo";
  fixture: Omit<ReplayFixture, "decisions"> & { config: Record<string, unknown>; decisions: Decision[] };
  components: Record<string, number>;
  score: { final_score: number; strategy_score: number; protocol_penalty: number };
}
export interface Trajectories {
  schema: "gm-bench-public-trajectories-v1";
  track: "experimental-public-demo";
  seed_scope: "public-dev";
  source_commit: string;
  starting_state_digest: string;
  original_replay_sha256: string;
  tool_trace: null;
  episodes: Episode[];
}
export const trajectoryUrl = () => `${import.meta.env.BASE_URL}replay/trajectory-demo.json`;
export const LABELS: Record<string, string> = { conservative: "Conservative", "pick-trader": "Pick-trader" };
export const COMPONENTS = [
  ["recent_wins", "Recent wins"], ["playoff_rounds", "Playoff rounds"],
  ["championships", "Championships"], ["total_assets", "Roster assets"],
  ["young_assets", "Young assets"], ["future_pick_assets", "Future picks"],
  ["cap_room", "Cap flexibility"], ["current_strength", "Lineup strength"],
  ["roster_depth", "Roster depth"],
] as const;

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);

function player(value: unknown): boolean {
  return object(value) && finite(value.id) &&
    ["name", "position"].every(key => value[key] == null || typeof value[key] === "string") &&
    ["age", "overall", "potential", "salary", "contract_years"].every(key => value[key] === undefined || finite(value[key]));
}

/** Fail closed on corrupted exports; missing observations remain explicitly unavailable. */
export function parseTrajectories(value: unknown): Trajectories {
  if (!object(value) || value.schema !== "gm-bench-public-trajectories-v1" ||
      value.track !== "experimental-public-demo" || value.seed_scope !== "public-dev" ||
      !digest(value.starting_state_digest) || !digest(value.original_replay_sha256) ||
      typeof value.source_commit !== "string" || !/^[a-f0-9]{40}$/.test(value.source_commit) ||
      value.tool_trace !== null || !Array.isArray(value.episodes)) throw new Error("Unsupported public trajectory export.");
  for (const item of value.episodes) {
    if (!object(item) || item.kind !== "scripted-demo" || !object(item.fixture) ||
        !object(item.components) || !object(item.score)) throw new Error("Invalid episode evidence.");
    const f = item.fixture;
    if (f.schema !== "gm-bench-decision-replay-v1" || typeof f.agent !== "string" ||
        !finite(f.seed) || !finite(f.user_team_id) || !object(f.config) || !object(f.provenance) ||
        typeof f.provenance.contract_fingerprint !== "string" || !object(f.expected) ||
        !digest(f.expected.state_digest) || !object(f.expected.state) || !Array.isArray(f.decisions) ||
        !Array.isArray(f.expected.state.summaries)) throw new Error("Incomplete replay evidence.");
    for (const key of ["players", "prospects"]) {
      const pool = f.expected.state[key];
      if (pool != null && (!object(pool) || !Object.values(pool).every(player))) throw new Error("Invalid player evidence.");
    }
    const teams = f.expected.state.teams;
    if (teams != null && (!object(teams) || !Object.values(teams).every(t => object(t) && (t.name == null || typeof t.name === "string")))) throw new Error("Invalid team evidence.");
    if (!COMPONENTS.every(([key]) => finite((item.components as Record<string, unknown>)[`${key}_contribution`])) ||
        !Object.values(item.score).every(finite) || !finite(item.score.final_score) ||
        !finite(item.score.strategy_score) || !finite(item.score.protocol_penalty)) throw new Error("Invalid score evidence.");
    const sum = COMPONENTS.reduce((total, [key]) => total + (item.components as Record<string, number>)[`${key}_contribution`], 0);
    if (Math.abs(sum - item.score.strategy_score) > 0.0001 ||
        Math.abs(sum - item.score.protocol_penalty - item.score.final_score) > 0.0001) throw new Error("Score decomposition does not reconcile.");
    for (const summary of f.expected.state.summaries) {
      if (!object(summary) || ![summary.season, summary.wins, summary.losses, summary.score_after_season].every(finite)) throw new Error("Invalid season summary.");
    }
    for (const d of f.decisions) {
      if (!object(d) || !finite(d.season) || !finite(d.decision_index) || typeof d.phase !== "string" ||
          !Array.isArray(d.interaction_rounds) || !Array.isArray(d.results) || !object(d.delta) ||
          !Object.values(d.delta).every(finite)) throw new Error("Invalid decision evidence.");
      for (const r of d.interaction_rounds) {
        if (!object(r) || !finite(r.round) || !Array.isArray(r.actions) || !r.actions.every(object)) throw new Error("Invalid action round.");
        if (r.observation != null) {
          if (!object(r.observation)) throw new Error("Invalid observation.");
          const team = r.observation.team;
          if (team != null && (!object(team) || (team.name != null && typeof team.name !== "string") ||
              [team.cap_room, team.payroll, team.wins, team.losses].some(v => v !== undefined && !finite(v)) ||
              (team.roster != null && (!Array.isArray(team.roster) || !team.roster.every(player))))) throw new Error("Invalid roster observation.");
        }
      }
      if (!d.results.every(r => object(r) && typeof r.accepted === "boolean" && typeof r.message === "string" && object(r.action))) throw new Error("Invalid action results.");
    }
  }
  if (new Set(value.episodes.map(e => e.fixture.agent)).size !== value.episodes.length) throw new Error("Duplicate episode identifiers.");
  return value as unknown as Trajectories;
}

/** Same starting world is necessary; later decisions are not matched-state experiments. */
export function comparisonIssue(a: Episode, b: Episode): string | null {
  const x = a.fixture, y = b.fixture;
  if (x.agent === y.agent) return "Choose two different policies to compare their trajectories.";
  if (!x.decisions.length || !y.decisions.length) return "This pair has no recorded decision windows.";
  if (!x.decisions[0].interaction_rounds[0]?.observation || !y.decisions[0].interaction_rounds[0]?.observation) return "Starting observation unavailable. A matched starting scenario cannot be verified.";
  if (x.seed !== y.seed || x.user_team_id !== y.user_team_id ||
      x.provenance?.contract_fingerprint !== y.provenance?.contract_fingerprint ||
      JSON.stringify(x.config) !== JSON.stringify(y.config) ||
      JSON.stringify(x.decisions[0].interaction_rounds[0]?.observation) !== JSON.stringify(y.decisions[0].interaction_rounds[0]?.observation)) {
    return "Starting scenarios do not match. Paired navigation is unavailable: check seed, team, contract, configuration and initial observation.";
  }
  const phases = ["preseason", "midseason", "trade_deadline", "draft"];
  if ([x, y].some(f => f.decisions.length !== 20 || f.decisions.some((d, i) => d.season !== Math.floor(i / 4) + 1 || d.phase !== phases[i % 4]))) {
    return "The recordings do not contain matching, complete five-season decision windows.";
  }
  return null;
}

export function rosterChange(previous?: Observation, current?: Observation) {
  const before = previous?.team?.roster, after = current?.team?.roster;
  if (!before || !after) return null;
  return {
    added: after.filter(p => !before.some(q => p.id === q.id)),
    removed: before.filter(p => !after.some(q => p.id === q.id)),
  };
}
