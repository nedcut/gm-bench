import { useState } from "react";
import ModelLogo, { BotLogo } from "./ModelLogo";
import type { Leaderboard } from "../types";
import {
  clearsBar,
  costText,
  laneOf,
  num,
  signed,
  type BotRow,
  type ModelRow,
  type StandingsRow,
} from "../v2";
import Rink from "./Rink";
import SeasonStrip from "./SeasonStrip";
import { type WorkspaceView } from "./Workspace";

function Bar({
  row,
  max,
  bar,
}: {
  row: StandingsRow;
  max: number;
  bar: number;
}) {
  const at = (v: number) => `${Math.max(0, Math.min(100, (v / max) * 100))}%`;
  const ci = row.kind === "model" ? row.ci : null;
  return (
    <span className="meter" aria-hidden="true">
      <i
        className={
          row.kind === "model" ? `vendor-${row.vendor.key}` : undefined
        }
        style={{ width: at(row.score) }}
      />
      {ci && (
        <b
          className="whisker"
          style={{
            left: at(ci[0]),
            width: `calc(${at(ci[1])} - ${at(ci[0])})`,
          }}
        />
      )}
      <s style={{ left: at(bar) }} />
    </span>
  );
}

function vsBar(row: ModelRow) {
  return (
    <>
      <span className={row.lift < 0 ? "neg" : "pos"}>{signed(row.lift)}</span>
      {row.liftCi && (
        <small>
          {" "}
          [{signed(row.liftCi[0], 0)}, {signed(row.liftCi[1], 0)}]
        </small>
      )}
    </>
  );
}

/* The headline counts the current contract's rows (2.1) against its own pick-trader. */
export function StandingsIntro({ data }: { data: Leaderboard }) {
  const { models, bar: pickTrader } = laneOf(data, "2.1");
  const bar = pickTrader ?? 0;
  const clear = models.filter(clearsBar).length;
  const above = models.filter((row) => row.score > bar).length;

  return (
    <section className="intro">
      <Rink />
      <div className="intro-copy">
        <h1>Can an LLM run a hockey team?</h1>
        <p className="intro-answer">
          {clear > 0
            ? `${clear} of ${models.length} models beat${clear === 1 ? "s" : ""} pick-trader by more than the noise.`
            : above > 0
              ? `Not clearly. ${above} of ${models.length} score above pick-trader, within the noise.`
              : "Not yet. No model beats pick-trader."}
        </p>
        <p>
          Each agent runs a franchise for five seasons inside its own harness:
          Claude Code, Codex, Cursor or OpenCode. pick-trader is a short
          scripted GM.
        </p>
      </div>
    </section>
  );
}

type SortKey = "player" | "score" | "lift" | "toolCalls" | "cost";
type Sort = { key: SortKey; desc: boolean };

/* Bots have no lift, tool calls or cost; they sink below every model on those
   columns whichever way the column is sorted. Ties fall back to score. */
function sortValue(row: StandingsRow, key: SortKey): number | string | null {
  if (key === "player") return row.label.toLowerCase();
  if (key === "score") return row.score;
  if (row.kind === "bot") return null;
  if (key === "lift") return row.lift;
  if (key === "toolCalls") return row.toolCalls;
  return row.cost.usd;
}

function sortRows(rows: StandingsRow[], { key, desc }: Sort): StandingsRow[] {
  return [...rows].sort((a, b) => {
    const x = sortValue(a, key);
    const y = sortValue(b, key);
    if (x === null || y === null) return x === y ? b.score - a.score : x === null ? 1 : -1;
    const order = x < y ? -1 : x > y ? 1 : 0;
    return (desc ? -order : order) || b.score - a.score;
  });
}

function SortHeader({
  label,
  column,
  sort,
  setSort,
  className,
}: {
  label: string;
  column: SortKey;
  sort: Sort;
  setSort: (sort: Sort) => void;
  className?: string;
}) {
  const active = sort.key === column;
  return (
    <th
      scope="col"
      className={className}
      aria-sort={active ? (sort.desc ? "descending" : "ascending") : undefined}
    >
      <button
        type="button"
        className={active ? "sort is-sorted" : "sort"}
        onClick={() =>
          setSort(
            active
              ? { key: column, desc: !sort.desc }
              : { key: column, desc: column !== "player" },
          )
        }
      >
        {label}
        <span className="sort-arrow" aria-hidden="true">
          {active ? (sort.desc ? "↓" : "↑") : "↕"}
        </span>
      </button>
    </th>
  );
}

function StandingsTable({
  rows,
  bar,
  selected,
  select,
}: {
  rows: StandingsRow[];
  bar: number;
  selected: string | null;
  select: (id: string) => void;
}) {
  const [sort, setSort] = useState<Sort>({ key: "score", desc: true });
  const header = { sort, setSort };
  const max =
    Math.ceil(
      Math.max(
        bar,
        ...rows.map((r) =>
          r.kind === "model" && r.ci ? r.ci[1] : r.score,
        ),
      ) / 50,
    ) * 50;
  return (
    <div className="card table-card">
      <table className="standings">
        <thead>
          <tr>
            <SortHeader label="Player" column="player" {...header} />
            <th scope="col" className="col-bar">
              <span className="sr-only">Score bar</span>
            </th>
            <SortHeader label="Score" column="score" className="r" {...header} />
            <SortHeader label="vs baseline" column="lift" className="r" {...header} />
            <SortHeader label="Tool calls" column="toolCalls" className="r hide-sm" {...header} />
            <SortHeader label="$ / game" column="cost" className="r hide-sm" {...header} />
          </tr>
        </thead>
        <tbody>
          {sortRows(rows, sort).map((row) => (
            <tr
              key={row.id}
              className={
                row.kind === "bot"
                  ? row.isBar
                    ? "is-bar"
                    : "is-bot"
                  : undefined
              }
              aria-selected={row.id === selected}
              onClick={(event) => {
                event.currentTarget.querySelector("button")?.focus();
                select(row.id);
              }}
            >
              <th scope="row">
                <button
                  type="button"
                  className="row-name"
                  onClick={(e) => {
                    e.stopPropagation();
                    e.currentTarget.focus();
                    select(row.id);
                  }}
                >
                  {row.kind === "model" ? <ModelLogo vendor={row.vendor.key} /> : <BotLogo />}
                  {row.kind === "bot" && row.isBar ? (
                    <span className="name">
                      baseline <span className="sub">{row.label}</span>
                    </span>
                  ) : (
                    <span className="name">{row.label}</span>
                  )}
                  {row.kind === "model" && (
                    <span className="tag">{row.harness}</span>
                  )}
                  {row.kind === "bot" && (
                    <span className="tag">
                      {row.isBar ? "the bar" : "scripted"}
                    </span>
                  )}
                </button>
              </th>
              <td className="col-bar">
                <Bar row={row} max={max} bar={bar} />
              </td>
              <td className="r score">{num(row.score)}</td>
              <td className="r lift">
                {row.kind === "model" ? vsBar(row) : ""}
              </td>
              <td className="r hide-sm calls">
                {row.kind === "model" ? num(row.toolCalls, 0) : ""}
              </td>
              <td className="r hide-sm">
                {row.kind === "model" ? costText(row.cost) : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function standingsRows(models: ModelRow[], bots: BotRow[], showBots: boolean): StandingsRow[] {
  return [...models, ...bots.filter((row) => showBots || row.isBar)];
}

export function StandingsSection({ view }: { view: WorkspaceView }) {
  const { lane, shown, bots, filters, selected, select } = view;
  const archived = lane.contract !== "2.1";
  return (
    <section className="view stats-section" id="standings" tabIndex={-1} aria-labelledby="standings-title">
      <div className="view-head">
        <h2 id="standings-title">{archived ? `GM-Bench ${lane.contract} standings` : "Standings"}</h2>
        <span>
          {lane.seeds ?? "—"} private seeds · bars show 95%
          intervals · red line: pick-trader
        </span>
      </div>
      <StandingsTable rows={standingsRows(shown, bots, filters.showBots)} bar={lane.bar ?? 0} selected={selected} select={select} />
      <p className="view-note">
        Sorted by score unless you pick a column. Each row is compared only with
        pick-trader on the same seeds, never with another row.
      </p>
      {!archived && <SeasonStrip />}
    </section>
  );
}
