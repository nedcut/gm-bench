import type { Leaderboard } from "../types";
import { REPO_BLOB, routes } from "../site";
import { laneOf, num } from "../v2";
import ReplayVerifier from "../components/ReplayVerifier";
import "../legacy.css";

const PHASES = [
  ["Preseason", "Sign free agents, extend contracts, set an 18-player lineup."],
  ["Midseason", "Claim waived players, or keep the cap room."],
  ["Trade deadline", "Trade with 11 scripted rival front offices."],
  ["Draft", "Pick from a seeded prospect class."],
];

/* Copied from ScoreScaleV2 in gm_bench/v21/scoring.py (score-v2). */
const SCORE_ROWS = [
  ["Wins", "+1.02", "per regular-season win, every season"],
  ["Playoff rounds", "+9", "per expected round won, last three seasons"],
  ["Championships", "+35", "per expected title, every season"],
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

# one 2.1 episode through a harness (spends that harness's quota)
python -m gm_bench agentic --contract 2.1 --harness claude --model claude-sonnet-5-5 \\
  --seeds 1 --seasons 5 --isolation container --output /tmp/gm-run`;

export default function Method({ data }: { data: Leaderboard }) {
  const { seeds, bar } = laneOf(data, "2.1");
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

      <h2>How a game is played</h2>
      <ul>
        <li>The model runs inside its own agent harness (Claude Code, Codex, Cursor or OpenCode) as one session per five-season game.</li>
        <li>It reads the league and makes moves through tools on an MCP server, then ends each phase itself.</li>
        <li>The harness runs in a firewalled container, so it cannot read the private seeds from the machine. The container still reaches the public internet.</li>
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
      <p>
        This is score-v2. Playoffs are single games, so the score counts each playoff run by its odds, worked out exactly
        from the bracket and the team ratings the simulator used, not by which coin flips landed. The playoffs are
        still played and still decide the champion; over many games the expected and actual results agree, but the
        expected ones don't swing from seed to seed. Every season's own wins count equally.
      </p>
      <p>
        Assets count at the end of season five, so trading away the future for one good season loses points. Simulating
        five more seasons from each final league shows the end-of-game assets are worth about what they score.
      </p>
      <p>
        GM-Bench 2.1 is played and scored this way: 2.0 with three simulator fixes and this score. Team records reset
        each season, rival teams use every draft pick they own, and playoff runs count by their odds. The 2.0 rows were
        played under score-v1, which scored realized playoff results and, because team records never reset, weighted
        early seasons' wins most; they are kept, rescored with score-v2, in the <a href={routes.v2}>2.0 archive</a>.
        Scores are not comparable across the two contracts.{" "}
        <a href={`${REPO_BLOB}docs/bench_v2_1_spec.md`}>What 2.1 changed</a>,{" "}
        <a href={`${REPO_BLOB}docs/score_v2_proposal.md`}>Why the score changed</a>,{" "}
        <a href={`${REPO_BLOB}docs/score_deep_dive.md`}>how it was tested</a>.
      </p>

      <h2>How rows are compared</h2>
      <ul>
        <li>
          Every row plays the same {seeds ?? "—"} private seeds. Its only test is against pick-trader
          under 2.1 ({num(bar)}) on those seeds: the mean per-seed difference, a 95% bootstrap interval, and a
          sign-flip p-value.
        </li>
        <li>Rows are never tested against each other. The standings are sorted by score for reading, not ranked.</li>
        <li>The other scripted bots are context only, hidden unless you turn on Show bots in the filter.</li>
        <li>
          This panel reliably detects a difference of about 13 points under 2.1; smaller ones can't always be told
          apart from zero (it took 20 to 37 under score-v1, when playoff luck was in the score). "Not significant" means
          the panel can't tell, not that a row matches pick-trader.
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
        <a href={`${REPO_BLOB}docs/bench_v2_1_spec.md`}>2.1 specification</a>,{" "}
        <a href={`${REPO_BLOB}docs/bench_v2_spec.md`}>2.0 specification</a>,{" "}
        <a href={`${REPO_BLOB}docs/REPRODUCING_GM_BENCH_2_0.md`}>checking the 2.0 rows</a>.
      </p>

      <h2>Check a recorded game in your browser</h2>
      <p>This replays a committed game with the real simulator, compiled to WebAssembly, and checks it lands on the recorded final state.</p>
      <div className="legacy">
        <ReplayVerifier />
      </div>

      <p className="view-note">
        Earlier versions: the <a href={routes.v2}>2.0 archive</a> and the single-prompt{" "}
        <a href={routes.v1}>1.0 archive</a>.
      </p>
    </article>
  );
}
