import { useMemo, useState } from "react";
import { max } from "d3-array";
import { scaleLinear } from "d3-scale";
import {
  MECHANICS,
  rejectionRate,
  shortModelName,
  type BenchmarkView,
  type ResultModel,
} from "../benchmarkData";
import { fmt } from "../lib";

type HeatMetric = "rate" | "count";

function RankingPlot({
  benchmark,
  selected,
  onSelect,
}: {
  benchmark: BenchmarkView;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const width = 690;
  const height = 398;
  const left = 210;
  const right = 30;
  const top = 44;
  const bottom = 48;
  const rowHeight = 37;
  const x = scaleLinear()
    .domain([0, Math.max(450, benchmark.oracle * 1.05)])
    .range([left, width - right]);
  const ticks = x.ticks(5);

  return (
    <div className="chart-scroll">
      <svg
        className="analysis-ranking"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-labelledby="ranking-title ranking-desc"
      >
        <title id="ranking-title">Mean GM-Bench scores</title>
        <desc id="ranking-desc">
          Select a model to inspect its mechanic-level accepted and rejected actions.
        </desc>
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={x(tick)}
              x2={x(tick)}
              y1={top - 12}
              y2={height - bottom}
              className="chart-grid"
            />
            <text x={x(tick)} y={height - 24} textAnchor="middle" className="chart-tick">
              {tick}
            </text>
          </g>
        ))}
        <line
          x1={x(benchmark.scriptedBar)}
          x2={x(benchmark.scriptedBar)}
          y1={top - 20}
          y2={height - bottom}
          className="chart-reference"
        />
        <text
          x={x(benchmark.scriptedBar)}
          y={top - 25}
          textAnchor="end"
          className="chart-reference-label"
        >
          {fmt(benchmark.scriptedBar, 1)} scripted bar
        </text>
        <line
          x1={x(benchmark.oracle)}
          x2={x(benchmark.oracle)}
          y1={top - 20}
          y2={height - bottom}
          className="chart-oracle"
        />
        <text
          x={x(benchmark.oracle)}
          y={top - 8}
          textAnchor="end"
          className="chart-oracle-label"
        >
          {fmt(benchmark.oracle, 1)} oracle
        </text>

        {benchmark.models.map((model, index) => {
          const y = top + index * rowHeight + rowHeight / 2;
          const active = model.id === selected;
          return (
            <g
              key={model.id}
              className={active ? "ranking-row is-selected" : "ranking-row"}
              role="button"
              tabIndex={0}
              aria-label={`Inspect ${model.model}`}
              onClick={() => onSelect(model.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(model.id);
                }
              }}
            >
              <rect x="0" y={y - rowHeight / 2} width={width} height={rowHeight} />
              <text x="4" y={y + 5} className="ranking-model">
                {shortModelName(model.model)}
              </text>
              <text x={left - 12} y={y + 5} textAnchor="end" className="chart-value">
                {fmt(model.mean_score, 1)}
              </text>
              <line x1={left} x2={x(model.mean_score)} y1={y} y2={y} className="rank-line" />
              <circle cx={x(model.mean_score)} cy={y} r={active ? 6 : 4.5} className="candidate-dot" />
            </g>
          );
        })}
        <text
          x={(left + width - right) / 2}
          y={height - 6}
          textAnchor="middle"
          className="chart-axis-label"
        >
          Mean GM-Bench score
        </text>
      </svg>
    </div>
  );
}

function MechanicBars({ model }: { model: ResultModel }) {
  const totals = MECHANICS.map(([key]) => {
    const outcome = model.mechanic_breakdown[key];
    return outcome.accepted + outcome.rejected;
  });
  const maxTotal = max(totals) ?? 1;

  return (
    <div className="mechanic-bars">
      <div className="mechanic-legend">
        <span>
          <i className="accepted-key" /> Accepted
        </span>
        <span>
          <i className="rejected-key" /> Rejected
        </span>
      </div>
      {MECHANICS.map(([key, label]) => {
        const outcome = model.mechanic_breakdown[key];
        const total = outcome.accepted + outcome.rejected;
        return (
          <div className="mechanic-bar-row" key={key}>
            <span>{label}</span>
            <div className="mechanic-track">
              <div
                className="mechanic-total"
                style={{ width: `${(total / maxTotal) * 100}%` }}
              >
                <i
                  className="accepted-segment"
                  style={{ width: `${total === 0 ? 0 : (outcome.accepted / total) * 100}%` }}
                />
                <i
                  className="rejected-segment"
                  style={{ width: `${total === 0 ? 0 : (outcome.rejected / total) * 100}%` }}
                />
              </div>
            </div>
            <span className="mechanic-count">
              {outcome.accepted.toLocaleString("en-US")} /{" "}
              {outcome.rejected.toLocaleString("en-US")}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function MechanicsHeatmap({
  benchmark,
  metric,
  onSelect,
}: {
  benchmark: BenchmarkView;
  metric: HeatMetric;
  onSelect: (id: string) => void;
}) {
  const rates = benchmark.models.flatMap((model) =>
    MECHANICS.map(([key]) => rejectionRate(model, key)),
  );
  const counts = benchmark.models.flatMap((model) =>
    MECHANICS.map(([key]) => model.mechanic_breakdown[key].rejected),
  );
  const maxValue = metric === "rate" ? max(rates) ?? 1 : max(counts) ?? 1;
  const opacity = scaleLinear().domain([0, maxValue]).range([0.06, 0.9]);

  return (
    <div className="heatmap-wrap" role="grid" aria-label="Model outcomes by mechanic">
      <div className="heatmap-grid heatmap-head" role="row">
        <span />
        {MECHANICS.map(([key, label]) => (
          <span key={key} role="columnheader">
            {label}
          </span>
        ))}
      </div>
      {benchmark.models.map((model) => (
        <div className="heatmap-grid heatmap-row" role="row" key={model.id}>
          <button type="button" onClick={() => onSelect(model.id)} role="rowheader">
            {shortModelName(model.model)}
          </button>
          {MECHANICS.map(([key]) => {
            const outcome = model.mechanic_breakdown[key];
            const value =
              metric === "rate" ? rejectionRate(model, key) : outcome.rejected;
            const display =
              metric === "rate"
                ? `${fmt(value * 100, 1)}%`
                : outcome.rejected.toLocaleString("en-US");
            return (
              <button
                type="button"
                key={key}
                role="gridcell"
                style={{ backgroundColor: `rgba(26, 95, 143, ${opacity(value)})` }}
                onClick={() => onSelect(model.id)}
                aria-label={`${model.model}, ${key.replaceAll("_", " ")}, ${display}`}
              >
                {display}
              </button>
            );
          })}
        </div>
      ))}
      <div className="heatmap-legend">
        <span>{metric === "rate" ? "0%" : "0"}</span>
        <i />
        <span>
          {metric === "rate"
            ? `${fmt(maxValue * 100, 1)}%`
            : Math.round(maxValue).toLocaleString("en-US")}
        </span>
      </div>
    </div>
  );
}

export default function Analysis({ benchmark }: { benchmark: BenchmarkView }) {
  const [selectedId, setSelectedId] = useState(benchmark.models[0]?.id ?? "");
  const [metric, setMetric] = useState<HeatMetric>("rate");
  const selected = useMemo(
    () => benchmark.models.find((model) => model.id === selectedId) ?? benchmark.models[0],
    [benchmark.models, selectedId],
  );

  if (!selected) return null;

  return (
    <section className="analysis-section" id="analysis">
      <div className="results-shell">
        <div className="analysis-heading">
          <div>
            <p className="kicker">Analysis</p>
            <h2>Where the model systems lose ground.</h2>
          </div>
          <p>
            Select a score or heatmap cell to inspect accepted and rejected actions from the
            same published record.
          </p>
        </div>

        <div className="analysis-evidence">
          <div className="analysis-ranking-panel">
            <div className="analysis-panel-title">
              <h3>Mean GM-Bench score</h3>
              <span>Higher is better</span>
            </div>
            <RankingPlot
              benchmark={benchmark}
              selected={selected.id}
              onSelect={setSelectedId}
            />
          </div>
          <aside className="model-inspector">
            <p>Selected model</p>
            <h3>{shortModelName(selected.model)}</h3>
            <dl>
              <div>
                <dt>Score</dt>
                <dd>{fmt(selected.mean_score, 1)}</dd>
              </div>
              <div>
                <dt>Lift vs panel</dt>
                <dd>{fmt(selected.paired_lift, 1)}</dd>
              </div>
              <div>
                <dt>Cost / episode</dt>
                <dd>${fmt(selected.cost_per_episode_usd, 2)}</dd>
              </div>
              <div>
                <dt>Failed queries</dt>
                <dd>
                  {(selected.failed_queries ?? 0).toLocaleString("en-US")} /{" "}
                  {selected.decision_points.toLocaleString("en-US")}
                </dd>
              </div>
            </dl>
            <h4>Accepted / rejected actions</h4>
            <MechanicBars model={selected} />
          </aside>
        </div>

        <div className="heatmap-section">
          <div className="heatmap-title">
            <div>
              <h3>Where models lose actions</h3>
              <p>
                Darker cells indicate more rejection. Red remains reserved for the scripted
                benchmark line.
              </p>
            </div>
            <div className="segmented" aria-label="Heatmap metric">
              <button
                type="button"
                className={metric === "rate" ? "is-active" : ""}
                onClick={() => setMetric("rate")}
                aria-pressed={metric === "rate"}
              >
                Rejection rate
              </button>
              <button
                type="button"
                className={metric === "count" ? "is-active" : ""}
                onClick={() => setMetric("count")}
                aria-pressed={metric === "count"}
              >
                Rejected count
              </button>
            </div>
          </div>
          <MechanicsHeatmap
            benchmark={benchmark}
            metric={metric}
            onSelect={setSelectedId}
          />
        </div>
      </div>
    </section>
  );
}
