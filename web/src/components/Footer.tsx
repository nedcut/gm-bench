import type { Leaderboard as LeaderboardData } from "../types";
import { Logo } from "./Nav";

export default function Footer({ data }: { data: LeaderboardData }) {
  return (
    <footer className="footer">
      <div className="shell footer-inner">
        <div className="footer-brand">
          <div>
            <Logo size={22} />
            <span>GM-Bench · a pre-registered front-office benchmark for LLM agents</span>
          </div>
          <a className="byline" href="https://github.com/nedcut">
            Built by Ned Cutler
          </a>
        </div>
        <div className="footer-links">
          <a href="https://github.com/nedcut/gm-bench">GitHub</a>
          <a href="https://github.com/nedcut/gm-bench/blob/main/docs/blog/sota-v2-findings.md">
            Findings
          </a>
          <a href="https://github.com/nedcut/gm-bench/releases/tag/sota-v2-phase-one-2026-07-19">
            Evidence release
          </a>
          <a href="https://github.com/nedcut/gm-bench/blob/main/docs/REPRODUCING_SOTA_V2_RELEASE.md">
            Reproduce
          </a>
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
