import type { ReactNode } from "react";
import type { Player } from "./types";

export const PHASES = ["preseason", "midseason", "trade_deadline", "draft"];
export const LABEL: Record<string, string> = {
  preseason: "Preseason",
  midseason: "Midseason",
  trade_deadline: "Trade deadline",
  draft: "Draft",
};
export const NEXT: Record<string, string> = {
  preseason: "Simulate to midseason",
  midseason: "Open trade deadline",
  trade_deadline: "Open the draft",
  draft: "Finish season",
};
export const NOTE: Record<string, string> = {
  preseason:
    "Extend expiring contracts, sign free agents, and set your lineup before the first games.",
  midseason:
    "The first games are in the books. Check the standings, claim waivers, and adjust your lineup.",
  trade_deadline:
    "Review incoming offers or build a deal. Rival teams also make moves when you advance.",
  draft:
    "Spend scouting points and use every pick you own. Finishing this phase plays the remaining games and playoffs, ages players, and expires contracts.",
};
export const SCORE_LABEL: Record<string, string> = {
  recent_wins: "Recent wins",
  playoff_rounds: "Playoff rounds",
  championships: "Championships",
  total_assets: "Roster assets",
  young_assets: "Young assets",
  future_pick_assets: "Future picks",
  cap_room: "Cap room",
  current_strength: "Lineup strength",
  roster_depth: "Roster depth",
};
export const VIEWS = [
  "Office",
  "Roster",
  "Free agents",
  "Trades",
  "Draft",
  "League",
  "History",
  "Rules",
] as const;
export type View = (typeof VIEWS)[number];
export const money = (n: number) => `$${n.toFixed(2)}M`;
export const rating = (n: number) => n.toFixed(1);
export const ranked = (players: Player[]) =>
  [...players].sort((a, b) => b.overall - a.overall);
export type Act = (tool: string, args?: Record<string, unknown>) => void;
export type Review = (
  title: string,
  body: ReactNode,
  tool: string,
  args?: Record<string, unknown>,
) => void;
