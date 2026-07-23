import { useMemo, useState } from "react";
import { max } from "d3-array";
import { scaleLinear } from "d3-scale";
import type { BenchmarkView, ResultModel } from "../benchmarkData";
import { issueLabels, shortModelName } from "../benchmarkData";
import type { Leaderboard as LeaderboardData } from "../types";
import { fmt } from "../lib";

type ChartView = "lift" | "cost";
type SortKey = "score" | "lift" | "cost";

function ObservationDisclosure({ model }: { model: ResultModel }) {
  const issues = model.sota_v2_issues ?? [];
  const labels = issueLabels(model);
  return (
    <details className="observations">
      <summary>
        {issues.length} observation{issues.length === 1 ? "" : "s"}
      </summary>
      <div className="observation-popover">
        <div className="observation-labels">
          {labels.map((label, index) => (
            <span key={`${label}-${index}`}>{label}</span>
          ))}
        </div>
        <ul>
          {issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      </div>
    </details>
  );
}

function ForestPlot({ models }: { models: ResultModel[] }) {
  const width = 1280;
  const left = 300;
  const right = 196;
  const rowHeight = 48;
  const top = 54;
  const bottom = 58;
  const height = top + models.length * rowHeight + bottom;
  const ciValues = models.flatMap((model) => model.ci95);
  const minLift = Math.min(-20, Math.floor((Math.min(...ciValues) - 8) / 20) * 20);
  const x = scaleLinear().domain([minLift, 20]).range([left, width - right]);
  const ticks = x.ticks(8);

  return (
    <div className="chart-scroll">
      <svg
        className="result-chart forest-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-labelledby="forest-title forest-desc"
      >
        <title id="forest-title">Paired score-point lift versus the scripted panel</title>
        <desc id="forest-desc">
          Every published model has a negative paired lift and a 95 percent confidence
          interval below zero. Higher values are better.
        </desc>
        <text x="18" y="33" className="chart-tier-label">
          TIER 1
        </text>
        <text x={left} y="27" className="chart-axis-note">
          Higher is better →
        </text>
        <text x={width - 155} y="27" textAnchor="middle" className="chart-column-head">
          Lift
        </text>
        <text x={width - 60} y="27" textAnchor="middle" className="chart-column-head">
          95% CI
        </text>

        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={x(tick)}
              x2={x(tick)}
              y1={top - 10}
              y2={height - bottom}
              className={tick === 0 ? "chart-reference" : "chart-grid"}
            />
            <text
              x={x(tick)}
              y={height - 26}
              textAnchor="middle"
              className={tick === 0 ? "chart-tick chart-tick-bar" : "chart-tick"}
            >
              {tick}
            </text>
          </g>
        ))}

        {models.map((model, index) => {
          const y = top + index * rowHeight + rowHeight / 2;
          return (
            <g className="forest-row" key={model.id} tabIndex={0}>
              <title>
                {model.model}: {fmt(model.paired_lift, 1)} score points, 95% CI [
                {fmt(model.ci95[0], 1)}, {fmt(model.ci95[1], 1)}]
              </title>
              <line
                x1="0"
                x2={width}
                y1={y + rowHeight / 2}
                y2={y + rowHeight / 2}
                className="chart-row-rule"
              />
              <text x="18" y={y + 5} className="chart-tier-dot">
                {index === 0 ? "Tier 1" : "·"}
              </text>
              <text x="116" y={y + 5} className="chart-model-label">
                {model.model}
              </text>
              <line
                x1={x(model.ci95[0])}
                x2={x(model.ci95[1])}
                y1={y}
                y2={y}
                className="interval-line"
              />
              <line
                x1={x(model.ci95[0])}
                x2={x(model.ci95[0])}
                y1={y - 7}
                y2={y + 7}
                className="interval-cap"
              />
              <line
                x1={x(model.ci95[1])}
                x2={x(model.ci95[1])}
                y1={y - 7}
                y2={y + 7}
                className="interval-cap"
              />
              <circle cx={x(model.paired_lift)} cy={y} r="5.5" className="candidate-dot" />
              <text x={width - 155} y={y + 5} textAnchor="middle" className="chart-value">
                {fmt(model.paired_lift, 1)}
              </text>
              <text x={width - 60} y={y + 5} textAnchor="middle" className="chart-ci">
                [{fmt(model.ci95[0], 1)}, {fmt(model.ci95[1], 1)}]
              </text>
            </g>
          );
        })}

        <text
          x={x(0)}
          y={height - 8}
          textAnchor="middle"
          className="chart-reference-label"
        >
          scripted panel (0)
        </text>
        <text
          x={(left + width - right) / 2}
          y={height - 8}
          textAnchor="middle"
          className="chart-axis-label"
        >
          Score-point lift vs scripted panel
        </text>
      </svg>
    </div>
  );
}

function CostScatter({
  models,
  scriptedBar,
  oracle,
}: {
  models: ResultModel[];
  scriptedBar: number;
  oracle: number;
}) {
  const width = 1280;
  const height = 480;
  const left = 88;
  const right = 42;
  const top = 34;
  const bottom = 64;
  const maxCost = max(models, (model) => model.cost_per_episode_usd) ?? 0.5;
  const x = scaleLinear()
    .domain([0, Math.max(0.5, maxCost * 1.08)])
    .nice()
    .range([left, width - right]);
  const y = scaleLinear()
    .domain([0, Math.max(450, oracle * 1.04)])
    .nice()
    .range([height - bottom, top]);
  const xTicks = x.ticks(6);
  const yTicks = y.ticks(6);

  return (
    <div className="chart-scroll">
      <svg
        className="result-chart scatter-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-labelledby="scatter-title scatter-desc"
      >
        <title id="scatter-title">GM-Bench score versus cost per episode</title>
        <desc id="scatter-desc">
          All model scores fall well below the scripted bar. Models farther up and left are
          more efficient.
        </desc>
        <text x={left} y="22" className="chart-axis-note">
          More efficient ↖
        </text>
        {xTicks.map((tick) => (
          <g key={`x-${tick}`}>
            <line
              x1={x(tick)}
              x2={x(tick)}
              y1={top}
              y2={height - bottom}
              className="chart-grid"
            />
            <text x={x(tick)} y={height - 36} textAnchor="middle" className="chart-tick">
              ${tick.toFixed(2)}
            </text>
          </g>
        ))}
        {yTicks.map((tick) => (
          <g key={`y-${tick}`}>
            <line
              x1={left}
              x2={width - right}
              y1={y(tick)}
              y2={y(tick)}
              className="chart-grid"
            />
            <text x={left - 14} y={y(tick) + 4} textAnchor="end" className="chart-tick">
              {tick}
            </text>
          </g>
        ))}
        <line
          x1={left}
          x2={width - right}
          y1={y(scriptedBar)}
          y2={y(scriptedBar)}
          className="chart-reference"
        />
        <text
          x={width - right}
          y={y(scriptedBar) - 9}
          textAnchor="end"
          className="chart-reference-label"
        >
          pick-trader · scripted bar {fmt(scriptedBar, 1)}
        </text>
        <line
          x1={left}
          x2={width - right}
          y1={y(oracle)}
          y2={y(oracle)}
          className="chart-oracle"
        />
        <text
          x={width - right}
          y={y(oracle) - 9}
          textAnchor="end"
          className="chart-oracle-label"
        >
          oracle ceiling {fmt(oracle, 1)}
        </text>
        {models.map((model, index) => {
          const labelAbove = index % 2 === 0;
          return (
            <g key={model.id} className="scatter-point" tabIndex={0}>
              <title>
                {model.model}: score {fmt(model.mean_score, 1)}, $
                {fmt(model.cost_per_episode_usd, 2)} per episode
              </title>
              <circle
                cx={x(model.cost_per_episode_usd)}
                cy={y(model.mean_score)}
                r={6}
                className="candidate-dot"
              />
              <text
                x={x(model.cost_per_episode_usd) + 9}
                y={y(model.mean_score) + (labelAbove ? -9 : 18)}
                className="scatter-label"
              >
                {shortModelName(model.model)}
              </text>
            </g>
          );
        })}
        <text
          x={(left + width - right) / 2}
          y={height - 8}
          textAnchor="middle"
          className="chart-axis-label"
        >
          Cost per episode (USD)
        </text>
        <text
          x="20"
          y={(top + height - bottom) / 2}
          textAnchor="middle"
          transform={`rotate(-90 20 ${(top + height - bottom) / 2})`}
          className="chart-axis-label"
        >
          Mean GM-Bench score
        </text>
      </svg>
    </div>
  );
}

function ResultsTable({ models }: { models: ResultModel[] }) {
  const [sort, setSort] = useState<SortKey>("score");
  const sorted = useMemo(() => {
    const next = [...models];
    if (sort === "score") next.sort((a, b) => b.mean_score - a.mean_score);
    if (sort === "lift") next.sort((a, b) => b.paired_lift - a.paired_lift);
    if (sort === "cost") next.sort((a, b) => a.cost_per_episode_usd - b.cost_per_episode_usd);
    return next;
  }, [models, sort]);

  return (
    <div className="results-table-wrap" role="region" aria-label="API lane results table" tabIndex={0}>
      <table className="results-table">
        <thead>
          <tr>
            <th>Tier</th>
            <th>Model</th>
            <th>
              <button type="button" onClick={() => setSort("score")} aria-pressed={sort === "score"}>
                Score
              </button>
            </th>
            <th>
              <button type="button" onClick={() => setSort("lift")} aria-pressed={sort === "lift"}>
                Lift
              </button>
            </th>
            <th>95% CI</th>
            <th>
              <button type="button" onClick={() => setSort("cost")} aria-pressed={sort === "cost"}>
                Cost / episode
              </button>
            </th>
            <th>Protocol observations</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((model) => (
            <tr key={model.id}>
              <td>
                <span className="tier-label">Tier {model.tier}</span>
              </td>
              <td className="model-name">{model.model}</td>
              <td className="numeric strong">{fmt(model.mean_score, 1)}</td>
              <td className="numeric">{fmt(model.paired_lift, 1)}</td>
              <td className="numeric ci-cell">
                [{fmt(model.ci95[0], 1)}, {fmt(model.ci95[1], 1)}]
              </td>
              <td className="numeric">${fmt(model.cost_per_episode_usd, 2)}</td>
              <td>
                <ObservationDisclosure model={model} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ResultsExplorer({
  data,
  benchmark,
}: {
  data: LeaderboardData;
  benchmark: BenchmarkView;
}) {
  const [view, setView] = useState<ChartView>("lift");
  const [query, setQuery] = useState("");
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState(
    () => new Set(benchmark.models.map((model) => model.id)),
  );

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return benchmark.models.filter(
      (model) =>
        selectedIds.has(model.id) &&
        (normalized === "" ||
          model.model.toLowerCase().includes(normalized) ||
          model.provider.toLowerCase().includes(normalized)),
    );
  }, [benchmark.models, query, selectedIds]);

  const toggleModel = (id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <section className="results-section" id="results">
      <div className="results-shell">
        <div className="result-summary">
          <p>
            <strong>{benchmark.modelsAboveBar}</strong> of {benchmark.modelCount} model-plus-scaffold
            systems exceeded the scripted bar’s observed mean.
          </p>
          <dl>
            <div>
              <dt>Seeds</dt>
              <dd>{data.preset.seeds.length}</dd>
            </div>
            <div>
              <dt>Seasons</dt>
              <dd>{data.preset.seasons}</dd>
            </div>
            <div>
              <dt>Repeats</dt>
              <dd>{benchmark.repeats}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{data.updated}</dd>
            </div>
          </dl>
          <a href="#protocol">Methodology</a>
        </div>

        <div className="result-toolbar" aria-label="Results controls">
          <div className="segmented" aria-label="Chart view">
            <button
              type="button"
              className={view === "lift" ? "is-active" : ""}
              onClick={() => setView("lift")}
              aria-pressed={view === "lift"}
            >
              Paired lift
            </button>
            <button
              type="button"
              className={view === "cost" ? "is-active" : ""}
              onClick={() => setView("cost")}
              aria-pressed={view === "cost"}
            >
              Score vs cost
            </button>
          </div>
          <div className="segmented lane-switch" aria-label="Evaluation lane">
            <button type="button" className="is-active" aria-pressed="true">
              API lane
            </button>
            <button type="button" disabled title="No published coding-harness rows">
              Coding harness ({data.cli_harness_models.length})
            </button>
          </div>
          <label className="model-filter">
            <span className="sr-only">Filter models</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter models…"
            />
          </label>
          <div className="model-picker">
            <button
              type="button"
              className="picker-button"
              onClick={() => setModelMenuOpen((open) => !open)}
              aria-expanded={modelMenuOpen}
            >
              Models ({selectedIds.size}/{benchmark.modelCount})
            </button>
            {modelMenuOpen && (
              <div className="picker-menu">
                <div className="picker-menu-actions">
                  <button
                    type="button"
                    onClick={() =>
                      setSelectedIds(new Set(benchmark.models.map((model) => model.id)))
                    }
                  >
                    Select all
                  </button>
                  <button type="button" onClick={() => setSelectedIds(new Set())}>
                    Clear
                  </button>
                </div>
                {benchmark.models.map((model) => (
                  <label key={model.id}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(model.id)}
                      onChange={() => toggleModel(model.id)}
                    />
                    <span>{shortModelName(model.model)}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="chart-panel">
          <div className="chart-panel-head">
            <div>
              <h1>
                {view === "lift"
                  ? "Paired lift vs scripted panel"
                  : "Score vs cost per episode"}
              </h1>
              <p>
                {view === "lift"
                  ? "Paired per-seed score-point difference. All eight rows overlap in one descriptive tier."
                  : "An alternate efficiency lens; price is measured, not normalized into the score."}
              </p>
            </div>
            <span>{filtered.length} visible models</span>
          </div>
          {filtered.length === 0 ? (
            <div className="empty-results">
              <p>No models match the current filters.</p>
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  setSelectedIds(new Set(benchmark.models.map((model) => model.id)));
                }}
              >
                Reset filters
              </button>
            </div>
          ) : view === "lift" ? (
            <ForestPlot models={filtered} />
          ) : (
            <CostScatter
              models={filtered}
              scriptedBar={benchmark.scriptedBar}
              oracle={benchmark.oracle}
            />
          )}
        </div>

        <ResultsTable models={filtered} />
        <p className="result-caveat">
          These are observed means and descriptive intervals, not an ordinal #1 ranking. The
          predeclared Holm-adjusted family result does not reject at 0.05.
        </p>
      </div>
    </section>
  );
}
