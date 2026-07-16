import type { Leaderboard as LeaderboardData } from "../types";
import { Logo } from "./Nav";

export default function Footer({ data }: { data: LeaderboardData }) {
  return (
    <footer className="footer">
      <div className="shell footer-inner">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Logo size={22} />
          <span>GM-Bench · a pre-registered front-office benchmark for LLM agents</span>
        </div>
        <div className="footer-links">
          <a href="https://github.com/nedcut/gm-bench">GitHub</a>
          <a href="#leaderboard">The board</a>
          <a href="#protocol">Protocol</a>
          <a href="#quickstart">Quickstart</a>
        </div>
        <span className="mono">
          {data.contract
            ? `${data.contract.benchmark_version} · contract ${data.contract.contract_fingerprint}`
            : "sota-v2"}
          {data.updated ? ` · data updated ${data.updated}` : " · no official model rows yet"}
        </span>
      </div>
    </footer>
  );
}
