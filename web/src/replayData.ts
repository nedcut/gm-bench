import type {
  ReplayDecision,
  ReplayFixture,
  ReplayObservation,
  ReplaySeasonSummary,
  ReplayTransaction,
} from "./types";

/* Reading helpers for the committed replay fixture.
 *
 * The fixture is a reproducibility artifact, not a presentation format: the
 * browsable view has to derive its own labels from raw state, and has to stay
 * legible when a field the site would like is simply absent. Every helper here
 * degrades to a readable fallback rather than throwing. */

export const PHASE_LABEL: Record<string, string> = {
  preseason: "preseason",
  midseason: "midseason",
  trade_deadline: "trade deadline",
  draft: "draft",
};

export function phaseLabel(phase: string): string {
  return PHASE_LABEL[phase] ?? phase.replace(/_/g, " ");
}

export function fixtureUrl(): string {
  return `${import.meta.env.BASE_URL}replay/replay_fixture.json`;
}

export async function loadReplayFixture(signal?: AbortSignal): Promise<ReplayFixture> {
  const response = await fetch(fixtureUrl(), { signal });
  if (!response.ok) {
    throw new Error(`replay fixture request failed (${response.status})`);
  }
  const payload = (await response.json()) as ReplayFixture;
  if (!Array.isArray(payload.decisions) || payload.decisions.length === 0) {
    throw new Error("replay fixture has no decisions");
  }
  return payload;
}

/** id -> display name, drawn from both rostered players and undrafted prospects. */
export function nameIndex(fixture: ReplayFixture): Map<number, string> {
  const names = new Map<number, string>();
  const state = fixture.expected.state;
  for (const pool of [state?.players, state?.prospects]) {
    for (const [key, player] of Object.entries(pool ?? {})) {
      const id = Number(key);
      if (Number.isFinite(id) && player?.name) names.set(id, player.name);
    }
  }
  return names;
}

export function teamNameIndex(fixture: ReplayFixture): Map<number, string> {
  const names = new Map<number, string>();
  for (const [key, team] of Object.entries(fixture.expected.state?.teams ?? {})) {
    const id = Number(key);
    if (Number.isFinite(id) && team?.name) names.set(id, team.name);
  }
  return names;
}

function playerLabel(names: Map<number, string>, id: unknown): string {
  if (typeof id !== "number") return "an unknown player";
  return names.get(id) ?? `player #${id}`;
}

function money(value: unknown): string {
  return typeof value === "number" ? `$${value.toFixed(2)}M` : "";
}

/** Draft picks trade by season in v6, so a trade line has to name them. */
function tradeSide(
  playerIds: unknown,
  pickSeasons: unknown,
  names: Map<number, string>,
): string {
  const parts = Array.isArray(playerIds)
    ? playerIds.map((id) => playerLabel(names, id))
    : [];
  if (Array.isArray(pickSeasons)) {
    for (const season of pickSeasons) {
      if (typeof season === "number") parts.push(`season ${season} pick`);
    }
  }
  return parts.length > 0 ? parts.join(", ") : "nothing";
}

function offerLabel(action: Record<string, unknown>): string {
  const id = action.offer_id;
  return typeof id === "string" && id ? `offer ${id}` : "the standing offer";
}

/** One human line per action, so a reader can follow a decision without JSON. */
export function describeAction(
  action: Record<string, unknown>,
  names: Map<number, string>,
  teams: Map<number, string>,
): string {
  const type = String(action.type ?? "action");
  switch (type) {
    case "sign_free_agent":
      return `Sign ${playerLabel(names, action.player_id)} — ${money(action.salary)} × ${action.years ?? "?"} yr`;
    case "extend_contract":
      return `Extend ${playerLabel(names, action.player_id)} — ${money(action.salary)} × ${action.years ?? "?"} yr`;
    case "release":
      return `Release ${playerLabel(names, action.player_id)}`;
    case "draft":
      return `Draft ${playerLabel(names, action.prospect_id)}`;
    case "set_lineup": {
      const ids = Array.isArray(action.player_ids) ? action.player_ids.length : 0;
      return `Set lineup — ${ids} players dressed`;
    }
    case "trade": {
      const partner = action.partner_team_id;
      const partnerName =
        typeof partner === "number" ? (teams.get(partner) ?? `team ${partner}`) : "a partner";
      const give = tradeSide(action.give_player_ids, action.give_pick_seasons, names);
      const receive = tradeSide(action.receive_player_ids, action.receive_pick_seasons, names);
      return `Trade with ${partnerName} — send ${give}, receive ${receive}`;
    }
    case "accept_trade_offer":
      return `Accept ${offerLabel(action)}`;
    case "reject_trade_offer":
      return `Reject ${offerLabel(action)}`;
    case "counter_trade_offer": {
      // A side the counter leaves out keeps the offer's own terms, so only the
      // sides the model actually restated are described here.
      const sides: string[] = [];
      if (action.give_player_ids !== undefined || action.give_pick_seasons !== undefined) {
        sides.push(`send ${tradeSide(action.give_player_ids, action.give_pick_seasons, names)}`);
      }
      if (action.receive_player_ids !== undefined || action.receive_pick_seasons !== undefined) {
        sides.push(
          `receive ${tradeSide(action.receive_player_ids, action.receive_pick_seasons, names)}`,
        );
      }
      const terms = sides.length > 0 ? sides.join(", ") : "terms as offered";
      return `Counter ${offerLabel(action)} — ${terms}`;
    }
    case "claim_waiver":
      return `Claim ${playerLabel(names, action.player_id)} off waivers`;
    case "scout":
      return `Scout ${playerLabel(names, action.prospect_id ?? action.player_id)}`;
    case "memo":
      return `Memo — "${String(action.text ?? "")}"`;
    case "noop":
      return "No action";
    default:
      return type.replace(/_/g, " ");
  }
}

/**
 * The record an observation carries is the team's career total, not this
 * season's: it accumulates across the episode exactly as the season summaries
 * do. Callers must label it accordingly, or use `observedSeasonRecord` below.
 */
export function teamRecord(observation: ReplayObservation | undefined): string {
  const team = observation?.team;
  if (!team) return "—";
  if (team.record) return team.record;
  if (team.wins === undefined && team.losses === undefined) return "—";
  return `${team.wins ?? 0}-${team.losses ?? 0}`;
}

function careerWinsLosses(
  observation: ReplayObservation | undefined,
): { wins: number; losses: number } | null {
  const team = observation?.team;
  if (!team) return null;
  if (typeof team.wins === "number" && typeof team.losses === "number") {
    return { wins: team.wins, losses: team.losses };
  }
  const parsed = /^(\d+)-(\d+)/.exec(team.record ?? "");
  if (!parsed) return null;
  return { wins: Number(parsed[1]), losses: Number(parsed[2]) };
}

/**
 * The record inside the season on screen, de-cumulated the same way
 * `seasonRecord` de-cumulates the season summaries: subtract everything
 * recorded up to the end of the previous season.
 */
export function observedSeasonRecord(
  observation: ReplayObservation | undefined,
  summaries: ReplaySeasonSummary[],
  season: number,
): string | null {
  const career = careerWinsLosses(observation);
  if (!career) return null;
  const previous = summaries.filter((row) => row.season < season).sort((a, b) => a.season - b.season).at(-1);
  const wins = career.wins - (previous?.wins ?? 0);
  const losses = career.losses - (previous?.losses ?? 0);
  if (wins < 0 || losses < 0) return null;
  return `${wins}-${losses}`;
}

export interface RosterTable {
  columns: string[];
  rows: string[][];
}

/**
 * The v6 observation ships the roster as pipe-delimited rows with a separate
 * column header, which is exactly what the model reads. Rendering those rows
 * verbatim keeps the replay honest; pre-v6 fixtures fall back to their object
 * roster. Column names carry parenthetical notes, trimmed for the table head.
 */
export function rosterTable(observation: ReplayObservation | undefined): RosterTable | null {
  const team = observation?.team;
  if (Array.isArray(team?.roster) && team.roster.length > 0) {
    const columns = (team.roster_columns ?? "")
      .split("|")
      .map((column) => column.replace(/\s*\(.*$/, "").trim())
      .filter(Boolean);
    return { columns, rows: team.roster.map((row) => row.split("|")) };
  }
  if (Array.isArray(team?.top_roster) && team.top_roster.length > 0) {
    return {
      columns: ["id", "name", "pos", "age", "overall", "salary"],
      rows: team.top_roster.map((player) => [
        String(player.id),
        player.name ?? "",
        player.position ?? "",
        String(player.age ?? ""),
        player.overall === undefined ? "" : player.overall.toFixed(1),
        player.salary === undefined ? "" : player.salary.toFixed(2),
      ]),
    };
  }
  return null;
}

/**
 * Season summaries accumulate wins and losses across the episode, so a per-
 * season record is the difference from the previous season. Printing the raw
 * totals under a "record" label would misreport every season after the first.
 */
export function seasonRecord(
  summaries: ReplaySeasonSummary[],
  season: number,
): string | null {
  const index = summaries.findIndex((row) => row.season === season);
  if (index < 0) return null;
  const current = summaries[index];
  const previous = index > 0 ? summaries[index - 1] : null;
  const wins = current.wins - (previous?.wins ?? 0);
  const losses = current.losses - (previous?.losses ?? 0);
  if (wins < 0 || losses < 0) return `${current.wins}-${current.losses}`;
  return `${wins}-${losses}`;
}

/** Transaction lines the model's own team produced, oldest first. */
export function teamTransactions(fixture: ReplayFixture): ReplayTransaction[] {
  const all = fixture.expected.state?.transactions ?? [];
  return all.filter((txn) => txn.team_id === fixture.user_team_id);
}

export interface SeasonHistory {
  season: number;
  phases: Array<{ phase: string; transactions: ReplayTransaction[] }>;
}

/** Season -> phase -> transactions, preserving recorded order within a phase. */
export function transactionHistory(fixture: ReplayFixture): SeasonHistory[] {
  const bySeason = new Map<number, Map<string, ReplayTransaction[]>>();
  for (const txn of teamTransactions(fixture)) {
    const phases = bySeason.get(txn.season) ?? new Map<string, ReplayTransaction[]>();
    const rows = phases.get(txn.phase) ?? [];
    rows.push(txn);
    phases.set(txn.phase, rows);
    bySeason.set(txn.season, phases);
  }
  return [...bySeason.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([season, phases]) => ({
      season,
      phases: [...phases.entries()].map(([phase, transactions]) => ({ phase, transactions })),
    }));
}

/** What the league recorded for the model's team at one decision point. */
export function decisionOutcome(
  fixture: ReplayFixture,
  decision: ReplayDecision,
): ReplayTransaction[] {
  return teamTransactions(fixture).filter(
    (txn) => txn.season === decision.season && txn.phase === decision.phase,
  );
}

/**
 * Rejected attempts carry the REJECTED prefix the artifact format uses, so a
 * reader never mistakes an attempted move for a completed one.
 */
export function transactionLine(txn: ReplayTransaction): string {
  const message = txn.message.trim();
  if (txn.accepted) return message;
  return message.toUpperCase().startsWith("REJECTED") ? message : `REJECTED · ${message}`;
}
