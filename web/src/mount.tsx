import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import leaderboardData from "./data/leaderboard.json";
import type { Leaderboard } from "./types";
import type { PageKey } from "./site";
import Nav from "./components/Nav";
import Footer from "./components/Footer";
import "./index.css";
import "./site.css";

export const leaderboard = leaderboardData as Leaderboard;

/* Every page shares the nav, the skip link, and the footer; only <main> differs. */
export function mountPage(page: PageKey, children: ReactNode) {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Nav contract={leaderboard.contract?.benchmark_version} page={page} />
      <main id="main" tabIndex={-1}>
        {children}
      </main>
      <Footer data={leaderboard} />
    </StrictMode>,
  );
}
