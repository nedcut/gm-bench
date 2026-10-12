import type { Leaderboard } from "../types";
import { REPO_BLOB, routes } from "../site";
import { num, pickTraderScore, seedCount } from "../v2";
import ReplayVerifier from "../components/ReplayVerifier";
import "../legacy.css";

const PHASES = [
  ["Preseason", "Sign free agents, extend contracts, set an 18-player lineup."],
  ["Midseason", "Claim waived players, or keep the cap room."],
  ["Trade deadline", "Trade with 11 scripted rival front offices."],
  ["Draft", "Pick from a seeded prospect class."],
];

/* Copied from SCORE_SCALES["score-v1"] in gm_bench/scoring.py (frozen). */
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
  ["Illegal move", "−2.5", "each rejected move"],
];

const RUN = `# a scripted bot, offline
python -m gm_bench run --agent pick-trader --seeds 1 2 3 --seasons 5

# one 2.0 episode through a harness (spends that harness's quota)
python -m gm_bench agentic --harness claude --model claude-sonnet-5 \\
  --seeds 1 --seasons 5 --isolation container --output /tmp/gm-run`;

export default function Method({ data }: { data: Leaderboard }) {
  const seeds = seedCount(data);
  return (
    <article className="page">
      <h1>Method</h1>
      <p className="lede">
        An agent runs one fictional hockey team for five seasons. Every league is built from a seed, so the same seed
        always plays out the same way for the same moves.
      </p>

      <h2>A season</h2>
      <table className="data-table">
        <tbody>
          {PHASES.map(([phase, what]) => (
            <tr key={phase}>
              <th scope="row">{phase}</th>
              <td>{what}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>How a 2.0 game is played</h2>
      <ul>
        <li>The model runs inside its own agent harness (Claude Code, Codex, Cursor or OpenCode) as one session per five-season game.</li>
        <li>It reads the league and makes moves through tools on an MCP server, then ends each phase itself.</li>
        <li>The harness runs in a firewalled container, so it cannot read the private seeds from the machine.</li>
        <li>Tool calls, tokens, cost and time are recorded beside the score, never capped and never part of it.</li>
      </ul>

      <h2>The score</h2>
      <table className="data-table">
        <thead>
          <tr>
            <th>Component</th>
            <th className="r">Points</th>
            <th>Unit</th>
          </tr>
        </thead>
        <tbody>
          {SCORE_ROWS.map(([name, points, unit]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td className="r">{points}</td>
              <td>{unit}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>Assets count at the end of season five, so trading away the future for one good season loses points.</p>

      <h2>How rows are compared</h2>
      <ul>
        <li>
          Every row plays the same {seeds ?? "—"} private seeds. Its only test is against pick-trader
          ({num(pickTraderScore(data))}) on those seeds: the mean per-seed difference, a 95% bootstrap interval, and a
          sign-flip p-value.
        </li>
        <li>Rows are never tested against each other. The standings are sorted by score for reading, not ranked.</li>
        <li>The other scripted bots are shown for context only.</li>
        <li>
          Per-seed differences vary more than the panel was sized for, so a difference smaller than about 20 to 36
          points can't be told apart from zero. "Not significant" means the panel can't tell, not that a row matches
          pick-trader.
        </li>
      </ul>

      <h2>Caveats</h2>
      <ul>
        <li>No row pins its model version, so rows may not reproduce.</li>
        <li>Each harness ran at its default reasoning effort.</li>
        <li>Harnesses give the model different extra tools. Claude Code ran without web tools; Codex and OpenCode ship them. No panel agent used the web.</li>
        <li>Cost is billed where a harness reports it, an API list-price estimate where it reports tokens only, and unmeasured otherwise.</li>
      </ul>

      <h2>Run it yourself</h2>
      <pre className="code-block">
        <code>{RUN}</code>
      </pre>
      <p>
        Full guides: <a href={`${REPO_BLOB}docs/agentic_lane.md`}>operator guide</a>,{" "}
        <a href={`${REPO_BLOB}docs/bench_v2_spec.md`}>2.0 specification</a>,{" "}
        <a href={`${REPO_BLOB}docs/REPRODUCING_GM_BENCH_2_0.md`}>checking the published rows</a>.
      </p>

      <h2>Check a recorded game in your browser</h2>
      <p>This replays a committed game with the real simulator, compiled to WebAssembly, and checks it lands on the recorded final state.</p>
      <div className="legacy">
        <ReplayVerifier />
      </div>

      <p className="view-note">
        The earlier single-prompt version is in the <a href={routes.v1}>1.0 archive</a>.
      </p>
    </article>
  );
}
