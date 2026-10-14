import { advance, contain, createSkaters, FIXED_STEP, limitSpeed, PUCK_RADIUS, type Skater } from "./rinkPhysics";

export const RINK_STORAGE_KEY = "gm-bench.rink.v1";
export const PUCK_INDEX = 12;
export const GOAL_LEFT = 138;
export const GOAL_RIGHT = 182;
export const GOAL_TOP = 67;
export const GOAL_BOTTOM = 403;
export type ScoringTeam = "home" | "away";
export interface RinkGame {
  bodies: Skater[];
  score: { home: number; away: number };
}

export function newRinkGame(): RinkGame {
  return {
    bodies: [...createSkaters(), {
      x: 160, y: 255, vx: 0, vy: 0, homeX: 160, homeY: 255, label: "Puck", team: "puck",
    }],
    score: { home: 0, away: 0 },
  };
}

function goal(game: RinkGame, team: ScoringTeam): ScoringTeam {
  game.score[team]++;
  const puck = game.bodies[PUCK_INDEX];
  puck.x = puck.homeX; puck.y = puck.homeY; puck.vx = puck.vy = 0;
  return team;
}

/** Count the entire puck crossing the goal line inside the posts, including a
 * fast diagonal shot. Blue attacks the top goal; red attacks the bottom. */
export function checkGoal(game: RinkGame, fromX: number, fromY: number): ScoringTeam | null {
  const puck = game.bodies[PUCK_INDEX];
  const top = GOAL_TOP - PUCK_RADIUS, bottom = GOAL_BOTTOM + PUCK_RADIUS;
  const team = fromY > top && puck.y <= top ? "home" : fromY < bottom && puck.y >= bottom ? "away" : null;
  if (!team) return null;
  const plane = team === "home" ? top : bottom;
  const x = fromX + (puck.x - fromX) * (plane - fromY) / (puck.y - fromY);
  return x >= GOAL_LEFT + PUCK_RADIUS && x <= GOAL_RIGHT - PUCK_RADIUS ? goal(game, team) : null;
}

/** A puck dropped into the net scores once on release, never while it is held. */
export function scoreDroppedPuck(game: RinkGame): ScoringTeam | null {
  const puck = game.bodies[PUCK_INDEX];
  if (puck.x < GOAL_LEFT + PUCK_RADIUS || puck.x > GOAL_RIGHT - PUCK_RADIUS) return null;
  if (puck.y >= GOAL_TOP - 20 && puck.y <= GOAL_TOP - PUCK_RADIUS) return goal(game, "home");
  if (puck.y <= GOAL_BOTTOM + 20 && puck.y >= GOAL_BOTTOM + PUCK_RADIUS) return goal(game, "away");
  return null;
}

export function advanceRink(game: RinkGame, dt = FIXED_STEP, held = -1) {
  const puck = game.bodies[PUCK_INDEX], x = puck.x, y = puck.y;
  const moving = advance(game.bodies, dt, held);
  return { moving, scored: held === PUCK_INDEX ? null : checkGoal(game, x, y) };
}

// Persist only the compact simulation state. Labels, teams and geometry are code-owned.
export function encodeRink(game: RinkGame): string {
  return JSON.stringify({ version: 1, score: game.score,
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
