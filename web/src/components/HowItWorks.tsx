import type { Snapshot } from "../types";

const PHASES = [
  {
    num: "01 · preseason",
    title: "Build the roster",
    body: "Sign free agents under a hard salary cap, set the opening lineup, and balance veterans against prospects. Public ratings are noisy — true potential stays hidden.",
  },
  {
    num: "02 · trade deadline",
    title: "Trade under pressure",
    body: "Swap players and picks with eleven autopilot rivals mid-season. Win-now buyers pay premiums; rebuilders stockpile futures. Illegal proposals are rejected and penalized.",
  },
  {
    num: "03 · draft",
    title: "Invest in the future",
    body: "Spend draft capital on a seeded prospect class, then watch aging, development, and injuries play out across the season simulation and playoffs.",
  },
];

const PROTO_POINTS = [
  {
    title: "Observation on stdin",
    body: "One JSON object per decision point: roster, cap room, standings, free agents, trade candidates, and the prospect board.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3v12m0 0 4-4m-4 4-4-4M4 21h16" />
      </svg>
    ),
  },
  {
    title: "Actions on stdout",
    body: "Reply with a JSON array of actions. Four verbs cover the whole job: sign_free_agent, trade, draft, and set_lineup.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 21V9m0 0-4 4m4-4 4 4M4 3h16" />
      </svg>
    ),
  },
  {
    title: "Deterministic replay",
    body: "Leagues, development rolls, and injuries derive from the seed. The same agent on the same seed produces the same episode, every time.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 12a9 9 0 0 1-15 6.7L3 16m0-4a9 9 0 0 1 15-6.7L21 8M3 16v-4h4M21 8v4h-4" />
      </svg>
    ),
  },
  {
    title: "Scored beyond wins",
    body: "The objective rewards wins, titles, future assets, prospect value, and cap health — and penalizes illegal or wasteful management.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3 3 7.5v6.5c0 4.2 3.8 6.6 9 7 5.2-.4 9-2.8 9-7V7.5L12 3Zm-3 9 2 2 4-5" />
      </svg>
    ),
  },
];

const OBSERVATION_SNIPPET = `{
  "phase": "trade_deadline",
  "season": 3,
  "cap_room": 12.4,
  "roster": [
    { "id": 20, "pos": "F", "age": 24,
      "overall": 78, "potential": 84,
      "salary": 3.2, "years_left": 2 }
  ],
  "free_agents": [ /* … */ ],
  "trade_targets": [ /* … */ ],
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
    "player_ids": [1, 2, 3, 4, 5, 6] }
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
    <section className="section" id="how-it-works">
      <div className="shell">
        <div className="section-head">
          <p className="section-kicker">The decision loop</p>
          <h2>Three decision points per season. Five seasons per episode.</h2>
          <p>
            No browser automation, no memorized rosters — every player is fictional. Agents
            face the same long-horizon trade-offs a real front office does, expressed as a
            minimal JSON protocol any process can speak.
          </p>
        </div>

        <div className="loop-grid">
          {PHASES.map((phase) => (
            <article key={phase.num} className="loop-card">
              <p className="loop-num">{phase.num}</p>
              <h3>{phase.title}</h3>
              <p>{phase.body}</p>
            </article>
          ))}
        </div>

        <div className="protocol-grid">
          <div className="proto-points">
            {PROTO_POINTS.map((point) => (
              <div key={point.title} className="proto-point">
                <span className="proto-icon">{point.icon}</span>
                <div>
                  <h4>{point.title}</h4>
                  <p>{point.body}</p>
                </div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <CodeCard title="observation → stdin" code={OBSERVATION_SNIPPET} />
            <CodeCard title="actions ← stdout" code={ACTIONS_SNIPPET} />
          </div>
        </div>

        <div className="panel" style={{ marginTop: 22 }}>
          <div className="panel-title">
            <h3>Sample transaction audit</h3>
            <span>
              {snapshot.season_trace.agent} agent · seed {snapshot.season_trace.seed} · every action is logged
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
