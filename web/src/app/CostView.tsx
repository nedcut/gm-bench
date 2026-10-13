import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Leaderboard } from "../types";
import { costText, modelRows, num, pickTraderScore, useFilters, visible } from "../v2";
import FilterNote from "./FilterNote";

const TICKS = [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30];
/* Rough advance width of an 11.5px label character, for placing labels. */
const CHAR = 6.4;

interface Label {
  x: number;
  y: number;
  width: number;
}

/* Label each point beside it, on the side with room; push a label down when
   it would overlap one already placed. */
function placeLabels(points: Label[], gap: number, right: number): { y: number; anchorEnd: boolean }[] {
  const order = points.map((p, i) => ({ ...p, i })).sort((a, b) => a.y - b.y);
  const placed: { x0: number; x1: number; y: number }[] = [];
  const out = new Array<{ y: number; anchorEnd: boolean }>(points.length);
  for (const point of order) {
    const anchorEnd = point.x + 12 + point.width > right;
    const x0 = anchorEnd ? point.x - 12 - point.width : point.x + 12;
    const x1 = x0 + point.width;
    let y = point.y + 4;
    for (const other of placed) {
      if (x0 < other.x1 && other.x0 < x1 && Math.abs(y - other.y) < gap) y = other.y + gap;
    }
    placed.push({ x0, x1, y });
    out[point.i] = { y, anchorEnd };
  }
  return out;
}

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

export default function CostView({ data }: { data: Leaderboard }) {
  const [filters, setFilters] = useFilters();
  const [frame, width] = useWidth<HTMLDivElement>();
  const all = useMemo(() => modelRows(data), [data]);
  const shown = all.filter((row) => visible(row, filters));
  const priced = shown.filter((row) => row.cost.usd !== null);
  const unmeasured = shown.filter((row) => row.cost.usd === null);
  const bar = pickTraderScore(data) ?? 0;

  const W = Math.max(width || 1040, 280);
  const narrow = W < 640;
  const H = narrow ? 360 : 460;
  const PAD = narrow ? { l: 40, r: 10, t: 20, b: 48 } : { l: 52, r: 16, t: 24, b: 48 };

  const costs = priced.map((row) => row.cost.usd as number).filter((usd) => usd > 0);
  const hasZero = priced.some((row) => row.cost.usd === 0);
  const zeroGap = narrow ? 56 : 100;
  const positiveStart = PAD.l + (hasZero ? zeroGap : 16);
  const xLo = Math.log10(Math.min(...costs, 0.1) / 1.6);
  const xHi = Math.log10(Math.max(...costs, 1) * 1.6);
  const scores = [...priced.flatMap((row) => [row.score, ...(row.ci ?? [])]), bar];
  const yLo = Math.floor(Math.min(...scores) / 50) * 50;
  const yHi = Math.ceil(Math.max(...scores) / 50) * 50;
  const x = (usd: number) =>
    usd === 0 ? PAD.l + 16 : positiveStart + ((Math.log10(usd) - xLo) / (xHi - xLo)) * (W - positiveStart - PAD.r);
  const y = (score: number) => PAD.t + (1 - (score - yLo) / (yHi - yLo)) * (H - PAD.t - PAD.b);
  const text = (row: (typeof priced)[number]) => (narrow ? row.model : `${row.model}  ${row.harness} · ${costText(row.cost)}`);
  const labels = placeLabels(
    priced.map((row) => ({ x: x(row.cost.usd as number), y: y(row.score), width: text(row).length * CHAR })),
    17,
    W - PAD.r,
  );
  const yTicks: number[] = [];
  for (let t = yLo; t <= yHi; t += 50) yTicks.push(t);
  const xTicks = TICKS.filter((t) => Math.log10(t) >= xLo && Math.log10(t) <= xHi);

  return (
    <section className="view page-view" aria-labelledby="cost-title">
      <div className="view-head">
        <h1 id="cost-title">Score vs cost per game</h1>
        <span>Hollow dots: API list-price estimates. Filled: billed. Lines: 95% score intervals.</span>
      </div>
      <FilterNote filters={filters} onReset={() => setFilters({ hiddenHarnesses: [], hiddenVendors: [], showBots: filters.showBots })} />
      <div ref={frame}>
        {priced.length === 0 ? (
          <p className="view-note">No row in the current filter has a cost measurement.</p>
        ) : (
          <svg className="chart" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Score against cost per game for ${priced.length} rows`}>
            {yTicks.map((t) => (
              <g key={t}>
                <line className="grid" x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} />
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
            <text className="axis-label" x={(PAD.l + W - PAD.r) / 2} y={H - 8} textAnchor="middle">
              {narrow ? "Cost per game (USD, log)" : `Cost per five-season game (USD, ${hasZero ? "positive costs log scale; $0 separate" : "log scale"})`}
            </text>
            <line className="bar-line" x1={PAD.l} x2={W - PAD.r} y1={y(bar)} y2={y(bar)} />
            <text className="bar-label" x={W - PAD.r} y={y(bar) - 7} textAnchor="end">pick-trader {num(bar)}</text>
            {priced.map((row, i) => {
              const px = x(row.cost.usd as number);
              const py = y(row.score);
              const color = `var(--vendor-${row.vendor.key})`;
              const label = labels[i];
              return (
                <g key={row.id}>
                  <title>{`${row.model} (${row.harness}): score ${num(row.score)}, ${costText(row.cost)} per game`}</title>
                  {row.ci && <line x1={px} x2={px} y1={y(row.ci[0])} y2={y(row.ci[1])} stroke={color} strokeOpacity="0.45" strokeWidth="1.5" />}
                  <circle cx={px} cy={py} r="6" fill={row.cost.kind === "estimate" ? "var(--bg)" : color} stroke={color} strokeWidth="2" />
                  <text className="point-label" x={label.anchorEnd ? px - 12 : px + 12} y={label.y} textAnchor={label.anchorEnd ? "end" : "start"}>
                    {row.model}
                    {!narrow && (
                      <tspan className="axis-label" dx="6">
                        {row.harness} · {costText(row.cost)}
                      </tspan>
                    )}
                  </text>
                </g>
              );
            })}
          </svg>
        )}
      </div>
      {narrow && priced.length > 0 && (
        <ul className="chart-key">
          {[...priced].sort((a, b) => (a.cost.usd as number) - (b.cost.usd as number)).map((row) => (
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
      {unmeasured.length > 0 && (
        <p className="view-note">
          Not shown, cost unmeasured: {unmeasured.map((row) => `${row.model} (${row.harness})`).join(", ")}.
        </p>
      )}
    </section>
  );
}
