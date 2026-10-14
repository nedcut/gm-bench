import { useEffect, useState } from "react";
import type { AgenticLaneRow, Leaderboard } from "./types";

/* Everything the 2.0 pages show, derived from the published leaderboard
   record. Rows are compared with pick-trader and nothing else; the table is
   sorted by score for reading only. */

export const HARNESSES: Record<string, string> = {
  claude: "Claude Code",
  codex: "Codex",
  cursor: "Cursor",
  opencode: "OpenCode",
};

/* Vendor by model-id prefix. Colors live in CSS (--vendor-<key>) so both themes tune them. */
const VENDOR_PREFIXES: Array<[RegExp, string, string]> = [
  [/^claude/, "anthropic", "Anthropic"],
  [/^(gpt|o\d|codex)/, "openai", "OpenAI"],
  [/^composer/, "cursor", "Cursor"],
  [/^gemini/, "google", "Google"],
  [/^grok/, "xai", "xAI"],
  [/^glm/, "zai", "Z.ai"],
  [/^kimi/, "moonshot", "Moonshot"],
  [/^deepseek/, "deepseek", "DeepSeek"],
  [/^minimax/, "minimax", "MiniMax"],
  [/^qwen/, "qwen", "Qwen"],
];

export interface Vendor {
  key: string;
  name: string;
}

export function vendorOf(model: string): Vendor {
  const id = model.split("/").at(-1) ?? model;
  for (const [pattern, key, name] of VENDOR_PREFIXES) if (pattern.test(id)) return { key, name };
  return { key: "other", name: "Other" };
}

export interface Cost {
  usd: number | null;
  kind: "billed" | "estimate" | "unmeasured";
  /** The estimate may be low: some turns exceeded the long-context price threshold. */
  lowerBound: boolean;
}

/* A billed or harness-reported cost wins; without one, the API list-price
   estimate; with neither, unmeasured (never zero). */
export function costOf(row: AgenticLaneRow): Cost {
  const t = row.telemetry;
  if (t.cost_per_episode_usd !== null) return { usd: t.cost_per_episode_usd, kind: "billed", lowerBound: false };
  const estimate = t.api_equivalent_cost_per_episode_usd ?? null;
  if (estimate !== null) {
    return { usd: estimate, kind: "estimate", lowerBound: Boolean(t.api_equivalent_long_context_possible) };
  }
  return { usd: null, kind: "unmeasured", lowerBound: false };
}

export interface ModelRow {
  kind: "model";
  id: string;
  label: string;
  model: string;
  harness: string;
  harnessKey: string;
  harnessVersion: string;
  vendor: Vendor;
  score: number;
  /** Score interval: pick-trader's mean plus the paired-lift 95% interval. */
  ci: [number, number] | null;
  lift: number;
  liftCi: [number, number] | null;
  p: number;
  pUpperBound: boolean;
  seedWinRate: number;
  toolCalls: number;
  inputTokens: number | null;
  outputTokens: number | null;
  minutes: number;
  emptyPhases: number | null;
  phases: number;
  cost: Cost;
  unpinned: boolean;
  isolation: string;
  seeds: number;
  sd: number;
  seedRange: [number, number];
  illegal: number | null;
  nudges: number;
  artifact: string;
  caveat: string | null;
  source: AgenticLaneRow;
}

export interface BotRow {
  kind: "bot";
  id: string;
  label: string;
  score: number;
  isBar: boolean;
}

export type StandingsRow = ModelRow | BotRow;

/* Caveats a row's numbers cannot carry, keyed by row id. Source:
   docs/bench_v2_spec.md, "Changes after the freeze". */
const ROW_CAVEATS: Record<string, string> = {
  "agentic:claude-2.1.281:claude-haiku-4-5":
    "Admitted under a post-hoc audit rule adopted on 2026-09-27, after this panel ran: in 4 episodes the " +
    "model drafted 6 prospects by guessed id without listing the draft class. Prospect ids carry no hidden " +
    "information, so these picks are reported as warnings, not violations. Played on driver commit 21b71dc; " +
    "the gpt-6-luna and claude-sonnet-5 rows ran on 4d742cc. The two differ only in how Claude Code's tool " +
    "calls are counted, not in scoring.",
  "agentic:claude-2.1.281:claude-haiku-5-5":
    "The cost shown is a lower bound. Haiku 5.5 charges 5x on every token category for a request whose " +
    "prompt is over 100,000 tokens, and 1,037 of the 2,837 requests were; the estimate uses the lower " +
    "rates throughout. Pricing those requests at the higher tier puts the panel at about $12 to $16. " +
    "Played on driver commit 3e8e600.",
  "agentic:claude-2.1.281:claude-sonnet-5":
    "One episode's tool-call count is a recount: the run recorded 165 of 166 because the event parser " +
    "counted a call to a tool name that does not exist; after the parser fix the count is 165 of 165.",
  "agentic:claude-2.1.281:claude-sonnet-5-5":
    "Admitted under a post-hoc audit rule adopted on 2026-10-14, after this panel ran: in one episode the " +
    "model signed a free agent whose id the listing had not shown, then released him soon afterward. " +
    "The model-independent 2026-10-14 policy reports accepted blind signings as warnings in every season, " +
    "including retained players. This does not rule out leakage. The published row failed the original " +
    "audit and passes the revised audit; its matching raw evidence was unavailable for this retrospective. " +
    "Significant on its own (p = 0.012) but not under a Holm correction across the ten rows. " +
    "Played on driver commit 0f3042d.",
  "agentic:codex-0.156.1:gpt-6-luna":
    "Ran with the ChatGPT account's connected apps and plugins available: Codex exposed about 668 extra " +
    "tools (Gmail, GitHub, Google Drive and others). The row records no tool call other than GM-Bench calls. " +
    "Codex runs since 2026-10-13 turn these off.",
  "agentic:codex-0.162.1:gpt-6-astra":
    "Ran with the ChatGPT account's apps, plugins and connectors turned off. Codex reports no cost; " +
    "gpt-6-astra had no pricing.json entry when the panel ran, so the estimate was re-derived at redaction " +
    "from the retained event streams, at short-context list prices. Every episode had a turn whose input " +
    "passed the 272K long-context threshold, so it may be low. Played on driver commit 5d56c71.",
  "agentic:codex-0.162.1:gpt-6.1-sol":
    "Ran with the ChatGPT account's apps, plugins and connectors turned off, unlike the gpt-6-luna row. " +
    "Codex reports no cost; the estimate is at short-context list prices and may be low. The agent made 36 " +
    "draft calls across the 160 draft phases and 518 trade calls. The lift's 95% interval starts at +1.6, " +
    "so the margin is thin. Played on driver commit 1411e2e, the first with Codex 0.162.1.",
  "agentic:cursor-2026.09.26-dd393fe:composer-2.5":
    "Cursor's servers add seven default User Rules of their own to every prompt; they are part of the " +
    "harness. Cursor reports no cost and composer-2.5 has no per-token list price, so cost is unmeasured. " +
    "Played on driver commit b3d7de7, the first with Cursor's container driver.",
  "agentic:opencode-1.18.31:opencode-go/deepseek-v4.1-flash":
    "Run on an OpenCode Go subscription. The cost shown is OpenCode's own figure; Go counts usage against " +
    "the plan's limits rather than billing per token, and there is no API-equivalent estimate. Played on " +
    "driver commit 07de4b2, the first with OpenCode Go keys.",
  "agentic:opencode-2.0.27:opencode-go/deepseek-v4.1-flash":
    "The same model and OpenCode Go plan as the 1.18.31 row, on OpenCode 2.0.27. The cost shown is " +
    "OpenCode's own figure, not a per-token bill. A first 2.0.27 panel was discarded: OpenCode sent the " +
    "first request before the GM-Bench tools had connected, fixed in driver commit 93b1f7c, which played " +
    "this one. One episode's tool-call count is a recount: OpenCode refused one trade call on its own " +
    "schema check before sending it, so it never reached GM-Bench; counted as 166 of 166.",
};

function modelRow(row: AgenticLaneRow): ModelRow {
  const t = row.telemetry;
  const r = row.reference;
  const liftCi = r.paired_lift_ci95?.length === 2 ? ([r.paired_lift_ci95[0], r.paired_lift_ci95[1]] as [number, number]) : null;
  const phases = Object.values(t.phases_ended_by).reduce((sum, count) => sum + count, 0);
  const perGame = (value: number | null) => (value === null || t.telemetry_episodes === 0 ? null : value / t.telemetry_episodes);
  return {
    kind: "model",
    id: row.id,
    label: row.model.split("/").at(-1) ?? row.model,
    model: row.model.split("/").at(-1) ?? row.model,
    harness: HARNESSES[row.harness.name] ?? row.harness.name,
    harnessKey: row.harness.name,
    harnessVersion: row.harness.version + (row.harness.variant ? ` (${row.harness.variant})` : ""),
    vendor: vendorOf(row.model),
    score: row.mean_score,
    ci: liftCi ? [r.mean_score + liftCi[0], r.mean_score + liftCi[1]] : null,
    lift: r.paired_lift_mean,
    liftCi,
    p: r.sign_flip_p_value,
    pUpperBound: Boolean(r.sign_flip_p_value_upper_bound),
    seedWinRate: r.candidate_seed_win_rate,
    toolCalls: t.tool_calls_per_episode,
    inputTokens: perGame(t.input_tokens),
    outputTokens: perGame(t.output_tokens),
    minutes: t.wall_seconds_per_episode / 60,
    emptyPhases: t.empty_phases ?? null,
    phases,
    cost: costOf(row),
    unpinned: row.unpinned,
    isolation: row.isolation,
    seeds: row.panel.distinct_seeds,
    sd: row.score_stddev,
    seedRange: [row.seed_mean_min, row.seed_mean_max],
    illegal: row.illegal_actions,
    nudges: t.nudges_per_episode,
    artifact: row.artifact_path,
    caveat: ROW_CAVEATS[row.id] ?? null,
    source: row,
  };
}

export const PICK_TRADER = "pick-trader";

/* Scripted bots on the 2.0 panel. Until every bot is recorded, the two each
   row's reference block carries (pick-trader and random) stand in. */
export function botRows(data: Leaderboard): BotRow[] {
  const recorded = data.agentic_bots ?? [];
  const reference = data.agentic_lane?.[0]?.reference;
  const bots =
    recorded.length > 0
      ? recorded
      : reference
        ? [
            { agent: PICK_TRADER, mean_score: reference.mean_score },
            { agent: reference.floor.agent, mean_score: reference.floor.mean_score },
          ]
        : [];
  return bots.map((bot) => ({ kind: "bot", id: `bot:${bot.agent}`, label: bot.agent, score: bot.mean_score, isBar: bot.agent === PICK_TRADER }));
}

export function modelRows(data: Leaderboard): ModelRow[] {
  const rows = (data.agentic_lane ?? []).map(modelRow);
  // The same model in two versions of one harness: name the version so the two read apart.
  const key = (row: ModelRow) => `${row.harnessKey} ${row.model}`;
  return rows.map((row) => {
    if (rows.filter((other) => key(other) === key(row)).length < 2) return row;
    const named = `${row.model} (${row.source.harness.version})`;
    return { ...row, label: named, model: named };
  });
}

export function pickTraderScore(data: Leaderboard): number | null {
  return data.agentic_lane?.[0]?.reference.mean_score ?? null;
}

/** Ahead of pick-trader by more than the noise: the paired-lift 95% interval sits above zero. */
export function clearsBar(row: ModelRow): boolean {
  return row.liftCi !== null && row.liftCi[0] > 0;
}

export function seedCount(data: Leaderboard): number | null {
  return data.agentic_lane?.[0]?.reference.num_seeds ?? null;
}

/* ---------- filters, shared by every tab through the URL and localStorage ---------- */

export interface Filters {
  hiddenHarnesses: string[];
  hiddenVendors: string[];
  showBots: boolean;
}

const FILTER_KEY = "gm-bench-filters";
const EMPTY: Filters = { hiddenHarnesses: [], hiddenVendors: [], showBots: true };

function readFilters(): Filters {
  try {
    const saved = JSON.parse(localStorage.getItem(FILTER_KEY) ?? "null");
    if (saved && Array.isArray(saved.hiddenHarnesses) && Array.isArray(saved.hiddenVendors)) {
      return { hiddenHarnesses: saved.hiddenHarnesses, hiddenVendors: saved.hiddenVendors, showBots: saved.showBots !== false };
    }
  } catch {
    // Unreadable or blocked storage: start unfiltered.
  }
  return EMPTY;
}

export function useFilters(): [Filters, (next: Filters) => void] {
  const [filters, setFilters] = useState<Filters>(readFilters);
  useEffect(() => {
    try {
      localStorage.setItem(FILTER_KEY, JSON.stringify(filters));
    } catch {
      // Blocked storage only means the choice is not remembered.
    }
  }, [filters]);
  return [filters, setFilters];
}

export function visible(row: ModelRow, filters: Filters): boolean {
  return !filters.hiddenHarnesses.includes(row.harnessKey) && !filters.hiddenVendors.includes(row.vendor.key);
}

/* ---------- formatting ---------- */

export function num(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function signed(value: number, digits = 1): string {
  const text = num(Math.abs(value), digits);
  if (Number(text) === 0) return text;
  return value > 0 ? `+${text}` : `−${text}`;
}

export function compact(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1_000_000) return `${num(value / 1_000_000, 1)}M`;
  if (value >= 1_000) return `${num(value / 1_000, 1)}k`;
  return num(value, 0);
}

export function costText(cost: Cost): string {
  if (cost.usd === null) return "—";
  return `$${num(cost.usd, 2)}${cost.kind === "estimate" ? " est." : ""}`;
}

export function pText(row: ModelRow): string {
  return row.pUpperBound || row.p < 0.001 ? "p < 0.001" : `p = ${num(row.p, 3)}`;
}
