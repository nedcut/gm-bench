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
            <th scope="col">Player</th>
            <th scope="col" className="col-bar">
              <span className="sr-only">Score bar</span>
            </th>
            <th scope="col" className="r">
              Score
            </th>
            <th scope="col" className="r">
              vs pick-trader
            </th>
            <th scope="col" className="r hide-sm">
              Tool calls
            </th>
            <th scope="col" className="r hide-sm">
              $ / game
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
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
                  <span
                    className={`dot ${row.kind === "model" ? `vendor-${row.vendor.key}` : ""}`}
                    aria-hidden="true"
                  />
                  <span className="name">{row.label}</span>
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
              <td className="r hide-sm">
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

function sorted(models: ModelRow[], bots: BotRow[], showBots: boolean): StandingsRow[] {
  return [...models, ...bots.filter((row) => showBots || row.isBar)].sort((a, b) => b.score - a.score);
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
      <StandingsTable rows={sorted(shown, bots, filters.showBots)} bar={lane.bar ?? 0} selected={selected} select={select} />
      <p className="view-note">
        Sorted by score for reading. Each row is compared only with
        pick-trader on the same seeds, never with another row.
      </p>
      {!archived && <SeasonStrip />}
    </section>
  );
}
