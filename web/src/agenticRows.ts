import type { LadderRow } from "./components/ScoreLadder";
import type { AgenticLaneRow, Leaderboard } from "./types";

const HARNESS_NAMES: Record<string, string> = {
  claude: "Claude Code",
  codex: "Codex",
  cursor: "Cursor",
  opencode: "OpenCode",
};

export const harnessName = (row: AgenticLaneRow) => HARNESS_NAMES[row.harness.name] ?? row.harness.name;

/* 2.0 rows ordered by harness and model, never by score: 2.0 ranks nothing.
   A row's interval is pick-trader's mean plus the paired-lift interval. */
export function agenticLadderRows(data: Leaderboard): LadderRow[] {
  return [...(data.agentic_lane ?? [])]
    .sort((a, b) => harnessName(a).localeCompare(harnessName(b)) || a.model.localeCompare(b.model))
    .map((row) => {
      const ci = row.reference.paired_lift_ci95;
      return {
        id: row.id,
        label: row.model,
        detail: `${harnessName(row)} ${row.harness.version}`,
        score: row.mean_score,
        ci: ci?.length === 2 ? [row.reference.mean_score + ci[0], row.reference.mean_score + ci[1]] : null,
      };
    });
}

export const agenticReference = (data: Leaderboard) => data.agentic_lane?.[0]?.reference.mean_score ?? null;
