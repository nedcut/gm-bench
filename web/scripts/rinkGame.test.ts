import { describe, expect, test } from "bun:test";
import { advanceRink, checkGoal, decodeRink, encodeRink, newRinkGame, PUCK_INDEX, scoreDroppedPuck } from "../src/app/rinkGame";
import { advance, bodyRadius, resolveCollisions } from "../src/app/rinkPhysics";

describe("rink game", () => {
  test("a skater transfers momentum to the lighter puck", () => {
    const game = newRinkGame(), player = game.bodies[0], puck = game.bodies[PUCK_INDEX];
    Object.assign(player, { x: 141, y: 235, vx: 600 });
    Object.assign(puck, { x: 159, y: 235 });
    resolveCollisions([player, puck]);
    expect(puck.vx).toBeGreaterThan(player.vx);
    expect(Math.hypot(puck.x - player.x, puck.y - player.y)).toBeCloseTo(19);
  });
  test("the entire puck must cross between the posts, from the ice side", () => {
    const game = newRinkGame(), puck = game.bodies[PUCK_INDEX];
    Object.assign(puck, { x: 160, y: 64 });
    expect(checkGoal(game, 160, 70)).toBeNull();
    puck.y = 62;
    expect(checkGoal(game, 160, 70)).toBe("home");
    expect(game.score).toEqual({ home: 1, away: 0 });
    expect([puck.x, puck.y, puck.vx, puck.vy]).toEqual([160, 255, 0, 0]);
    Object.assign(puck, { x: 185, y: 61 });
    expect(checkGoal(game, 185, 70)).toBeNull();
    Object.assign(puck, { x: 160, y: 75 });
    expect(checkGoal(game, 160, 55)).toBeNull();
  });
  test("a fast diagonal crossing is scored at the crossing point", () => {
    const game = newRinkGame();
    Object.assign(game.bodies[PUCK_INDEX], { x: 185, y: 50 });
    expect(checkGoal(game, 160, 70)).toBe("home");
  });
  test("the bottom goal scores for Red and a dropped puck scores only once", () => {
    const game = newRinkGame(), puck = game.bodies[PUCK_INDEX];
    Object.assign(puck, { x: 160, y: 415 });
    expect(scoreDroppedPuck(game)).toBe("away");
    expect(scoreDroppedPuck(game)).toBeNull();
    expect(game.score).toEqual({ home: 0, away: 1 });
  });
  test("a moving puck scores once in the physics loop; a held puck cannot score", () => {
    const game = newRinkGame(), puck = game.bodies[PUCK_INDEX];
    game.bodies[11].x = 75; // Move the red goalie out of the shooting lane.
    Object.assign(puck, { x: 160, y: 70, vy: -1200 });
    expect(advanceRink(game).scored).toBe("home");
    expect(advanceRink(game).scored).toBeNull();
    Object.assign(puck, { x: 160, y: 55 });
    expect(advanceRink(game, 1 / 120, PUCK_INDEX).scored).toBeNull();
    expect(game.score.home).toBe(1);
  });
  test("players and puck remain inside rounded boards through repeated collisions", () => {
    const game = newRinkGame();
    game.bodies.forEach((body, i) => { body.vx = Math.cos(i) * 1200; body.vy = Math.sin(i) * 1200; });
    for (let frame = 0; frame < 1500; frame++) {
      advance(game.bodies);
      for (const body of game.bodies) {
        const cx = Math.max(100, Math.min(220, body.x)), cy = Math.max(94, Math.min(376, body.y));
        expect(Math.hypot(body.x - cx, body.y - cy)).toBeLessThanOrEqual(78 - bodyRadius(body) + 0.00001);
      }
    }
  });
  test("save round trips positions, momentum and scores with canonical team metadata", () => {
    const game = newRinkGame();
    Object.assign(game.bodies[0], { x: 80, y: 270, vx: 120, vy: -80 });
    Object.assign(game.bodies[PUCK_INDEX], { x: 170, y: 240, vx: -200, vy: 100 });
    game.score = { home: 3, away: 2 };
    expect(decodeRink(encodeRink(game))).toEqual(game);
    const tampered = JSON.parse(encodeRink(game));
    tampered.bodies[0].team = "puck";
    expect(decodeRink(JSON.stringify(tampered)).bodies[0].team).toBe("home");
  });
  test("missing, corrupt, older and malformed saves recover without breaking play", () => {
    const valid = JSON.parse(encodeRink(newRinkGame()));
    for (const raw of [null, "broken", "null", "{}", JSON.stringify({ ...valid, version: 0 }),
      JSON.stringify({ ...valid, score: { home: -1, away: 0 } }),
      JSON.stringify({ ...valid, bodies: valid.bodies.slice(0, 12) }),
      JSON.stringify({ ...valid, bodies: valid.bodies.map(() => null) }),
      JSON.stringify(valid).replace('"vx":0', '"vx":"bad"')]) {
      expect(decodeRink(raw)).toEqual(newRinkGame());
    }
    valid.bodies[0] = { x: -10000, y: -10000, vx: 10000, vy: 10000 };
    const recovered = decodeRink(JSON.stringify(valid)).bodies[0];
    expect(Math.hypot(recovered.x - 100, recovered.y - 94)).toBeCloseTo(64);
    expect(Math.hypot(recovered.vx, recovered.vy)).toBeCloseTo(900);
  });
});
