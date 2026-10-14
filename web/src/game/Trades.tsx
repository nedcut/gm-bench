import { useState } from "react";
import type { Player, Snapshot, Team } from "./types";
import { money, rating, ranked, type Act, type Review } from "./gameConfig";

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
export default function Trades({
  s,
  review,
  act,
}: {
  s: Snapshot;
  review: Review;
  act: Act;
}) {
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
