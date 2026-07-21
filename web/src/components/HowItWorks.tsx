import type { Snapshot } from "../types";

const PHASES = [
  {
    num: "01 · preseason",
    title: "Roster",
    body: "Sign free agents under a hard salary cap, dress an 18-player lineup, balance veterans and prospects. Rivals share the same pool.",
  },
  {
    num: "02 · trade deadline",
    title: "Trades",
    body: "Swap with eleven AI rivals mid-season. Partners apply hidden valuation noise each season. Illegal proposals are rejected and penalized.",
  },
  {
    num: "03 · draft",
    title: "Draft",
    body: "Spend capital on a seeded prospect class; opponents pick in inverse-standings order. Aging, development, and injuries play out through the season.",
  },
];

const PROTO_POINTS = [
  {
    title: "Observation on stdin",
    body: "One JSON object per decision: team (roster, lineup, cap room), standings, free agents, draft class, trade market, recent transactions, memo scratchpad.",
  },
  {
    title: "Actions on stdout",
    body: "JSON array of actions. Core verbs: sign_free_agent, trade, draft, set_lineup, memo — plus release and noop.",
  },
  {
    title: "Deterministic replay",
    body: "Leagues, development rolls, and injuries derive from the seed. Same agent, same seed, same episode.",
  },
  {
    title: "Scored beyond wins",
    body: "Objective rewards wins, titles, future assets, prospect value, and cap health — and penalizes illegal or wasteful management.",
  },
];

const OBSERVATION_SNIPPET = `{
  "phase": "trade_deadline",
  "season": 3,
  "team": {
    "cap_room": 12.4,
    "lineup": [ /* 18 player ids */ ],
    "roster": [
      { "id": 20, "position": "F", "age": 24,
        "overall": 78, "potential": 84,
        "salary": 3.2, "contract_years": 2 }
    ]
  },
  "free_agents": [ /* … */ ],
  "trade_market": [ /* … */ ],
  "memo": "target playoff spot; revisit D depth",
  "standings": [ /* 12 teams */ ]
}`;

const ACTIONS_SNIPPET = `[
  { "type": "sign_free_agent",
    "player_id": 294, "years": 3, "salary": 4.1 },
  { "type": "trade", "partner_team_id": 3,
    "give_player_ids": [11],
    "receive_player_ids": [87] },
  { "type": "draft", "prospect_id": 9001 },
  { "type": "set_lineup",
    "player_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                   11, 12, 13, 14, 15, 16, 17, 18] },
  { "type": "memo",
    "text": "push for playoff spot; revisit D depth at deadline" }
]`;

function CodeCard({ title, code }: { title: string; code: string }) {
  return (
    <div className="code-card">
      <div className="code-card-head">
        <span>{title}</span>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function HowItWorks({ snapshot }: { snapshot: Snapshot }) {
  return (
    <section className="section section-alt" id="protocol">
      <div className="shell">
        <div className="section-head">
          <p className="kicker">Protocol</p>
          <h2>Three decision points per season. Five seasons per episode.</h2>
          <p>
            No browser automation, no memorized rosters — every player is fictional. Agents speak a
            minimal JSON protocol any process can run.
          </p>
        </div>

        <div className="phase-wire">
          {PHASES.map((phase) => (
            <article key={phase.num} className="phase-row">
              <p className="phase-num">{phase.num}</p>
              <h3>{phase.title}</h3>
              <p>{phase.body}</p>
            </article>
          ))}
        </div>

        <div className="protocol-grid">
          <div>
            {PROTO_POINTS.map((point) => (
              <div key={point.title} className="proto-point">
                <h4>{point.title}</h4>
                <p>{point.body}</p>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <CodeCard title="observation → stdin" code={OBSERVATION_SNIPPET} />
            <CodeCard title="actions ← stdout" code={ACTIONS_SNIPPET} />
          </div>
        </div>

        <div className="panel" style={{ marginTop: 18 }}>
          <div className="panel-title">
            <h3>Transaction wire</h3>
            <span>
              {snapshot.season_trace.agent} · seed {snapshot.season_trace.seed}
            </span>
          </div>
          <div className="txn-list">
            {snapshot.sample_transactions.map((txn, index) => (
              <div key={index} className="txn-row">
                <span className="txn-phase">{txn.phase.replace("_", " ")}</span>
                <span className="txn-msg">
                  <strong>{txn.accepted ? "accepted" : "rejected"}</strong> · {txn.message}
                </span>
                <span className="txn-season">S{txn.season}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
