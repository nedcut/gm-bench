import { useEffect, useRef, useState, type ReactNode } from "react";
import type { GameRequest, GameResponse, GameSave, Snapshot } from "./types";
import {
  PHASES,
  LABEL,
  NEXT,
  NOTE,
  VIEWS,
  money,
  rating,
  ranked,
  type View,
  type Act,
  type Review,
} from "./gameConfig";
import { Confirm } from "./common";
import Roster from "./Roster";
import Market from "./Market";
import Trades from "./Trades";
import { Draft, League, HistoryView, Rules } from "./Views";

const SAVE_KEY = "gm-bench-human-save-v1";

export default function Game() {
  const lastSnapshot = useRef<Snapshot | null>(null);
  const worker = useRef<Worker | null>(null);
  const requestId = useRef(0);
  const busyRef = useRef(false);
  const [s, setSnapshot] = useState<Snapshot | null>(null);
  const [save, setSave] = useState<GameSave | null>(null);
  const [stored, setStored] = useState<string | null>(() => {
    try {
      return localStorage.getItem(SAVE_KEY);
    } catch {
      return null;
    }
  });
  const [seed, setSeed] = useState("1");
  const [view, setView] = useState<View>("Office");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{
    ok: boolean;
    text: string;
    detail: string;
  } | null>(null);
  const [saveStatus, setSaveStatus] = useState("");
  const [confirm, setConfirm] = useState<{
    title: string;
    body: ReactNode;
    run: () => void;
  } | null>(null);
  const [memo, setMemo] = useState("");
  useEffect(() => () => worker.current?.terminate(), []);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 9000);
    return () => clearTimeout(timer);
  }, [notice]);
  function send(request: Omit<GameRequest, "id">) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice(null);
    if (!worker.current) {
      worker.current = new Worker(new URL("./gameWorker.ts", import.meta.url), {
        type: "module",
      });
      worker.current.onmessage = (event: MessageEvent<GameResponse>) => {
        const response = event.data;
        if (response.id !== requestId.current) return;
        busyRef.current = false;
        setBusy(false);
        if (response.error) {
          setError(response.error);
          return;
        }
        if (!response.snapshot || !response.save) {
          setError(
            "The simulator returned an incomplete response. Reload to resume your saved game.",
          );
          return;
        }
        const before = lastSnapshot.current;
        lastSnapshot.current = response.snapshot;
        setSnapshot(response.snapshot);
        setSave(response.save);
        setMemo(response.snapshot.memo);
        const result = response.result;
        if (result) {
          const after = response.snapshot;
          const changes: string[] = [];
          if (result.season_result)
            changes.push(
              `Season result ${result.season_result.wins}–${result.season_result.losses}`,
            );
          if (before) {
            if (before.team.cap_room !== after.team.cap_room)
              changes.push(
                `Cap room ${money(before.team.cap_room)} → ${money(after.team.cap_room)}`,
              );
            if (before.team.roster.length !== after.team.roster.length)
              changes.push(
                `Roster ${before.team.roster.length} → ${after.team.roster.length}`,
              );
            if (before.score.final_score !== after.score.final_score)
              changes.push(
                `Score ${rating(before.score.final_score)} → ${rating(after.score.final_score)}`,
              );
          }
          setNotice({
            ok: result.ok,
            text: `${result.ok ? "" : "Move declined: "}${result.message}${result.penalized ? " This illegal move costs score." : ""}`,
            detail: changes.join(" · "),
          });
        }
        try {
          const text = JSON.stringify(response.save);
          localStorage.setItem(SAVE_KEY, text);
          setStored(text);
          setSaveStatus("Autosaved");
        } catch {
          setSaveStatus(
            "Autosave unavailable. Export your save before leaving.",
          );
        }
      };
      worker.current.onerror = () => {
        busyRef.current = false;
        setBusy(false);
        setError(
          "The simulator worker stopped. Reload this page to resume the last autosave.",
        );
        worker.current?.terminate();
        worker.current = null;
      };
    }
    worker.current.postMessage({ ...request, id: ++requestId.current });
  }
  const act: Act = (tool, args = {}) =>
    send({ command: "act", tool, arguments: args });
  const review: Review = (title, body, tool, args) =>
    setConfirm({ title, body, run: () => act(tool, args) });
  function start() {
    const value = Number(seed);
    if (
      !/^\d+$/.test(seed) ||
      !Number.isSafeInteger(value) ||
      value > 2147483647
    ) {
      setError("Choose a whole-number seed between 0 and 2147483647.");
      return;
    }
    const run = () => {
      setView("Office");
      send({ command: "new", seed: value });
    };
    if (stored || s)
      setConfirm({
        title: "Start a new challenge?",
        body: (
          <p>
            This replaces this browser's autosave. Export your current save
            first if you want to keep it.
          </p>
        ),
        run,
      });
    else run();
  }
  function restore(text: string) {
    try {
      const payload: unknown = JSON.parse(text);
      send({ command: "restore", save: payload });
    } catch {
      setError("That save is not valid JSON. Your current game has been kept.");
    }
  }
  function exportSave() {
    const text = save ? JSON.stringify(save, null, 2) : stored;
    if (!text) return;
    const url = URL.createObjectURL(
      new Blob([text], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `gm-bench-challenge-${save?.seed ?? "save"}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const advance = () => {
    if (!s) return;
    const unspent = s.team.draft_picks[s.season] ?? 0;
    review(
      NEXT[s.phase] + "?",
      <>
        <p>{NOTE[s.phase]}</p>
        <p>
          {s.phase === "preseason"
            ? "Opponents make their moves, then the first portion of games is simulated."
            : s.phase === "draft"
              ? "The rest of the season and playoffs will run. Contracts expire and players develop before your next preseason."
              : "Opponents make their moves and the next decision window opens."}
        </p>
        {s.phase === "draft" && unspent > 0 && (
          <p className="neg">
            You still have {unspent} unused pick(s). Advancing skips them.
          </p>
        )}
        <p>You cannot return to this decision window.</p>
      </>,
      "end_phase",
    );
  };
  // Switching views from deep in a long table lands at the top of the new view.
  const go = (v: View) => {
    setView(v);
    const calendar = document.querySelector(".gm-progress");
    if (calendar)
      window.scrollTo({
        top: Math.min(
          window.scrollY,
          calendar.getBoundingClientRect().bottom + window.scrollY - 56,
        ),
      });
  };
  const rank = s
    ? s.standings.findIndex((t) => t.team_id === s.team.id) + 1
    : 0;
  return (
    <article className="gm-game" aria-busy={busy}>
      <header className={`gm-heading ${s ? "is-compact" : ""}`}>
        <div>
          {!s && <p className="gm-eyebrow">THE HUMAN CHALLENGE</p>}
          <h1>Your call, GM.</h1>
          {!s && <p>Five seasons. One franchise. Every decision is yours.</p>}
        </div>
        <div className="gm-actions">
          {s && <span className="gm-save-status">{saveStatus}</span>}
          <button onClick={exportSave} disabled={busy || (!save && !stored)}>
            Export save
          </button>
          <label className={`gm-file ${busy ? "is-disabled" : ""}`}>
            Import save
            <input
              type="file"
              accept=".json,application/json"
              disabled={busy}
              onChange={async (e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (!file) return;
                if (file.size > 5_000_000) {
                  setError("Save files must be smaller than 5 MB.");
                  return;
                }
                try {
                  const text = await file.text();
                  const run = () => restore(text);
                  if (s)
                    setConfirm({
                      title: "Import this challenge?",
                      body: (
                        <p>
                          A valid import replaces your current autosave. Export
                          your current game first to keep it. Invalid imports
                          leave your game intact.
                        </p>
                      ),
                      run,
                    });
                  else run();
                } catch {
                  setError("This file could not be read.");
                }
              }}
            />
          </label>
        </div>
      </header>
      <div className="gm-toasts">
        {error && (
          <div className="gm-toast gm-error" role="alert">
            <span>{error}</span>
            <button aria-label="Dismiss message" onClick={() => setError("")}>
              ×
            </button>
          </div>
        )}
        <div role="status" aria-live="polite">
          {busy ? (
            <p className="gm-toast">
              <span>
                {s
                  ? "Applying your decision…"
                  : "Loading the real simulator… First launch downloads Python and can take a moment."}
              </span>
            </p>
          ) : notice ? (
            <p className={`gm-toast ${notice.ok ? "is-ok" : "gm-error"}`}>
              <span>
                {notice.ok && "✓ "}
                {notice.text}
                {notice.detail && <small>{notice.detail}</small>}
              </span>
              <button
                aria-label="Dismiss message"
                onClick={() => setNotice(null)}
              >
                ×
              </button>
            </p>
          ) : null}
        </div>
      </div>
      {!s ? (
        <section className="gm-welcome">
          <div>
            <span className="gm-eyebrow">TAKE THE BENCH</span>
            <h2>
              Build a contender.
              <br />
              Leave a better team.
            </h2>
            <p>
              Manage the Anchorage Auroras in a 12-team hockey league. Sign
              players, negotiate trades, scout prospects, set your lineup, and
              see how your decisions hold up over a five-season benchmark
              challenge.
            </p>
            <p>
              Your roster, standings, and cap space stay within reach. The final
              score rewards both winning now and the future you build.
            </p>
            <div className="gm-actions">
              <label>
                League seed
                <input
                  type="number"
                  min="0"
                  max="2147483647"
                  step="1"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value)}
                  disabled={busy}
                />
              </label>
              <button className="gm-primary" disabled={busy} onClick={start}>
                {busy ? "Loading simulator…" : "Start challenge"}
              </button>
              {stored && (
                <button disabled={busy} onClick={() => restore(stored)}>
                  Resume saved challenge
                </button>
              )}
            </div>
            <p className="muted">
              Same seed, same starting league. Runs in your browser with the
              benchmark engine. No model account needed. Autosaves after every
              move.
            </p>
          </div>
          <aside className="gm-welcome-aside">
            <b>20 decision windows</b>
            <span>Preseason → Midseason → Trade deadline → Draft</span>
            <b>Full GM control</b>
            <span>Roster · Contracts · Lineup · Trades · Scouting</span>
            <b>A score to beat</b>
            <span>Wins + playoffs + the team you leave behind</span>
          </aside>
        </section>
      ) : (
        <>
          <section className="gm-scoreboard" aria-label="Your team summary">
            <div>
              <span>YOUR FRANCHISE · SEED {s.seed}</span>
              <h2>{s.team.name}</h2>
              <small>
                Season {s.season} / 5 ·{" "}
                {s.done ? "Challenge complete" : LABEL[s.phase]}
              </small>
            </div>
            <dl>
              <div>
                <dt>Record</dt>
                <dd>
                  {s.team.wins}–{s.team.losses}
                </dd>
              </div>
              <div>
                <dt>Standing</dt>
                <dd>{s.team.wins + s.team.losses ? `${rank} / 12` : "Tied"}</dd>
              </div>
              <div>
                <dt>Cap room</dt>
                <dd className={s.team.cap_room < 0 ? "neg" : "pos"}>
                  {money(s.team.cap_room)}
                </dd>
              </div>
              <div>
                <dt>Payroll / cap</dt>
                <dd>
                  {money(s.team.payroll)}
                  <small> / {money(s.rules.salary_cap)}</small>
                </dd>
              </div>
              <div>
                <dt>{s.done ? "Final score" : "Score so far"}</dt>
                <dd>{rating(s.score.final_score)}</dd>
              </div>
            </dl>
          </section>
          <div className="gm-progress" aria-label="Season calendar">
            {PHASES.map((p, i) => (
              <span
                key={p}
                aria-current={!s.done && s.phase === p ? "step" : undefined}
              >
                {String(i + 1).padStart(2, "0")} · {LABEL[p]}
              </span>
            ))}
          </div>
          {s.done && (
            <section className="gm-finale">
              <p className="gm-eyebrow">FIVE SEASONS IN THE BOOKS</p>
              <h2>Final score: {rating(s.score.final_score)}</h2>
              <p>
                {s.history.reduce((v, h) => v + h.wins, 0)} wins ·{" "}
                {s.team.championships} titles · Strategy{" "}
                {rating(s.score.strategy_score)} − penalties{" "}
                {rating(s.score.protocol_penalty)}
              </p>
              {s.reference && (
                <p>
                  <b>
                    {s.score.final_score >= s.reference.final_score
                      ? "You beat"
                      : "You finished behind"}{" "}
                    {s.reference.name} by{" "}
                    {rating(
                      Math.abs(s.score.final_score - s.reference.final_score),
                    )}{" "}
                    points.
                  </b>{" "}
                  Scripted GM on the same seed and five seasons:{" "}
                  {rating(s.reference.final_score)} points · {s.reference.wins}{" "}
                  wins · {s.reference.championships} titles. One practice seed,
                  not a leaderboard estimate.
                </p>
              )}
              <p>
                Explore your final roster and season history, export the save,
                or try another seed below. Public practice results do not enter
                the model leaderboard.
              </p>
              <button onClick={() => go("History")}>View season history</button>
            </section>
          )}
          <div className="gm-bar">
            <nav className="gm-nav" aria-label="Front office">
              {VIEWS.map((v) => (
                <button
                  key={v}
                  aria-label={v}
                  aria-current={view === v ? "page" : undefined}
                  onClick={() => go(v)}
                >
                  {v}
                  {v === "Trades" && s.incoming_offers.length > 0 && (
                    <span className="gm-badge">{s.incoming_offers.length}</span>
                  )}
                </button>
              ))}
            </nav>
            <div className="gm-bar-status">
              <span>
                {s.team.wins}–{s.team.losses}
              </span>
              <span className={s.team.cap_room < 0 ? "neg" : "pos"}>
                {money(s.team.cap_room)} cap room
              </span>
              <button
                className="gm-primary gm-advance"
                disabled={busy || s.done}
                onClick={advance}
              >
                {s.done ? "Challenge complete" : NEXT[s.phase]} →
              </button>
            </div>
          </div>
          <div className={`gm-layout ${view === "Roster" ? "is-wide" : ""}`}>
            <section className="gm-main" aria-label={view}>
              <fieldset className="gm-controls" disabled={busy}>
                {view === "Office" && (
                  <>
                    <p className="gm-eyebrow">
                      SEASON {s.season} ·{" "}
                      {s.done ? "COMPLETE" : LABEL[s.phase].toUpperCase()}
                    </p>
                    <h2>
                      {s.done
                        ? "Your challenge is complete."
                        : "Welcome to the front office."}
                    </h2>
                    <p>
                      {s.done
                        ? "Review how your team changed across five seasons."
                        : NOTE[s.phase]}
                    </p>
                    <div className="gm-office-grid">
                      {(
                        [
                          [
                            "Roster",
                            "Set the lineup",
                            `${s.team.roster.length} players under contract. Check positions, development, and expiring deals.`,
                          ],
                          [
                            "Free agents",
                            "Find the missing piece",
                            `${s.free_agents.length} free agents. ${money(s.team.cap_room)} of cap room.`,
                          ],
                          [
                            "Trades",
                            "Work the phones",
                            `${s.incoming_offers.length} incoming offers. Build your own deal with any rival.`,
                          ],
                          [
                            "Draft",
                            "Build the future",
                            `${s.rules.scouting.points_remaining} scouting points. ${s.team.draft_picks[s.season] ?? 0} picks this season.`,
                          ],
                        ] as [View, string, string][]
                      ).map(([v, title, text]) => (
                        <button
                          key={v}
                          className="gm-office-card"
                          onClick={() => go(v)}
                        >
                          <b>{title} →</b>
                          <span>{text}</span>
                        </button>
                      ))}
                    </div>
                    <h3>Cap outlook</h3>
                    <p>
                      Current payroll {money(s.team.payroll)} includes{" "}
                      {money(s.team.dead_cap[s.season] ?? 0)} in dead cap. Hard
                      cap: {money(s.rules.salary_cap + s.rules.hard_cap_buffer)}
                      .
                    </p>
                    <h3>Expiring contracts</h3>
                    <p>
                      {s.team.roster
                        .filter((p) => p.contract_years === 1)
                        .map((p) => `${p.name} (${money(p.salary)})`)
                        .join(", ") || "No expiring contracts."}{" "}
                      Extensions are negotiated from Roster during preseason.
                    </p>
                    {s.phase === "midseason" && (
                      <Market s={s} review={review} act={act} waiver />
                    )}
                    <h3>GM notebook</h3>
                    <label className="gm-note-label" htmlFor="gm-notebook">
                      Your plan
                    </label>
                    <textarea
                      id="gm-notebook"
                      maxLength={2000}
                      value={memo}
                      onChange={(e) => setMemo(e.target.value)}
                      disabled={s.done}
                      rows={4}
                    />
                    <button
                      disabled={s.done || memo === s.memo}
                      onClick={() => act("write_memo", { text: memo })}
                    >
                      Save notebook
                    </button>
                  </>
                )}
                {view === "Roster" && (
                  <Roster
                    key={`${s.season}-${s.phase}`}
                    s={s}
                    act={act}
                    review={review}
                  />
                )}
                {view === "Free agents" && (
                  <Market s={s} act={act} review={review} />
                )}
                {view === "Trades" && (
                  <Trades
                    key={`${s.season}-${s.phase}-${s.actions_taken}`}
                    s={s}
                    act={act}
                    review={review}
                  />
                )}
                {view === "Draft" && <Draft s={s} act={act} review={review} />}
                {view === "League" && <League s={s} />}
                {view === "History" && <HistoryView s={s} />}
                {view === "Rules" && <Rules s={s} />}
              </fieldset>
            </section>
            {view !== "Roster" && (
              <aside className="gm-context">
                <details open>
                  <summary>
                    Your roster · {s.team.roster.length} players
                  </summary>
                  <p className="muted">
                    {s.effective_lineup.length} dressed · ✓ scouted potential
                  </p>
                  <div
                    className="gm-context-scroll"
                    tabIndex={0}
                    role="region"
                    aria-label="Your roster ratings and contracts"
                  >
                    <table>
                      <thead>
                        <tr>
                          <th>Player / contract</th>
                          <th>Ovr</th>
                          <th>Pot*</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ranked(s.team.roster).map((p) => (
                          <tr key={p.id}>
                            <th scope="row">
                              <span>
                                {s.effective_lineup.includes(p.id)
                                  ? "● "
                                  : "○ "}
                                {p.name}
                              </span>
                              <small>
                                {p.sub_position ?? p.position} · {p.age} ·{" "}
                                {money(p.salary)} × {p.contract_years}
                              </small>
                            </th>
                            <td>{rating(p.overall)}</td>
                            <td>
                              {rating(s.scout_reports[p.id] ?? p.potential)}
                              {s.scout_reports[p.id] !== undefined ? "✓" : ""}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="muted">
                    ● dressed · ○ bench · *Potential is an estimate
                  </p>
                  <button onClick={() => go("Roster")}>
                    Manage roster & lineup
                  </button>
                </details>
              </aside>
            )}
          </div>
          <section className="gm-new">
            <label>
              New league seed
              <input
                type="number"
                min="0"
                max="2147483647"
                step="1"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                disabled={busy}
              />
            </label>
            <button disabled={busy} onClick={start}>
              New challenge
            </button>
          </section>
        </>
      )}
      {confirm && (
        <Confirm
          title={confirm.title}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            const run = confirm.run;
            setConfirm(null);
            run();
          }}
        >
          {confirm.body}
        </Confirm>
      )}
    </article>
  );
}
