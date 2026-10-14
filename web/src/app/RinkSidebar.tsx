import RinkBoard from "./RinkBoard";

const PHASES = [
  { title: "Preseason", detail: "Sign, extend, set the lineup" },
  { title: "Midseason", detail: "Adapt to injuries and waivers" },
  { title: "Trade deadline", detail: "Make the final trades" },
  { title: "Draft", detail: "Scout the next generation" },
];

/** A schematic rink, rather than a representation of a recorded game. */
export default function RinkSidebar({ step, replay = false }: { step?: number; replay?: boolean }) {
  return (
    <aside className="rink-sidebar" aria-label="Season at a glance">
      <div className="rink-eyebrow">GM-Bench / Front office</div>
      <h2>{replay ? "Every move matters." : "Build a contender."}</h2>
      <p className="rink-intro">{replay ? "Follow the decisions behind the team." : "One team. Five seasons. Your decisions."}</p>
      <RinkBoard />
      <div className="rink-caption">The season, at a glance</div>
      <ol className="rink-phases">
        {PHASES.map((phase, i) => <li key={phase.title} className={step === i + 1 ? "is-active" : undefined}>
          <span className="rink-phase-number">0{i + 1}</span>
          <div><strong>{phase.title}</strong><span>{phase.detail}</span></div>
          {step === i + 1 && <span className="sr-only">Current walkthrough phase</span>}
        </li>)}
      </ol>
      <p className="rink-footnote">{replay ? "A front-office simulation: replays track GM decisions, not on-ice play." : "The GM makes the moves. The simulator plays the games."}</p>
    </aside>
  );
}
