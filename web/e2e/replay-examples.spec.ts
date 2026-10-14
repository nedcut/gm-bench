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
    const best = page.getByRole("button", { name: /Best-case agent episode/ });
    const replay = page.getByRole("button", { name: /Public replay · Pick Trader/ });
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
