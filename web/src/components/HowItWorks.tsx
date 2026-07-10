import { Reveal } from "./Reveal";

const PHASES = [
  {
    num: "01 · preseason",
    title: "Build the roster",
    body: "Sign free agents under a hard salary cap, dress an 18-player lineup, and balance veterans against prospects. Rivals compete for the same pool — a free agent visible now may be gone next phase.",
  },
  {
    num: "02 · midseason",
    title: "React to injuries",
    body: "About a third of the schedule is in the books. Injuries open waiver claims; depth and lineup choices start to matter before the deadline.",
  },
  {
    num: "03 · trade deadline",
    title: "Trade under pressure",
    body: "Negotiate with eleven scripted rivals. Partners apply hidden valuation noise each season, so what looked fair in preseason may fail at the deadline. Illegal proposals are rejected and penalized.",
  },
  {
    num: "04 · draft",
    title: "Invest in the future",
    body: "Spend draft capital on a seeded prospect class while opponents pick in inverse-standings order. Aging, development, and injuries play out across the season simulation and playoffs.",
  },
];

const SCORE_TERMS = [
  { term: "Wins & playoffs", weight: "recent form" },
  { term: "Championships", weight: "largest single reward" },
  { term: "Assets & youth", weight: "roster + age ≤ 24" },
  { term: "Picks & cap", weight: "future capital" },
  { term: "Lineup strength", weight: "dressed roster" },
  { term: "Illegal actions", weight: "−2.5 each" },
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

export default function HowItWorks() {
  return (
    <section className="section" id="how-it-works">
      <div className="shell">
        <Reveal className="section-head">
          <p className="section-kicker">The decision loop</p>
          <h2>Four phases per season. Five seasons per episode.</h2>
          <p>
            No browser automation, no memorized rosters — every player is fictional. Agents
            speak a minimal JSON protocol: observation on stdin, actions on stdout, optional
            memo for cross-decision memory.
          </p>
        </Reveal>

        <div className="loop-grid loop-grid-4">
          {PHASES.map((phase, index) => (
            <Reveal key={phase.num} as="article" className="loop-card" delay={index * 70}>
              <p className="loop-num">{phase.num}</p>
              <h3>{phase.title}</h3>
              <p>{phase.body}</p>
            </Reveal>
          ))}
        </div>

        <Reveal className="score-strip" delay={80}>
          <div>
            <p className="section-kicker">How scoring works</p>
            <h3>Strategy first. Protocol penalties broken out.</h3>
            <p>
              The headline score rewards wins, titles, assets, youth, picks, cap health, and
              dressed strength — then subtracts illegal actions. Artifacts report strategy score
              and protocol penalty separately so JSON discipline is not confused with GM skill.
            </p>
            <p className="score-link">
              Full weights live in{" "}
              <a
                href="https://github.com/nedcut/gm-bench/blob/main/docs/scoring_calibration.md"
                target="_blank"
                rel="noreferrer"
              >
                scoring_calibration.md
              </a>
              .
            </p>
          </div>
          <ul className="score-terms">
            {SCORE_TERMS.map((item) => (
              <li key={item.term}>
                <strong>{item.term}</strong>
                <span>{item.weight}</span>
              </li>
            ))}
          </ul>
        </Reveal>

        <Reveal className="protocol-grid" delay={120}>
          <div className="proto-points">
            <div className="proto-point">
              <span className="proto-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3v12m0 0 4-4m-4 4-4-4M4 21h16" />
                </svg>
              </span>
              <div>
                <h4>Observation on stdin</h4>
                <p>
                  One JSON object per decision: roster, lineup, cap, standings, free agents,
                  draft class, trade market, and your memo scratchpad.
                </p>
              </div>
            </div>
            <div className="proto-point">
              <span className="proto-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 21V9m0 0-4 4m4-4 4 4M4 3h16" />
                </svg>
              </span>
              <div>
                <h4>Actions on stdout</h4>
                <p>
                  Reply with a JSON array. Core verbs: sign, trade, draft, set_lineup, memo —
                  plus negotiation, scouting, and waiver claims in protocol v2.
                </p>
              </div>
            </div>
            <div className="proto-point">
              <span className="proto-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 12a9 9 0 0 1-15 6.7L3 16m0-4a9 9 0 0 1 15-6.7L21 8M3 16v-4h4M21 8v4h-4" />
                </svg>
              </span>
              <div>
                <h4>Deterministic replay</h4>
                <p>
                  Leagues, development, and injuries derive from the seed. Same agent, same
                  seed, same episode — every time.
                </p>
              </div>
            </div>
          </div>
          <div className="proto-code-col">
            <CodeCard title="observation → stdin" code={OBSERVATION_SNIPPET} />
            <CodeCard title="actions ← stdout" code={ACTIONS_SNIPPET} />
          </div>
        </Reveal>
      </div>
    </section>
  );
}
