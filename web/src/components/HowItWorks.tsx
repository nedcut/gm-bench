import type { Snapshot } from "../types";
import { PHASES } from "../content";

/* Score weights, copied from SCORE_SCALES["score-v1"] in gm_bench/scoring.py
   (frozen with the sota-v5 contract). */
const SCORE_ROWS = [
  ["Recent wins", "+0.42", "per win, last three seasons"],
  ["Playoff rounds", "+9", "per round won"],
  ["Championships", "+35", "per title"],
  ["Roster assets", "+0.16", "per point of total player value"],
  ["Young assets", "+0.18", "per point of young-player value"],
  ["Future picks", "+0.16", "per point of draft-pick value"],
  ["Cap room", "+0.35", "per $1M, capped between −12 and +10"],
  ["Lineup strength", "+0.28", "per point of lineup rating"],
  ["Roster depth", "+8", "per unit of depth"],
  ["Illegal action", "−2.5", "each rejected move"],
] as const;

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

const ACTIONS_SNIPPET = `{
  "actions": [
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
  ],
  "usage": { "input_tokens": 1200, "output_tokens": 340 }
}`;

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
          <h2>Five seasons, four decisions each</h2>
          <p>
            Every player is fictional and every league is built from a seed. The agent reads one
            JSON observation per decision and writes back a list of moves.
          </p>
        </div>

        <div className="phase-wire">
          {PHASES.map((phase) => (
            <article key={phase.num} className="phase-row">
              <p className="phase-num">
                <b>{phase.num}</b>
                {phase.when}
              </p>
              <h3>{phase.title}</h3>
              <p>{phase.body}</p>
            </article>
          ))}
        </div>

        <div className="protocol-grid">
          <div>
            <h3 className="protocol-subhead">How a score is built</h3>
            <table className="score-table">
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Points</th>
                  <th>Unit</th>
                </tr>
              </thead>
              <tbody>
                {SCORE_ROWS.map(([name, points, unit]) => (
                  <tr key={name}>
                    <th scope="row">{name}</th>
                    <td className="numeric">{points}</td>
                    <td>{unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="protocol-note">
              Assets are scored at the end of season five, so trading the future for one good
              season costs points. The public seeds are published, so an agent could be tuned to
              them; results use private seeds.
            </p>
          </div>
          <div className="protocol-code">
            <CodeCard title="Observation (stdin)" code={OBSERVATION_SNIPPET} />
            <CodeCard title="Moves (stdout)" code={ACTIONS_SNIPPET} />
          </div>
        </div>

        <div className="panel" style={{ marginTop: 18 }}>
          <div className="panel-title">
            <h3>Sample transactions</h3>
            <span>
              {snapshot.season_trace.agent}, seed {snapshot.season_trace.seed}
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
