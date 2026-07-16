import { useState } from "react";
import type { Snapshot } from "../types";
import { COLOR, fmt } from "../lib";

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

interface Tip {
  x: number;
  y: number;
  lines: string[];
}

function GridLines({ max, ticks = 4 }: { max: number; ticks?: number }) {
  return (
    <g>
      {Array.from({ length: ticks + 1 }, (_, index) => {
        const value = (max / ticks) * index;
        const y = yScale(value, max);
        return (
          <g key={index}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y} stroke={COLOR.grid} />
            <text x={PAD.left - 8} y={y + 4} textAnchor="end" fontSize="10.5" fill={COLOR.faint} fontFamily="IBM Plex Mono, monospace">
              {Math.round(value)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

function TipBox({ tip }: { tip: Tip | null }) {
  if (!tip) {
    return null;
  }
  return (
    <div className="chart-tip" style={{ left: `${(tip.x / W) * 100}%`, top: `${(tip.y / H) * 100}%` }}>
      {tip.lines.map((line, index) => (index === 0 ? <b key={line}>{line}</b> : <div key={line}>{line}</div>))}
    </div>
  );
}

export function LiftChart({ snapshot }: { snapshot: Snapshot }) {
  const [tip, setTip] = useState<Tip | null>(null);
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
      <div className="chart-holder">
        <svg
          className="chart-svg"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label="Candidate versus baseline panel score for each seed"
          onMouseLeave={() => setTip(null)}
        >
          <GridLines max={max} />
          {rows.map((row, index) => {
            const cx = PAD.left + band * index + band / 2;
            const candidateY = yScale(row.candidate_score, max);
            const panelY = yScale(row.baseline_panel_score, max);
            const baseY = yScale(0, max);
            const showTip = () =>
              setTip({
                x: cx,
                y: Math.min(candidateY, panelY),
                lines: [
                  `seed ${row.seed}`,
                  `candidate ${fmt(row.candidate_score, 1)}`,
                  `panel ${fmt(row.baseline_panel_score, 1)}`,
                  `lift ${row.lift >= 0 ? "+" : ""}${fmt(row.lift, 1)}`,
                ],
              });
            return (
              <g
                key={row.seed}
                role="button"
                tabIndex={0}
                aria-label={`Seed ${row.seed}: candidate ${fmt(row.candidate_score, 1)}, panel ${fmt(row.baseline_panel_score, 1)}, lift ${row.lift >= 0 ? "+" : ""}${fmt(row.lift, 1)}`}
                onMouseEnter={showTip}
                onMouseLeave={() => setTip(null)}
                onFocus={showTip}
                onBlur={() => setTip(null)}
                onClick={showTip}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    showTip();
                  }
                }}
              >
                <rect x={cx - band / 2} y={PAD.top} width={band} height={H - PAD.top - PAD.bottom} fill="transparent" />
                <rect x={cx - barWidth - 3} y={panelY} width={barWidth} height={baseY - panelY} rx="2" fill={COLOR.red} opacity="0.75" />
                <rect x={cx + 3} y={candidateY} width={barWidth} height={baseY - candidateY} rx="2" fill={COLOR.blue} />
                <text x={cx + 3 + barWidth / 2} y={candidateY - 6} textAnchor="middle" fontSize="10" fill={COLOR.blue} fontFamily="IBM Plex Mono, monospace">
                  {row.lift >= 0 ? "+" : ""}{Math.round(row.lift)}
                </text>
                <text x={cx} y={H - PAD.bottom + 18} textAnchor="middle" fontSize="10.5" fill={COLOR.faint} fontFamily="IBM Plex Mono, monospace">
                  seed {row.seed}
                </text>
              </g>
            );
          })}
        </svg>
        <TipBox tip={tip} />
      </div>
      <div className="legend">
        <span>
          <i style={{ background: COLOR.blue }} />
          value (candidate)
        </span>
        <span>
          <i style={{ background: COLOR.red, opacity: 0.75 }} />
          baseline panel mean — the bar
        </span>
        <span>
          mean lift +{fmt(snapshot.paired.paired_lift_mean, 1)} · σ {fmt(snapshot.paired.paired_lift_stddev, 1)}
        </span>
      </div>
    </div>
  );
}

export function SeasonTraceChart({ snapshot }: { snapshot: Snapshot }) {
  const [tip, setTip] = useState<Tip | null>(null);
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

  return (
    <div className="panel">
      <div className="panel-title">
        <h3>One franchise, five seasons</h3>
        <span>
          {trace.agent} agent · seed {trace.seed}
        </span>
      </div>
      <div className="chart-holder">
        <svg
          className="chart-svg"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label="Objective score of the value agent after each season"
          onMouseLeave={() => setTip(null)}
        >
          <GridLines max={max} />
          <path d={path} fill="none" stroke={COLOR.blue} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {points.map(({ x, y, row }) => {
            const showTip = () =>
              setTip({
                  x,
                  y,
                  lines: [
                    `season ${row.season} · ${row.wins}-${row.losses}`,
                    `score ${fmt(row.score_after_season, 1)}`,
                    `cap room $${fmt(row.cap_room, 1)}M${row.champion ? " · champion" : ""}`,
                  ],
                });
            return (
            <g
              key={row.season}
              role="button"
              tabIndex={0}
              aria-label={`Season ${row.season}: record ${row.wins}-${row.losses}, score ${fmt(row.score_after_season, 1)}, cap room $${fmt(row.cap_room, 1)}M${row.champion ? ", champion" : ""}`}
              onMouseEnter={showTip}
              onMouseLeave={() => setTip(null)}
              onFocus={showTip}
              onBlur={() => setTip(null)}
              onClick={showTip}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  showTip();
                }
              }}
            >
              <rect x={x - band / 2} y={PAD.top} width={band} height={H - PAD.top - PAD.bottom} fill="transparent" />
              {row.champion && (
                <text x={x} y={y - 16} textAnchor="middle" fontSize="13">
                  🏆
                </text>
              )}
              <circle cx={x} cy={y} r="4.5" fill="#ffffff" stroke={COLOR.blue} strokeWidth="2" />
              <text x={x} y={H - PAD.bottom + 18} textAnchor="middle" fontSize="10.5" fill={COLOR.faint} fontFamily="IBM Plex Mono, monospace">
                S{row.season}
              </text>
              <text x={x} y={H - PAD.bottom + 31} textAnchor="middle" fontSize="9.5" fill={COLOR.faint} fontFamily="IBM Plex Mono, monospace">
                {row.wins}-{row.losses}
              </text>
            </g>
            );
          })}
        </svg>
        <TipBox tip={tip} />
      </div>
      <div className="legend">
        <span>
          <i style={{ background: COLOR.blue }} />
          objective score after season
        </span>
        <span>🏆 championship</span>
        <span>final cap room ${fmt(rows[rows.length - 1].cap_room, 1)}M</span>
      </div>
    </div>
  );
}
