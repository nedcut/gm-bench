import type { Leaderboard } from "../../types";
import { REPO_BLOB, routes } from "../../site";

const HARNESSES = ["OpenCode", "Codex CLI", "Claude Code", "Cursor CLI"];

/* Argument names and id shapes match gm_bench/agentic/tools.py: player ids
   are small integers, prospect ids are 1_000_000 + season * 10_000 + index. */
const TOOL_LOG = [
  ["→", "get_status", "()"],
  ["→", "list_trade_market", "()"],
  ["→", "inspect_player", "(player_id=41)"],
  ["→", "trade", "(partner_team_id=1, give_player_ids=[7], receive_player_ids=[41])"],
  ["→", "set_lineup", "(player_ids=[18 ids])"],
  ["→", "end_phase", "()"],
  ["→", "list_draft_class", "()"],
  ["→", "draft", "(prospect_id=1010002)"],
] as const;

/* GM-Bench 2.0 on the home page. Deliberately carries no scores or order: 2.0 ranks nothing, and a row's only supported
   comparison is against pick-trader, which the results page shows with its
   interval. Smoke rows never reach the site, so every row counted here is
   panel grade. */
export default function NextUp({ data }: { data: Leaderboard }) {
  const panelRows = (data.agentic_lane ?? []).length;
  return (
    <section className="next" aria-labelledby="next-title">
      <div className="shell next-inner">
        <div>
          <p className="eyebrow">{panelRows === 0 ? "Next · GM-Bench 2.0" : "New · GM-Bench 2.0"}</p>
          <h2 id="next-title" className="display-2">
            One continuous <span className="accent-blue">five-season episode.</span>
          </h2>
          <p>
            In 2.0 the model stops answering one prompt per decision. It plays the whole episode
            inside a real agent harness, acting through an MCP tool server (a standard interface
            for giving a model tools), on the same simulator and a frozen 32-seed private panel.
            A result is tied to model, harness and harness version, and never mixed into a 1.0
            table.
          </p>
          <ul className="harness-chips" aria-label="Supported harnesses">
            {HARNESSES.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
          {panelRows === 0 ? (
            <p className="next-status">
              <span className="status-dot" aria-hidden="true" /> No panel results yet. They will
              appear on the results page when the first panel-grade run is published.
            </p>
          ) : (
            <p className="next-status">
              <span className="status-dot" aria-hidden="true" />
              <span>
                {panelRows} panel {panelRows === 1 ? "row is" : "rows are"} published.{" "}
                <a href={`${routes.results}#agentic-lane`}>See the 2.0 rows on the results page</a>,
                each compared only with pick-trader on the same seeds.
              </span>
            </p>
          )}
          <a className="link-arrow" href={`${REPO_BLOB}docs/bench_v2_spec.md`}>
            Read the 2.0 design
          </a>
        </div>
        <div className="terminal" aria-hidden="true">
          <div className="terminal-bar">
            <span>mcp · gm-bench tools</span>
            <span className="accent-red">season 1 / 5</span>
          </div>
          <ol>
            {TOOL_LOG.map(([dir, name, args], i) => (
              <li key={i} style={{ animationDelay: `${i * 0.35}s` }}>
                <span className="accent-blue">{dir}</span> <b>{name}</b>
                <span className="terminal-dim">{args}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
