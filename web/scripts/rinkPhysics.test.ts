import { describe, expect, test } from "bun:test";
import { advance, contain, createSkaters, FIXED_STEP, moveHeld, PLAYER_RADIUS, resolveCollisions } from "../src/app/rinkPhysics";

function inside(x: number, y: number) {
  const cx = Math.max(100, Math.min(220, x)), cy = Math.max(94, Math.min(376, y));
  return Math.hypot(x - cx, y - cy) <= 78 - PLAYER_RADIUS + 0.00001;
}

describe("rink physics", () => {
  test("two teams of six start separated inside the boards", () => {
    const players = createSkaters();
    expect(players.filter(p => p.team === "home")).toHaveLength(6);
    expect(players.filter(p => p.team === "away")).toHaveLength(6);
    for (const [i, player] of players.entries()) {
      expect(inside(player.x, player.y)).toBe(true);
      for (const other of players.slice(i + 1)) expect(Math.hypot(player.x - other.x, player.y - other.y)).toBeGreaterThanOrEqual(28);
    }
  });
  test("head-on contact transfers momentum and separates the players", () => {
    const players = createSkaters().slice(0, 2);
    Object.assign(players[0], { x: 145, y: 235, vx: 600 });
    Object.assign(players[1], { x: 172, y: 235, vx: 0 });
    resolveCollisions(players);
    expect(players[1].vx).toBeGreaterThan(500);
    expect(players[0].vx).toBeLessThan(100);
    expect(players[1].x - players[0].x).toBeCloseTo(28, 8);
  });
  test("curved corners reflect outward velocity along their normal", () => {
    const player = createSkaters()[0];
    Object.assign(player, { x: 24, y: 18, vx: -400, vy: -400 });
    contain(player);
    expect(inside(player.x, player.y)).toBe(true);
    expect(player.vx).toBeGreaterThan(0);
    expect(player.vy).toBeGreaterThan(0);
  });
  test("held players push others without skipping through them", () => {
    const players = createSkaters().slice(0, 2);
    Object.assign(players[0], { x: 90, y: 235, vx: 600 });
    Object.assign(players[1], { x: 145, y: 235, vx: 0 });
    moveHeld(players, 0, 200, 235);
    expect(players[0].x).toBe(200);
    expect(players[1].x).toBeGreaterThanOrEqual(228 - 0.001);
    expect(players[1].vx).toBeGreaterThan(0);
    moveHeld(players, 0, -10000, -10000);
    expect(inside(players[0].x, players[0].y)).toBe(true);
  });
  test("repeated fast throws stay finite and contained, then stop completely", () => {
    const players = createSkaters();
    for (let frame = 0; frame < 3000; frame++) {
      if (frame < 1000 && frame % 20 === 0) {
        const player = players[(frame / 20) % 12];
        player.vx = Math.cos(frame) * 900; player.vy = Math.sin(frame) * 900;
      }
      advance(players);
      for (const player of players) {
        expect(Number.isFinite(player.x + player.y + player.vx + player.vy)).toBe(true);
        expect(inside(player.x, player.y)).toBe(true);
      }
    }
    expect(advance(players)).toBe(false);
    expect(players.every(p => p.vx === 0 && p.vy === 0)).toBe(true);
  });
  test("coincident players separate without NaNs", () => {
    const players = createSkaters().slice(0, 2);
    Object.assign(players[0], { x: 160, y: 235 });
    Object.assign(players[1], { x: 160, y: 235 });
    advance(players);
    expect(Math.hypot(players[0].x - players[1].x, players[0].y - players[1].y)).toBeCloseTo(28, 8);
  });
  test("the fixed step keeps a maximum-speed player from tunneling", () => {
    const players = createSkaters().slice(0, 2);
    Object.assign(players[0], { x: 90, y: 235, vx: 900 });
    Object.assign(players[1], { x: 145, y: 235, vx: 0 });
    for (let i = 0; i < 8; i++) advance(players, FIXED_STEP);
    expect(players[1].vx).toBeGreaterThan(0);
    expect(players[1].x).toBeGreaterThan(players[0].x);
  });
});
