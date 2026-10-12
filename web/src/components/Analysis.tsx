import { useMemo, useState } from "react";
import { max } from "d3-array";
import {
  MECHANICS,
  rejectionRate,
  shortModelName,
  type BenchmarkView,
} from "../benchmarkData";
import { fmt } from "../lib";

type HeatMetric = "rate" | "count";

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
          Higher rejection,{" "}
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
        <div className="heatmap-section">
          <div className="heatmap-title">
            <div>
              <h2>Where models make illegal moves</h2>
              <p>Share of each model's actions the simulator rejected, by mechanic.</p>
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
              <span>Selected model's highest rejection rate</span>
              <strong>
                {highestRejection.label}, {fmt(highestRejection.rate * 100, 1)}%
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
