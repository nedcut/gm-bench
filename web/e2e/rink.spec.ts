import { encodeRink, newRinkGame, PUCK_INDEX, RINK_STORAGE_KEY } from "../src/app/rinkGame";
import { test, expect } from "@playwright/test";

test.use({ viewport: { width: 1440, height: 1000 }, reducedMotion: "no-preference" });

test("both pages share the corrected rink and twelve players", async ({ page }) => {
  for (const route of ["/how-it-works/", "/replays/"]) {
    await page.goto(route);
    await expect(page.locator(".rink-player-home")).toHaveCount(6);
    await expect(page.locator(".rink-player-away")).toHaveCount(6);
    await expect(page.getByRole("button", { name: "Puck", exact: true })).toBeVisible();
    await expect(page.locator(".rink-dot")).toHaveCount(8);
    await expect(page.locator(".rink-center-logo path")).toHaveCount(3);
    await expect(page.locator(".rink-board [stroke-dasharray]")).toHaveCount(0);
  }
});

test("puck shots score once, then positions and scores survive navigation and reload", async ({ page }) => {
  const game = newRinkGame();
  game.bodies[11].x = 75; // Open the top net for a clean shot.
  Object.assign(game.bodies[PUCK_INDEX], { x: 160, y: 90 });
  await page.addInitScript(({ key, save }) => {
    if (!localStorage.getItem(key)) localStorage.setItem(key, save);
  }, { key: RINK_STORAGE_KEY, save: encodeRink(game) });
  await page.goto("/how-it-works/");
  await page.getByRole("button", { name: "Puck", exact: true }).focus();
  await page.keyboard.press("Shift+ArrowUp");
  await expect(page.locator('[data-score="home"]')).toHaveText("1");
  await expect(page.getByRole("status")).toContainText("Goal for Blue!");
  await expect(page.locator(".rink-puck")).toHaveAttribute("transform", "translate(160.00 255.00)");
  await page.waitForTimeout(100);
  await expect(page.locator('[data-score="home"]')).toHaveText("1");
  const player = page.locator('[data-player="0"]');
  await player.focus();
  await page.keyboard.press("ArrowRight");
  const position = await player.getAttribute("transform");
  await page.locator('.tabs a[href="/replays/"]').click();
  await expect(page.locator('[data-player="0"]')).toHaveAttribute("transform", position!);
  await expect(page.locator('[data-score="home"]')).toHaveText("1");
  await page.locator('[data-player="0"]').focus();
  await page.keyboard.press("ArrowRight");
  await page.goBack();
  await expect(page.locator('[data-player="0"]')).toHaveAttribute("transform", "translate(95.00 265.00)");
  await expect(page.locator('[data-score="home"]')).toHaveText("1");
  await page.reload();
  await expect(page.locator('[data-player="0"]')).toHaveAttribute("transform", "translate(95.00 265.00)");
  await expect(page.locator('[data-score="home"]')).toHaveText("1");
  await page.getByRole("button", { name: "Reset rink and score" }).click();
  await expect(page.locator('[data-score="home"]')).toHaveText("0");
  await page.goto("/how-it-works/");
  await expect(page.locator('[data-score="home"]')).toHaveText("0");
  await expect(page.locator('[data-player="0"]')).toHaveAttribute("transform", "translate(75.00 265.00)");
});

test("restoring a cached page loads the latest saved rink", async ({ page }) => {
  await page.goto("/how-it-works/");
  const changed = newRinkGame();
  changed.score.home = 2;
  changed.bodies[0].x = 100;
  await page.evaluate(({ key, save }) => {
    localStorage.setItem(key, save);
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
  }, { key: RINK_STORAGE_KEY, save: encodeRink(changed) });
  await expect(page.locator('[data-score="home"]')).toHaveText("2");
  await expect(page.locator('[data-player="0"]')).toHaveAttribute("transform", "translate(100.00 265.00)");
});

test("another open page mirrors saved state without starting a second simulation", async ({ page, context }) => {
  await page.goto("/how-it-works/");
  const other = await context.newPage();
  await other.goto("/replays/");
  await page.bringToFront();
  await page.locator('[data-player="0"]').focus();
  await page.keyboard.press("ArrowRight");
  await expect(other.locator('[data-player="0"]')).toHaveAttribute("transform", "translate(85.00 265.00)");
  await other.close();
});

test("idle wiggle hints at interaction without changing saved physics positions", async ({ page }) => {
  await page.clock.install();
  await page.goto("/how-it-works/");
  await page.clock.runFor(100);
  const position = await page.locator('[data-player="1"]').getAttribute("transform");
  await page.clock.runFor(5000);
  await expect(page.locator(".rink-player.is-hinting")).toHaveCount(1);
  await expect(page.locator('[data-player="1"]')).toHaveAttribute("transform", position!);
  await page.locator('[data-player="1"]').focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.locator(".rink-player.is-hinting")).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.runFor(30000);
  await expect(page.locator(".rink-player.is-hinting")).toHaveCount(0);
});

test("blocked browser storage does not prevent dragging or reset", async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new Error("Storage disabled"); };
    Storage.prototype.setItem = () => { throw new Error("Storage disabled"); };
  });
  await page.goto("/how-it-works/");
  const player = page.locator('[data-player="0"]');
  await player.focus();
  await page.keyboard.press("ArrowRight");
  await expect(player).toHaveAttribute("transform", "translate(85.00 265.00)");
  await page.getByRole("button", { name: "Reset rink and score" }).click();
  await expect(player).toHaveAttribute("transform", "translate(75.00 265.00)");
});

test("real pointer dragging, release inertia, collisions and reset", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/how-it-works/");
  const player = page.locator('[data-player="0"]');
  const initial = await player.getAttribute("transform");
  const box = (await player.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 95, box.y + 25, { steps: 8 });
  await expect(player).toHaveClass(/is-held/);
  const held = await player.getAttribute("transform");
  expect(held).not.toBe(initial);
  await page.mouse.up();
  await expect(player).not.toHaveClass(/is-held/);
  await expect.poll(() => player.getAttribute("transform")).not.toBe(held);
  // Launch a player directly towards an opponent and observe transferred motion.
  await page.getByRole("button", { name: "Reset rink and score" }).click();
  const homeCenter = page.locator('[data-player="1"]');
  const awayCenter = page.locator('[data-player="7"]');
  const opponentStart = await awayCenter.getAttribute("transform");
  await homeCenter.focus();
  await page.keyboard.press("Shift+ArrowUp");
  await expect.poll(() => awayCenter.getAttribute("transform")).not.toBe(opponentStart);
  await page.getByRole("button", { name: "Reset rink and score" }).click();
  await expect(player).toHaveAttribute("transform", initial!);
  await page.waitForTimeout(300);
  await expect(player).toHaveAttribute("transform", initial!);
  expect(errors).toEqual([]);
});

test("animation sleeps at rest, pauses offscreen, and respects reduced motion", async ({ page }) => {
  await page.addInitScript(() => {
    const request = window.requestAnimationFrame.bind(window);
    const stats = { frames: 0 };
    Object.assign(window, { rinkTestStats: stats });
    window.requestAnimationFrame = callback => request(time => { stats.frames++; callback(time); });
  });
  const frames = () => page.evaluate(() => (window as unknown as { rinkTestStats: { frames: number } }).rinkTestStats.frames);
  await page.goto("/how-it-works/");
  await page.waitForTimeout(200);
  const idle = await frames();
  await page.waitForTimeout(250);
  expect(await frames()).toBe(idle);
  await page.setViewportSize({ width: 390, height: 844 });
  const player = page.locator('[data-player="1"]');
  await player.focus();
  await page.keyboard.press("Shift+ArrowUp");
  await page.waitForTimeout(100);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
  const paused = await player.getAttribute("transform"), pausedFrames = await frames();
  await page.waitForTimeout(250);
  expect(await player.getAttribute("transform")).toBe(paused);
  expect(await frames()).toBe(pausedFrames);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await player.focus();
  await page.keyboard.press("Shift+ArrowRight");
  const reduced = await player.getAttribute("transform");
  await page.waitForTimeout(250);
  expect(await player.getAttribute("transform")).toBe(reduced);
});

test("touch drag stays captured until release and cannot leave a rounded corner", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/how-it-works/");
  const rink = page.locator(".rink-board"), player = page.locator('[data-player="6"]');
  await rink.scrollIntoViewIfNeeded();
  const box = (await player.boundingBox())!, board = (await rink.boundingBox())!;
  const client = await page.context().newCDPSession(page);
  await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: box.x + box.width / 2, y: box.y + box.height / 2 }] });
  await expect(player).toHaveClass(/is-held/);
  await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: board.x + 2, y: board.y + 2 }] });
  const position = await player.evaluate(node => {
    const m = (node as unknown as SVGGElement).transform.baseVal.getItem(0).matrix;
    return { x: m.e, y: m.f };
  });
  const cx = Math.max(100, Math.min(220, position.x)), cy = Math.max(94, Math.min(376, position.y));
  expect(Math.hypot(position.x - cx, position.y - cy)).toBeLessThanOrEqual(64.01);
  await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await expect(player).not.toHaveClass(/is-held/);
  await page.getByRole("button", { name: "Reset rink and score" }).click();
  await expect(player).toHaveAttribute("transform", "translate(75.00 205.00)");
  await client.detach();
});
