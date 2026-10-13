import { routes } from "../site";

/* The four decisions of a season, as the zones of the rink they are drawn on. */
const PHASES = [
  ["Preseason", "Sign, extend, set the lineup"],
  ["Midseason", "Claim from waivers"],
  ["Trade deadline", "Deal with 11 rival GMs"],
  ["Draft", "Pick from the prospect class"],
] as const;

export default function SeasonStrip() {
  return (
    <section className="season-strip" aria-labelledby="season-title">
      <h2 id="season-title">Five seasons, four calls each</h2>
      <ol>
        {PHASES.map(([phase, what], i) => (
          <li key={phase} className={i === 2 ? "is-red" : undefined}>
            <span>{phase}</span>
            {what}
          </li>
        ))}
      </ol>
      <a className="text-link" href={routes.method}>
        How a game is scored
      </a>
    </section>
  );
}
