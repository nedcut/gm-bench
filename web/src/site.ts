/* Page URLs, built from Vite's base so they work at "/" locally and at
   "/gm-bench/" on GitHub Pages. */
// "/" outside Vite, where the chart tests render components directly.
const BASE = import.meta.env?.BASE_URL ?? "/";

export const routes = {
  standings: BASE,
  how: `${BASE}how-it-works/`,
  cost: `${BASE}cost/`,
  tools: `${BASE}tools/`,
  play: `${BASE}play/`,
  replays: `${BASE}replays/`,
  method: `${BASE}method/`,
  v2: `${BASE}v2/`,
  v1: `${BASE}v1/`,
} as const;

export type PageKey = keyof typeof routes;

export const REPO = "https://github.com/nedcut/gm-bench";
export const REPO_BLOB = `${REPO}/blob/main/`;
