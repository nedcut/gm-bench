import type { Snapshot } from "../types";
import { Logo } from "./Nav";

export default function Footer({ snapshot }: { snapshot: Snapshot }) {
  const { config } = snapshot;
  return (
    <footer className="footer">
      <div className="shell footer-inner">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Logo size={22} />
          <span>
            GM-Bench · deterministic front-office benchmark for LLM agents
          </span>
        </div>
        <div className="footer-links">
          <a href="#results">Results</a>
          <a href="#how-it-works">Protocol</a>
          <a href="#quickstart">Quickstart</a>
        </div>
        <span>
          reference snapshot · {config.candidate} vs {config.baselines.join(", ")} · seeds{" "}
          {config.seeds.join(" ")} × {config.seasons} seasons
        </span>
      </div>
    </footer>
  );
}
