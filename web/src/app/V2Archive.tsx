import type { Leaderboard } from "../types";
import { REPO_BLOB, routes } from "../site";
import Workspace from "./Workspace";
import { StandingsSection } from "./Standings";

/* GM-Bench 2.0, kept for the record: its board as the site last showed it,
   under score-v2, with its own pick-trader. Superseded by 2.1 on 2026-10-16. */
export default function V2Archive({ data }: { data: Leaderboard }) {
  return (
    <Workspace data={data} contract="2.0" hint="Select a row for its details.">
      {(view) => (
        <div className="stats-content">
          <div className="view archive-head">
            <h1>GM-Bench 2.0 archive</h1>
            <p className="lede">
              Superseded by <a href={routes.standings}>GM-Bench 2.1</a> on 2026-10-16. 2.1 is 2.0 with three simulator
              fixes and score-v2. Scores are not comparable across the two contracts: each row here is compared only
              with pick-trader under 2.0 (contract {view.lane.fingerprint ?? "—"}).
            </p>
            <p className="view-note">
              The 2.0 rows were played under score-v1 and are shown rescored with score-v2 from their recorded games;
              each row's score-v1 numbers are in its details.{" "}
              <a href={`${REPO_BLOB}docs/bench_v2_spec.md`}>2.0 specification</a> ·{" "}
              <a href={`${REPO_BLOB}docs/REPRODUCING_GM_BENCH_2_0.md`}>Reproduce</a>
            </p>
          </div>
          <nav className="stats-index" aria-label="Archive">
            <span className="stats-count">{view.shown.length} of {view.models.length} models</span>
            {view.filterButton}
          </nav>
          <StandingsSection view={view} />
        </div>
      )}
    </Workspace>
  );
}
