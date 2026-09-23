import type { AgenticLaneRow, Leaderboard } from "./types";

/* Publication rules for the GM-Bench 2.0 section, checked at build time by
 * scripts/validate_results_data.ts. The Python builder already refuses a row
 * that fails these; this is the second lock on the site's own data file, so a
 * hand edit or a builder regression cannot put a smoke row, a same-user row,
 * or a row off the frozen panel on the page, and cannot let a 2.0 row leak
 * into a 1.0 table. */

export const AGENTIC_PANEL_MIN_SEEDS = 32;
export const AGENTIC_PANEL_ISOLATION: ReadonlySet<string> = new Set(["separate-user", "container"]);

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
    if (Object.keys(row).some((key) => /p_value|holm|paired|lift|reference/i.test(key))) {
      issues.push(`${label} carries a significance, paired, or reference field; 2.0 rows attach none`);
    }
  }
  return issues;
}
