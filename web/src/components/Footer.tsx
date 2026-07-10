import type { Leaderboard as LeaderboardData } from "../types";
import { Logo } from "./Nav";

const REPO = "https://github.com/nedcut/gm-bench";

export default function Footer({ leaderboard }: { leaderboard: LeaderboardData }) {
  return (
    <footer className="footer">
      <div className="shell footer-inner">
        <div className="footer-brand">
          <Logo size={22} />
          <span>GM-Bench · long-horizon front-office benchmark for LLM agents</span>
        </div>
        <div className="footer-links">
          <a href={REPO} target="_blank" rel="noreferrer">
            GitHub
          </a>
          <a href={`${REPO}/blob/main/docs/production_benchmark.md`} target="_blank" rel="noreferrer">
            Docs
          </a>
          <a href="#leaderboard">Leaderboard</a>
          <a href="#quickstart">Run</a>
        </div>
        <span className="footer-meta">
          official panel · seeds {leaderboard.preset.seeds.join("–")} × {leaderboard.preset.seasons}{" "}
          seasons · updated {leaderboard.updated}
        </span>
      </div>
    </footer>
  );
}
