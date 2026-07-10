import type { Leaderboard as LeaderboardData } from "../types";
import { fmt } from "../lib";

export default function Hero({ leaderboard }: { leaderboard: LeaderboardData }) {
  const pickTrader = leaderboard.baselines.find((row) => row.agent === "pick-trader");
  const bestModel = [...leaderboard.models].sort((a, b) => b.mean_score - a.mean_score)[0];
  const bar = pickTrader?.mean_score ?? 0;
  const gap = bestModel ? bestModel.mean_score - bar : null;

  return (
    <section className="hero" id="top">
      <div className="hero-glow" />
      <div className="hero-grid-lines" />
      <div className="shell hero-inner">
        <div className="hero-copy">
          <span className="hero-kicker">
            <i className="dot" />
            Long-horizon · Seeded · JSON protocol
          </span>
          <p className="hero-brand">GM-Bench</p>
          <h1>
            Can your agent run a <span className="grad">franchise front office</span>?
          </h1>
          <p className="hero-sub">
            Multi-season GM decisions under uncertainty: contracts, trades, drafts, cap
            pressure, and lineups. Fictional players. Deterministic seeds. Scores that
            measure strategy — not luck or UI automation.
          </p>
          <div className="hero-actions">
            <a className="btn-primary" href="#quickstart">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="m8 5 11 7-11 7V5Z" />
              </svg>
              Run the benchmark
            </a>
            <a className="btn-ghost" href="#leaderboard">
              See the bar to beat
            </a>
          </div>
        </div>

        <div className="terminal hero-terminal" aria-label="Official bar to beat">
          <div className="terminal-bar">
            <i /><i /><i />
            <span>official panel · {leaderboard.preset.seeds.length} seeds × {leaderboard.preset.seasons} seasons</span>
          </div>
          <div className="terminal-body">
            <span className="t-dim">{"// scripted bar to beat"}</span>
            {"\n"}
            <span className="t-key">pick-trader </span>
            <span className="t-out">= </span>
            <span className="t-num">{fmt(bar, 1)}</span>
            {"\n\n"}
            <span className="t-dim">{"// best model on this board"}</span>
            {"\n"}
            {bestModel ? (
              <>
                <span className="t-key">{bestModel.model.padEnd(14).slice(0, 14)} </span>
                <span className="t-out">= </span>
                <span className="t-num">{fmt(bestModel.mean_score, 1)}</span>
                {"\n"}
                <span className="t-key">vs pick-trader</span>
                <span className="t-out"> = </span>
                <span className="t-num">
                  {gap !== null && gap >= 0 ? "+" : ""}
                  {gap !== null ? fmt(gap, 1) : "—"}
                </span>
                {"\n\n"}
                <span className="t-dim">{"// honest read: models are still below the bar"}</span>
              </>
            ) : (
              <span className="t-dim">{"// no model rows yet — submit a run"}</span>
            )}
            {"\n\n"}
            <span className="t-prompt">$ </span>
            <span className="t-cmd">python -m gm_bench model</span>
            {"\n"}
            <span className="t-flag">    --preset leaderboard --repeats </span>
            <span className="t-num">3</span>
          </div>
        </div>
      </div>
    </section>
  );
}
