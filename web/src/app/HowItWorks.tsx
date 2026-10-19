import { useEffect, useState, type ReactNode } from "react";
import type { Leaderboard } from "../types";
import { routes } from "../site";
import { num, pickTraderScoreV1 } from "../v2";
import walkthroughData from "../data/walkthrough.json";
import RinkSidebar from "./RinkSidebar";

/* Built by scripts/build_walkthrough.py from season 1 of the public pick-trader
   demo game (web/public/replay/trajectory-demo.json). */

interface Card {
  id: number;
  name: string;
  position: string;
  age: number;
  overall: number;
  potential: number;
  salary: number;
  contract_years: number;
}

interface Offer {
  id: string;
  team: string;
  you_give: Card[];
  you_give_picks: number[];
  you_get: Card[];
  you_get_picks: number[];
}

interface Move {
  tool: string;
  arguments: Record<string, unknown>;
  accepted: boolean;
  message: string;
  player?: Card;
  partner?: string;
  give?: Card[];
  get?: Card[];
  dressed?: number;
}

interface Step {
  phase: "preseason" | "midseason" | "trade_deadline" | "draft";
  note: string;
  situation: { wins: number; losses: number; rank: number; cap_room: number; payroll: number; roster_size: number; picks: number };
  context: {
    expiring?: (Card & { extension_quotes: Record<string, number> })[];
    free_agents?: (Card & { asking_salary: number })[];
    free_agent_count?: number;
    waiver_wire?: Card[];
    offers?: Offer[];
    trade_market_count?: number;
    prospects?: Card[];
    prospect_count?: number;
  };
  queries: { tool: string; arguments: Record<string, unknown> }[];
  scouted: (Card & { scouted_potential: number })[];
  moves: Move[];
  delta: Record<string, number>;
}

interface Walkthrough {
  source: { seed: number; seed_scope: string; agent: string };
  team: { id: number; name: string; teams: number };
  brief: string;
  tools: { name: string; kind: string; summary: string; only: string | null }[];
  steps: Step[];
  seasons: { season: number; wins: number; losses: number; playoff_rounds: number; champion: string; score_after_season: number }[];
  final_score: number;
}

const walkthrough = walkthroughData as Walkthrough;

const PHASE_LABEL: Record<Step["phase"], string> = {
  preseason: "Preseason",
  midseason: "Midseason",
  trade_deadline: "Trade deadline",
  draft: "Draft",
};

const money = (value: number) => `$${num(value, 2)}M`;

/* Why pick-trader did what it did, from its policy in gm_bench/agents.py
   (PickTraderAgent and the StrategicAgent and ShrewdAgent it extends). */
const WHY: Record<Step["phase"], (step: Step) => string> = {
  preseason: () =>
    "Pick-trader saves a one-line plan to its memo, then extends up to two expiring players aged 27 or under who rate as real assets, at the quoted price. Next it walks the best-value free agents and signs every one it can afford: three years for players 27 and under, one year for older ones. Last, it dresses 18 players by rating, with a bump for young players who still have room to grow.",
  midseason: (step) =>
    `Midseason it would sign free agents on a looser bar, but ${money(step.situation.cap_room)} of cap room buys nobody worth it. It re-dresses the lineup strictly by current rating, since the rest of the season rewards form over development.`,
  trade_deadline: () =>
    "It values each incoming offer from public ratings and accepts the best one only if it gets at least 8% more than it gives. None clear that bar, so it declines all three. Then comes the move it is named for: it sells its least valuable veteran (28 or older, two years or less left) for next season's draft pick.",
  draft: () =>
    "It spends its three scouting points on the three prospects with the highest public value, then drafts the best one using the scouted potential where it has a report. Scouting can reorder the board: the highest scouted potential does not win if a prospect is further from playing.",
};

const DELTA_LABEL: Record<string, string> = {
  total_assets_contribution: "Roster assets",
  young_assets_contribution: "Young assets",
  future_pick_assets_contribution: "Future picks",
  cap_room_contribution: "Cap room",
  current_strength_contribution: "Lineup strength",
  roster_depth_contribution: "Roster depth",
};

const STEP_IDS = ["brief", "preseason", "midseason", "trade-deadline", "draft", "recap"] as const;
const STEP_TITLES = ["The brief", "Preseason", "Midseason", "Trade deadline", "Draft", "The rest of the game"];

const ordinal = (n: number) => `${n}${n % 10 === 1 && n !== 11 ? "st" : n % 10 === 2 && n !== 12 ? "nd" : n % 10 === 3 && n !== 13 ? "rd" : "th"}`;
const signed = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${num(Math.abs(value), 1)}`;
const call = (tool: string, args: Record<string, unknown>) => `${tool}(${JSON.stringify(args)})`;

function Player({ card, potential }: { card: Card; potential?: number }) {
  return (
    <span className="how-player">
      <b>{card.name}</b>
      <span className="muted">
        {card.position} · {card.age} · {num(card.overall)} ovr · {num(potential ?? card.potential)} pot
      </span>
    </span>
  );
}

function Players({ cards }: { cards: Card[] }) {
  return (
    <>
      {cards.map((card) => (
        <Player key={card.id} card={card} />
      ))}
    </>
  );
}

function moveText(move: Move, step: Step): ReactNode {
  const p = move.player;
  const years = Number(move.arguments.years);
  switch (move.tool) {
    case "write_memo":
      return <>Saved a memo: “{String(move.arguments.text)}”</>;
    case "extend_contract":
      return (
        <>
          Extended <Player card={p!} /> for {years} years at {money(Number(move.arguments.salary))} a year
        </>
      );
    case "sign_free_agent":
      return (
        <>
          Signed <Player card={p!} /> for {years} year{years === 1 ? "" : "s"} at {money(Number(move.arguments.salary))}
        </>
      );
    case "set_lineup":
      return <>Set the lineup: {move.dressed} players dress</>;
    case "accept_trade_offer":
    case "reject_trade_offer": {
      const offer = step.context.offers?.find((o) => o.id === move.arguments.offer_id);
      return (
        <>
          {move.tool === "accept_trade_offer" ? "Accepted" : "Declined"} {offer?.team ?? "an"}’s offer
        </>
      );
    }
    case "trade": {
      const picks = (move.arguments.receive_pick_seasons as number[]) ?? [];
      return (
        <>
          Traded {(move.give ?? []).map((card) => <Player key={card.id} card={card} />)} to {move.partner} for their season-{picks.join(", ")} draft pick
        </>
      );
    }
    case "draft":
      return (
        <>
          Drafted <Player card={p!} />
        </>
      );
    default:
      return <code>{call(move.tool, move.arguments)}</code>;
  }
}

function Situation({ step }: { step: Step }) {
  const s = step.situation;
  const played = s.wins + s.losses > 0;
  const stats: [string, string][] = [
    ["Record", played ? `${s.wins}–${s.losses}` : "0–0"],
    ["Standing", played ? `${ordinal(s.rank)} of ${walkthrough.team.teams}` : "—"],
    ["Cap room", money(s.cap_room)],
    ["Payroll", money(s.payroll)],
    ["Roster", `${s.roster_size} players`],
    ["Draft picks held", String(s.picks)],
  ];
  return (
    <dl className="how-situation">
      {stats.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PlayerTable({ cards, extra }: { cards: Card[]; extra?: [string, (card: Card) => string] }) {
  return (
    <table className="data-table how-table">
      <thead>
        <tr>
          <th>Player</th>
          <th>Pos</th>
          <th className="r">Age</th>
          <th className="r">Ovr</th>
          <th className="r">Pot</th>
          {extra && <th className="r">{extra[0]}</th>}
        </tr>
      </thead>
      <tbody>
        {cards.map((card) => (
          <tr key={card.id}>
            <th scope="row">{card.name}</th>
            <td>{card.position}</td>
            <td className="r">{card.age}</td>
            <td className="r">{num(card.overall)}</td>
            <td className="r">{num(card.potential)}</td>
            {extra && <td className="r">{extra[1](card)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OnTheTable({ step }: { step: Step }) {
  const c = step.context;
  switch (step.phase) {
    case "preseason":
      return (
        <>
          <p>{c.expiring!.length} of the team’s players are in the last year of their contract. Each can be extended now, at a quoted salary:</p>
          <PlayerTable
            cards={c.expiring!}
            extra={[
              "Now / 3 yr / 4 yr",
              (card) => {
                const quotes = (card as Card & { extension_quotes: Record<string, number> }).extension_quotes;
                return `${money(card.salary)} / ${money(quotes["3"])} / ${money(quotes["4"])}`;
              },
            ]}
          />
          <p>{c.free_agent_count} free agents are on the market. The best by rating:</p>
          <PlayerTable cards={c.free_agents!} extra={["Asks", (card) => money((card as Card & { asking_salary: number }).asking_salary)]} />
        </>
      );
    case "midseason":
      return (
        <>
          <p>A third of the season is played. Opponents have waived {c.waiver_wire!.length} players, who can be claimed:</p>
          <PlayerTable cards={c.waiver_wire!} extra={["Salary", (card) => money(card.salary)]} />
        </>
      );
    case "trade_deadline":
      return (
        <>
          <p>
            {c.offers!.length} rival GMs have sent offers, and {c.trade_market_count} players are on the trade market.
          </p>
          <ul className="how-offers">
            {c.offers!.map((offer) => (
              <li key={offer.id}>
                <b>{offer.team}</b>
                <span>
                  <span className="muted">You give</span> <Players cards={offer.you_give} />
                  {offer.you_give_picks.length > 0 && ` + season-${offer.you_give_picks.join(", ")} pick`}
                </span>
                <span>
                  <span className="muted">You get</span> <Players cards={offer.you_get} />
                  {offer.you_get_picks.length > 0 && ` + season-${offer.you_get_picks.join(", ")} pick`}
                </span>
              </li>
            ))}
          </ul>
        </>
      );
    case "draft":
      return (
        <>
          <p>
            It is the team’s turn to pick, from {c.prospect_count} prospects. Ratings are public estimates; true potential is hidden unless
            scouted. The top prospects by current rating:
          </p>
          <PlayerTable cards={c.prospects!} />
          {step.scouted.length > 0 && (
            <>
              <p>Three scouting reports, one point each:</p>
              <PlayerTable
                cards={step.scouted}
                extra={["Scouted pot", (card) => num((card as Card & { scouted_potential: number }).scouted_potential)]}
              />
            </>
          )}
        </>
      );
  }
}

function Tools({ step }: { step: Step }) {
  const used = new Set([...step.moves, ...step.queries].map((m) => m.tool));
  const groups: [string, string[]][] = [
    ["Read", ["read", "query"]],
    ["Move", ["move"]],
    ["Advance", ["control"]],
  ];
  return (
    <div className="how-tools">
      {groups.map(([label, kinds]) => (
        <div key={label}>
          <span className="how-tools-label">{label}</span>
          <ul>
            {walkthrough.tools
              .filter((tool) => kinds.includes(tool.kind))
              .map((tool) => {
                const closed = tool.only !== null && tool.only !== step.phase;
                return (
                  <li
                    key={tool.name}
                    className={`${closed ? "is-closed" : ""}${used.has(tool.name) ? " is-used" : ""}`}
                    title={closed ? `${tool.summary} Not open in this phase.` : tool.summary}
                  >
                    {tool.name}
                  </li>
                );
              })}
          </ul>
        </div>
      ))}
    </div>
  );
}

function Delta({ step }: { step: Step }) {
  const rows = Object.entries(step.delta)
    .filter(([, value]) => Math.abs(value) >= 0.05)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const total = rows.reduce((sum, [, value]) => sum + value, 0);
  const max = Math.max(...rows.map(([, value]) => Math.abs(value)), 1);
  if (rows.length === 0) return <p>No change to the asset terms of the score.</p>;
  return (
    <div className="how-delta">
      {rows.map(([key, value]) => (
        <div key={key} className="how-delta-row">
          <span>{DELTA_LABEL[key] ?? key}</span>
          <span className="how-delta-track">
            <i className={value < 0 ? "is-neg" : undefined} style={{ width: `${(Math.abs(value) / max) * 50}%` }} />
          </span>
          <b className={value < 0 ? "neg" : "pos"}>{signed(value)}</b>
        </div>
      ))}
      <div className="how-delta-row is-total">
        <span>Net</span>
        <span />
        <b className={total < 0 ? "neg" : "pos"}>{signed(total)}</b>
      </div>
    </div>
  );
}

function PhaseStep({ step }: { step: Step }) {
  const calls = [...step.queries, ...step.moves];
  return (
    <>
      <section className="how-block">
        <h3>What the GM is told</h3>
        <p className="how-note">
          <span className="muted">From the brief:</span> {step.note}.
        </p>
        <Situation step={step} />
      </section>
      <section className="how-block">
        <h3>What’s on the table</h3>
        <OnTheTable step={step} />
      </section>
      <section className="how-block">
        <h3>Tools open this phase</h3>
        <p className="how-hint">
          Highlighted: the ones pick-trader’s moves map to. Faded: open in another phase only. A model also calls read tools like{" "}
          <code>get_status</code> and <code>get_team</code>; pick-trader reads the same state directly.
        </p>
        <Tools step={step} />
      </section>
      <section className="how-block">
        <h3>What pick-trader did</h3>
        <ol className="how-moves">
          {step.queries.map((query, i) => {
            const scouted = step.scouted.find((s) => s.id === query.arguments.player_id);
            return (
              <li key={`q${i}`}>
                {scouted ? (
                  <>
                    Scouted <b>{scouted.name}</b>: potential {num(scouted.potential)} public, {num(scouted.scouted_potential)} scouted
                  </>
                ) : (
                  <code>{call(query.tool, query.arguments)}</code>
                )}
              </li>
            );
          })}
          {step.moves.map((move, i) => (
            <li key={`m${i}`} className={move.accepted ? undefined : "is-rejected"}>
              {moveText(move, step)}
            </li>
          ))}
        </ol>
        <p className="how-why">{WHY[step.phase](step)}</p>
        <details className="how-raw">
          <summary>The {calls.length + 1} tool calls a model would make for these moves</summary>
          <pre className="code-block">
            <code>
              {calls
                .map((c) => `${call(c.tool, c.arguments)}${"message" in c ? `\n  → ${(c as Move).message}` : ""}`)
                .concat("end_phase({})")
                .join("\n")}
            </code>
          </pre>
        </details>
      </section>
      <section className="how-block">
        <h3>How the score moved</h3>
        <p className="how-hint">
          The asset terms of the score, measured as if the game ended right after this phase. Wins and playoff rounds count as the games are
          played.
        </p>
        <Delta step={step} />
      </section>
    </>
  );
}

function BriefStep() {
  const tools = walkthrough.tools;
  return (
    <>
      <section className="how-block">
        <h3>The setup</h3>
        <p>
          A model is put in charge of the {walkthrough.team.name}, one of {walkthrough.team.teams} teams in a fictional hockey league, for five
          seasons. It plays inside its own agent harness (Claude Code, Codex, Cursor or OpenCode) and touches the league only through{" "}
          {tools.length} tools on an MCP server. Each season has four decisions. In each one the model reads what it needs, makes moves, then
          calls <code>end_phase</code>; that is the only way time moves.
        </p>
        <p>
          This walkthrough follows one real season. The GM here is pick-trader, the scripted bot every model is measured against, playing
          public seed {walkthrough.source.seed}. It sees the same league a model does and makes the same moves, so it shows what a good
          season of decisions looks like.
        </p>
      </section>
      <section className="how-block">
        <h3>The brief, word for word</h3>
        <p className="how-hint">The first thing a model reads. It has the rules and the scoring, but no rosters or prices: those are behind tools.</p>
        <pre className="code-block how-brief" tabIndex={0} aria-label="The task brief">
          <code>{walkthrough.brief}</code>
        </pre>
      </section>
      <section className="how-block">
        <h3>The tools</h3>
        <ul className="how-tool-list">
          {tools.map((tool) => (
            <li key={tool.name}>
              <code>{tool.name}</code>
              <span>
                {tool.summary}
                {tool.only && <span className="muted"> {PHASE_LABEL[tool.only as Step["phase"]]} only.</span>}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function RecapStep({ data }: { data: Leaderboard }) {
  // This walkthrough is a recorded score-v1 game, so it is compared with pick-trader under score-v1.
  const bar = pickTraderScoreV1(data);
  return (
    <>
      <section className="how-block">
        <h3>Then it does it again, four more times</h3>
        <p>
          The same four decisions repeat each season, against rivals who keep making their own moves. On this seed, pick-trader’s running score
          after each season:
        </p>
        <table className="data-table how-table">
          <thead>
            <tr>
              <th>Season</th>
              <th className="r">Record</th>
              <th className="r">Playoff rounds won</th>
              <th>Champion</th>
              <th className="r">Score so far</th>
            </tr>
          </thead>
          <tbody>
            {walkthrough.seasons.map((s) => (
              <tr key={s.season}>
                <th scope="row">{s.season}</th>
                <td className="r">
                  {s.wins}–{s.losses}
                </td>
                <td className="r">{s.playoff_rounds}</td>
                <td>{s.champion}</td>
                <td className="r">{num(s.score_after_season)}</td>
              </tr>
            ))}
            <tr className="how-final">
              <th scope="row">Final</th>
              <td colSpan={3}>After season five, with the leftover roster, prospects, picks and cap room counted</td>
              <td className="r">{num(walkthrough.final_score)}</td>
            </tr>
          </tbody>
        </table>
        <p className="how-hint">Under 2.0, the rules this game was played with, the record counts all games so far, so it grows across the seasons. 2.1 resets it each season.</p>
      </section>
      <section className="how-block">
        <h3>What a model has to beat</h3>
        <p>
          A model plays the same game on a set of private seeds, and its score is compared with pick-trader’s on those same seeds. The{" "}
          {num(walkthrough.final_score)} above is one public seed; pick-trader’s average on the private seeds is {bar === null ? "—" : num(bar)}.
          Both are under GM-Bench 2.0 and score-v1, the rules this walkthrough was recorded with; the standings now use GM-Bench 2.1 and score-v2. See
          the full scoring in <a href={routes.method}>Method</a>.
        </p>
        <p className="how-links">
          <a className="text-link" href={routes.standings}>
            See how the models did
          </a>
          <a className="text-link" href={routes.replays}>
            Step through real model games
          </a>
        </p>
      </section>
    </>
  );
}

function readHash(): number {
  if (typeof window === "undefined") return 0;
  const index = STEP_IDS.indexOf(window.location.hash.slice(1) as (typeof STEP_IDS)[number]);
  return index < 0 ? 0 : index;
}

export default function HowItWorks({ data }: { data: Leaderboard }) {
  const [index, setIndex] = useState(readHash);
  const last = STEP_IDS.length - 1;

  useEffect(() => {
    const sync = () => setIndex(readHash());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const go = (next: number) => {
    const clamped = Math.max(0, Math.min(last, next));
    setIndex(clamped);
    window.history.replaceState(null, "", `#${STEP_IDS[clamped]}`);
    document.getElementById("how-step")?.focus({ preventScroll: true });
    document.querySelector(".how-steps")?.scrollIntoView({ block: "nearest" });
  };

  const step = index >= 1 && index <= 4 ? walkthrough.steps[index - 1] : null;
  const nav = (
    <div className="how-nav">
      <button type="button" className="how-button" onClick={() => go(index - 1)} disabled={index === 0}>
        ← {index > 0 ? STEP_TITLES[index - 1] : "Back"}
      </button>
      <span className="muted">
        {index + 1} of {STEP_IDS.length}
      </span>
      <button type="button" className="how-button is-primary" onClick={() => go(index + 1)} disabled={index === last}>
        {index < last ? STEP_TITLES[index + 1] : "Done"} →
      </button>
    </div>
  );

  return (
    <div className="rink-layout">
      <article className="page how">
        <h1>How it works</h1>
        <p className="lede">
          One real season, decision by decision: the brief a model reads, the tools it gets, and what pick-trader did with them.
        </p>
        <ol className="how-steps" aria-label="Walkthrough steps">
          {STEP_TITLES.map((title, i) => (
            <li key={title}>
              <button type="button" aria-current={i === index ? "step" : undefined} className={i < index ? "is-done" : undefined} onClick={() => go(i)}>
                <span>{i === 0 ? "0" : i === last ? "★" : i}</span>
                {title}
              </button>
            </li>
          ))}
        </ol>
        <div id="how-step" className="how-step" tabIndex={-1} aria-live="polite">
          <h2>
            {step ? (
              <>
                <span className="muted">Season 1 ·</span> {PHASE_LABEL[step.phase]}
              </>
            ) : (
              STEP_TITLES[index]
            )}
          </h2>
          {index === 0 && <BriefStep />}
          {step && <PhaseStep step={step} />}
          {index === last && <RecapStep data={data} />}
        </div>
        {nav}
      </article>
      <RinkSidebar />
    </div>
  );
}
