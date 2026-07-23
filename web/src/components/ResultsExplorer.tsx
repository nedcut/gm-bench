import { useMemo, useState, type CSSProperties } from "react";
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

function ForestPlot({
  models,
  selected,
  onSelect,
}: {
  models: ResultModel[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const width = 1280;
  const left = 270;
  const right = 42;
  const rowHeight = 48;
  const top = 46;
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
        <title id="forest-title">Paired score-point lift versus the baseline panel</title>
        <desc id="forest-desc">
          Every published model has a negative paired lift and a 95 percent confidence
          interval below zero. Higher values are better.
        </desc>
        <text x={left} y="27" className="chart-axis-note">
          Higher is better →
        </text>

        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={x(tick)}
              x2={x(tick)}
              y1={top - 10}
              y2={height - bottom}
              className={tick === 0 ? "chart-panel-reference" : "chart-grid"}
            />
            <text
              x={x(tick)}
              y={height - 26}
              textAnchor="middle"
              className="chart-tick"
            >
              {tick}
            </text>
          </g>
        ))}

        {models.map((model, index) => {
          const y = top + index * rowHeight + rowHeight / 2;
          const active = model.id === selected;
          return (
            <g
              className={active ? "forest-row is-selected" : "forest-row"}
              key={model.id}
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
                {model.model}: {fmt(model.paired_lift, 1)} score points, 95% CI [
                {fmt(model.ci95[0], 1)}, {fmt(model.ci95[1], 1)}]
              </title>
              <rect
                x="0"
                y={y - rowHeight / 2}
                width={width}
                height={rowHeight}
                className="chart-row-hit"
              />
              <line
                x1="0"
                x2={width}
                y1={y + rowHeight / 2}
                y2={y + rowHeight / 2}
                className="chart-row-rule"
              />
              <text x="18" y={y + 5} className="chart-model-label">
                {model.model}
              </text>
              <line
                x1={x(model.ci95[0])}
                x2={x(model.ci95[1])}
                y1={y}
                y2={y}
                className="interval-line chart-mark-line"
              />
              <line
                x1={x(model.ci95[0])}
                x2={x(model.ci95[0])}
                y1={y - 7}
                y2={y + 7}
                className="interval-cap chart-mark-cap"
              />
              <line
                x1={x(model.ci95[1])}
                x2={x(model.ci95[1])}
                y1={y - 7}
                y2={y + 7}
                className="interval-cap chart-mark-cap"
              />
              <circle
                cx={x(model.paired_lift)}
                cy={y}
                r={active ? 7 : 5.5}
                className="candidate-dot chart-mark-dot"
              />
            </g>
          );
        })}

        <text
          x={x(0)}
          y={height - 8}
          textAnchor="middle"
          className="chart-panel-reference-label"
        >
          baseline panel (0)
        </text>
        <text
          x={(left + width - right) / 2}
          y={height - 8}
          textAnchor="middle"
          className="chart-axis-label"
        >
          Score-point lift vs baseline panel
        </text>
      </svg>
    </div>
  );
}

function CostScatter({
  models,
  scriptedBar,
  oracle,
  selected,
  onSelect,
}: {
  models: ResultModel[];
  scriptedBar: number;
  oracle: number;
  selected: string;
  onSelect: (id: string) => void;
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
  const labels = [...models]
    .map((model) => ({
      id: model.id,
      x: x(model.cost_per_episode_usd),
      pointY: y(model.mean_score),
      labelY: y(model.mean_score) - 10,
    }))
    .sort((a, b) => a.labelY - b.labelY);
  labels.forEach((label, index) => {
    if (index > 0) {
      label.labelY = Math.max(label.labelY, labels[index - 1].labelY + 18);
    }
  });
  const labelById = new Map(labels.map((label) => [label.id, label]));

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
          scripted bar · pick-trader {fmt(scriptedBar, 1)}
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
          const label = labelById.get(model.id);
          const active = model.id === selected;
          const anchorEnd = (label?.x ?? 0) > width - 180;
          return (
            <g
              key={model.id}
              className={active ? "scatter-point is-selected" : "scatter-point"}
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
                {model.model}: score {fmt(model.mean_score, 1)}, $
                {fmt(model.cost_per_episode_usd, 2)} per episode
              </title>
              <circle
                cx={x(model.cost_per_episode_usd)}
                cy={y(model.mean_score)}
                r={active ? 8 : 6}
                className="candidate-dot chart-mark-dot"
              />
              <line
                x1={x(model.cost_per_episode_usd)}
                x2={(label?.x ?? 0) + (anchorEnd ? -7 : 7)}
                y1={y(model.mean_score)}
                y2={(label?.labelY ?? y(model.mean_score) - 10) - 4}
                className="scatter-leader"
              />
              <text
                x={(label?.x ?? 0) + (anchorEnd ? -10 : 10)}
                y={label?.labelY ?? y(model.mean_score) - 10}
                textAnchor={anchorEnd ? "end" : "start"}
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

function ResultsTable({
  models,
  selected,
  onSelect,
}: {
  models: ResultModel[];
  selected: string;
  onSelect: (id: string) => void;
}) {
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
            <tr key={model.id} className={model.id === selected ? "is-selected" : ""}>
              <td className="model-name">
                <button type="button" onClick={() => onSelect(model.id)}>
                  {model.model}
                </button>
              </td>
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
  selectedModelId,
  onSelectModel,
}: {
  data: LeaderboardData;
  benchmark: BenchmarkView;
  selectedModelId: string;
  onSelectModel: (id: string) => void;
}) {
  const [view, setView] = useState<ChartView>("lift");
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState(
    () => new Set(benchmark.models.map((model) => model.id)),
  );

  const filtered = useMemo(() => {
    return benchmark.models.filter((model) => selectedIds.has(model.id));
  }, [benchmark.models, selectedIds]);

  const selectedModel =
    benchmark.models.find((model) => model.id === selectedModelId) ??
    benchmark.models[0];
  const bestModel = benchmark.models[0];
  const panelMean = bestModel?.baseline_panel_mean_score;

  const toggleModel = (id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      if (id === selectedModelId && !next.has(id)) {
        const fallback = benchmark.models.find((model) => next.has(model.id));
        if (fallback) onSelectModel(fallback.id);
      }
      return next;
    });
  };

  return (
    <section className="results-section" id="results">
      <div className="results-shell">
        <div className="result-overview">
          <div className="result-overview-copy">
            <p className="kicker">Phase one results</p>
            <h1>Performance against the baseline panel.</h1>
            <p>
              Paired seed-level differences for eight published model-plus-scaffold
              systems.
            </p>
            <small>
              Descriptive intervals; the predeclared Holm-adjusted family test does
              not reject at 0.05.
            </small>
          </div>
          <dl className="result-readouts">
            <div>
              <dt>Best observed mean</dt>
              <dd>{bestModel ? fmt(bestModel.mean_score, 1) : "—"}</dd>
              <span>{bestModel ? shortModelName(bestModel.model) : "No result"}</span>
            </div>
            <div>
              <dt>Baseline panel mean</dt>
              <dd>{panelMean === null || panelMean === undefined ? "—" : fmt(panelMean, 1)}</dd>
              <span>paired reference</span>
            </div>
            <div>
              <dt>Above scripted bar</dt>
              <dd>
                {benchmark.modelsAboveBar}/{benchmark.modelCount}
              </dd>
              <span>pick-trader · {fmt(benchmark.scriptedBar, 1)}</span>
            </div>
          </dl>
        </div>

        <div className="result-metadata">
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
          <a href="#protocol">Read the protocol</a>
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
          <span className="toolbar-context">API lane · {filtered.length} visible</span>
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
                    onClick={() => {
                      setSelectedIds(new Set(benchmark.models.map((model) => model.id)));
                      if (!selectedModelId && benchmark.models[0]) {
                        onSelectModel(benchmark.models[0].id);
                      }
                    }}
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
              <span className="chart-story-label">
                {view === "lift" ? "Primary comparison" : "Secondary lens"}
              </span>
              <h2>
                {view === "lift"
                  ? "Every paired difference is below the panel reference."
                  : "Score vs cost per episode"}
              </h2>
              <p>
                {view === "lift"
                  ? "Whiskers show 95% intervals. All eight rows overlap in one descriptive tier."
                  : "Price varies widely, but no observed mean reaches the pick-trader bar."}
              </p>
            </div>
            <span>{filtered.length} models</span>
          </div>
          {filtered.length === 0 ? (
            <div className="empty-results">
              <p>No models match the current filters.</p>
              <button
                type="button"
                onClick={() => {
                  setSelectedIds(new Set(benchmark.models.map((model) => model.id)));
                }}
              >
                Reset filters
              </button>
            </div>
          ) : (
            <div className="chart-stage" key={view}>
              {view === "lift" ? (
                <ForestPlot
                  models={filtered}
                  selected={selectedModelId}
                  onSelect={onSelectModel}
                />
              ) : (
                <CostScatter
                  models={filtered}
                  scriptedBar={benchmark.scriptedBar}
                  oracle={benchmark.oracle}
                  selected={selectedModelId}
                  onSelect={onSelectModel}
                />
              )}
            </div>
          )}
          {selectedModel && selectedIds.has(selectedModel.id) && (
            <div className="chart-selection" aria-live="polite">
              <span className="selection-status">Selected</span>
              <strong>{shortModelName(selectedModel.model)}</strong>
              <span>score {fmt(selectedModel.mean_score, 1)}</span>
              <span>paired lift {fmt(selectedModel.paired_lift, 1)}</span>
              <span>
                95% CI [{fmt(selectedModel.ci95[0], 1)},{" "}
                {fmt(selectedModel.ci95[1], 1)}]
              </span>
              <span>${fmt(selectedModel.cost_per_episode_usd, 2)} / episode</span>
              <a href="#analysis">Inspect mechanics ↓</a>
            </div>
          )}
        </div>

        <ResultsTable
          models={filtered}
          selected={selectedModelId}
          onSelect={onSelectModel}
        />
      </div>
    </section>
  );
}
