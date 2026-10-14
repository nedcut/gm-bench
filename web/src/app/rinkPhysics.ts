export const PLAYER_RADIUS = 14;
export const PUCK_RADIUS = 5;
export const FIXED_STEP = 1 / 120;
export const MAX_SPEED = 900;
const BOUNCE = 0.88;
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));

export interface Skater {
  x: number; y: number; vx: number; vy: number;
  homeX: number; homeY: number; label: string; team: "home" | "away" | "puck";
  locked?: boolean;
}

export const bodyRadius = (body: Skater) => body.team === "puck" ? PUCK_RADIUS : PLAYER_RADIUS;
/** Inspect each puck movement before boards or another collision can undo it.
 * Return true to stop the operation after a goal resets the puck. */
export type PuckMotion = (fromX: number, fromY: number) => boolean;

export function createSkaters(): Skater[] {
  const formation: [number, number, string][] = [
    [75, 265, "LW"], [160, 310, "C"], [245, 265, "RW"],
    [110, 350, "D"], [210, 350, "D"], [160, 398, "G"],
  ];
  return (["home", "away"] as const).flatMap(team => formation.map(([x, y, label]) => ({
    x, y: team === "home" ? y : 470 - y, vx: 0, vy: 0,
    homeX: x, homeY: team === "home" ? y : 470 - y, label, team,
  })));
}

/** Project the whole player inside the ice's rounded rectangle, including corners.
 * Ice: x=22..298, y=16..454, radius=78. Inset by the player radius. */
export function contain(skater: Skater) {
  const cx = clamp(skater.x, 100, 220);
  const cy = clamp(skater.y, 94, 376);
  const dx = skater.x - cx, dy = skater.y - cy;
  const distance = Math.hypot(dx, dy);
  const radius = 78 - bodyRadius(skater);
  if (distance <= radius) return;
  const nx = dx / distance, ny = dy / distance;
  skater.x = cx + nx * radius;
  skater.y = cy + ny * radius;
  const outward = skater.vx * nx + skater.vy * ny;
  if (outward > 0) {
    skater.vx -= (1 + BOUNCE) * outward * nx;
    skater.vy -= (1 + BOUNCE) * outward * ny;
  }
}

export function resolveCollisions(skaters: Skater[], held = -1, onPuckMove?: PuckMotion): boolean {
  // A held player is kinematic: it pushes other players without moving the pointer.
  for (let pass = 0; pass < 3; pass++) {
    for (let i = 0; i < skaters.length; i++) {
      for (let j = i + 1; j < skaters.length; j++) {
        const a = skaters[i], b = skaters[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const squared = dx * dx + dy * dy;
        const contact = bodyRadius(a) + bodyRadius(b);
        if (squared >= contact * contact) continue;
        const distance = Math.sqrt(squared);
        const nx = distance > 0.001 ? dx / distance : 1;
        const ny = distance > 0.001 ? dy / distance : 0;
        const wa = i === held || a.locked ? 0 : a.team === "puck" ? 5 : 1;
        const wb = j === held || b.locked ? 0 : b.team === "puck" ? 5 : 1;
        if (wa + wb === 0) continue;
        const overlap = (contact - distance) / (wa + wb);
        const puck = a.team === "puck" ? a : b.team === "puck" ? b : null;
        const fromX = puck?.x ?? 0, fromY = puck?.y ?? 0;
        a.x -= nx * overlap * wa; a.y -= ny * overlap * wa;
        b.x += nx * overlap * wb; b.y += ny * overlap * wb;
        if (puck && onPuckMove?.(fromX, fromY)) {
          for (const skater of skaters) contain(skater);
          return true;
        }
        const approach = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny;
        if (approach < 0) {
          const impulse = -(1 + BOUNCE) * approach / (wa + wb);
          a.vx -= impulse * nx * wa; a.vy -= impulse * ny * wa;
          b.vx += impulse * nx * wb; b.vy += impulse * ny * wb;
        }
      }
    }
    for (const skater of skaters) contain(skater);
  }
  return false;
}

export function limitSpeed(skater: Skater) {
  const speed = Math.hypot(skater.vx, skater.vy);
  const maximum = skater.team === "puck" ? 1200 : MAX_SPEED;
  if (speed > maximum) {
    skater.vx *= maximum / speed; skater.vy *= maximum / speed;
  }
}

/** Small fixed steps avoid tunneling and make damping independent of display Hz. */
export function advance(skaters: Skater[], dt = FIXED_STEP, held = -1, onPuckMove?: PuckMotion): boolean {
  for (let i = 0; i < skaters.length; i++) {
    if (i === held || skaters[i].locked) continue;
    const skater = skaters[i];
    const damping = Math.exp(-(skater.team === "puck" ? 0.65 : 0.85) * dt);
    limitSpeed(skater);
    const fromX = skater.x, fromY = skater.y;
    skater.x += skater.vx * dt; skater.y += skater.vy * dt;
    if (skater.team === "puck" && onPuckMove?.(fromX, fromY)) {
      return skaters.some((body, i) => i !== held && (body.vx !== 0 || body.vy !== 0));
    }
    skater.vx *= damping; skater.vy *= damping;
    contain(skater);
  }
  resolveCollisions(skaters, held, onPuckMove);
  let moving = false;
  for (let i = 0; i < skaters.length; i++) {
    if (i === held || skaters[i].locked) continue;
    const skater = skaters[i];
    limitSpeed(skater);
    if (Math.hypot(skater.vx, skater.vy) < 5) skater.vx = skater.vy = 0;
    else moving = true;
  }
  return moving;
}

export function moveHeld(skaters: Skater[], index: number, x: number, y: number, onPuckMove?: PuckMotion) {
  const skater = skaters[index];
  const radius = bodyRadius(skater);
  x = clamp(x, 22 + radius, 298 - radius); y = clamp(y, 16 + radius, 454 - radius);
  // Sweep a drag in small increments so the grabbed player cannot skip a teammate.
  const startX = skater.x, startY = skater.y;
  const steps = Math.max(1, Math.ceil(Math.hypot(x - startX, y - startY) / 7));
  for (let n = 1; n <= steps; n++) {
    const fromX = skater.x, fromY = skater.y;
    skater.x = startX + (x - startX) * n / steps;
    skater.y = startY + (y - startY) * n / steps;
    if (skater.team === "puck" && onPuckMove?.(fromX, fromY)) return;
    contain(skater);
    if (resolveCollisions(skaters, index, onPuckMove)) return;
  }
}
