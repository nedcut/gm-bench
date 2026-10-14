import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  GameRequest,
  GameResponse,
  GameSave,
  Player,
  Snapshot,
  Team,
} from "./types";

const SAVE_KEY = "gm-bench-human-save-v1";
const PHASES = ["preseason", "midseason", "trade_deadline", "draft"];
const LABEL: Record<string, string> = {
  preseason: "Preseason",
  midseason: "Midseason",
  trade_deadline: "Trade deadline",
  draft: "Draft",
};
const NEXT: Record<string, string> = {
  preseason: "Simulate to midseason",
  midseason: "Open trade deadline",
  trade_deadline: "Open the draft",
  draft: "Finish season",
};
const NOTE: Record<string, string> = {
  preseason:
    "Extend expiring contracts, sign free agents, and set your lineup before the first games.",
  midseason:
    "The first games are in the books. Check the standings, claim waivers, and adjust your lineup.",
  trade_deadline:
    "Review incoming offers or build a deal. Rival teams also make moves when you advance.",
  draft:
    "Spend scouting points and use every pick you own. Finishing this phase plays the remaining games and playoffs, ages players, and expires contracts.",
};
const SCORE_LABEL: Record<string, string> = {
  recent_wins: "Recent wins",
  playoff_rounds: "Playoff rounds",
  championships: "Championships",
  total_assets: "Roster assets",
  young_assets: "Young assets",
  future_pick_assets: "Future picks",
  cap_room: "Cap room",
  current_strength: "Lineup strength",
  roster_depth: "Roster depth",
};
const VIEWS = [
  "Office",
  "Roster",
  "Free agents",
  "Trades",
  "Draft",
  "League",
  "History",
  "Rules",
] as const;
type View = (typeof VIEWS)[number];
const money = (n: number) => `$${n.toFixed(2)}M`;
const rating = (n: number) => n.toFixed(1);
const ranked = (players: Player[]) =>
  [...players].sort((a, b) => b.overall - a.overall);
type Act = (tool: string, args?: Record<string, unknown>) => void;
type Review = (
  title: string,
  body: ReactNode,
  tool: string,
  args?: Record<string, unknown>,
) => void;

function Confirm({
  title,
  children,
  onCancel,
  onConfirm,
}: {
  title: string;
  children: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="gm-dialog"
      onCancel={onCancel}
      aria-labelledby="gm-confirm-title"
    >
      <h2 id="gm-confirm-title">{title}</h2>
      <div>{children}</div>
      <div className="gm-actions">
        <button autoFocus onClick={onCancel}>
          Cancel
        </button>
        <button className="gm-primary" onClick={onConfirm}>
          Confirm
        </button>
      </div>
    </dialog>
  );
}

function PlayerTable({
  players,
  reports,
  children,
}: {
  players: Player[];
  reports?: Snapshot["scout_reports"];
  children?: (p: Player) => ReactNode;
}) {
  return (
    <div
      className="gm-scroll"
      tabIndex={0}
      role="region"
      aria-label="Player table"
    >
      <table className="data-table gm-table">
        <thead>
          <tr>
            <th>Player</th>
            <th>Pos</th>
            <th className="r">Age</th>
            <th className="r">Ovr</th>
            <th className="r">Pot*</th>
            <th className="r">Salary / yrs</th>
            {children && <th>Manage</th>}
          </tr>
        </thead>
        <tbody>
          {ranked(players).map((p) => (
            <tr key={p.id}>
              <th scope="row">{p.name}</th>
              <td>{p.sub_position ?? p.position}</td>
              <td className="r">{p.age}</td>
              <td className="r">{rating(p.overall)}</td>
              <td className="r">
                {rating(reports?.[p.id] ?? p.potential)}
                {reports?.[p.id] !== undefined ? " ✓" : ""}
              </td>
              <td className="r">
                {money(p.asking_salary ?? p.salary)} / {p.contract_years}
              </td>
              {children && <td>{children(p)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {players.length === 0 && (
        <p className="gm-empty">No players available.</p>
      )}
    </div>
  );
}

function Contract({
  player,
  quotes,
  tool,
  s,
  review,
}: {
  player: Player;
  quotes: Record<string, number>;
  tool: string;
  s: Snapshot;
  review: Review;
}) {
  const [years, setYears] = useState(Object.keys(quotes)[0]);
  const salary = quotes[years];
  const capDelta = salary - (tool === "extend_contract" ? player.salary : 0);
  return (
    <div className="gm-contract">
      <label>
        Contract length
        <select value={years} onChange={(e) => setYears(e.target.value)}>
          {Object.keys(quotes).map((y) => (
            <option key={y} value={y}>
              {y} years · {money(quotes[y])}/yr
            </option>
          ))}
        </select>
      </label>
      <p>
        Cap room after: <b>{money(s.team.cap_room - capDelta)}</b> · Total
        commitment: {money(salary * Number(years))}
      </p>
      {s.team.cap_room - capDelta < -s.rules.hard_cap_buffer && (
        <p className="neg">
          This contract would exceed the hard cap. Free up salary first.
        </p>
      )}
      <button
        disabled={
          s.done ||
          !s.legal_tools.includes(tool) ||
          s.team.cap_room - capDelta < -s.rules.hard_cap_buffer
        }
        onClick={() =>
          review(
            `${tool === "extend_contract" ? "Extend" : "Sign"} ${player.name}?`,
            <p>
              {years} years at {money(salary)} per year. Cap room changes from{" "}
              {money(s.team.cap_room)} to {money(s.team.cap_room - capDelta)}.
              The simulator checks cap and contract eligibility.
            </p>,
            tool,
            { player_id: player.id, years: Number(years), salary },
          )
        }
      >
        {tool === "extend_contract" ? "Review extension" : "Review signing"}
      </button>
    </div>
  );
}

function Roster({ s, act, review }: { s: Snapshot; act: Act; review: Review }) {
  const [selected, setSelected] = useState<number | null>(null);
  const [lineup, setLineup] = useState(s.effective_lineup);
  const player = s.team.roster.find((p) => p.id === selected);
  const counts = Object.fromEntries(
    Object.keys(s.rules.lineup_min_positions).map((pos) => [
      pos,
      s.team.roster.filter((p) => lineup.includes(p.id) && p.position === pos)
        .length,
    ]),
  );
  const valid =
    lineup.length === s.rules.lineup_size &&
    Object.entries(s.rules.lineup_min_positions).every(
      ([pos, n]) => counts[pos] >= n,
    );
  return (
    <>
      <h2>Roster & lineup</h2>
      <p>
        Dress {s.rules.lineup_size} players with at least 10 forwards, 4
        defensemen, and 1 goalie. Up to 3 centers add strength. Benched players
        develop at half speed.
      </p>
      <div className="gm-actions">
        <b>
          {lineup.length} / {s.rules.lineup_size} dressed · {counts.F} F /{" "}
          {counts.D} D / {counts.G} G
        </b>
        <button
          disabled={s.done || !valid}
          onClick={() => act("set_lineup", { player_ids: lineup })}
        >
          Save lineup
        </button>
        <button
          disabled={s.done}
          onClick={() => setLineup(autoLineup(s.team.roster, s))}
        >
          Select best by rating
        </button>
      </div>
      <PlayerTable players={s.team.roster} reports={s.scout_reports}>
        {(p) => (
          <div className="gm-actions">
            <label className="gm-check">
              <input
                type="checkbox"
                disabled={s.done}
                checked={lineup.includes(p.id)}
                onChange={(e) =>
                  setLineup((old) =>
                    e.target.checked
                      ? [...old, p.id]
                      : old.filter((id) => id !== p.id),
                  )
                }
                aria-label={`Dress ${p.name}`}
              />{" "}
              Dress
            </label>
            <button onClick={() => setSelected(p.id)}>Manage {p.name}</button>
          </div>
        )}
      </PlayerTable>
      {player && (
        <section className="gm-card">
          <h3>{player.name}</h3>
          <p>
            {player.sub_position ?? player.position} · Age {player.age} ·{" "}
            {rating(player.overall)} overall · {money(player.salary)} /{" "}
            {player.contract_years} years · Injury risk{" "}
            {(player.injury_risk * 100).toFixed(1)}%
          </p>
          {player.extension_quotes && (
            <Contract
              key={player.id}
              player={player}
              quotes={player.extension_quotes}
              tool="extend_contract"
              s={s}
              review={review}
            />
          )}
          <div className="gm-actions">
            <button
              disabled={
                s.done ||
                s.rules.scouting.points_remaining === 0 ||
                s.scout_reports[player.id] !== undefined
              }
              onClick={() => act("scout", { player_id: player.id })}
            >
              Scout potential
            </button>
            <button
              disabled={s.done || s.team.roster.length <= s.rules.roster_min}
              onClick={() =>
                review(
                  `Release ${player.name}?`,
                  <>
                    <p>
                      Lose this player immediately. They cannot re-sign with you
                      this season.
                    </p>
                    <p>
                      Dead cap:{" "}
                      {Object.entries(player.release_dead_cap?.by_season ?? {})
                        .map(([y, charge]) => `Season ${y}: ${money(charge)}`)
                        .join("; ")}
                      . Total: {money(player.release_dead_cap?.total ?? 0)}.
                    </p>
                  </>,
                  "release_player",
                  { player_id: player.id },
                )
              }
            >
              Review release
            </button>
          </div>
        </section>
      )}
    </>
  );
}
function autoLineup(players: Player[], s: Snapshot) {
  const selected: number[] = [];
  const sorted = ranked(players);
  for (const [pos, min] of Object.entries(s.rules.lineup_min_positions))
    selected.push(
      ...sorted
        .filter((p) => p.position === pos)
        .slice(0, min)
        .map((p) => p.id),
    );
  selected.push(
    ...sorted
      .filter((p) => !selected.includes(p.id))
      .slice(0, Math.max(0, s.rules.lineup_size - selected.length))
      .map((p) => p.id),
  );
  return selected;
}

function Market({
  s,
  review,
  act,
  waiver = false,
}: {
  s: Snapshot;
  review: Review;
  act: Act;
  waiver?: boolean;
}) {
  const [position, setPosition] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const all = waiver ? s.waiver_wire : s.free_agents;
  const players = all.filter(
    (p) =>
      (!position || p.position === position) &&
      p.name.toLowerCase().includes(search.toLowerCase()),
  );
  const player = all.find((p) => p.id === selected);
  return (
    <>
      <h2>{waiver ? "Waiver wire" : "Free agency"}</h2>
      <p>
        {waiver
          ? "Claims take on the existing contract. The waiver wire opens at midseason."
          : "Published quotes account for your team's record and the player's role. Choose a length to see the exact cap impact."}
      </p>
      <div className="gm-actions">
        <label>
          Position
          <select
            value={position}
            onChange={(e) => setPosition(e.target.value)}
          >
            <option value="">All positions</option>
            {["F", "D", "G"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <label>
          Search players
          <input value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <span>{players.length} players</span>
      </div>
      <PlayerTable players={players} reports={s.scout_reports}>
        {(p) =>
          waiver ? (
            <button
              disabled={s.done || !s.legal_tools.includes("claim_waiver")}
              onClick={() =>
                review(
                  `Claim ${p.name}?`,
                  <p>
                    Take on {money(p.salary)} per year for {p.contract_years}{" "}
                    years. Cap room after: {money(s.team.cap_room - p.salary)}.
                  </p>,
                  "claim_waiver",
                  { player_id: p.id },
                )
              }
            >
              Review claim
            </button>
          ) : (
            <button disabled={s.done} onClick={() => setSelected(p.id)}>
              Negotiate {p.name}
            </button>
          )
        }
      </PlayerTable>
      {player && !waiver && (
        <section className="gm-card">
          <h3>{player.name}</h3>
          <Contract
            key={`${player.id}-${s.actions_taken}`}
            player={player}
            quotes={
              player.contract_quotes ?? { "1": player.asking_salary ?? 0 }
            }
            tool="sign_free_agent"
            s={s}
            review={review}
          />
          <button
            disabled={
              s.done ||
              s.rules.scouting.points_remaining === 0 ||
              s.scout_reports[player.id] !== undefined
            }
            onClick={() => act("scout", { player_id: player.id })}
          >
            Scout potential
          </button>
        </section>
      )}
    </>
  );
}

function TradeAssets({
  team,
  season,
  chosen,
  setChosen,
  picks,
  setPicks,
}: {
  team: Team;
  season: number;
  chosen: number[];
  setChosen: (v: number[]) => void;
  picks: string[];
  setPicks: (v: string[]) => void;
}) {
  return (
    <section className="gm-card">
      <h3>{team.name}</h3>
      <p>
        Payroll {money(team.payroll)} · Cap room {money(team.cap_room)}
      </p>
      <div className="gm-asset-list">
        {ranked(team.roster).map((p) => (
          <label key={p.id} className="gm-check">
            <input
              type="checkbox"
              checked={chosen.includes(p.id)}
              onChange={(e) =>
                setChosen(
                  e.target.checked
                    ? [...chosen, p.id]
                    : chosen.filter((id) => id !== p.id),
                )
              }
            />
            <span>
              <b>{p.name}</b> · {p.sub_position ?? p.position} ·{" "}
              {rating(p.overall)} ovr / {rating(p.potential)} pot · Age {p.age}
              <small>
                {money(p.salary)} × {p.contract_years} years
              </small>
            </span>
          </label>
        ))}
      </div>
      <h4>Future picks</h4>
      {Object.entries(team.draft_picks)
        .filter(([y]) => Number(y) > season && Number(y) <= season + 3)
        .flatMap(([y, count]) =>
          Array.from({ length: count }, (_, i) => {
            const key = `${y}:${i}`;
            return (
              <label className="gm-check" key={key}>
                <input
                  type="checkbox"
                  checked={picks.includes(key)}
                  onChange={(e) =>
                    setPicks(
                      e.target.checked
                        ? [...picks, key]
                        : picks.filter((p) => p !== key),
                    )
                  }
                />
                Season {y} pick {i + 1}
              </label>
            );
          }),
        )}
    </section>
  );
}
function Trades({ s, review, act }: { s: Snapshot; review: Review; act: Act }) {
  const [partnerId, setPartnerId] = useState(
    s.teams.find((t) => t.id !== s.team.id)!.id,
  );
  const [give, setGive] = useState<number[]>([]);
  const [receive, setReceive] = useState<number[]>([]);
  const [givePicks, setGivePicks] = useState<string[]>([]);
  const [receivePicks, setReceivePicks] = useState<string[]>([]);
  const [counter, setCounter] = useState<string | null>(null);
  const partner = s.teams.find((t) => t.id === partnerId)!;
  const outgoing = s.team.roster.filter((p) => give.includes(p.id));
  const incoming = partner.roster.filter((p) => receive.includes(p.id));
  const bothSides =
    give.length + givePicks.length > 0 &&
    receive.length + receivePicks.length > 0;
  const net =
    incoming.reduce((v, p) => v + p.salary, 0) -
    outgoing.reduce((v, p) => v + p.salary, 0);
  const describe = (players: Player[], picks: number[]) =>
    [
      ...players.map(
        (p) => `${p.name} (${money(p.salary)} × ${p.contract_years})`,
      ),
      ...picks.map((y) => `Season ${y} pick`),
    ].join(", ") || "Nothing";
  return (
    <>
      <h2>Trade desk</h2>
      <p>
        Trade players and future picks with any team. Rivals use their own
        valuations and may decline. Repeated declines can close negotiations for
        this phase.
      </p>
      <h3>Incoming offers</h3>
      {s.incoming_offers.length === 0 && (
        <p className="muted">
          No incoming offers. Offers normally arrive at the trade deadline.
        </p>
      )}
      {s.incoming_offers.map((o) => (
        <section className="gm-card" key={o.offer_id}>
          <h4>{o.team_name}</h4>
          <p>
            You give:{" "}
            {describe(o.they_receive_players, o.they_receive_pick_seasons)}
          </p>
          <p>
            You receive:{" "}
            {describe(o.you_receive_players, o.you_receive_pick_seasons)}
          </p>
          <div className="gm-actions">
            <button
              disabled={s.done}
              onClick={() =>
                review(
                  `Accept ${o.team_name}'s offer?`,
                  <>
                    <p>
                      You give:{" "}
                      {describe(
                        o.they_receive_players,
                        o.they_receive_pick_seasons,
                      )}
                    </p>
                    <p>
                      You receive:{" "}
                      {describe(
                        o.you_receive_players,
                        o.you_receive_pick_seasons,
                      )}
                    </p>
                    <p>
                      Cap room after:{" "}
                      {money(
                        s.team.cap_room +
                          o.they_receive_players.reduce(
                            (n, p) => n + p.salary,
                            0,
                          ) -
                          o.you_receive_players.reduce(
                            (n, p) => n + p.salary,
                            0,
                          ),
                      )}
                    </p>
                  </>,
                  "accept_trade_offer",
                  { offer_id: o.offer_id },
                )
              }
            >
              Review offer
            </button>
            <button
              disabled={s.done}
              onClick={() =>
                act("reject_trade_offer", { offer_id: o.offer_id })
              }
            >
              Decline offer
            </button>
            <button
              disabled={s.done}
              onClick={() => {
                setPartnerId(o.team_id);
                setGive(o.they_receive_players.map((p) => p.id));
                setReceive(o.you_receive_players.map((p) => p.id));
                setGivePicks(
                  o.they_receive_pick_seasons.map(
                    (y, i) =>
                      `${y}:${o.they_receive_pick_seasons.slice(0, i).filter((v) => v === y).length}`,
                  ),
                );
                setReceivePicks(
                  o.you_receive_pick_seasons.map(
                    (y, i) =>
                      `${y}:${o.you_receive_pick_seasons.slice(0, i).filter((v) => v === y).length}`,
                  ),
                );
                setCounter(o.offer_id);
              }}
            >
              Build counteroffer
            </button>
          </div>
        </section>
      ))}
      <h3>{counter ? "Counteroffer" : "Build a trade"}</h3>
      <label>
        Trade partner
        <select
          value={partnerId}
          onChange={(e) => {
            setPartnerId(Number(e.target.value));
            setReceive([]);
            setGive([]);
            setGivePicks([]);
            setReceivePicks([]);
            setCounter(null);
          }}
        >
          {s.teams
            .filter((t) => t.id !== s.team.id)
            .map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
        </select>
      </label>
      <fieldset disabled={s.done} className="gm-trade-grid">
        <legend>Select assets each team gives</legend>
        <TradeAssets
          team={s.team}
          season={s.season}
          chosen={give}
          setChosen={setGive}
          picks={givePicks}
          setPicks={setGivePicks}
        />
        <TradeAssets
          team={partner}
          season={s.season}
          chosen={receive}
          setChosen={setReceive}
          picks={receivePicks}
          setPicks={setReceivePicks}
        />
      </fieldset>
      <p>
        Your cap room after: <b>{money(s.team.cap_room - net)}</b> · Partner cap
        room after: {money(partner.cap_room + net)}
      </p>
      <button
        disabled={s.done || !bothSides}
        onClick={() =>
          review(
            counter ? "Send counteroffer?" : "Propose this trade?",
            <>
              <p>
                You give:{" "}
                {describe(
                  outgoing,
                  givePicks.map((p) => Number(p.split(":")[0])),
                )}
              </p>
              <p>
                You receive:{" "}
                {describe(
                  incoming,
                  receivePicks.map((p) => Number(p.split(":")[0])),
                )}
              </p>
              <p>
                Your cap room after: {money(s.team.cap_room - net)}. Acceptance
                depends on the rival's valuation.
              </p>
            </>,
            counter ? "counter_trade_offer" : "trade",
            {
              ...(counter
                ? { offer_id: counter }
                : { partner_team_id: partnerId }),
              give_player_ids: give,
              receive_player_ids: receive,
              give_pick_seasons: givePicks.map((p) => Number(p.split(":")[0])),
              receive_pick_seasons: receivePicks.map((p) =>
                Number(p.split(":")[0]),
              ),
            },
          )
        }
      >
        Review {counter ? "counteroffer" : "trade"}
      </button>
    </>
  );
}

function Draft({ s, act, review }: { s: Snapshot; act: Act; review: Review }) {
  const count = s.team.draft_picks[s.season] ?? 0;
  return (
    <>
      <h2>Draft room</h2>
      <p>
        {s.phase === "draft" && !s.done
          ? `You have ${count} pick${count === 1 ? "" : "s"} remaining this season. Rivals ahead of your first pick have already selected.`
          : "The draft board opens in the draft phase. Scouting points can also be spent on your roster and free agents."}
      </p>
      <p>
        <b>{s.rules.scouting.points_remaining} scouting points left.</b>{" "}
        Potential is an estimate. A scouting report gives a closer reading and
        persists across seasons.
      </p>
      <PlayerTable players={s.draft_class} reports={s.scout_reports}>
        {(p) => (
          <div className="gm-actions">
            <button
              disabled={
                s.done ||
                s.rules.scouting.points_remaining === 0 ||
                s.scout_reports[p.id] !== undefined
              }
              onClick={() => act("scout", { player_id: p.id })}
            >
              Scout {p.name}
            </button>
            <button
              disabled={
                s.done || count === 0 || !s.legal_tools.includes("draft")
              }
              onClick={() =>
                review(
                  `Draft ${p.name}?`,
                  <p>
                    Use one season-{s.season} pick on {p.name},{" "}
                    {p.sub_position ?? p.position}, age {p.age},{" "}
                    {rating(p.overall)} overall /{" "}
                    {rating(s.scout_reports[p.id] ?? p.potential)} potential.
                    The simulator assigns a rookie contract.
                  </p>,
                  "draft",
                  { prospect_id: p.id },
                )
              }
            >
              Draft {p.name}
            </button>
          </div>
        )}
      </PlayerTable>
      <h3>Your picks</h3>
      <div className="gm-scroll">
        <table className="data-table gm-table">
          <thead>
            <tr>
              <th>Season</th>
              <th>Original team</th>
              <th>Projected slot</th>
            </tr>
          </thead>
          <tbody>
            {s.team.picks?.map((p, i) => (
              <tr key={i}>
                <td>{p.season}</td>
                <td>{p.from_team_name}</td>
                <td>{p.projected_slot}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Future slots are projections. The four non-playoff teams enter a
        weighted lottery; picks keep the original team's slot when traded.
      </p>
    </>
  );
}

function League({ s }: { s: Snapshot }) {
  const [selected, setSelected] = useState<number | null>(null);
  const team = s.teams.find((t) => t.id === selected);
  const played = s.standings.some((t) => t.wins + t.losses > 0);
  return (
    <>
      <h2>League standings</h2>
      <p>
        12 teams. The top 8 make the playoffs.{" "}
        {played
          ? "Records are for the current or most recently completed season."
          : "No games played yet; teams are tied."}
      </p>
      <div className="gm-scroll">
        <table className="data-table gm-table">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Team</th>
              <th className="r">W</th>
              <th className="r">L</th>
              <th className="r">Strength</th>
              <th className="r">Titles</th>
            </tr>
          </thead>
          <tbody>
            {s.standings.map((t, i) => (
              <tr
                key={t.team_id}
                className={t.team_id === s.team.id ? "gm-you" : undefined}
              >
                <td>{played ? i + 1 : "—"}</td>
                <th scope="row">
                  <button
                    className="gm-link"
                    onClick={() => setSelected(t.team_id)}
                  >
                    {t.team_name}
                    {t.team_id === s.team.id ? " · You" : ""}
                  </button>
                </th>
                <td className="r">{t.wins}</td>
                <td className="r">{t.losses}</td>
                <td className="r">{rating(t.public_strength)}</td>
                <td className="r">{t.championships}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {team && (
        <section className="gm-card">
          <h3>{team.name}</h3>
          <p>
            Payroll: {money(team.payroll)} · Cap room: {money(team.cap_room)}
          </p>
          <PlayerTable players={team.roster} />
        </section>
      )}
    </>
  );
}
function HistoryView({ s }: { s: Snapshot }) {
  return (
    <>
      <h2>Season history</h2>
      {s.history.length === 0 ? (
        <p>Finish your first season to see the results here.</p>
      ) : (
        <div className="gm-scroll">
          <table className="data-table gm-table">
            <thead>
              <tr>
                <th>Season</th>
                <th>Record</th>
                <th>Playoff rounds won</th>
                <th>Champion</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {s.history.map((h) => (
                <tr key={h.season}>
                  <th scope="row">{h.season}</th>
                  <td>
                    {h.wins}–{h.losses}
                  </td>
                  <td>{h.playoff_rounds}</td>
                  <td>
                    {s.teams.find((t) => t.id === h.champion_team_id)?.name}
                  </td>
                  <td>{rating(h.score_after_season)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h3>Score breakdown</h3>
      <p>
        Provisional during play; final after five seasons. Contributions add up
        to the strategy score, then illegal-action penalties are subtracted.
      </p>
      <dl className="gm-score-terms">
        {Object.entries(s.score_terms).map(([key, value]) => (
          <div key={key}>
            <dt>{SCORE_LABEL[key] ?? key.replaceAll("_", " ")}</dt>
            <dd>{rating(value)}</dd>
          </div>
        ))}
        <div>
          <dt>Penalties</dt>
          <dd>−{rating(s.score.protocol_penalty)}</dd>
        </div>
        <div>
          <dt>{s.done ? "Final score" : "Score so far"}</dt>
          <dd>{rating(s.score.final_score)}</dd>
        </div>
      </dl>
      <h3>Recent league transactions</h3>
      <p className="muted">
        Current and previous season. Your complete action history is included in
        your exported save.
      </p>
      <ol className="gm-transactions">
        {[...s.recent_transactions].reverse().map((t, i) => (
          <li key={i}>
            <small>
              Season {t.season} · {LABEL[t.phase] ?? t.phase} ·{" "}
              {s.teams.find((team) => team.id === t.team_id)?.name}
            </small>
            {t.message}{" "}
            <span className="muted">({String(t.action.type ?? "move")})</span>
          </li>
        ))}
      </ol>
    </>
  );
}
function Rules({ s }: { s: Snapshot }) {
  return (
    <>
      <h2>How to play</h2>
      <p>
        Run the Anchorage Auroras for five seasons. Make as many moves as you
        need in each of four decision windows, then advance. Opponents run
        automatically. The game uses the benchmark simulator and scoring rules.
      </p>
      <h3>Your score</h3>
      <p>
        Wins, playoff rounds, titles, roster assets, young talent, future picks,
        cap room, lineup strength, and depth all contribute. Illegal moves cost
        points; a rival declining a reasonable offer does not. The score shown
        during play is provisional. This is a public practice challenge,
        separate from the private-seed model leaderboard.
      </p>
      <h3>Roster & money</h3>
      <p>
        Salary cap: {money(s.rules.salary_cap)}. Hard-cap buffer:{" "}
        {money(s.rules.hard_cap_buffer)}. Minimum roster: {s.rules.roster_min}.
        Dress {s.rules.lineup_size} players, including at least 10 F, 4 D, and 1
        G. Three dressed centers maximize the center bonus. Players outside the
        lineup develop at half speed.
      </p>
      <p>
        Releasing a player leaves 25% of salary as dead cap for up to two
        seasons, and blocks re-signing them this season. Preseason extensions
        are available only for eligible players in the last year of a contract.
        Quotes are annual salaries in millions. The cap and market inflate 4%
        each season.
      </p>
      <h3>The calendar</h3>
      <ol>
        {PHASES.map((p) => (
          <li key={p}>
            <b>{LABEL[p]}.</b> {NOTE[p]}
          </li>
        ))}
      </ol>
      <p>
        The benchmark draft happens before the remaining games and playoffs.
        There is no daily schedule or box-score simulation. Standings retain the
        last completed record into preseason until the next midseason games run.
      </p>
      <h3>Scouting & trading</h3>
      <p>
        You have 3 scouting points each season. Potential ratings are estimates,
        including on your own roster; ✓ marks a scouted estimate. Picks up to 3
        seasons ahead can be traded. Other GMs use hidden valuations. After
        repeated declines they may stop negotiating until the next phase.
      </p>
      <h3>Saves</h3>
      <p>
        One challenge autosaves in this browser after every action. Export a
        file to back it up or move it to another browser. Saves replay your
        decisions and require the same simulator version. The first launch
        downloads Python from jsDelivr; there are no model calls or provider
        accounts.
      </p>
    </>
  );
}

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
  const [notice, setNotice] = useState("");
  const [saveStatus, setSaveStatus] = useState("");
  const [confirm, setConfirm] = useState<{
    title: string;
    body: ReactNode;
    run: () => void;
  } | null>(null);
  const [memo, setMemo] = useState("");
  useEffect(() => () => worker.current?.terminate(), []);
  function send(request: Omit<GameRequest, "id">) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
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
        if (response.result) {
          const after = response.snapshot;
          const delta = before
            ? ` Cap room ${money(before.team.cap_room)} → ${money(after.team.cap_room)} · Roster ${before.team.roster.length} → ${after.team.roster.length} · Score ${rating(before.score.final_score)} → ${rating(after.score.final_score)}.`
            : "";
          setNotice(
            `${response.result.ok ? "✓" : "Move declined:"} ${response.result.message}${response.result.penalized ? " This illegal move costs score." : ""}${response.result.season_result ? ` Season result: ${response.result.season_result.wins} wins, ${response.result.season_result.losses} losses.` : ""}${delta}`,
          );
        }
        try {
          const text = JSON.stringify(response.save);
          localStorage.setItem(SAVE_KEY, text);
          setStored(text);
          setSaveStatus("Saved in this browser");
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
  const rank = s
    ? s.standings.findIndex((t) => t.team_id === s.team.id) + 1
    : 0;
  return (
    <article className="gm-game" aria-busy={busy}>
      <header className="gm-heading">
        <div>
          <p className="gm-eyebrow">THE HUMAN CHALLENGE</p>
          <h1>Your call, GM.</h1>
          <p>Five seasons. One franchise. Every decision is yours.</p>
        </div>
        <div className="gm-actions">
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
      {error && (
        <div className="gm-message gm-error" role="alert">
          {error}
        </div>
      )}
      <div role="status" aria-live="polite">
        {busy ? (
          <p className="gm-message">
            {s
              ? "Applying your decision…"
              : "Loading the real simulator… First launch downloads Python and can take a moment."}
          </p>
        ) : notice ? (
          <p className="gm-message">{notice}</p>
        ) : null}
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
                Start challenge
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
            <button
              className="gm-primary"
              disabled={busy || s.done}
              onClick={advance}
            >
              {s.done ? "Challenge complete" : NEXT[s.phase]} →
            </button>
          </div>
          <div className="gm-save-status">
            {saveStatus}
            <span>
              {s.rules.scouting.points_remaining} scouting points ·{" "}
              {s.team.roster.length} players · {s.actions_taken} actions
            </span>
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
              <button onClick={() => setView("History")}>
                View season history
              </button>
            </section>
          )}
          <nav className="gm-nav" aria-label="Front office">
            {VIEWS.map((v) => (
              <button
                key={v}
                aria-label={v}
                aria-current={view === v ? "page" : undefined}
                onClick={() => setView(v)}
              >
                {v}
                {v === "Trades" && s.incoming_offers.length > 0
                  ? ` (${s.incoming_offers.length})`
                  : ""}
              </button>
            ))}
          </nav>
          <div className="gm-layout">
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
                          onClick={() => setView(v)}
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
                    key={`${s.season}-${s.phase}-${s.actions_taken}`}
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
            <aside className="gm-context">
              <dl className="gm-context-stats">
                <div>
                  <dt>Record / standing</dt>
                  <dd>
                    {s.team.wins}–{s.team.losses} ·{" "}
                    {s.team.wins + s.team.losses ? `${rank} / 12` : "Tied"}
                  </dd>
                </div>
                <div>
                  <dt>Cap room</dt>
                  <dd className={s.team.cap_room < 0 ? "neg" : "pos"}>
                    {money(s.team.cap_room)}
                  </dd>
                </div>
              </dl>
              <details open>
                <summary>Your roster · {s.team.roster.length} players</summary>
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
                              {s.effective_lineup.includes(p.id) ? "● " : "○ "}
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
                <button onClick={() => setView("Roster")}>
                  Manage roster & lineup
                </button>
              </details>
            </aside>
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
