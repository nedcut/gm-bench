import { useMemo } from "react";
import type { Leaderboard } from "../types";
import { compact, modelRows, num, seedCount, useFilters, visible, type ModelRow } from "../v2";
import FilterNote from "./FilterNote";

interface Metric {
  title: string;
  unit: string;
  value: (row: ModelRow) => number | null;
  text: (value: number) => string;
}

const METRICS: Metric[] = [
  { title: "Tool calls", unit: "per game", value: (r) => r.toolCalls, text: (v) => num(v, 0) },
  { title: "Input tokens", unit: "per game", value: (r) => r.inputTokens, text: (v) => compact(v) },
  { title: "Wall time", unit: "minutes per game", value: (r) => r.minutes, text: (v) => num(v, 1) },
  {
    title: "Empty phases",
    unit: "status check, then end; share of all phases",
    value: (r) => (r.emptyPhases === null || r.phases === 0 ? null : (100 * r.emptyPhases) / r.phases),
    text: (v) => `${num(v, 0)}%`,
  },
];

function Multiple({ metric, rows }: { metric: Metric; rows: ModelRow[] }) {
  const measured = rows
    .map((row) => ({ row, value: metric.value(row) }))
    .filter((item): item is { row: ModelRow; value: number } => item.value !== null)
    .sort((a, b) => b.value - a.value);
  const missing = rows.length - measured.length;
  const max = Math.max(...measured.map((item) => item.value), 1e-9);
  return (
    <div className="multiple">
      <h3>
        {metric.title}
        <small>{metric.unit}</small>
      </h3>
      {measured.map(({ row, value }) => (
        <div key={row.id} className="hbar">
          <span className="name" title={`${row.model}, ${row.harness}`}>
            {row.model} <span className="muted">· {row.harness}</span>
          </span>
          <span className="meter" aria-hidden="true">
            <i className={`vendor-${row.vendor.key}`} style={{ width: `${(value / max) * 100}%` }} />
          </span>
          <span className="val">{metric.text(value)}</span>
        </div>
      ))}
      {missing > 0 && <p className="view-note">{missing} not measured.</p>}
    </div>
  );
}

export default function ToolsView({ data }: { data: Leaderboard }) {
  const [filters, setFilters] = useFilters();
  const rows = useMemo(() => modelRows(data), [data]).filter((row) => visible(row, filters));
  return (
    <section className="view page-view" aria-labelledby="tools-title">
      <div className="view-head">
        <h2 id="tools-title">How each agent used its harness</h2>
        <span>Averages over {seedCount(data) ?? "—"} five-season games. Longer bars are not better.</span>
      </div>
      <FilterNote filters={filters} onReset={() => setFilters({ hiddenHarnesses: [], hiddenVendors: [], showBots: filters.showBots })} />
      <div className="small-multiples">
        {METRICS.map((metric) => (
          <Multiple key={metric.title} metric={metric} rows={rows} />
        ))}
      </div>
    </section>
  );
}
