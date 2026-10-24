import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";

for (const width of [1440, 390]) {
  test(`best-case summary and public replay remain separate at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("/replays/?left=conservative&right=pick-trader&window=3&view=roster");
    await expect(page.locator(".tx-left h3")).toHaveText("Conservative");
    await expect(page.getByText("Window 3 of 20", { exact: true })).toBeVisible();
    const best = page.getByRole("button", { name: /The best AI game/ });
    const replay = page.getByRole("button", { name: /AI vs pick-trader, side by side/ });
    for (let attempt = 0; attempt < 3; attempt++) {
      await best.click();
      await expect(page.getByRole("heading", { name: "gpt-6-astra", exact: true })).toBeVisible();
      await expect(page.locator(".best-run-score strong")).toHaveText("409.132");
      await expect(page.locator(".best-run-outcomes > div").first()).toContainText("Championships3");
      await expect(page.locator(".best-run")).toContainText("not a representative mean");
      await expect(page.locator(".best-run")).toContainText("private seed is redacted");
      await expect(page.locator(".tx-explorer")).toHaveCount(0);
      await replay.click();
      await expect(page.locator(".tx-left h3")).toHaveText("Conservative");
      await expect(page.locator(".tx-right h3")).toHaveText("Pick-trader");
      await expect(page.getByText("Window 3 of 20", { exact: true })).toBeVisible();
    }
    await page.goBack();
    await expect(best).toHaveAttribute("aria-pressed", "true");
    await page.reload();
    await expect(page.locator(".best-run-score strong")).toHaveText("409.132");
    const seasons = page.locator(".best-run-season");
    await expect(seasons).toHaveCount(5);
    await expect(page.locator(".best-run-title-badge")).toHaveCount(3);
    for (const [index, record] of ["17–16", "20–13", "26–7", "22–11", "24–9"].entries()) {
      await expect(seasons.nth(index).locator(".best-run-season-stats")).toContainText(record);
      await seasons.nth(index).locator("summary").click();
      await expect(seasons.nth(index).locator(".best-run-moves")).toBeVisible();
    }
    await expect(seasons.nth(2)).toContainText("Rejected attempt");
    await expect(seasons.nth(3)).toContainText("Offered Alex Chen + season 6, 7 draft picks");
    await expect(seasons.nth(4)).toContainText("$8.50M/year, 2 years");
    await expect(page.locator(".best-run-counter-note")).toContainText("109 actual wins");
    await expect(page.locator(".best-run a[href*='seed=']")).toHaveCount(0);
    const axe = await new AxeBuilder({ page }).include(".replay-examples").include(".best-run").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(axe.violations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    mkdirSync("../output/playwright", { recursive: true });
    await page.screenshot({ path: `../output/playwright/best-run-${width}.png`, fullPage: true });
    await page.goForward();
    await expect(replay).toHaveAttribute("aria-pressed", "true");
    expect(errors).toEqual([]);
  });
}

test("replays open on the quiz and the best AI game; replay links still open the replay", async ({ page }) => {
  await page.goto("/replays/");
  await expect(page.getByRole("heading", { name: "Your call, GM." })).toBeVisible();
  await expect(page.getByRole("button", { name: /The best AI game/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".best-run")).toContainText("best case, not a representative mean");
  await expect(page.locator(".best-run-about")).not.toHaveAttribute("open", "");
  await expect(page.locator(".tx-explorer")).toHaveCount(0);
  await page.goto("/replays/?window=3");
  await expect(page.getByRole("button", { name: /AI vs pick-trader/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Window 3 of 20", { exact: true })).toBeVisible();
});
