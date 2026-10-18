import { advance, contain, createSkaters, FIXED_STEP, limitSpeed, PUCK_RADIUS, type Skater } from "./rinkPhysics";
import { bounceOffNets, GOAL_LEFT, GOAL_RIGHT, GOAL_TOP, GOAL_BOTTOM, NET_DEPTH } from "./rinkNets";
export { GOAL_LEFT, GOAL_RIGHT, GOAL_TOP, GOAL_BOTTOM } from "./rinkNets";

export const RINK_STORAGE_KEY = "gm-bench.rink.v1";
export const PUCK_INDEX = 12;
export const FACEOFF_DELAY_MS = 1000;
export type ScoringTeam = "home" | "away";
export interface RinkGame {
  bodies: Skater[];
  score: { home: number; away: number };
  puckInGoal: ScoringTeam | null;
}

export function newRinkGame(): RinkGame {
  return {
    bodies: [...createSkaters(), {
      x: 160, y: 235, vx: 0, vy: 0, homeX: 160, homeY: 235, label: "Puck", team: "puck", locked: false,
    }],
    score: { home: 0, away: 0 },
    puckInGoal: null,
  };
}

export function awardGoal(game: RinkGame, team: ScoringTeam): ScoringTeam {
  game.score[team]++;
  const puck = game.bodies[PUCK_INDEX];
  settleInNet(puck, team);
  game.puckInGoal = team;
  return team;
}

/** Drop the puck back on its starting spot so play can resume after a goal. */
export function faceoff(game: RinkGame) {
  const puck = game.bodies[PUCK_INDEX];
  puck.x = puck.homeX; puck.y = puck.homeY;
  puck.vx = puck.vy = 0; puck.locked = false;
  game.puckInGoal = null;
}

function settleInNet(puck: Skater, team: ScoringTeam) {
  puck.x = Math.max(GOAL_LEFT + PUCK_RADIUS + 1, Math.min(GOAL_RIGHT - PUCK_RADIUS - 1, puck.x));
  puck.y = team === "home"
    ? Math.max(GOAL_TOP - NET_DEPTH + PUCK_RADIUS + 1, Math.min(GOAL_TOP - PUCK_RADIUS, puck.y))
    : Math.max(GOAL_BOTTOM + PUCK_RADIUS, Math.min(GOAL_BOTTOM + NET_DEPTH - PUCK_RADIUS - 1, puck.y));
  puck.vx = puck.vy = 0; puck.locked = true;
}

/** Count the entire puck crossing the goal line inside the posts, including a
 * fast diagonal shot. Blue attacks the top goal; red attacks the bottom. */
export function crossedGoal(game: RinkGame, fromX: number, fromY: number): ScoringTeam | null {
  const puck = game.bodies[PUCK_INDEX];
  if (game.puckInGoal) {
    const out = game.puckInGoal === "home" ? puck.y > GOAL_TOP + PUCK_RADIUS : puck.y < GOAL_BOTTOM - PUCK_RADIUS;
    if (out) game.puckInGoal = null;
    else return null;
  }
  const top = GOAL_TOP - PUCK_RADIUS, bottom = GOAL_BOTTOM + PUCK_RADIUS;
  const team = fromY > top && puck.y <= top ? "home" : fromY < bottom && puck.y >= bottom ? "away" : null;
  if (!team) return null;
  const plane = team === "home" ? top : bottom;
  const x = fromX + (puck.x - fromX) * (plane - fromY) / (puck.y - fromY);
  return x >= GOAL_LEFT + PUCK_RADIUS && x <= GOAL_RIGHT - PUCK_RADIUS ? team : null;
}

export function checkGoal(game: RinkGame, fromX: number, fromY: number): ScoringTeam | null {
  const team = crossedGoal(game, fromX, fromY);
  return team ? awardGoal(game, team) : null;
}

/** A puck dropped into the net scores once on release, never while it is held. */
export function scoreDroppedPuck(game: RinkGame): ScoringTeam | null {
  if (game.puckInGoal) return null;
  const puck = game.bodies[PUCK_INDEX];
  if (puck.x < GOAL_LEFT + PUCK_RADIUS || puck.x > GOAL_RIGHT - PUCK_RADIUS) return null;
  if (puck.y >= GOAL_TOP - 20 && puck.y <= GOAL_TOP - PUCK_RADIUS) return awardGoal(game, "home");
  if (puck.y <= GOAL_BOTTOM + 20 && puck.y >= GOAL_BOTTOM + PUCK_RADIUS) return awardGoal(game, "away");
  return null;
}

export function advanceRink(game: RinkGame, dt = FIXED_STEP, held = -1) {
  let scored: ScoringTeam | null = null;
  const moving = advance(game.bodies, dt, held, held === PUCK_INDEX ? undefined : (x, y) => {
    const result = tracePuck(game, x, y);
    scored = result.scored;
    return result.blocked;
  });
  return { moving, scored };
}

export function tracePuck(game: RinkGame, fromX: number, fromY: number) {
  const hit = bounceOffNets(game.bodies[PUCK_INDEX], fromX, fromY);
  const scored = checkGoal(game, fromX, fromY);
  return { scored, blocked: hit || scored !== null };
}

// Persist only the compact simulation state. Labels, teams and geometry are code-owned.
export function encodeRink(game: RinkGame): string {
  return JSON.stringify({ version: 1, score: game.score, puckInGoal: game.puckInGoal,
    bodies: game.bodies.map(({ x, y, vx, vy }) => ({ x, y, vx, vy })) });
}

export function decodeRink(raw: string | null): RinkGame {
  const game = newRinkGame();
  if (!raw) return game;
  try {
    const data = JSON.parse(raw);
    if (data.version !== 1 || !Array.isArray(data.bodies) || data.bodies.length !== 13 ||
      ![data.score?.home, data.score?.away].every(n => Number.isSafeInteger(n) && n >= 0 && n <= 1_000_000) ||
      !data.bodies.every((b: Record<string, unknown>) => b && [b.x, b.y, b.vx, b.vy].every(n => typeof n === "number" && Number.isFinite(n)))) return game;
    game.score = { home: data.score.home, away: data.score.away };
    for (const [i, body] of game.bodies.entries()) {
      const saved = data.bodies[i];
      body.x = saved.x; body.y = saved.y; body.vx = saved.vx; body.vy = saved.vy;
      contain(body); limitSpeed(body);
    }
    // A page closed before the post-goal faceoff resumes with the puck at center.
    if (data.puckInGoal === "home" || data.puckInGoal === "away") faceoff(game);
  } catch { /* A corrupt or older save starts a fresh rink. */ }
  return game;
}

export function loadRink(): RinkGame {
  try { return decodeRink(localStorage.getItem(RINK_STORAGE_KEY)); }
  catch { return newRinkGame(); }
}

export function saveRink(game: RinkGame) {
  try { localStorage.setItem(RINK_STORAGE_KEY, encodeRink(game)); }
  catch { /* The rink still works when browser storage is unavailable. */ }
}
