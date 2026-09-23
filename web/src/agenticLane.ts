import type { AgenticLaneRow, Leaderboard } from "./types";

/* Publication rules for the GM-Bench 2.0 section, checked at build time by
 * scripts/validate_results_data.ts. The Python builder already refuses a row
 * that fails these; this is the second lock on the site's own data file, so a
 * hand edit or a builder regression cannot put a smoke row, a same-user row,
 * or a row off the frozen panel on the page, and cannot let a 2.0 row leak
 * into a 1.0 table.
 *
 * The one inference a row may carry is its `reference` block: the spec's
 * predeclared pick-trader contrast on the row's own seeds (docs/bench_v2_spec.md,
 * Panel design). It must be on-panel and seed-free, and no other p-value or
 * paired field may appear anywhere in the row: nothing compares two rows,
 * two harnesses, or two models. */

export const AGENTIC_PANEL_MIN_SEEDS = 32;
export const AGENTIC_PANEL_ISOLATION: ReadonlySet<string> = new Set(["separate-user", "container"]);
/** config/bench_v2_lane.json panel_design.reference_agent, and the floor shown beside it. */
export const AGENTIC_REFERENCE_AGENT = "pick-trader";
export const AGENTIC_REFERENCE_FLOOR_AGENT = "random";
const REFERENCE_KEYS = [
  "agent",
  "mean_score",
  "floor",
  "seasons",
  "num_seeds",
  "paired_lift_mean",
  "paired_lift_stddev",
  "paired_lift_ci95",
  "sign_flip_p_value",
  "significant_at_95",
  "candidate_seed_win_rate",
  "per_seed",
];
const INFERENCE_KEY = /p_value|holm|paired|lift|per_seed/i;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Every key path in `value` whose last key looks like an inference field. */
function inferenceKeyPaths(value: unknown, path: string): string[] {
  if (Array.isArray(value)) return value.flatMap((item, index) => inferenceKeyPaths(item, `${path}[${index}]`));
  if (value === null || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([key, child]) => [
    ...(INFERENCE_KEY.test(key) ? [`${path}.${key}`] : []),
    ...inferenceKeyPaths(child, `${path}.${key}`),
  ]);
}

function referenceIssues(row: AgenticLaneRow, lanePanel: AgenticLanePanel, label: string): string[] {
  const reference = row.reference as AgenticLaneRow["reference"] | undefined;
  if (reference === null || typeof reference !== "object") {
    return [`${label} has no reference block; a panel row carries the ${AGENTIC_REFERENCE_AGENT} contrast on its own seeds`];
  }
  const issues: string[] = [];
  const unexpected = Object.keys(reference).filter((key) => !REFERENCE_KEYS.includes(key));
  if (unexpected.length > 0) issues.push(`${label} reference carries unexpected fields: ${unexpected.join(", ")}`);
  if (reference.agent !== AGENTIC_REFERENCE_AGENT) {
    issues.push(`${label} reference is ${String(reference.agent)}; the predeclared contrast is ${AGENTIC_REFERENCE_AGENT}`);
  }
  if (reference.floor?.agent !== AGENTIC_REFERENCE_FLOOR_AGENT || !isFiniteNumber(reference.floor?.mean_score)) {
    issues.push(`${label} reference floor must be ${AGENTIC_REFERENCE_FLOOR_AGENT} with a score`);
  }
  const distinct = row.panel?.distinct_seeds;
  if (reference.num_seeds !== distinct || reference.num_seeds !== lanePanel.count) {
    issues.push(
      `${label} reference ran on ${String(reference.num_seeds)} seeds; it must run on the row's ${String(distinct)} ` +
        `seeds, the lane's ${lanePanel.count}`,
    );
  }
  if (reference.seasons !== row.seasons) {
    issues.push(`${label} reference played ${String(reference.seasons)} seasons; the row played ${String(row.seasons)}`);
  }
  const perSeed = (reference as { per_seed?: unknown }).per_seed;
  if (perSeed !== undefined && !(Array.isArray(perSeed) && perSeed.length === 0)) {
    issues.push(`${label} reference carries per-seed values; on private seeds they invert to per-seed scores`);
  }
  for (const key of ["mean_score", "paired_lift_mean", "paired_lift_stddev", "candidate_seed_win_rate"] as const) {
    if (!isFiniteNumber(reference[key])) issues.push(`${label} reference.${key} is not a number`);
  }
  const ci = reference.paired_lift_ci95;
  const ciOk = Array.isArray(ci) && ci.length === 2 && ci.every(isFiniteNumber) && ci[0] <= ci[1];
  if (!ciOk) issues.push(`${label} reference.paired_lift_ci95 is not [low, high]`);
  const p = reference.sign_flip_p_value;
  if (!isFiniteNumber(p) || p < 0 || p > 1) issues.push(`${label} reference.sign_flip_p_value is not a probability`);
  if (typeof reference.significant_at_95 !== "boolean") {
    issues.push(`${label} reference.significant_at_95 is not a boolean`);
  } else if (ciOk && reference.significant_at_95 !== (ci[0] > 0 || ci[1] < 0)) {
    issues.push(`${label} reference.significant_at_95 contradicts its interval`);
  }
  return issues;
}

/** The lane's frozen private panel, by digest and size only (config/bench_v2_lane.json). */
export interface AgenticLanePanel {
  artifact_panel_sha256: string;
  count: number;
}

export function agenticLaneIssues(data: Leaderboard, lanePanel: AgenticLanePanel): string[] {
  const issues: string[] = [];
  const rows: AgenticLaneRow[] = data.agentic_lane ?? [];
  const oneZero: Array<[string, Array<{ id: string; lane?: string }>]> = [
    ["headline", data.models],
    ["CLI-harness", data.cli_harness_models],
    ["decision-lane", data.decision_lane_models ?? []],
  ];
  const oneZeroIds = new Set<string>();
  for (const [table, tableRows] of oneZero) {
    for (const row of tableRows) {
      oneZeroIds.add(row.id);
      if ((row.lane as string | undefined) === "agentic" || row.id.startsWith("agentic:")) {
        issues.push(`Agentic row ${row.id} is in the 1.0 ${table} table`);
      }
    }
  }
  const seen = new Set<string>();
  for (const row of rows) {
    const label = `Agentic row ${row.id}`;
    if (seen.has(row.id)) issues.push(`Duplicate agentic row ${row.id}`);
    seen.add(row.id);
    if (oneZeroIds.has(row.id)) issues.push(`${label} shares an id with a 1.0 row`);
    if (row.lane !== "agentic") issues.push(`${label} is not labelled agentic`);
    if (row.grade !== "panel") issues.push(`${label} is ${String(row.grade)} grade; only panel rows are published`);
    const distinct = row.panel?.distinct_seeds;
    if (!Number.isInteger(distinct) || distinct < AGENTIC_PANEL_MIN_SEEDS) {
      issues.push(`${label} has ${String(distinct)} distinct seed groups; panel grade needs ${AGENTIC_PANEL_MIN_SEEDS}`);
    } else if (distinct !== lanePanel.count) {
      issues.push(`${label} has ${distinct} distinct seed groups; the lane's frozen panel has ${lanePanel.count}`);
    }
    if (row.panel?.sha256 !== lanePanel.artifact_panel_sha256) {
      issues.push(`${label} is not on the lane's frozen private panel (panel.sha256)`);
    }
    if (typeof row.unpinned !== "boolean") {
      issues.push(`${label} does not say whether its model is pinned (unpinned flag)`);
    } else if (!row.unpinned && !(typeof row.pin === "string" && row.pin.trim())) {
      issues.push(`${label} is marked pinned but names no pin`);
    }
    if (!AGENTIC_PANEL_ISOLATION.has(row.isolation)) {
      issues.push(`${label} has isolation ${String(row.isolation)}; panel grade needs separate-user or container`);
    }
    if (!row.harness?.name || !row.harness?.version || !row.harness?.model) {
      issues.push(`${label} is missing its harness name, version, or model`);
    }
    if (!row.artifact_path?.startsWith("results/agentic/")) {
      issues.push(`${label} does not point at a committed results/agentic/ artifact`);
    }
    issues.push(...referenceIssues(row, lanePanel, label));
    const outsideReference = Object.fromEntries(Object.entries(row).filter(([key]) => key !== "reference"));
    const stray = inferenceKeyPaths(outsideReference, "row");
    if (stray.length > 0) {
      issues.push(
        `${label} carries a p-value or paired field outside its pick-trader reference (${stray.join(", ")}); ` +
          "2.0 compares no rows, harnesses, or models",
      );
    }
  }
  return issues;
}
