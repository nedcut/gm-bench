/* Page URLs, built from Vite's base so they work at "/" locally and at
   "/gm-bench/" on GitHub Pages. */
const BASE = import.meta.env.BASE_URL;

export const routes = {
  home: BASE,
  results: `${BASE}results/`,
  replays: `${BASE}replays/`,
  protocol: `${BASE}protocol/`,
  media: `${BASE}media/`,
} as const;

export type PageKey = "home" | "results" | "replays" | "protocol";

export const REPO = "https://github.com/nedcut/gm-bench";
export const REPO_BLOB = `${REPO}/blob/main/`;

/* The site used to be one long page addressed by hash. Links to those anchors
   are out in the wild, so the home page forwards each old hash to the page the
   section now lives on. */
const LEGACY_HASHES: Record<string, string> = {
  "#results": `${routes.results}#results`,
  "#profile": `${routes.results}#profile`,
  "#analysis": `${routes.results}#analysis`,
  "#decision-lane": `${routes.results}#decision-lane`,
  "#agentic-lane": `${routes.results}#agentic-lane`,
  "#replay": `${routes.replays}#replay`,
  "#protocol": `${routes.protocol}#protocol`,
};

export function forwardLegacyHash(): void {
  const forward = () => {
    const target = LEGACY_HASHES[window.location.hash];
    if (target) window.location.replace(target);
  };
  forward();
  window.addEventListener("hashchange", forward);
}
