import { routes } from "../../site";
import { PHASES } from "../../content";

/* How a season plays, in four zones of the rink. */
export default function Season() {
  return (
    <section className="season" aria-labelledby="season-title">
      <div className="shell">
        <h2 id="season-title" className="display-2">
          Five seasons. Four calls a season.
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
        <p className="season-note">
          The score counts wins, titles, prospects, future picks and cap health, so selling the
          future for one good season doesn't pay. The same seed always builds the same league.{" "}
          <a href={routes.protocol}>Full rules</a>
        </p>
      </div>
    </section>
  );
}
