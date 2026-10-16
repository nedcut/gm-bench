import type { ReactNode } from "react";
import { routes } from "../site";
import { compact, num, type ModelRow } from "../v2";
import { type WorkspaceView } from "./Workspace";

interface Metric {
  title: string;
  note: ReactNode;
  value: (row: ModelRow) => number | null;
  text: (value: number) => string;
}

const METRICS: Metric[] = [
  { title: "Tool calls", note: "Per game", value: (r) => r.toolCalls, text: (v) => num(v, 0) },
  { title: "Wall time", note: "Minutes per five-season game", value: (r) => r.minutes, text: (v) => `${num(v, 1)} min` },
  { title: "Input tokens", note: "Per game", value: (r) => r.inputTokens, text: (v) => compact(v) },
  { title: "Output tokens", note: "Per game", value: (r) => r.outputTokens, text: (v) => compact(v) },
  {
    title: "Empty phases",
    note: (
      <>
        Share of phases ended with at most a status check. Mostly drafts with no pick and models that skip get_status,
        not missed decisions: <a href={routes.findings}>findings</a>
      </>
    ),
    value: (r) => (r.emptyPhases === null || r.phases === 0 ? null : (100 * r.emptyPhases) / r.phases),
    text: (v) => `${num(v, v < 10 && v > 0 ? 1 : 0)}%`,
  },
  {
    title: "Illegal moves",
    note: "Moves the simulator rejected, per game",
    value: (r) => (r.illegal === null || r.source.panel.episodes === 0 ? null : r.illegal / r.source.panel.episodes),
    text: (v) => num(v, 2),
  },
];

function MetricCard({ metric, rows, view }: { metric: Metric; rows: ModelRow[]; view: WorkspaceView }) {
  const measured = rows
    .map((row) => ({ row, value: metric.value(row) }))
    .filter((item): item is { row: ModelRow; value: number } => item.value !== null)
    .sort((a, b) => b.value - a.value);
  const missing = rows.length - measured.length;
  const max = Math.max(...measured.map((item) => item.value), 1e-9);
  return (
    <section className="card metric">
      <h4>{metric.title}</h4>
      <p className="card-note">{metric.note}</p>
      <div className="hbars">
        {measured.map(({ row, value }) => (
          <button
            key={row.id}
            type="button"
            className={`hbar${view.focus !== null && view.focus !== row.id ? " is-dim" : ""}`}
            aria-pressed={view.selected === row.id}
            onClick={() => view.select(row.id)}
            onMouseEnter={() => view.hover(row.id)}
            onMouseLeave={() => view.hover(null)}
            onFocus={() => view.hover(row.id)}
            onBlur={() => view.hover(null)}
          >
            <span className="name">
              <span className={`dot vendor-${row.vendor.key}`} aria-hidden="true" />
              <span className="name-text">{row.model}</span>
              <span className="muted">{row.harness}</span>
            </span>
            <span className="meter" aria-hidden="true">
              <i className={`vendor-${row.vendor.key}`} style={{ width: `${Math.max((value / max) * 100, value > 0 ? 1 : 0)}%` }} />
            </span>
            <span className="val">{metric.text(value)}</span>
          </button>
        ))}
      </div>
      {missing > 0 && <p className="view-note">{missing} not measured.</p>}
    </section>
  );
}

const GROUPS = [
  { title: "Activity & time", note: "How much work each harness did", metrics: METRICS.slice(0, 2) },
  { title: "Token budget", note: "Reported input and output per game", metrics: METRICS.slice(2, 4) },
  { title: "Phase outcomes", note: "Status-only phases and rejected moves", metrics: METRICS.slice(4) },
];

export function ToolsSection({ view }: { view: WorkspaceView }) {
  return (
    <section className="view stats-section" id="tools" tabIndex={-1} aria-labelledby="tools-title">
      <div className="view-head">
        <h2 id="tools-title">How each agent used its harness</h2>
        <span>Averages over {view.lane.seeds ?? "—"} five-season games. Longer bars are not better.</span>
      </div>
      {view.shown.length === 0 && <p className="view-note">No models match the current filters. Reset the filters to see their statistics.</p>}
      <div className="tool-ledger">
        {GROUPS.map(group => (
          <section className="tool-group" key={group.title} aria-label={group.title}>
            <header><h3>{group.title}</h3><p>{group.note}</p></header>
            <div className="tool-pair">{group.metrics.map(metric => <MetricCard key={metric.title} metric={metric} rows={view.shown} view={view} />)}</div>
          </section>
        ))}
      </div>
    </section>
  );
}
