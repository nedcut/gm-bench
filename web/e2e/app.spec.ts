import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";

const data = JSON.parse(readFileSync(new URL("../src/data/leaderboard.json", import.meta.url), "utf8"));
const rows: { model: string; mean_score: number }[] = data.agentic_lane;
const PAGES = ["/", "/cost/", "/tools/", "/replays/", "/method/", "/v1/"];

async function noErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("standings lists every 2.0 row by score with pick-trader, and nothing from 1.0", async ({ page }) => {
  const errors = await noErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Can an LLM run a hockey team?");
  await expect(page.locator(".intro-answer")).toHaveText("Not yet. No model beats pick-trader.");
  const names = await page.locator(".standings tbody .name").allTextContents();
  for (const row of rows) expect(names).toContain(row.model);
  expect(names).toContain("pick-trader");
  expect(names).not.toContain("gemini-3.7-flash");
  const scores = (await page.locator(".standings tbody .score").allTextContents()).map(Number);
  expect([...scores].sort((a, b) => b - a)).toEqual(scores);
  await expect(page.locator(".tabs a[aria-current=page]")).toHaveText("Standings");
  expect(errors).toEqual([]);
});

test("filters hide rows on every tab and a row opens its details", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("checkbox", { name: /Claude Code/ }).uncheck();
  await expect(page.locator(".standings tbody .name", { hasText: "claude-sonnet-5" })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Show bots" }).uncheck();
  await expect(page.locator(".standings tbody .name", { hasText: "random" })).toHaveCount(0);
  await expect(page.locator(".standings tbody .name", { hasText: "pick-trader" })).toHaveCount(1);
  await page.goto("/tools/");
  await expect(page.getByText(/Hidden by your filter: Claude Code/)).toBeVisible();
  await expect(page.locator(".hbar", { hasText: "claude-sonnet-5" })).toHaveCount(0);
  await page.getByRole("button", { name: "Show all" }).click();
  await expect(page.locator(".hbar", { hasText: "claude-sonnet-5" }).first()).toBeVisible();
  await page.goto("/");
  await page.locator(".row-name", { hasText: "gpt-6-luna" }).click();
  await expect(page.locator(".panel h2")).toHaveText("gpt-6-luna");
  await expect(page.locator(".panel")).toContainText("vs pick-trader");
  await page.getByRole("button", { name: "← Filters" }).click();
  await expect(page.locator(".panel h2")).toHaveText("Filter");
});

test("score vs cost plots measured rows and names the unmeasured ones", async ({ page }) => {
  await page.goto("/cost/");
  const unmeasured = data.agentic_lane.filter((r: { telemetry: { cost_per_episode_usd: number | null; api_equivalent_cost_per_episode_usd?: number | null } }) =>
    r.telemetry.cost_per_episode_usd === null && (r.telemetry.api_equivalent_cost_per_episode_usd ?? null) === null);
  await expect(page.locator(".chart circle")).toHaveCount(rows.length - unmeasured.length);
  for (const r of unmeasured) await expect(page.getByText(new RegExp(`cost unmeasured: .*${r.model}`))).toBeVisible();
});

test("phone layout: filter opens as a sheet and no page scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "Filter", exact: true }).click();
  await expect(page.locator(".panel.is-open")).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.locator(".panel.is-open")).toHaveCount(0);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 800 });
    for (const path of PAGES) {
      await page.goto(path);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${path} at ${width}px`).toBe(true);
    }
  }
});

test("every page passes axe in both themes", async ({ page }) => {
  for (const theme of ["dark", "light"]) {
    await page.addInitScript((t) => localStorage.setItem("gm-bench-theme", t), theme);
    for (const path of ["/", "/cost/", "/tools/", "/method/", "/v1/"]) {
      await page.goto(path);
      const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(result.violations.map((v) => `${path} ${theme}: ${v.id} ${v.nodes[0]?.target}`)).toEqual([]);
    }
  }
});
