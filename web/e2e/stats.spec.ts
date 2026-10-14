import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

for (const width of [1440, 620, 390, 320]) {
  test(`shared stats, jumps, selection and filters at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.goto("/");
    await expect(page.locator(".workspace")).toHaveCount(1);
    await expect(page.locator(".tabs a")).toHaveCount(3);
    const index = page.getByRole("navigation", { name: "Statistics sections" });
    for (const [label, id] of [["Score vs cost", "cost"], ["Tool use", "tools"], ["Standings", "standings"]]) {
      await index.getByRole("link", { name: label, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`#${id}$`));
      const target = page.locator(`#${id}`);
      const box = await target.boundingBox();
      const indexBox = await index.boundingBox();
      expect(box && indexBox && box.y >= indexBox.y + indexBox.height - 1).toBe(true);
    }
    const row = page.locator(".row-name", { hasText: "gpt-6-astra" });
    await row.click();
    await expect(page.locator(".side-panel h2")).toHaveText("gpt-6-astra");
    await expect(page.locator("#cost .pt[aria-pressed=true]")).toHaveCount(1);
    await expect(page.locator("#tools .hbar[aria-pressed=true]")).toHaveCount(6);
    if (width <= 900) await page.getByRole("button", { name: "Close", exact: true }).click();
    else await page.getByRole("button", { name: "← Filters" }).click();
    for (let repeat = 0; repeat < 2; repeat++) {
      if (width <= 900) await page.getByRole("button", { name: "Filter", exact: true }).click();
      await page.getByRole("checkbox", { name: /OpenAI/ }).uncheck();
      if (width <= 900) await page.getByRole("button", { name: "Close", exact: true }).click();
      await expect(page.locator(".row-name", { hasText: "gpt-6-astra" })).toHaveCount(0);
      await expect(page.locator("#cost .pt", { hasText: "gpt-6-astra" })).toHaveCount(0);
      await expect(page.locator("#tools .hbar", { hasText: "gpt-6-astra" })).toHaveCount(0);
      if (width <= 900) await page.getByRole("button", { name: "Filter", exact: true }).click();
      await page.getByRole("button", { name: "Reset", exact: true }).click();
      if (width <= 900) await page.getByRole("button", { name: "Close", exact: true }).click();
      await expect(row).toHaveCount(1);
    }
    await index.getByRole("link", { name: "Score vs cost", exact: true }).click();
    const point = page.getByRole("button", { name: /^gpt-6-astra, Codex: score/ });
    await point.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".standings tr[aria-selected=true]")).toHaveCount(1);
    if (width <= 900) await page.getByRole("button", { name: "Close", exact: true }).click();
    await index.getByRole("link", { name: "Tool use", exact: true }).click();
    await page.locator(".hbar", { hasText: "gpt-6-astra" }).first().click();
    await expect(page.locator("#cost .pt[aria-pressed=true]")).toHaveCount(0);
    if (width <= 900) await page.getByRole("button", { name: "Close", exact: true }).click();
    if (width <= 900) {
      await index.getByRole("link", { name: "Score vs cost", exact: true }).click();
      const key = page.locator(".chart-key button", { hasText: "gpt-6-astra" });
      await key.click();
      await expect(page.locator(".side-panel h2")).toHaveText("gpt-6-astra");
      await expect(key).toHaveAttribute("aria-pressed", "true");
      await page.getByRole("button", { name: "Close", exact: true }).click();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    mkdirSync("../output/playwright", { recursive: true });
    await page.goto("/");
    await page.screenshot({ path: `../output/playwright/stats-${width}.png`, fullPage: true });
    await index.getByRole("link", { name: "Score vs cost", exact: true }).click();
    await page.screenshot({ path: `../output/playwright/cost-${width}.png` });
    await page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: "How it works" }).click();
    await expect(page).toHaveURL(/\/how-it-works\/$/);
    await page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: "Replays" }).click();
    await expect(page).toHaveURL(/\/replays\/$/);
    expect(errors).toEqual([]);
  });
}

test("legacy stats URLs open their section and permit scrolling to all stats", async ({ page }) => {
  for (const id of ["cost", "tools"]) {
    await page.goto(`/${id}/`);
    await expect.poll(async () => (await page.locator(`#${id}`).boundingBox())?.y).toBeGreaterThanOrEqual(95);
    await expect.poll(async () => (await page.locator(`#${id}`).boundingBox())?.y).toBeLessThan(150);
    await expect(page.locator("#standings")).toHaveCount(1);
    await expect(page.locator("#cost")).toHaveCount(1);
    await expect(page.locator("#tools")).toHaveCount(1);
  }
  await page.goto("/#tools");
  await expect.poll(async () => (await page.locator("#tools").boundingBox())?.y).toBeLessThan(150);
});
