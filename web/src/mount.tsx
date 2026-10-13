import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import leaderboardData from "./data/leaderboard.json";
import type { Leaderboard } from "./types";
import type { PageKey } from "./site";
import Shell from "./app/Shell";
import "./app.css";

export const leaderboard = leaderboardData as Leaderboard;

export function mountPage(page: PageKey, children: ReactNode) {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <Shell page={page} data={leaderboard}>
        {children}
      </Shell>
    </StrictMode>,
  );
}
