import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";

for (const width of [1440, 390, 320]) {
  test(`axis switching preserves shared selection and filters at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.goto("/#cost");
    await page.evaluate(() => document.fonts.ready);
    const picker = page.getByRole("combobox", { name: "X-axis", exact: true });
    await expect(picker).toHaveValue("cost");
    await page.locator(".pt", { hasText: "gpt-6-astra" }).locator("circle").click();
    if (width <= 900) await page.getByRole("button", { name: "Close", exact: true }).click();
    for (let repeat = 0; repeat < 2; repeat++) {
      for (const id of ["output-total", "time", "calls", "input-total", "output-game", "cost"]) {
        await picker.selectOption(id);
        await expect(page.locator(".pt[aria-pressed=true]")).toHaveCount(1);
        await expect(page.locator("#standings .standings tr[aria-selected=true]")).toHaveCount(1);
        await expect(page.locator("#tools .hbar[aria-pressed=true]")).toHaveCount(6);
        expect(await page.locator("#cost").innerHTML()).not.toMatch(/NaN|Infinity/);
        await page.getByRole("button", { name: "Log", exact: true }).click();
        await expect(page.locator(".chart .axis-label").first()).toContainText(/log/);
        await page.getByRole("button", { name: "Linear", exact: true }).click();
      }
    }
    await expect(page.locator("#cost")).toContainText("cost unmeasured: composer-2.5");
    await picker.selectOption("output-total");
    mkdirSync("../output/playwright", { recursive: true });
    await page.screenshot({ path: `../output/playwright/output-tokens-${width}.png` });
    await picker.selectOption("cost");
    if (width <= 900) await page.getByRole("button", { name: "Filter", exact: true }).click();
    else await page.getByRole("button", { name: "← Filters" }).click();
    await page.getByRole("checkbox", { name: /OpenAI/ }).uncheck();
    if (width <= 900) await page.getByRole("button", { name: "Close", exact: true }).click();
    for (const id of ["calls", "output-total", "cost"]) {
      await picker.selectOption(id);
      await expect(page.locator(".pt", { hasText: "gpt-6-astra" })).toHaveCount(0);
    }
    await picker.selectOption("output-total");
    await expect(page.locator("#cost")).toContainText("including reasoning tokens");
    await expect(page.locator(".pt title").first()).toContainText(/tokens \/ panel; 32 five-season episodes/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const result = await new AxeBuilder({ page }).include("#cost").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(result.violations).toEqual([]);
    await page.getByRole("navigation", { name: "Statistics sections" }).getByRole("link", { name: "Tool use" }).click();
    await expect(page).toHaveURL(/#tools$/);
    await page.getByRole("navigation", { name: "Statistics sections" }).getByRole("link", { name: "Score vs cost" }).click();
    await expect(picker).toHaveValue("output-total");
    expect(errors).toEqual([]);
  });
}

test("all filtered out has a clear no-data state for every axis", async ({ page }) => {
  await page.goto("/");
  for (const label of [/Claude Code/, /Codex/, /Cursor/, /OpenCode/]) await page.getByRole("group", { name: "Harness", exact: true }).getByRole("checkbox", { name: label }).uncheck();
  for (const id of ["cost", "output-total", "time", "calls", "input-total", "output-game"]) {
    await page.getByRole("combobox", { name: "X-axis", exact: true }).selectOption(id);
    await expect(page.locator("#cost")).toContainText("No row in the current filter");
    await expect(page.locator(".chart")).toHaveCount(0);
  }
});
