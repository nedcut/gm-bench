import type { Leaderboard } from "../types";
import {
  clearsBar,
  costText,
  modelRows,
  num,
  pickTraderScore,
  seedCount,
  signed,
  type ModelRow,
  type StandingsRow,
} from "../v2";
import Rink from "./Rink";
import SeasonStrip from "./SeasonStrip";
import Workspace from "./Workspace";

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

export default function Standings({ data }: { data: Leaderboard }) {
  const bar = pickTraderScore(data) ?? 0;
  const models = modelRows(data);
  const clear = models.filter(clearsBar).length;
  const above = models.filter((row) => row.score > bar).length;

  return (
    <>
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
      <Workspace data={data} hint="Click a row for its details.">
        {({ shown, bots, filters, selected, select, filterButton }) => {
          const rows: StandingsRow[] = [
            ...shown,
            ...bots.filter((row) => filters.showBots || row.isBar),
          ].sort((a, b) => b.score - a.score);
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
            <section className="view" aria-labelledby="standings-title">
              <div className="view-head">
                <h2 id="standings-title">Standings</h2>
                <span>
                  {seedCount(data) ?? "—"} private seeds · bars show 95%
                  intervals · red line: pick-trader
                </span>
                {filterButton}
              </div>
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
              <p className="view-note">
                Sorted by score for reading. Each row is compared only with
                pick-trader on the same seeds, never with another row.
              </p>
              <SeasonStrip />
            </section>
          );
        }}
      </Workspace>
    </>
  );
}
