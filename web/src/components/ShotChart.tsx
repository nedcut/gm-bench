import { scaleLinear } from "d3-scale";
import type { ResultModel } from "../benchmarkData";
import { shortModelName } from "../benchmarkData";
import { fmt } from "../lib";

/* The hero draws the finding rather than describing it: one score axis, the
   scripted bar as the red line, the paired baseline as a blue line, and every
   model as a puck. All eleven pucks stop short of the red line. Values come
   from the same leaderboard record the results table reads. */

const W = 640;
const H = 176;
const PAD_L = 18;
const PAD_R = 86;
const R = 10;
const CENTER_Y = 88;
const AXIS_Y = 150;

type Puck = { x: number; y: number; model: ResultModel };

function swarm(models: ResultModel[], x: (v: number) => number): Puck[] {
  const placed: Puck[] = [];
  const gap = R * 2 + 4;
  for (const model of [...models].sort((a, b) => a.mean_score - b.mean_score)) {
    const cx = x(model.mean_score);
    let y = CENTER_Y;
    for (let step = 0; step < 8; step += 1) {
      const candidates = step === 0 ? [0] : [step, -step];
      const free = candidates
        .map((k) => CENTER_Y + k * gap)
        .find((cy) => placed.every((p) => Math.hypot(p.x - cx, p.y - cy) >= gap));
      if (free !== undefined) {
        y = free;
        break;
      }
    }
    placed.push({ x: cx, y, model });
  }
  return placed;
}

export default function ShotChart({
  models,
  scriptedBar,
  panelMean,
}: {
  models: ResultModel[];
  scriptedBar: number;
  panelMean: number | null;
}) {
  const scores = models.map((m) => m.mean_score);
  const lo = Math.min(...scores, panelMean ?? Infinity) - 10;
  const hi = scriptedBar + 14;
  const x = scaleLinear().domain([lo, hi]).range([PAD_L, W - PAD_R]);
  const pucks = swarm(models, x);
  const best = pucks.reduce((a, b) => (b.model.mean_score > a.model.mean_score ? b : a));
  const barX = x(scriptedBar);
  const above = models.filter((m) => m.mean_score > scriptedBar).length;
  const summary = `${above} of ${models.length} models score above the pick-trader bar of ${fmt(scriptedBar, 1)}. Best model ${shortModelName(best.model.model)} at ${fmt(best.model.mean_score, 1)}.`;

  return (
    <figure className="shot-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary}>
        {/* axis */}
        <line x1={PAD_L} x2={W - PAD_R + 40} y1={AXIS_Y} y2={AXIS_Y} className="shot-axis" />
        {x.ticks(5).map((t) => (
          <g key={t} transform={`translate(${x(t)} ${AXIS_Y})`}>
            <line y2={5} className="shot-axis" />
            <text y={19} textAnchor="middle" className="shot-tick">
              {t}
            </text>
          </g>
        ))}

        {/* baseline blue line */}
        {panelMean !== null && (
          <g transform={`translate(${x(panelMean)} 0)`}>
            <line y1={14} y2={AXIS_Y} className="shot-blue" />
            <text y={9} textAnchor="middle" className="shot-label shot-label-blue">
              baseline panel {fmt(panelMean, 1)}
            </text>
          </g>
        )}

        {/* the red line: the bar to beat */}
        <g transform={`translate(${barX} 0)`}>
          <line y1={14} y2={AXIS_Y} className="shot-red" />
          <text y={9} textAnchor="middle" className="shot-label shot-label-red">
            pick-trader {fmt(scriptedBar, 1)}
          </text>
        </g>

        {/* pucks */}
        {pucks.map((p) => (
          <circle key={p.model.id} cx={p.x} cy={p.y} r={R} className="shot-puck">
            <title>
              {shortModelName(p.model.model)} {fmt(p.model.mean_score, 1)}
            </title>
          </circle>
        ))}

        {/* annotate the best puck */}
        <g transform={`translate(${best.x} ${best.y})`}>
          <line x1={0} x2={0} y1={-R - 3} y2={-R - 16} className="shot-axis" />
          <text y={-R - 21} textAnchor="middle" className="shot-note">
            best: {shortModelName(best.model.model)} {fmt(best.model.mean_score, 1)}
          </text>
        </g>
      </svg>
      <figcaption>
        <b>
          {above} of {models.length}
        </b>{" "}
        models clear the scripted pick-trader bar. Each puck is one model's mean score on the
        private seed panel. Hover a puck for its name.
      </figcaption>
    </figure>
  );
}
