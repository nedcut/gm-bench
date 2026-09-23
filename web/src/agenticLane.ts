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
  const floor = reference.floor as Record<string, unknown> | null | undefined;
  const floorKeys = floor !== null && typeof floor === "object" ? Object.keys(floor).sort().join(",") : "";
  if (
    floorKeys !== "agent,mean_score" ||
    reference.floor.agent !== AGENTIC_REFERENCE_FLOOR_AGENT ||
    !isFiniteNumber(reference.floor.mean_score)
  ) {
    issues.push(`${label} reference floor must be exactly {agent: ${AGENTIC_REFERENCE_FLOOR_AGENT}, mean_score}`);
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
  const lift = reference.paired_lift_mean;
  if (!isFiniteNumber(lift)) return issues;
  // With one baseline and every seed in both, the mean lift is the row mean
  // minus pick-trader's mean (each rounded to 3 places).
  if (!isFiniteNumber(row.mean_score)) {
    issues.push(`${label} has no mean_score to check its reference lift against`);
  } else if (isFiniteNumber(reference.mean_score) && Math.abs(row.mean_score - reference.mean_score - lift) > 0.002) {
    issues.push(
      `${label} reference.paired_lift_mean ${lift} is not the row mean ${row.mean_score} ` +
        `minus the ${AGENTIC_REFERENCE_AGENT} mean ${reference.mean_score}`,
    );
  }
  // Relations the runner's paired statistics always satisfy, up to rounding.
  // The p-value is not tied to the interval: the sign-flip test and the
  // bootstrap interval can honestly disagree.
  const slack = 0.001;
  const stddev = reference.paired_lift_stddev;
  if (isFiniteNumber(stddev) && stddev < 0) issues.push(`${label} reference.paired_lift_stddev is negative`);
  if (ciOk) {
    if (lift < ci[0] - slack || lift > ci[1] + slack) {
      issues.push(`${label} reference.paired_lift_ci95 does not contain its paired_lift_mean`);
    }
    // No lift is further than stddev * sqrt(n) from the mean, and every
    // bootstrap mean lies between the smallest and largest lift.
    const n = reference.num_seeds;
    if (isFiniteNumber(stddev) && stddev >= 0 && Number.isInteger(n) && n >= 1) {
      const reach = (stddev + 0.0005) * Math.sqrt(n) + 2 * slack;
      if (lift - ci[0] > reach || ci[1] - lift > reach) {
        issues.push(`${label} reference.paired_lift_ci95 is wider than its paired_lift_stddev allows`);
      }
    }
  }
  const winRate = reference.candidate_seed_win_rate;
  if (isFiniteNumber(winRate)) {
    if (winRate < 0 || winRate > 1) issues.push(`${label} reference.candidate_seed_win_rate is not a rate`);
    if (winRate === 0 && (lift > 0 || (ciOk && ci[1] > 0))) {
      issues.push(`${label} reference wins no seed but its lift or interval is positive`);
    }
    if (winRate === 1 && (lift < 0 || (ciOk && ci[0] < 0))) {
      issues.push(`${label} reference wins every seed but its lift or interval is negative`);
    }
  }
  const pins = lanePanel.reference_scores;
  if (pins && pins.seasons === row.seasons) {
    const observed: Array<[string, unknown]> = [
      [AGENTIC_REFERENCE_AGENT, reference.mean_score],
      [AGENTIC_REFERENCE_FLOOR_AGENT, reference.floor?.mean_score],
    ];
    for (const [agent, value] of observed) {
      const pinned = pins.mean_scores[agent];
      if (pinned === null || pinned === undefined) continue;
      if (!isFiniteNumber(value) || Math.abs(value - pinned) > 1e-6) {
        issues.push(
          `${label} reference ${agent} mean ${String(value)} is not the frozen panel's ${pinned} ` +
            "(config/bench_v2_lane.json reference_scores)",
        );
      }
    }
  }
  return issues;
}

/* The API-equivalent estimate is a list-price figure for a harness that
 * reports no cost; it is never a billed cost. A row that carries both with
 * the same value has almost certainly copied one into the other. */
function estimateIssues(row: AgenticLaneRow, label: string): string[] {
  const t = row.telemetry as AgenticLaneRow["telemetry"] | undefined;
  if (!t) return [];
  const issues: string[] = [];
  for (const key of ["api_equivalent_cost_usd", "api_equivalent_cost_per_episode_usd"] as const) {
    const value = t[key];
    if (value !== undefined && value !== null && !(isFiniteNumber(value) && value >= 0)) {
      issues.push(`${label} telemetry.${key} is not a non-negative number or null`);
    }
  }
  const estimate = t.api_equivalent_cost_usd;
  if (isFiniteNumber(estimate) && isFiniteNumber(t.cost_usd) && Math.abs(estimate - t.cost_usd) < 1e-9) {
    issues.push(
      `${label} reports the same value as billed cost_usd and as an API-equivalent estimate; ` +
        "an estimate is for a harness that reports no cost",
    );
  }
  return issues;
}

/** The lane's frozen private panel, by digest and size only (config/bench_v2_lane.json). */
export interface AgenticLanePanel {
  artifact_panel_sha256: string;
  count: number;
  /** config/bench_v2_lane.json reference_scores: the frozen panel's pick-trader
   * and random means at `seasons`, once recorded (null until then). */
  reference_scores?: { seasons: number; mean_scores: Record<string, number | null> };
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
  // pick-trader and random are deterministic on the one frozen panel, so every
  // row at a season count shares their means, pinned or not.
  const referenceBySeasons = new Map<unknown, { id: string; means: string }>();
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
    issues.push(...estimateIssues(row, label));
    const means = JSON.stringify([row.reference?.mean_score, row.reference?.floor?.mean_score]);
    const first = referenceBySeasons.get(row.seasons);
    if (first === undefined) {
      referenceBySeasons.set(row.seasons, { id: row.id, means });
    } else if (first.means !== means) {
      issues.push(
        `${label} has pick-trader/random means ${means} but ${first.id} has ${first.means} at ` +
          `${String(row.seasons)} seasons; on one frozen panel every reference must agree`,
      );
    }
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
