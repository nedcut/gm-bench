import type { Snapshot } from "../types";
import { fmt, pct } from "../lib";

export default function Hero({ snapshot }: { snapshot: Snapshot }) {
  const { normalized, paired, config } = snapshot;
  return (
    <section className="hero" id="top">
      <div className="hero-glow" />
      <div className="hero-grid-lines" />
      <div className="shell hero-inner">
        <div>
          <span className="hero-kicker">
            <i className="dot" />
            Deterministic · Seeded · API-first
          </span>
          <h1>
            Can your agent run a <span className="grad">franchise front office</span>?
          </h1>
          <p className="hero-sub">
            GM-Bench drops LLM agents into a fictional hockey-style league for multi-season
            episodes: contracts, trades, drafts, cap pressure, and lineups. Every league is
            seeded and replayable, so scores measure strategy — not luck or UI automation.
          </p>
          <div className="hero-actions">
            <a className="btn-primary" href="#quickstart">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="m8 5 11 7-11 7V5Z" />
              </svg>
              Get started
            </a>
            <a className="btn-ghost" href="#how-it-works">
              Read the protocol
            </a>
          </div>
          <div className="hero-stats-label">
            Scripted reference baseline · {config.candidate} vs {config.baselines.join(", ")}
          </div>
          <div className="hero-stats">
            <div className="hero-stat">
              <strong>+{fmt(normalized.score_lift_pct, 0)}%</strong>
              <span>value agent lift vs panel</span>
            </div>
            <div className="hero-stat">
              <strong>{pct(paired.candidate_seed_win_rate)}</strong>
              <span>seed win rate</span>
            </div>
            <div className="hero-stat">
              <strong>{config.seeds.length}×{config.seasons}</strong>
              <span>seeds × seasons per eval</span>
            </div>
            <div className="hero-stat">
              <strong>{paired.significant_at_95 ? "95% CI ✓" : "n.s."}</strong>
              <span>paired bootstrap significance</span>
            </div>
          </div>
        </div>

        <div className="terminal" aria-label="Example benchmark run">
          <div className="terminal-bar">
            <i /><i /><i />
            <span>gm-bench — evaluate</span>
          </div>
          <div className="terminal-body">
            <span className="t-prompt">$ </span>
            <span className="t-cmd">python -m gm_bench evaluate</span>
            {"\n"}
            <span className="t-flag">    --agent-cmd</span> <span className="t-str">"python my_agent.py"</span>
            {"\n"}
            <span className="t-flag">    --seeds</span> <span className="t-num">1 2 3 4 5</span> <span className="t-flag">--seasons</span> <span className="t-num">5</span>
            {"\n\n"}
            <span className="t-dim">{"// observation → stdin, actions → stdout"}</span>
            {"\n"}
            <span className="t-out">{"["}</span>
            {"\n  "}
            <span className="t-out">{"{"}</span>
            <span className="t-key">"type"</span>
            <span className="t-out">: </span>
            <span className="t-str">"sign_free_agent"</span>
            <span className="t-out">, </span>
            <span className="t-key">"player_id"</span>
            <span className="t-out">: </span>
            <span className="t-num">294</span>
            <span className="t-out">{"}"},</span>
            {"\n  "}
            <span className="t-out">{"{"}</span>
            <span className="t-key">"type"</span>
            <span className="t-out">: </span>
            <span className="t-str">"trade"</span>
            <span className="t-out">, </span>
            <span className="t-key">"partner_team_id"</span>
            <span className="t-out">: </span>
            <span className="t-num">3</span>
            <span className="t-out">, </span>
            <span className="t-key">"give_player_ids"</span>
            <span className="t-out">: </span>
            <span className="t-out">[</span>
            <span className="t-num">11</span>
            <span className="t-out">], </span>
            <span className="t-key">"receive_player_ids"</span>
            <span className="t-out">: </span>
            <span className="t-out">[</span>
            <span className="t-num">87</span>
            <span className="t-out">]</span>
            <span className="t-out">{"}"},</span>
            {"\n  "}
            <span className="t-out">{"{"}</span>
            <span className="t-key">"type"</span>
            <span className="t-out">: </span>
            <span className="t-str">"draft"</span>
            <span className="t-out">, </span>
            <span className="t-key">"prospect_id"</span>
            <span className="t-out">: </span>
            <span className="t-num">9001</span>
            <span className="t-out">{"}"},</span>
            {"\n  "}
            <span className="t-out">{"{"}</span>
            <span className="t-key">"type"</span>
            <span className="t-out">: </span>
            <span className="t-str">"memo"</span>
            <span className="t-out">, </span>
            <span className="t-key">"text"</span>
            <span className="t-out">: </span>
            <span className="t-str">"target playoff spot; revisit D depth"</span>
            <span className="t-out">{"}"}</span>
            {"\n"}
            <span className="t-out">{"]"}</span>
            {"\n\n"}
            <span className="t-dim">{"// paired, seed-matched scoring"}</span>
            {"\n"}
            <span className="t-key">candidate_mean </span>
            <span className="t-out">= </span>
            <span className="t-num">{fmt(normalized.candidate_mean_score, 3)}</span>
            {"\n"}
            <span className="t-key">paired_lift    </span>
            <span className="t-out">= </span>
            <span className="t-num">+{fmt(paired.paired_lift_mean, 3)}</span>
            {"\n"}
            <span className="t-key">lift_ci95      </span>
            <span className="t-out">= </span>
            <span className="t-num">
              [{fmt(paired.paired_lift_ci95[0], 1)}, {fmt(paired.paired_lift_ci95[1], 1)}]
            </span>
            {"\n"}
            <span className="t-key">significant    </span>
            <span className="t-out">= </span>
            <span className="t-num">{String(paired.significant_at_95)}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
