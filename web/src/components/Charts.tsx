import type { Snapshot } from "../types";
import { fmt } from "../lib";

const ACCENT = "#34e0a1";
const BLUE = "#8ab4ff";
const GRID = "rgba(148, 173, 214, 0.14)";
const LABEL = "#66779a";

const W = 520;
const H = 250;
const PAD = { top: 18, right: 16, bottom: 34, left: 44 };

function yScale(value: number, max: number): number {
  const inner = H - PAD.top - PAD.bottom;
  return PAD.top + inner - (value / max) * inner;
}

function niceMax(value: number): number {
  const step = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / step) * step;
}

function GridLines({ max, ticks = 4 }: { max: number; ticks?: number }) {
  return (
    <g>
      {Array.from({ length: ticks + 1 }, (_, index) => {
        const value = (max / ticks) * index;
        const y = yScale(value, max);
        return (
          <g key={index}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y} stroke={GRID} />
            <text x={PAD.left - 8} y={y + 4} textAnchor="end" fontSize="10.5" fill={LABEL} fontFamily="IBM Plex Mono, monospace">
              {Math.round(value)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

export function LiftChart({ snapshot }: { snapshot: Snapshot }) {
  const rows = snapshot.paired.per_seed;
  const max = niceMax(Math.max(...rows.map((row) => row.candidate_score)) * 1.08);
  const band = (W - PAD.left - PAD.right) / rows.length;
  const barWidth = Math.min(26, band / 3);

  return (
    <div className="panel">
      <div className="panel-title">
        <h3>Per-seed paired lift</h3>
        <span>same seeds, differenced</span>
      </div>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Candidate versus baseline panel score for each seed">
        <GridLines max={max} />
        {rows.map((row, index) => {
          const cx = PAD.left + band * index + band / 2;
          const candidateY = yScale(row.candidate_score, max);
          const panelY = yScale(row.baseline_panel_score, max);
          const baseY = yScale(0, max);
          return (
            <g key={row.seed}>
              <rect
                x={cx - barWidth - 3}
                y={panelY}
                width={barWidth}
                height={baseY - panelY}
                rx="4"
                fill={BLUE}
                opacity="0.55"
              />
              <rect x={cx + 3} y={candidateY} width={barWidth} height={baseY - candidateY} rx="4" fill={ACCENT} opacity="0.9" />
              <text x={cx + 3 + barWidth / 2} y={candidateY - 6} textAnchor="middle" fontSize="10" fill={ACCENT} fontFamily="IBM Plex Mono, monospace">
                +{Math.round(row.lift)}
              </text>
              <text x={cx} y={H - PAD.bottom + 18} textAnchor="middle" fontSize="10.5" fill={LABEL} fontFamily="IBM Plex Mono, monospace">
                seed {row.seed}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="legend">
        <span>
          <i style={{ background: ACCENT }} />
          value (candidate)
        </span>
        <span>
          <i style={{ background: BLUE, opacity: 0.55 }} />
          baseline panel mean
        </span>
        <span>
          mean lift +{fmt(snapshot.paired.paired_lift_mean, 1)} · σ {fmt(snapshot.paired.paired_lift_stddev, 1)}
        </span>
      </div>
    </div>
  );
}

export function SeasonTraceChart({ snapshot }: { snapshot: Snapshot }) {
  const trace = snapshot.season_trace;
  const rows = trace.seasons;
  const max = niceMax(Math.max(...rows.map((row) => row.score_after_season)) * 1.12);
  const band = (W - PAD.left - PAD.right) / rows.length;

  const points = rows.map((row, index) => ({
    x: PAD.left + band * index + band / 2,
    y: yScale(row.score_after_season, max),
    row,
  }));
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x},${point.y}`).join(" ");
  const areaPath = `${path} L${points[points.length - 1].x},${yScale(0, max)} L${points[0].x},${yScale(0, max)} Z`;

  return (
    <div className="panel">
      <div className="panel-title">
        <h3>One franchise, five seasons</h3>
        <span>
          {trace.agent} agent · seed {trace.seed}
        </span>
      </div>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Objective score of the value agent after each season">
        <defs>
          <linearGradient id="trace-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={ACCENT} stopOpacity="0.28" />
            <stop offset="100%" stopColor={ACCENT} stopOpacity="0" />
          </linearGradient>
        </defs>
        <GridLines max={max} />
        <path d={areaPath} fill="url(#trace-fill)" />
        <path d={path} fill="none" stroke={ACCENT} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
        {points.map(({ x, y, row }) => (
          <g key={row.season}>
            {row.champion && (
              <text x={x} y={y - 16} textAnchor="middle" fontSize="13">
                🏆
              </text>
            )}
            <circle cx={x} cy={y} r="4.5" fill="#0f1728" stroke={ACCENT} strokeWidth="2.5" />
            <text x={x} y={H - PAD.bottom + 18} textAnchor="middle" fontSize="10.5" fill={LABEL} fontFamily="IBM Plex Mono, monospace">
              S{row.season}
            </text>
            <text x={x} y={H - PAD.bottom + 31} textAnchor="middle" fontSize="9.5" fill={LABEL} fontFamily="IBM Plex Mono, monospace">
              {row.wins}-{row.losses}
            </text>
          </g>
        ))}
      </svg>
      <div className="legend">
        <span>
          <i style={{ background: ACCENT }} />
          objective score after season
        </span>
        <span>🏆 championship</span>
        <span>final cap room ${fmt(rows[rows.length - 1].cap_room, 1)}M</span>
      </div>
    </div>
  );
}
