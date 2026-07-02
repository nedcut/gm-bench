import type { Snapshot } from "../types";
import { Logo } from "./Nav";

export default function Footer({ snapshot }: { snapshot: Snapshot }) {
  const generated = new Date(snapshot.generated_at);
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
          reference results generated{" "}
          {generated.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}
        </span>
      </div>
    </footer>
  );
}
