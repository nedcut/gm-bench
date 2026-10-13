import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Leaderboard } from "../types";
import { costText, num, pickTraderScore, type ModelRow } from "../v2";
import FilterNote from "./FilterNote";
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

/* Spread label positions at least `gap` apart, keeping each near its target
   and inside [top, bottom]. */
function spread(targets: number[], gap: number, top: number, bottom: number): number[] {
  const order = targets.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  const ys = order.map((o) => o.y);
  for (let k = 0; k < ys.length; k++) ys[k] = Math.max(ys[k], k === 0 ? top : ys[k - 1] + gap);
  for (let k = ys.length - 1; k >= 0; k--) ys[k] = Math.min(ys[k], k === ys.length - 1 ? bottom : ys[k + 1] - gap);
  const out = new Array<number>(targets.length);
  order.forEach((o, k) => (out[o.i] = ys[k]));
  return out;
}

/* In-place labels for narrow charts: beside the point, on the side with room,
   pushed down when they would overlap one already placed. */
function besidePoints(points: { x: number; y: number; width: number }[], right: number) {
  const order = points.map((p, i) => ({ ...p, i })).sort((a, b) => a.y - b.y);
  const placed: { x0: number; x1: number; y: number }[] = [];
  const out = new Array<{ y: number; anchorEnd: boolean }>(points.length);
  for (const point of order) {
    const anchorEnd = point.x + 12 + point.width > right;
    const x0 = anchorEnd ? point.x - 12 - point.width : point.x + 12;
    const x1 = x0 + point.width;
    let y = point.y + 4;
    for (const other of placed) if (x0 < other.x1 && other.x0 < x1 && Math.abs(y - other.y) < 17) y = other.y + 17;
    placed.push({ x0, x1, y });
    out[point.i] = { y, anchorEnd };
  }
  return out;
}

/* One sentence on cost and the bar. Rows are never compared with each other. */
function takeaway(priced: ModelRow[], bar: number): string {
  if (priced.length === 0) return "";
  const byCost = [...priced].sort((a, b) => (a.cost.usd as number) - (b.cost.usd as number));
  const lo = byCost[0];
  const hi = byCost.at(-1)!;
  const ratio = (hi.cost.usd as number) / (lo.cost.usd as number);
  const above = priced.filter((row) => row.score > bar).length;
  const range =
    priced.length === 1
      ? `One measured row, at ${costText(lo.cost)} a game.`
      : `Cost per game runs from ${costText(lo.cost)} to ${costText(hi.cost)}${Number.isFinite(ratio) && ratio >= 2 ? `, a ${Math.round(ratio)}× spread` : ""}.`;
  const verdict =
    above === 0 ? "No measured row scores above pick-trader." : `${above} measured row${above === 1 ? "" : "s"} score above pick-trader's mean.`;
  return `${range} ${verdict}`;
}

function Chart({ priced, bar, scale, view }: { priced: ModelRow[]; bar: number; scale: Scale; view: WorkspaceView }) {
  const [frame, width] = useWidth<HTMLDivElement>();
  const W = Math.max(width || 1040, 280);
  const narrow = W < 640;
  const viewport = typeof window === "undefined" ? 800 : window.innerHeight;
  const H = narrow ? 360 : Math.round(Math.max(420, Math.min(620, viewport - 300)));
  const PAD = narrow ? { l: 40, r: 10, t: 16, b: 46 } : { l: 52, r: 230, t: 16, b: 50 };
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
  /* pick-trader takes a slot in the label column too, last in the list. */
  const column = spread([...points.map((p) => p.y), y(bar)], 32, PAD.t + 8, H - PAD.b - 16);
  const barLabelY = column.at(-1)!;
  const beside = besidePoints(points.map((p, i) => ({ ...p, width: priced[i].model.length * CHAR })), right);

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
        {narrow ? (
          <>
            <line className="bar-line" x1={PAD.l} x2={right} y1={y(bar)} y2={y(bar)} />
            <text className="bar-label" x={right - 6} y={y(bar) - 7} textAnchor="end">pick-trader {num(bar)}</text>
          </>
        ) : (
          <>
            <polyline className="bar-line" fill="none" points={`${PAD.l},${y(bar)} ${right},${y(bar)} ${right + 20},${barLabelY}`} />
            <text className="bar-label" x={right + 26} y={barLabelY - 1}>
              pick-trader
              <tspan className="axis-label" x={right + 26} dy="15">
                scripted bar · {num(bar)}
              </tspan>
            </text>
          </>
        )}
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
              aria-label={`${row.model}, ${row.harness}: score ${num(row.score)}, ${costText(row.cost)} per game`}
              onClick={() => view.select(row.id)}
              onKeyDown={activate(row.id)}
              onMouseEnter={() => view.hover(row.id)}
              onMouseLeave={() => view.hover(null)}
              onFocus={() => view.hover(row.id)}
              onBlur={() => view.hover(null)}
            >
              {row.ci && <line x1={px} x2={px} y1={y(row.ci[0])} y2={y(row.ci[1])} stroke={color} strokeOpacity="0.5" strokeWidth="2" />}
              {!narrow && <line className="leader" x1={px + 9} x2={right + 20} y1={py} y2={column[i]} stroke={color} />}
              <circle cx={px} cy={py} r={selected ? 7.5 : 6} fill={row.cost.kind === "estimate" ? "var(--bg)" : color} stroke={color} strokeWidth={selected ? 3 : 2} />
              {narrow ? (
                <text className="point-label" x={beside[i].anchorEnd ? px - 12 : px + 12} y={beside[i].y} textAnchor={beside[i].anchorEnd ? "end" : "start"}>
                  {row.model}
                </text>
              ) : (
                <text className="point-label" x={right + 26} y={column[i] - 1}>
                  <tspan style={{ fill: color }}>{row.model}</tspan>
                  <tspan className="axis-label" x={right + 26} dy="15">
                    {row.harness} · {costText(row.cost)}
                  </tspan>
                </text>
              )}
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
                <span className="val">{costText(row.cost)}</span>
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
            <FilterNote filters={view.filters} onReset={() => view.setFilters({ hiddenHarnesses: [], hiddenVendors: [], showBots: view.filters.showBots })} />
            <div className="card">
              <div className="card-head">
                <ul className="legend" aria-label="Legend">
                  <li><i className="key-dot" /> Billed</li>
                  <li><i className="key-dot is-hollow" /> API list-price estimate</li>
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
