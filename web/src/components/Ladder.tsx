import { useState } from "react";
import type { Leaderboard as LeaderboardData } from "../types";
import { COLOR, fmt } from "../lib";

const W = 1080;
const H = 260;
const PAD = { left: 34, right: 34 };
const AXIS_Y = 168;

const BASELINE_NOTES: Record<string, string> = {
  "pick-trader": "best scripted heuristic — the bar",
  strategic: "scripted: plans across seasons",
  shrewd: "scripted: value-seeking trades",
  value: "scripted: drafts on surplus value",
  "win-now": "scripted: mortgages the future",
  conservative: "scripted: avoids risk",
  rebuild: "scripted: tears down, restocks",
  random: "random legal actions — the floor",
};

interface Marker {
  name: string;
  score: number;
  kind: "bar" | "ceiling" | "baseline" | "floor";
  note: string;
}

interface Tip {
  x: number;
  y: number;
  name: string;
  score: number;
  note: string;
}

/* Labels stagger across four heights above the axis; a label only drops to a
   lower row when the nearest one is already occupied within its width. */
const ROW_Y = [46, 80, 114, 148];
const LABEL_CLEARANCE = 108;

export default function Ladder({ data }: { data: LeaderboardData }) {
  const [tip, setTip] = useState<Tip | null>(null);

  const unsorted: Marker[] = [
    ...data.baselines.map<Marker>((baseline) => ({
      name: baseline.agent,
      score: baseline.mean_score,
      kind: baseline.agent === "pick-trader" ? "bar" : baseline.agent === "random" ? "floor" : "baseline",
      note: BASELINE_NOTES[baseline.agent] ?? "scripted baseline",
    })),
    {
      name: "oracle",
      score: data.headroom.oracle,
      kind: "ceiling",
      note: "plays with hidden information — the ceiling",
    },
  ];
  const markers = unsorted.sort((a, b) => a.score - b.score);

  const domainMax = Math.ceil((data.headroom.oracle * 1.05) / 50) * 50;
  const x = (value: number) => PAD.left + (value / domainMax) * (W - PAD.left - PAD.right);

  const rowLastX = ROW_Y.map(() => -Infinity);
  const rows = markers.map((marker) => {
    const mx = x(marker.score);
    let row = 0;
    while (row < ROW_Y.length - 1 && mx - rowLastX[row] < LABEL_CLEARANCE) {
      row += 1;
    }
    rowLastX[row] = mx;
    return { ...marker, x: mx, labelY: ROW_Y[row] };
  });
  /* A centered label whose neighbor has a taller marker line within half a
     label width would print across that line — anchor it away instead. */
  const placed = rows.map((marker) => {
    const collider = rows.find(
      (other) => other !== marker && other.labelY < marker.labelY && Math.abs(other.x - marker.x) < 42,
    );
    const anchor: "middle" | "end" | "start" =
      collider === undefined ? "middle" : collider.x > marker.x ? "end" : "start";
    const labelX = collider === undefined ? marker.x : collider.x > marker.x ? marker.x - 7 : marker.x + 7;
    return { ...marker, anchor, labelX };
  });

  const pending = data.publication;
  const ticks = Array.from({ length: Math.floor(domainMax / 100) + 1 }, (_, index) => index * 100);

  return (
    <div className="ladder-panel">
      <div className="ladder-head">
        <h2>The score ladder</h2>
        <span>
          objective score · {data.preset.seeds.length} seeds × {data.preset.seasons} seasons · scripted panel measured, model rows{" "}
          {pending.publishable_ranking ? "published" : "withheld"}
        </span>
      </div>
      <div className="ladder-wrap">
        <svg
          className="ladder-svg"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label="Score ladder: every scripted baseline and the oracle ceiling on one axis; model rows are withheld until the publication gate clears. The same numbers appear in the table below."
          onMouseLeave={() => setTip(null)}
        >
          <defs>
            <pattern id="pending-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="8" height="8" fill="none" />
              <line x1="0" y1="0" x2="0" y2="8" stroke={COLOR.grid} strokeWidth="2.5" />
            </pattern>
          </defs>

          {/* axis + ticks */}
          <line x1={PAD.left} x2={W - PAD.right} y1={AXIS_Y} y2={AXIS_Y} stroke={COLOR.ink} strokeWidth="1.5" />
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={x(tick)} x2={x(tick)} y1={AXIS_Y} y2={AXIS_Y + 7} stroke={COLOR.ink} strokeWidth="1" />
              <text
                x={x(tick)}
                y={AXIS_Y + 22}
                textAnchor="middle"
                fontSize="11"
                fill={COLOR.faint}
                fontFamily="IBM Plex Mono, monospace"
              >
                {tick}
              </text>
            </g>
          ))}

          {/* the pending zone: where the model rows will land */}
          <rect
            x={x(0)}
            y={AXIS_Y + 34}
            width={x(domainMax) - x(0)}
            height={34}
            fill="url(#pending-hatch)"
            stroke={COLOR.grid}
          />
          <text
            x={(x(0) + x(domainMax)) / 2}
            y={AXIS_Y + 55}
            textAnchor="middle"
            fontSize="12.5"
            fill={COLOR.steel}
            fontFamily="IBM Plex Mono, monospace"
            style={{ letterSpacing: "0.08em" }}
          >
            {pending.publishable_ranking
              ? "MODEL ROWS PUBLISHED ABOVE"
              : `${pending.eligible_headline_models}/${pending.minimum_headline_models} ELIGIBLE MODELS — ROWS WITHHELD UNTIL THE GATE CLEARS`}
          </text>

          {/* markers */}
          {placed.map((marker, index) => {
            const isBar = marker.kind === "bar";
            const isCeiling = marker.kind === "ceiling";
            const stroke = isBar ? COLOR.red : isCeiling ? COLOR.ink : COLOR.steel;
            const key = isBar || isCeiling || marker.kind === "floor";
            return (
              <g
                key={marker.name}
                className="rise"
                style={{ animationDelay: `${0.08 * index}s` }}
                onMouseEnter={() => setTip({ x: marker.x, y: marker.labelY, name: marker.name, score: marker.score, note: marker.note })}
                onMouseLeave={() => setTip(null)}
              >
                <line
                  x1={marker.x}
                  x2={marker.x}
                  y1={marker.labelY + 6}
                  y2={AXIS_Y}
                  stroke={stroke}
                  strokeWidth={isBar ? 3.5 : 1.5}
                  strokeDasharray={isCeiling ? "5 4" : undefined}
                />
                <text
                  className={key ? "lbl lbl-key" : "lbl"}
                  x={marker.labelX}
                  y={marker.labelY - 8}
                  textAnchor={marker.anchor}
                  fontSize={isBar ? "14" : "11.5"}
                  fontWeight={isBar ? 700 : 500}
                  fill={stroke}
                  fontFamily="Barlow Condensed, sans-serif"
                  style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}
                >
                  {marker.name}
                </text>
                <text
                  className={key ? "lbl lbl-key" : "lbl"}
                  x={marker.labelX}
                  y={marker.labelY + 3}
                  textAnchor={marker.anchor}
                  fontSize="10.5"
                  fill={isBar ? COLOR.red : COLOR.faint}
                  fontFamily="IBM Plex Mono, monospace"
                >
                  {isBar ? `${fmt(marker.score, 1)} · THE RED LINE` : fmt(marker.score, 1)}
                </text>
                {/* generous invisible hit target for the tooltip */}
                <rect
                  x={marker.x - 18}
                  y={marker.labelY - 20}
                  width={36}
                  height={AXIS_Y - marker.labelY + 20}
                  fill="transparent"
                />
              </g>
            );
          })}

        </svg>
        {tip && (
          <div
            className="chart-tip"
            style={{ left: `${(tip.x / W) * 100}%`, top: `${(tip.y / H) * 100}%` }}
          >
            <b>{tip.name}</b> · {fmt(tip.score, 1)}
            <br />
            {tip.note}
          </div>
        )}
      </div>
    </div>
  );
}
