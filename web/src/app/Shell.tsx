import type { ReactNode } from "react";
import { useTheme } from "../theme";
import { REPO, routes, type PageKey } from "../site";
import type { Leaderboard } from "../types";

const TABS: { page: PageKey; label: string }[] = [
  { page: "standings", label: "Standings" },
  { page: "cost", label: "Score vs cost" },
  { page: "tools", label: "Tool use" },
  { page: "replays", label: "Replays" },
];

function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const dark = theme === "dark";
  return (
    <button type="button" className="icon-button" onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
      {dark ? (
        <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><circle cx="10" cy="10" r="3.6" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M10 1.8v2.2M10 16v2.2M1.8 10H4M16 10h2.2M4.2 4.2l1.6 1.6M14.2 14.2l1.6 1.6M4.2 15.8l1.6-1.6M14.2 5.8l1.6-1.6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
      ) : (
        <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M16.5 12.4A7 7 0 0 1 7.6 3.5a7 7 0 1 0 8.9 8.9Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></svg>
      )}
    </button>
  );
}

export default function Shell({ page, data, children }: { page: PageKey; data: Leaderboard; children: ReactNode }) {
  const contract = data.agentic_lane?.[0]?.contract;
  return (
    <div className={`app page-${page}`}>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <a className="wordmark" href={routes.standings}>
          <img src={`${import.meta.env.BASE_URL}favicon.svg`} width="22" height="22" alt="" aria-hidden="true" />
          GM-Bench
        </a>
        <nav className="tabs" aria-label="Views">
          {TABS.map((tab) => (
            <a key={tab.page} href={routes[tab.page]} aria-current={tab.page === page ? "page" : undefined}>
              {tab.label}
            </a>
          ))}
        </nav>
        <div className="topbar-end">
          <a className="topbar-link" href={REPO}>GitHub</a>
          <ThemeToggle />
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        {children}
      </main>
      <footer className="footer">
        <span>
          GM-Bench 2.0{contract ? ` · contract ${contract.agentic_fingerprint}` : ""}
          {data.updated ? ` · updated ${data.updated}` : ""} · by <a href="https://github.com/nedcut">Ned Cutler</a>
        </span>
        <nav aria-label="More">
          <a href={routes.method} aria-current={page === "method" ? "page" : undefined}>Method</a>
          <a href={routes.v1} aria-current={page === "v1" ? "page" : undefined}>1.0 archive</a>
          <a href={`${REPO_BLOB_DOC}`}>Reproduce</a>
        </nav>
      </footer>
    </div>
  );
}

const REPO_BLOB_DOC = `${REPO}/blob/main/docs/REPRODUCING_GM_BENCH_2_0.md`;
