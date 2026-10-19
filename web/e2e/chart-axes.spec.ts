import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";

const data = JSON.parse(readFileSync(new URL("../src/data/leaderboard.json", import.meta.url), "utf8"));
type Telemetry = { cost_per_episode_usd: number | null; api_equivalent_cost_per_episode_usd?: number | null };
const unmeasured = (data.agentic_v21_lane as Array<{ model: string; telemetry: Telemetry }>)
  .filter((row) => row.telemetry.cost_per_episode_usd === null && (row.telemetry.api_equivalent_cost_per_episode_usd ?? null) === null)
  .map((row) => row.model.split("/").at(-1)!);

const SHORT: Record<string, string> = { cost: "Cost", "output-total": "Output tokens", time: "Wall time", calls: "Tool calls", "input-total": "Input tokens", "output-game": "Output / game" };

for (const width of [1440, 390, 320]) {
  test(`axis switching preserves shared selection and filters at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.goto("/#cost");
    await page.evaluate(() => document.fonts.ready);
    const picker = page.getByRole("group", { name: "X-axis", exact: true });
    const pick = (id: string) => picker.getByRole("button", { name: SHORT[id], exact: true }).click();
    await expect(picker.getByRole("button", { name: "Cost", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.locator('.pt[aria-label^="gpt-6-astra,"]').locator("circle").click();
    if (width <= 900) await page.getByRole("button", { name: "Close", exact: true }).click();
    for (let repeat = 0; repeat < 2; repeat++) {
      for (const id of ["output-total", "time", "calls", "input-total", "output-game", "cost"]) {
        await pick(id);
        await expect(page.locator(".pt[aria-pressed=true]")).toHaveCount(1);
        await expect(page.locator("#standings .standings tr[aria-selected=true]")).toHaveCount(1);
        await expect(page.locator("#tools .hbar[aria-pressed=true]")).toHaveCount(6);
        expect(await page.locator("#cost").innerHTML()).not.toMatch(/NaN|Infinity/);
        await page.getByRole("button", { name: "Log", exact: true }).click();
        await expect(page.locator(".chart .axis-label").first()).toContainText(/log/);
        await page.getByRole("button", { name: "Linear", exact: true }).click();
      }
    }
    if (unmeasured.length > 0) await expect(page.locator("#cost")).toContainText(`cost unmeasured: ${unmeasured[0]}`);
    else await expect(page.locator("#cost")).not.toContainText("cost unmeasured");
    await pick("output-total");
    mkdirSync("../output/playwright", { recursive: true });
    await page.screenshot({ path: `../output/playwright/output-tokens-${width}.png` });
    await pick("cost");
    if (width <= 900) await page.getByRole("button", { name: "Filter", exact: true }).click();
    else await page.getByRole("button", { name: "← Filters" }).click();
    await page.getByRole("checkbox", { name: /OpenAI/ }).uncheck();
    if (width <= 900) await page.getByRole("button", { name: "Close", exact: true }).click();
    for (const id of ["calls", "output-total", "cost"]) {
      await pick(id);
      await expect(page.locator('.pt[aria-label^="gpt-6-astra,"]')).toHaveCount(0);
    }
    await pick("output-total");
    await expect(page.locator("#cost")).toContainText("including reasoning tokens");
    await expect(page.locator(".pt").first()).toHaveAttribute("aria-label", /tokens \/ panel; 32 five-season episodes/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const result = await new AxeBuilder({ page }).include("#cost").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(result.violations).toEqual([]);
    await page.getByRole("navigation", { name: "Statistics sections" }).getByRole("link", { name: "Tool use" }).click();
    await expect(page).toHaveURL(/#tools$/);
    await page.getByRole("navigation", { name: "Statistics sections" }).getByRole("link", { name: "Score vs cost" }).click();
    await expect(picker.getByRole("button", { name: "Output tokens", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(errors).toEqual([]);
  });
}

test("all filtered out has a clear no-data state for every axis", async ({ page }) => {
  await page.goto("/");
  const harnesses = page.getByRole("group", { name: "Harness", exact: true }).getByRole("checkbox");
  await expect(harnesses).not.toHaveCount(0);
  for (const box of await harnesses.all()) await box.uncheck();
  for (const id of ["cost", "output-total", "time", "calls", "input-total", "output-game"]) {
    await page.getByRole("group", { name: "X-axis", exact: true }).getByRole("button", { name: SHORT[id], exact: true }).click();
    await expect(page.locator("#cost")).toContainText("No row in the current filter");
    await expect(page.locator(".chart")).toHaveCount(0);
  }
});
