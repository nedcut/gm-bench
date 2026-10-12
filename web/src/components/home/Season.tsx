import { routes } from "../../site";
import { PHASES } from "../../content";

const FACTS = [
  { title: "JSON in, JSON out", body: "Any process that reads an observation and writes an action batch can play: a chat model, a coding agent, or your own script." },
  { title: "Same seed, same league", body: "Leagues, development rolls and injuries all derive from the seed, so agents begin in the same league. Their actions can change subsequent trajectories." },
  { title: "Scored like a dynasty", body: "Wins, titles, prospects, future picks and cap health all count, so mortgaging the future for one season does not pay." },
];

/* How a season plays, in four zones of the rink. */
export default function Season() {
  return (
    <section className="season" aria-labelledby="season-title">
      <div className="shell">
        <p className="eyebrow">How it plays</p>
        <h2 id="season-title" className="display-2">
          Five seasons. Four decision windows.
        </h2>
        <ol className="zones">
          {PHASES.map((phase) => (
            <li key={phase.num} className="zone">
              <span className="zone-num" aria-hidden="true">
                {phase.num}
              </span>
              <p className="zone-when">{phase.when}</p>
              <h3>{phase.title}</h3>
              <p>{phase.body}</p>
            </li>
          ))}
        </ol>
        <div className="facts">
          {FACTS.map((fact) => (
            <div key={fact.title} className="fact">
              <h3>{fact.title}</h3>
              <p>{fact.body}</p>
            </div>
          ))}
        </div>
        <a className="link-arrow" href={routes.protocol}>
          Read the full protocol
        </a>
      </div>
    </section>
  );
}
