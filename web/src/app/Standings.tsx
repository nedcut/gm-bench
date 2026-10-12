import { useEffect, useMemo, useState } from "react";
import type { Leaderboard } from "../types";
import {
  botRows,
  costText,
  modelRows,
  num,
  pickTraderScore,
  seedCount,
  signed,
  useFilters,
  visible,
  type ModelRow,
  type StandingsRow,
} from "../v2";
import Panel from "./Panel";

function Bar({ row, max, bar }: { row: StandingsRow; max: number; bar: number }) {
  const at = (v: number) => `${Math.max(0, Math.min(100, (v / max) * 100))}%`;
  const ci = row.kind === "model" ? row.ci : null;
  return (
    <span className="meter" aria-hidden="true">
      <i className={row.kind === "model" ? `vendor-${row.vendor.key}` : undefined} style={{ width: at(row.score) }} />
      {ci && <b className="whisker" style={{ left: at(ci[0]), width: `calc(${at(ci[1])} - ${at(ci[0])})` }} />}
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
  const models = useMemo(() => modelRows(data), [data]);
  const bots = useMemo(() => botRows(data), [data]);
  const bar = pickTraderScore(data) ?? 0;
  const [filters, setFilters] = useFilters();
  const [selected, setSelected] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const rows: StandingsRow[] = [
    ...models.filter((row) => visible(row, filters)),
    ...bots.filter((row) => filters.showBots || row.isBar),
  ].sort((a, b) => b.score - a.score);
  const max = Math.ceil(Math.max(bar, ...rows.map((r) => (r.kind === "model" && r.ci ? r.ci[1] : r.score))) / 50) * 50;
  const selectedRow = [...models, ...bots].find((row) => row.id === selected) ?? null;
  const beat = models.filter((row) => row.score > bar).length;

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelected(null);
        setSheetOpen(false);
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const select = (id: string) => {
    setSelected((current) => (current === id ? null : id));
    setSheetOpen(true);
  };

  return (
    <>
      <section className="intro">
        <h1>{beat === 0 ? "No model beats pick-trader yet." : `${beat} of ${models.length} models beat pick-trader.`}</h1>
        <p>
          GM-Bench gives an AI agent a hockey team to run for five seasons, through its own coding-agent harness. pick-trader
          is a short scripted policy.
        </p>
      </section>
      <div className="workspace">
        <section className="view" aria-labelledby="standings-title">
          <div className="view-head">
            <h2 id="standings-title">Five-season score</h2>
            <span>
              {seedCount(data) ?? "—"} private seeds · bars show 95% intervals · red line: pick-trader
            </span>
            <button type="button" className="sheet-button" onClick={() => { setSelected(null); setSheetOpen(true); }}>
              Filter
            </button>
          </div>
          <table className="standings">
            <thead>
              <tr>
                <th scope="col">Player</th>
                <th scope="col" className="col-bar"><span className="sr-only">Score bar</span></th>
                <th scope="col" className="r">Score</th>
                <th scope="col" className="r">vs pick-trader</th>
                <th scope="col" className="r hide-sm">Tool calls</th>
                <th scope="col" className="r hide-sm">$ / game</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className={row.kind === "bot" ? (row.isBar ? "is-bar" : "is-bot") : undefined}
                  aria-selected={row.id === selected}
                  onClick={() => select(row.id)}
                >
                  <th scope="row">
                    <button type="button" className="row-name" onClick={(e) => { e.stopPropagation(); select(row.id); }}>
                      <span className={`dot ${row.kind === "model" ? `vendor-${row.vendor.key}` : ""}`} aria-hidden="true" />
                      <span className="name">{row.label}</span>
                      {row.kind === "model" && <span className="tag">{row.harness}</span>}
                      {row.kind === "bot" && <span className="tag">{row.isBar ? "the bar" : "bot"}</span>}
                    </button>
                  </th>
                  <td className="col-bar">
                    <Bar row={row} max={max} bar={bar} />
                  </td>
                  <td className="r score">{num(row.score)}</td>
                  <td className="r lift">{row.kind === "model" ? vsBar(row) : ""}</td>
                  <td className="r hide-sm">{row.kind === "model" ? num(row.toolCalls, 0) : ""}</td>
                  <td className="r hide-sm">{row.kind === "model" ? costText(row.cost) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="view-note">
            Sorted by score for reading. Each row is compared only with pick-trader on the same seeds, never with
            another row.
          </p>
        </section>
        <Panel
          models={models}
          filters={filters}
          onFilters={setFilters}
          row={selectedRow}
          onBack={() => setSelected(null)}
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
        />
      </div>
    </>
  );
}
