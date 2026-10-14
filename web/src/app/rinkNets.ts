import { PUCK_RADIUS, type Skater } from "./rinkPhysics";

export const GOAL_LEFT = 138;
export const GOAL_RIGHT = 182;
export const GOAL_TOP = 67;
export const GOAL_BOTTOM = 403;
export const NET_DEPTH = 20;
// The three closed sides of each net. The goal-line mouth stays open.
const WALLS = [
  [GOAL_LEFT, GOAL_TOP - NET_DEPTH, GOAL_LEFT, GOAL_TOP],
  [GOAL_RIGHT, GOAL_TOP - NET_DEPTH, GOAL_RIGHT, GOAL_TOP],
  [GOAL_LEFT, GOAL_TOP - NET_DEPTH, GOAL_RIGHT, GOAL_TOP - NET_DEPTH],
  [GOAL_LEFT, GOAL_BOTTOM, GOAL_LEFT, GOAL_BOTTOM + NET_DEPTH],
  [GOAL_RIGHT, GOAL_BOTTOM, GOAL_RIGHT, GOAL_BOTTOM + NET_DEPTH],
  [GOAL_LEFT, GOAL_BOTTOM + NET_DEPTH, GOAL_RIGHT, GOAL_BOTTOM + NET_DEPTH],
];
const RADIUS = PUCK_RADIUS + 1; // Include the visible frame's half-width.
const EPSILON = 0.001;

/** Sweep the puck against line-segment capsules, including round goalposts.
 * Clamp at the first hit before scoring: side/back shots cannot enter a net. */
export function bounceOffNets(puck: Skater, fromX: number, fromY: number): boolean {
  const dx = puck.x - fromX, dy = puck.y - fromY;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared < 1e-12) return false;
  let first = Infinity, nx = 0, ny = 0;
  const hit = (t: number, x: number, y: number) => {
    if (t >= -1e-8 && t <= 1 && t < first && dx * x + dy * y < -1e-8) {
      first = Math.max(0, t); nx = x; ny = y;
    }
  };
  for (const [ax, ay, bx, by] of WALLS) {
    if (ax === bx && dx !== 0) {
      const normal = dx > 0 ? -1 : 1;
      const t = (ax + normal * RADIUS - fromX) / dx;
      const y = fromY + dy * t;
      if (y >= ay && y <= by) hit(t, normal, 0);
    } else if (ay === by && dy !== 0) {
      const normal = dy > 0 ? -1 : 1;
      const t = (ay + normal * RADIUS - fromY) / dy;
      const x = fromX + dx * t;
      if (x >= ax && x <= bx) hit(t, 0, normal);
    }
    for (const [x, y] of [[ax, ay], [bx, by]]) {
      const ox = fromX - x, oy = fromY - y;
      const b = ox * dx + oy * dy;
      const c = ox * ox + oy * oy - RADIUS * RADIUS;
      const discriminant = b * b - lengthSquared * c;
      if (discriminant < 0) continue;
      const t = (-b - Math.sqrt(discriminant)) / lengthSquared;
      hit(t, (ox + dx * t) / RADIUS, (oy + dy * t) / RADIUS);
    }
  }
  if (!Number.isFinite(first)) return false;
  puck.x = fromX + dx * first + nx * EPSILON;
  puck.y = fromY + dy * first + ny * EPSILON;
  const approach = puck.vx * nx + puck.vy * ny;
  if (approach < 0) {
    puck.vx -= 1.85 * approach * nx;
    puck.vy -= 1.85 * approach * ny;
  }
  return true;
}
