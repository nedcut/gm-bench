import { useMemo, useState, type CSSProperties } from "react";
import { max } from "d3-array";
import { scaleLinear } from "d3-scale";
import {
  MECHANICS,
  rejectionRate,
  scoreCi95,
  shortModelName,
  type BenchmarkView,
  type ResultModel,
} from "../benchmarkData";
import { fmt, formatTokensPerDecision } from "../lib";

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
  const left = 210;
  const right = 30;
  const top = 44;
  const bottom = 48;
  const rowHeight = 37;
  const rows = useMemo(
    () =>
      [...benchmark.models].sort(
        (a, b) => a.tier - b.tier || b.mean_score - a.mean_score,
      ),
    [benchmark.models],
  );
  const ciExtents = rows.flatMap((model) => scoreCi95(model) ?? []);
  const x = scaleLinear()
    .domain([
      0,
      Math.max(
        450,
        benchmark.oracle * 1.05,
        ...rows.map((model) => model.mean_score),
        ...ciExtents,
      ),
    ])
    .range([left, width - right]);
  const ticks = x.ticks(5);
  const height = top + rows.length * rowHeight + bottom;

  return (
    <div className="chart-scroll">
      <svg
        className="analysis-ranking"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-labelledby="ranking-title ranking-desc"
      >
        <title id="ranking-title">Mean GM-Bench scores with across-seed intervals</title>
        <desc id="ranking-desc">
          Each model shows a mean score and 95 percent across-seed interval. Rows are grouped by
          Holm tier, not ranked ordinally.
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
          scripted bar · pick-trader {fmt(benchmark.scriptedBar, 1)}
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
          partial oracle reference {fmt(benchmark.oracle, 1)}
        </text>

        {rows.map((model, index) => {
          const y = top + index * rowHeight + rowHeight / 2;
          const active = model.id === selected;
          const ci = scoreCi95(model);
          const tierBreak = index === 0 || model.tier !== rows[index - 1].tier;
          return (
            <g
              key={model.id}
              className={active ? "ranking-row is-selected" : "ranking-row"}
              role="button"
              tabIndex={0}
              aria-label={`Inspect ${model.model}`}
              onMouseEnter={() => onSelect(model.id)}
              onFocus={() => onSelect(model.id)}
              onClick={() => onSelect(model.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(model.id);
                }
              }}
              style={{ "--row-index": index } as CSSProperties}
            >
              <title>
                {model.model}: mean {fmt(model.mean_score, 1)}
                {ci
                  ? `, 95% across-seed CI [${fmt(ci[0], 1)}, ${fmt(ci[1], 1)}]`
                  : ""}
                , tier {model.tier}
              </title>
              {tierBreak && index === 0 && (
                <text x="4" y={top + 14} className="chart-tier-label">
                  tier {model.tier}
                </text>
              )}
              {tierBreak && index > 0 && (
                <>
                  <line
                    x1={left}
                    x2={width - right}
                    y1={y - rowHeight / 2}
                    y2={y - rowHeight / 2}
                    className="chart-grid"
                  />
                  <text x="4" y={y - rowHeight / 2 - 4} className="chart-tier-label">
                    tier {model.tier}
                  </text>
                </>
              )}
              <rect x="0" y={y - rowHeight / 2} width={width} height={rowHeight} />
              <text x="4" y={y + 5} className="ranking-model">
                {shortModelName(model.model)}
              </text>
              <text x={left - 12} y={y + 5} textAnchor="end" className="chart-value">
                {fmt(model.mean_score, 1)}
              </text>
              {ci && (
                <>
                  <line
                    x1={x(ci[0])}
                    x2={x(ci[1])}
                    y1={y}
                    y2={y}
                    className="interval-line chart-mark-line"
                  />
                  <line
                    x1={x(ci[0])}
                    x2={x(ci[0])}
                    y1={y - 6}
                    y2={y + 6}
                    className="interval-cap chart-mark-cap"
                  />
                  <line
                    x1={x(ci[1])}
                    x2={x(ci[1])}
                    y1={y - 6}
                    y2={y + 6}
                    className="interval-cap chart-mark-cap"
                  />
                </>
              )}
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

function adverseBin(metric: HeatMetric, value: number): number {
  const thresholds =
    metric === "rate" ? [0.02, 0.08, 0.18, 0.35] : [10, 30, 75, 200];
  const index = thresholds.findIndex((threshold) => value <= threshold);
  return index === -1 ? 5 : index + 1;
}

function MechanicsHeatmap({
  benchmark,
  metric,
  selected,
  onSelect,
}: {
  benchmark: BenchmarkView;
  metric: HeatMetric;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const rates = benchmark.models.flatMap((model) =>
    MECHANICS.map(([key]) => rejectionRate(model, key)),
  );
  const counts = benchmark.models.flatMap((model) =>
    MECHANICS.map(([key]) => model.mechanic_breakdown[key].rejected),
  );
  const maxValue = metric === "rate" ? max(rates) ?? 1 : max(counts) ?? 1;

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
        <div
          className={
            model.id === selected
              ? "heatmap-grid heatmap-row is-selected"
              : "heatmap-grid heatmap-row"
          }
          role="row"
          key={model.id}
        >
          <button type="button" onClick={() => onSelect(model.id)} role="rowheader">
            {shortModelName(model.model)}
          </button>
          {MECHANICS.map(([key, label]) => {
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
                className={`adverse-${adverseBin(metric, value)}`}
                onClick={() => onSelect(model.id)}
                aria-label={`${model.model}, ${label}, ${display} rejected`}
              >
                {display}
              </button>
            );
          })}
        </div>
      ))}
      <div className="heatmap-legend">
        <span>Lower rejection</span>
        <span className="heatmap-ramp" aria-hidden="true">
          {[1, 2, 3, 4, 5].map((bin) => (
            <i key={bin} className={`adverse-${bin}`} />
          ))}
        </span>
        <span>
          Higher rejection (worse) ·{" "}
          {metric === "rate"
            ? `${fmt(maxValue * 100, 1)}% max`
            : `${Math.round(maxValue).toLocaleString("en-US")} max`}
        </span>
      </div>
    </div>
  );
}

export default function Analysis({
  benchmark,
  selectedModelId,
  onSelectModel,
}: {
  benchmark: BenchmarkView;
  selectedModelId: string;
  onSelectModel: (id: string) => void;
}) {
  const [metric, setMetric] = useState<HeatMetric>("rate");
  const selected = useMemo(
    () =>
      benchmark.models.find((model) => model.id === selectedModelId) ??
      benchmark.models[0],
    [benchmark.models, selectedModelId],
  );
  const highestRejection = useMemo(() => {
    if (!selected) return null;
    return MECHANICS.map(([key, label]) => ({
      key,
      label,
      rate: rejectionRate(selected, key),
      rejected: selected.mechanic_breakdown[key].rejected,
    })).sort((a, b) => b.rate - a.rate)[0];
  }, [selected]);

  if (!selected) return null;

  return (
    <section className="analysis-section" id="analysis">
      <div className="results-shell">
        <div className="analysis-heading">
          <div>
            <p className="kicker">Absolute score</p>
            <h2>The gap persists against the strongest scripted policy.</h2>
          </div>
          <p>
            Select a model anywhere on the page to trace its score, cost, and rejected
            actions through the same published record.
          </p>
          <p className="gap-decomposition-note">
            Three cheap explanations for the gap have been measured and ruled out.
            Invalid-action penalties account for 0.5–9.0% of it, so a perfectly legal run
            still trails <code>pick-trader</code> by 174–280 points. The scripted
            references carry no state between decisions — rebuilding them every turn
            reproduces their scores exactly — and memo volume does not buy score: 3 memos
            scored 215.6, 568 scored 217.5. Two limits: the 4,096-token output cap binds
            model rows only and is not controlled for, and the continuity result is
            one-sided — it rules out a reference advantage, not a cost to models denied
            persistent state. So this is not a claim that the residual is decision quality
            alone, nor a claim about reasoning in general.
          </p>
        </div>

        <div className="analysis-evidence">
          <div className="analysis-ranking-panel">
            <div className="analysis-panel-title">
              <h3>Observed scores with reference lines</h3>
              <span>Higher is better · across-seed 95% intervals</span>
            </div>
            <p className="ranking-callout">
              Order is descriptive within each Holm tier, not an ordinal ranking claim; the
              predeclared family test does not reject at 0.05.
            </p>
            <RankingPlot
              benchmark={benchmark}
              selected={selected.id}
              onSelect={onSelectModel}
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
                <dt>Gap to scripted bar</dt>
                <dd>{fmt(benchmark.scriptedBar - selected.mean_score, 1)}</dd>
              </div>
              <div>
                <dt>Cost / episode</dt>
                <dd>${fmt(selected.cost_per_episode_usd, 2)}</dd>
              </div>
              <div>
                <dt>Tokens / decision</dt>
                <dd>{formatTokensPerDecision(selected)}</dd>
              </div>
              <div>
                <dt>Failed queries</dt>
                <dd>
                  {(selected.failed_queries ?? 0).toLocaleString("en-US")} /{" "}
                  {selected.decision_points.toLocaleString("en-US")}
                  {(selected.failed_queries ?? 0) / selected.decision_points >= 0.25 && (
                    <em> high</em>
                  )}
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
              <span className="chart-story-label">Mechanics</span>
              <h3>Rejection patterns by mechanic</h3>
              <p>
                Amber means more actions were rejected. Exact values remain visible in
                every cell.
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
          {highestRejection && (
            <div className="heatmap-insight" aria-live="polite">
              <span>Selected system’s largest rejection rate</span>
              <strong>
                {highestRejection.label} · {fmt(highestRejection.rate * 100, 1)}%
              </strong>
              <span>
                {highestRejection.rejected.toLocaleString("en-US")} rejected actions
              </span>
            </div>
          )}
          <MechanicsHeatmap
            benchmark={benchmark}
            metric={metric}
            selected={selected.id}
            onSelect={onSelectModel}
          />
        </div>
      </div>
    </section>
  );
}
