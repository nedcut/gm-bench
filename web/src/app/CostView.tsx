import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Leaderboard } from "../types";
import { clearsBar, num, pickTraderScore, type ModelRow } from "../v2";
import Workspace, { type WorkspaceView } from "./Workspace";

type Scale = "log" | "linear";

const LOG_TICKS = [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30];
/* Rough advance width of an 11.5px label character, for placing labels. */
const CHAR = 6.4;

function useWidth<T extends Element>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    setWidth(element.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/* Round steps (1, 2 or 5 times a power of ten) from zero past max. */
function linearTicks(max: number): number[] {
  const rough = max / 5;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? rough;
  const ticks = [0];
  while (ticks.at(-1)! < max) ticks.push(Number((ticks.at(-1)! + step).toFixed(6)));
  return ticks;
}

interface Box {
  x0: number;
  x1: number;
  top: number;
  bottom: number;
}

const overlaps = (a: Box, b: Box) => a.x0 < b.x1 && b.x0 < a.x1 && a.top < b.bottom && b.top < a.bottom;

/* Labels beside their points: right of the dot when it fits, else left, else
   nudged up or down, clear of other labels, other dots and `fixed` boxes
   (the pick-trader line, its label, and the interval whiskers). */
function placeLabels(
  points: { x: number; y: number; width: number }[],
  lines: number,
  plot: { left: number; right: number; top: number; bottom: number },
  fixed: Box[],
) {
  const height = lines * 15 + 2;
  const taken: Box[] = [...fixed, ...points.map((p) => ({ x0: p.x - 8, x1: p.x + 8, top: p.y - 8, bottom: p.y + 8 }))];
  const out = new Array<{ x: number; y: number; anchorEnd: boolean }>(points.length);
  const order = points.map((p, i) => ({ ...p, i })).sort((a, b) => a.y - b.y);
  for (const point of order) {
    const base = point.y + 4 - (lines - 1) * 7.5;
    let best: { x: number; y: number; anchorEnd: boolean; box: Box } | null = null;
    search: for (const dy of [0, 16, -16, 32, -32, 48, -48]) {
      for (const anchorEnd of [false, true]) {
        const x = anchorEnd ? point.x - 12 : point.x + 12;
        const x0 = anchorEnd ? x - point.width : x;
        const box = { x0, x1: x0 + point.width, top: base + dy - 12, bottom: base + dy - 12 + height };
        if (box.x0 < plot.left || box.x1 > plot.right || box.top < plot.top || box.bottom > plot.bottom) continue;
        if (taken.some((other) => overlaps(box, other))) continue;
        best = { x, y: base + dy, anchorEnd, box };
        break search;
      }
    }
    if (!best) {
      const anchorEnd = point.x + 12 + point.width > plot.right;
      const x = anchorEnd ? point.x - 12 : point.x + 12;
      const x0 = anchorEnd ? x - point.width : x;
      best = { x, y: base, anchorEnd, box: { x0, x1: x0 + point.width, top: base - 12, bottom: base - 12 + height } };
    }
    taken.push(best.box);
    out[point.i] = { x: best.x, y: best.y, anchorEnd: best.anchorEnd };
  }
  return out;
}

/* The chart shows billed and estimated costs alike; the row details say which is which. */
const usd = (row: ModelRow) => `$${num(row.cost.usd, 2)}`;

/* One sentence on cost and the bar. Rows are never compared with each other. */
function takeaway(priced: ModelRow[], bar: number): string {
  if (priced.length === 0) return "";
  const byCost = [...priced].sort((a, b) => (a.cost.usd as number) - (b.cost.usd as number));
  const lo = byCost[0];
  const hi = byCost.at(-1)!;
  const ratio = (hi.cost.usd as number) / (lo.cost.usd as number);
  const above = priced.filter((row) => row.score > bar).length;
  const clear = priced.filter(clearsBar).length;
  const range =
    priced.length === 1
      ? `One measured row, at ${usd(lo)} a game.`
      : `Cost per game runs from ${usd(lo)} to ${usd(hi)}${Number.isFinite(ratio) && ratio >= 2 ? `, a ${Math.round(ratio)}× spread` : ""}.`;
  const verdict =
    clear > 0
      ? `${clear} measured row${clear === 1 ? " beats" : "s beat"} pick-trader by more than the noise.`
      : above > 0
        ? `${above} measured row${above === 1 ? " scores" : "s score"} above pick-trader's mean, within the noise.`
        : "No measured row scores above pick-trader.";
  return `${range} ${verdict}`;
}

function Chart({ priced, bar, scale, view }: { priced: ModelRow[]; bar: number; scale: Scale; view: WorkspaceView }) {
  const [frame, width] = useWidth<HTMLDivElement>();
  const W = Math.max(width || 1040, 280);
  const narrow = W < 640;
  const viewport = typeof window === "undefined" ? 800 : window.innerHeight;
  const H = narrow ? 360 : Math.round(Math.max(420, Math.min(620, viewport - 300)));
  const PAD = narrow ? { l: 40, r: 10, t: 16, b: 46 } : { l: 52, r: 20, t: 16, b: 50 };
  const right = W - PAD.r;

  const costs = priced.map((row) => row.cost.usd as number);
  const positive = costs.filter((usd) => usd > 0);
  const hasZero = scale === "log" && costs.some((usd) => usd === 0);
  const zeroGap = narrow ? 56 : 90;
  const start = PAD.l + (hasZero ? zeroGap : 16);
  const xLo = Math.log10(Math.min(...positive, 0.1) / 1.6);
  const xHi = Math.log10(Math.max(...positive, 1) * 1.6);
  const lin = linearTicks(Math.max(...costs, 0.01) * 1.05);
  const linMax = lin.at(-1)!;
  const x = (usd: number) =>
    scale === "linear"
      ? PAD.l + 16 + (usd / linMax) * (right - PAD.l - 16)
      : usd === 0
        ? PAD.l + 16
        : start + ((Math.log10(usd) - xLo) / (xHi - xLo)) * (right - start);
  const xTicks = scale === "linear" ? lin : LOG_TICKS.filter((t) => Math.log10(t) >= xLo && Math.log10(t) <= xHi);

  const scores = [...priced.flatMap((row) => [row.score, ...(row.ci ?? [])]), bar];
  const yLo = Math.floor(Math.min(...scores) / 50) * 50;
  const yHi = Math.ceil(Math.max(...scores) / 50) * 50;
  const y = (score: number) => PAD.t + (1 - (score - yLo) / (yHi - yLo)) * (H - PAD.t - PAD.b);
  const yTicks: number[] = [];
  for (let t = yLo; t <= yHi; t += 50) yTicks.push(t);

  const points = priced.map((row) => ({ x: x(row.cost.usd as number), y: y(row.score) }));
  const barLabel = `pick-trader ${num(bar)}`;
  const barBox = { x0: right - 6 - barLabel.length * CHAR, x1: right, top: y(bar) - 20, bottom: y(bar) - 2 };
  const noteBox = { x0: PAD.l, x1: PAD.l + 130, top: PAD.t, bottom: PAD.t + 26 };
  /* Wide charts add the harness and cost under each name. */
  const sub = (row: ModelRow) => `${row.harness} · ${usd(row)}`;
  const labels = placeLabels(
    points.map((p, i) => ({ ...p, width: Math.max(priced[i].model.length, narrow ? 0 : sub(priced[i]).length) * CHAR })),
    narrow ? 1 : 2,
    { left: PAD.l + 4, right: right - 4, top: PAD.t, bottom: H - PAD.b },
    [
      barBox,
      noteBox,
      { x0: PAD.l, x1: right, top: y(bar) - 3, bottom: y(bar) + 3 },
      ...priced.flatMap((row, i) => (row.ci ? [{ x0: points[i].x - 3, x1: points[i].x + 3, top: y(row.ci[1]), bottom: y(row.ci[0]) }] : [])),
    ],
  );

  const activate = (id: string) => (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      view.select(id);
    }
  };

  return (
    <div ref={frame}>
      <svg className="chart" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="group" aria-label={`Score against cost per game for ${priced.length} rows`}>
        <rect className="above-bar" x={PAD.l} y={PAD.t} width={right - PAD.l} height={Math.max(0, y(bar) - PAD.t)} />
        {yTicks.map((t) => (
          <g key={t}>
            <line className="grid" x1={PAD.l} x2={right} y1={y(t)} y2={y(t)} />
            <text x={PAD.l - 10} y={y(t) + 4} textAnchor="end">{t}</text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={t}>
            <line className="grid" x1={x(t)} x2={x(t)} y1={PAD.t} y2={H - PAD.b} />
            <text x={x(t)} y={H - PAD.b + 20} textAnchor="middle">${t}</text>
          </g>
        ))}
        {hasZero && (
          <g>
            <text x={x(0)} y={H - PAD.b + 20} textAnchor="middle">$0</text>
            <line className="grid" x1={PAD.l + zeroGap / 2} x2={PAD.l + zeroGap / 2} y1={PAD.t} y2={H - PAD.b} strokeDasharray="4 4" />
          </g>
        )}
        <text className="axis-label" x={(PAD.l + right) / 2} y={H - 8} textAnchor="middle">
          {narrow
            ? `Cost per game (USD${scale === "log" ? ", log" : ""})`
            : `Cost per five-season game (USD, ${scale === "linear" ? "linear scale" : hasZero ? "positive costs log scale; $0 separate" : "log scale"})`}
        </text>
        <text className="bar-note" x={PAD.l + 10} y={PAD.t + 18}>Above pick-trader</text>
        <line className="bar-line" x1={PAD.l} x2={right} y1={y(bar)} y2={y(bar)} />
        <text className="bar-label" x={right - 6} y={y(bar) - 7} textAnchor="end">{barLabel}</text>
        {priced.map((row, i) => {
          const { x: px, y: py } = points[i];
          const color = `var(--vendor-${row.vendor.key})`;
          const selected = view.selected === row.id;
          const dim = view.focus !== null && view.focus !== row.id;
          return (
            <g
              key={row.id}
              className={`pt${dim ? " is-dim" : ""}`}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={`${row.model}, ${row.harness}: score ${num(row.score)}, ${usd(row)} per game`}
              onClick={() => view.select(row.id)}
              onKeyDown={activate(row.id)}
              onMouseEnter={() => view.hover(row.id)}
              onMouseLeave={() => view.hover(null)}
              onFocus={() => view.hover(row.id)}
              onBlur={() => view.hover(null)}
            >
              {row.ci && <line x1={px} x2={px} y1={y(row.ci[0])} y2={y(row.ci[1])} stroke={color} strokeOpacity="0.5" strokeWidth="2" />}
              <circle cx={px} cy={py} r={selected ? 7.5 : 6} fill={color} stroke={selected ? "var(--text)" : color} strokeWidth={selected ? 2.5 : 2} />
              <text className="point-label" x={labels[i].x} y={labels[i].y} textAnchor={labels[i].anchorEnd ? "end" : "start"}>
                {row.model}
                {!narrow && (
                  <tspan className="axis-label" x={labels[i].x} dy="15">
                    {sub(row)}
                  </tspan>
                )}
              </text>
            </g>
          );
        })}
      </svg>
      {narrow && (
        <ul className="chart-key">
          {[...priced]
            .sort((a, b) => (a.cost.usd as number) - (b.cost.usd as number))
            .map((row) => (
              <li key={row.id}>
                <span className={`dot vendor-${row.vendor.key}`} aria-hidden="true" />
                <span>
                  {row.model} <span className="muted">· {row.harness}</span>
                </span>
                <span className="val">{usd(row)}</span>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

export default function CostView({ data }: { data: Leaderboard }) {
  const [scale, setScale] = useState<Scale>("log");
  const bar = pickTraderScore(data) ?? 0;
  return (
    <Workspace data={data} hint="Click a point for its details.">
      {(view) => {
        const priced = view.shown.filter((row) => row.cost.usd !== null);
        const unmeasured = view.shown.filter((row) => row.cost.usd === null);
        return (
          <section className="view page-view" aria-labelledby="cost-title">
            <div className="view-head">
              <h1 id="cost-title">Score vs cost per game</h1>
              <span>{takeaway(priced, bar)}</span>
              {view.filterButton}
            </div>
            <div className="card">
              <div className="card-head">
                <ul className="legend" aria-label="Legend">
                  <li><i className="key-dot" /> Model, colored by vendor</li>
                  <li><i className="key-ci" /> 95% interval</li>
                  <li><i className="key-bar" /> pick-trader</li>
                </ul>
                <div className="seg" role="group" aria-label="Cost axis">
                  {(["log", "linear"] as const).map((s) => (
                    <button key={s} type="button" aria-pressed={scale === s} onClick={() => setScale(s)}>
                      {s === "log" ? "Log" : "Linear"}
                    </button>
                  ))}
                </div>
              </div>
              {priced.length === 0 ? (
                <p className="view-note">No row in the current filter has a cost measurement.</p>
              ) : (
                <Chart priced={priced} bar={bar} scale={scale} view={view} />
              )}
            </div>
            {unmeasured.length > 0 && (
              <p className="view-note">
                Not shown, cost unmeasured: {unmeasured.map((row) => `${row.model} (${row.harness})`).join(", ")}.
              </p>
            )}
          </section>
        );
      }}
    </Workspace>
  );
}
