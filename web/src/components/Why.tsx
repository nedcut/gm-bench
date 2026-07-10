const POINTS = [
  {
    title: "Not coding. Not trivia. Not UI clicking.",
    body: "Most agent benches score patches, answers, or browser steps. GM-Bench scores multi-season resource allocation: contracts, trades, drafts, cap, and lineups under noisy ratings and delayed payoffs.",
  },
  {
    title: "Fictional leagues, fixed seeds",
    body: "Every player is synthetic, so memorized NHL/NBA knowledge does not help. The same seed produces the same league for every agent — paired lifts cancel generation luck.",
  },
  {
    title: "A scripted bar, not a vibes score",
    body: "Results are judged against a calibrated ladder ending at pick-trader. Beat that bar on the official panel before claiming frontier GM skill — and read the CI, not just the mean.",
  },
];

export default function Why() {
  return (
    <section className="section" id="why">
      <div className="shell">
        <div className="section-head">
          <p className="section-kicker">Why it exists</p>
          <h2>A stress test for long-horizon decisions — not another leaderboard of one-shot answers.</h2>
          <p>
            Treat GM-Bench as a diagnostic for whether an agent can stay coherent across
            twenty structured decisions with hidden information and a hard objective. Small
            score gaps on eight seeds are underpowered; clearing the scripted bar is the
            claim that matters.
          </p>
        </div>
        <div className="why-grid">
          {POINTS.map((point) => (
            <article key={point.title} className="why-card">
              <h3>{point.title}</h3>
              <p>{point.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
