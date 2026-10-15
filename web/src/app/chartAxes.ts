import { compact, num, type ModelRow } from "../v2";

export interface ChartAxis {
  id: string;
  label: string;
  unit: string;
  definition: string;
  defaultScale: "log" | "linear";
  value: (row: ModelRow) => number | null;
  format: (value: number) => string;
}

function tokenTotal(row: ModelRow, field: "input_tokens" | "output_tokens") {
  const t = row.source.telemetry;
  return t.telemetry_episodes === row.source.panel.episodes && t.telemetry_episodes > 0 && t.token_shape === "inclusive-v1" ? t[field] : null;
}

export const CHART_AXES: ChartAxis[] = [
  {
    id: "cost", label: "Cost per game", unit: "USD / game", defaultScale: "log",
    definition: "Billed or harness-reported cost, otherwise an API list-price estimate; a cost reported at a discounted data-sharing tier's rates is shown at the model's list price. Estimates may be low at long context; select a model for its cost basis.",
    value: row => row.cost.usd, format: v => `$${num(v, 2)}`,
  },
  {
    id: "output-total", label: "Total output tokens", unit: "tokens / panel", defaultScale: "linear",
    definition: "Recorded output tokens summed over the full panel, including reasoning tokens. Only complete panels using inclusive-v1 telemetry are shown; totals depend on panel size.",
    value: row => tokenTotal(row, "output_tokens"), format: compact,
  },
  {
    id: "time", label: "Wall time per game", unit: "minutes / game", defaultScale: "linear",
    definition: "Recorded elapsed wall time averaged over five-season episodes, including harness overhead and waits. This is not model-only inference time.",
    value: row => { const t = row.source.telemetry; return t.episodes > 0 && t.episodes === row.source.panel.episodes && typeof t.wall_seconds_per_episode === "number" ? t.wall_seconds_per_episode / 60 : null; }, format: v => `${num(v, 1)} min`,
  },
  {
    id: "calls", label: "Tool calls per game", unit: "calls / game", defaultScale: "linear",
    definition: "Recorded tool-call count averaged over five-season episodes. Read-only and action calls both count; more calls are not necessarily better.",
    value: row => row.source.telemetry.episodes > 0 && row.source.telemetry.episodes === row.source.panel.episodes ? row.toolCalls : null, format: v => num(v, 1),
  },
  {
    id: "input-total", label: "Total input tokens", unit: "tokens / panel", defaultScale: "linear",
    definition: "Recorded input tokens summed over the full panel: uncached input, cache reads and cache writes. Only complete inclusive-v1 panels are shown; totals depend on panel size.",
    value: row => tokenTotal(row, "input_tokens"), format: compact,
  },
  {
    id: "output-game", label: "Output tokens per game", unit: "tokens / game", defaultScale: "linear",
    definition: "Full-panel output-token total divided by recorded episode count, including reasoning. Only complete inclusive-v1 panels are shown.",
    value: row => { const total = tokenTotal(row, "output_tokens"); return total === null ? null : total / row.source.telemetry.telemetry_episodes; }, format: compact,
  },
];

export type ChartRow = ModelRow & { xValue: number };

export function chartRows(rows: ModelRow[], axis: ChartAxis): ChartRow[] {
  return rows.flatMap(row => {
    const value = axis.value(row);
    return value !== null && Number.isFinite(value) && value >= 0 ? [{ ...row, xValue: value }] : [];
  });
}

export function logTicks(min: number, max: number): number[] {
  const ticks: number[] = [];
  for (let power = Math.floor(Math.log10(min)); power <= Math.ceil(Math.log10(max)); power++) {
    for (const multiple of [1, 3]) {
      const value = Number((multiple * 10 ** power).toPrecision(12));
      if (value >= min && value <= max) ticks.push(value);
    }
  }
  return ticks;
}
