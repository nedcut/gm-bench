import { useMemo } from "react";
import type { Leaderboard } from "../types";
import { costText, modelRows, num, pickTraderScore, useFilters, visible } from "../v2";
import FilterNote from "./FilterNote";

const W = 1040;
const H = 480;
const PAD = { l: 52, r: 250, t: 24, b: 48 };
const TICKS = [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30];

/* Label each point to its right; push a label down when it would overlap one
   already placed nearby. */
function placeLabels(points: { x: number; y: number }[], gap: number, width: number): number[] {
  const order = points.map((p, i) => ({ ...p, i })).sort((a, b) => a.y - b.y);
  const placed: { x: number; y: number }[] = [];
  const out = new Array<number>(points.length);
  for (const point of order) {
    let y = point.y + 4;
    for (const other of placed) {
      if (Math.abs(other.x - point.x) < width && y - other.y < gap) y = other.y + gap;
    }
    placed.push({ x: point.x, y });
    out[point.i] = y;
  }
  return out;
}

export default function CostView({ data }: { data: Leaderboard }) {
  const [filters, setFilters] = useFilters();
  const all = useMemo(() => modelRows(data), [data]);
  const shown = all.filter((row) => visible(row, filters));
  const priced = shown.filter((row) => row.cost.usd !== null);
  const unmeasured = shown.filter((row) => row.cost.usd === null);
  const bar = pickTraderScore(data) ?? 0;

  const costs = priced.map((row) => row.cost.usd as number);
  const xLo = Math.log10(Math.min(...costs, 0.1) / 1.6);
  const xHi = Math.log10(Math.max(...costs, 1) * 1.6);
  const scores = [...priced.map((row) => row.score), bar];
  const yLo = Math.floor(Math.min(...scores) / 50) * 50 - 10;
  const yHi = Math.ceil(Math.max(...scores) / 50) * 50 + 10;
  const x = (usd: number) => PAD.l + ((Math.log10(usd) - xLo) / (xHi - xLo)) * (W - PAD.l - PAD.r);
  const y = (score: number) => PAD.t + (1 - (score - yLo) / (yHi - yLo)) * (H - PAD.t - PAD.b);
  const labelYs = placeLabels(priced.map((row) => ({ x: x(row.cost.usd as number), y: y(row.score) })), 17, 240);
  const yTicks: number[] = [];
  for (let t = Math.ceil(yLo / 50) * 50; t <= yHi; t += 50) yTicks.push(t);

  return (
    <section className="view page-view" aria-labelledby="cost-title">
      <div className="view-head">
        <h2 id="cost-title">Score vs cost per game</h2>
        <span>Hollow dots: API list-price estimates. Filled: billed. Lines: 95% score intervals.</span>
      </div>
      <FilterNote filters={filters} onReset={() => setFilters({ hiddenHarnesses: [], hiddenVendors: [], showBots: filters.showBots })} />
      {priced.length === 0 ? (
        <p className="view-note">No row in the current filter has a cost measurement.</p>
      ) : (
        <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Score against cost per game for ${priced.length} rows`}>
          {yTicks.map((t) => (
            <g key={t}>
              <line className="grid" x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} />
              <text x={PAD.l - 10} y={y(t) + 4} textAnchor="end">{t}</text>
            </g>
          ))}
          {TICKS.filter((t) => Math.log10(t) >= xLo && Math.log10(t) <= xHi).map((t) => (
            <text key={t} x={x(t)} y={H - PAD.b + 20} textAnchor="middle">${t}</text>
          ))}
          <text className="axis-label" x={(PAD.l + W - PAD.r) / 2} y={H - 6} textAnchor="middle">Cost per five-season game (USD, log scale)</text>
          <text className="axis-label" x={14} y={PAD.t + 4}>Score</text>
          <line className="bar-line" x1={PAD.l} x2={W - PAD.r} y1={y(bar)} y2={y(bar)} />
          <text className="bar-label" x={PAD.l + 6} y={y(bar) - 6}>pick-trader {num(bar)}</text>
          {priced.map((row, i) => {
            const px = x(row.cost.usd as number);
            const py = y(row.score);
            const color = `var(--vendor-${row.vendor.key})`;
            return (
              <g key={row.id}>
                {row.ci && <line x1={px} x2={px} y1={y(row.ci[0])} y2={y(row.ci[1])} stroke={color} strokeOpacity="0.45" strokeWidth="1.5" />}
                <circle cx={px} cy={py} r="6" fill={row.cost.kind === "estimate" ? "var(--bg)" : color} stroke={color} strokeWidth="2" />
                <text className="point-label" x={px + 12} y={labelYs[i]}>
                  {row.model}
                  <tspan className="axis-label" dx="6">{row.harness} · {costText(row.cost)}</tspan>
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {unmeasured.length > 0 && (
        <p className="view-note">
          Not shown, cost unmeasured: {unmeasured.map((row) => `${row.model} (${row.harness})`).join(", ")}.
        </p>
      )}
    </section>
  );
}
