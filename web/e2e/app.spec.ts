import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";

const data = JSON.parse(readFileSync(new URL("../src/data/leaderboard.json", import.meta.url), "utf8"));
type Row = {
  model: string;
  mean_score: number;
  reference: { mean_score: number; paired_lift_ci95: number[] };
  telemetry: { cost_per_episode_usd: number | null; api_equivalent_cost_per_episode_usd?: number | null };
};
const rows: Row[] = data.agentic_lane;
const bar = rows[0].reference.mean_score;
const clears = (row: Row) => row.reference.paired_lift_ci95[0] > 0;
const priced = rows.filter(
  (row) => (row.telemetry.cost_per_episode_usd ?? row.telemetry.api_equivalent_cost_per_episode_usd ?? null) !== null,
);
function verdict(set: Row[], clear: string, above: string, none: string): string {
  const c = set.filter(clears).length;
  const a = set.filter((row) => row.mean_score > bar).length;
  return c > 0 ? clear.replace("N", String(c)) : a > 0 ? above.replace("N", String(a)) : none;
}
const PAGES = ["/", "/how-it-works/", "/cost/", "/tools/", "/replays/", "/method/", "/v1/"];

async function noErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("standings lists every 2.0 row by score with pick-trader, and nothing from 1.0", async ({ page }) => {
  const errors = await noErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Can an LLM run a hockey team?");
  await expect(page.locator(".intro-answer")).toHaveText(
    verdict(
      rows,
      `N of ${rows.length} models beat${rows.filter(clears).length === 1 ? "s" : ""} pick-trader by more than the noise.`,
      `Not clearly. N of ${rows.length} score above pick-trader, within the noise.`,
      "Not yet. No model beats pick-trader.",
    ),
  );
  const names = await page.locator(".standings tbody .name").allTextContents();
  for (const row of rows) expect(names).toContain(row.model.split("/").at(-1));
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
  await expect(page.locator(".hbar", { hasText: "claude-sonnet-5" })).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: /Claude Code/ })).not.toBeChecked();
  await page.getByRole("button", { name: "Reset" }).click();
  await expect(page.locator(".hbar", { hasText: "claude-sonnet-5" }).first()).toBeVisible();
  await page.goto("/");
  await page.locator(".row-name", { hasText: "gpt-6-luna" }).click();
  await expect(page.locator(".side-panel h2")).toHaveText("gpt-6-luna");
  await expect(page.locator(".side-panel")).toContainText("vs pick-trader");
  await page.getByRole("button", { name: "← Filters" }).click();
  await expect(page.locator(".side-panel h2")).toHaveText("Filter");
});

test("score vs cost plots measured rows and names the unmeasured ones", async ({ page }) => {
  await page.goto("/cost/");
  const unmeasured = data.agentic_lane.filter((r: { telemetry: { cost_per_episode_usd: number | null; api_equivalent_cost_per_episode_usd?: number | null } }) =>
    r.telemetry.cost_per_episode_usd === null && (r.telemetry.api_equivalent_cost_per_episode_usd ?? null) === null);
  await expect(page.locator(".chart circle")).toHaveCount(rows.length - unmeasured.length);
  for (const r of unmeasured) await expect(page.getByText(new RegExp(`cost unmeasured: .*${r.model}`))).toBeVisible();
});

test("how it works steps through one pick-trader season with its tool calls", async ({ page }) => {
  const errors = await noErrors(page);
  await page.goto("/how-it-works/");
  await expect(page.locator(".tabs a[aria-current=page]")).toHaveText("How it works");
  await expect(page.locator(".how-brief")).toContainText("You are the general manager of");
  await page.getByRole("button", { name: "Preseason →" }).click();
  await expect(page).toHaveURL(/#preseason$/);
  await expect(page.locator(".how-step h2")).toHaveText("Season 1 · Preseason");
  await expect(page.locator(".how-moves")).toContainText("Extended Gabe Reed");
  await page.getByText(/tool calls a model would make/).click();
  await expect(page.locator(".how-raw code")).toContainText('extend_contract({"player_id":8');
  await page.getByRole("button", { name: /Trade deadline/ }).first().click();
  await expect(page.locator(".how-moves")).toContainText("to Boston Harbors for their season-2 draft pick");
  await page.goto("/how-it-works/#recap");
  await expect(page.locator(".how-step h2")).toHaveText("The rest of the game");
  await expect(page.locator(".how-final")).toContainText("198.");
  expect(errors).toEqual([]);
});

test("cost points and tool bars open details in the side panel and highlight their row", async ({ page }) => {
  const errors = await noErrors(page);
  await page.goto("/cost/");
  await expect(page.locator(".view-head span")).toContainText(
    verdict(
      priced,
      `N measured row${priced.filter(clears).length === 1 ? " beats" : "s beat"} pick-trader by more than the noise.`,
      `N measured row${priced.filter((row) => row.mean_score > bar).length === 1 ? " scores" : "s score"} above pick-trader's mean, within the noise.`,
      "No measured row scores above pick-trader.",
    ),
  );
  const point = page.getByRole("button", { name: /^gpt-6-luna, Codex: score/ });
  await point.locator("circle").hover();
  await expect(page.locator(".chart .pt.is-dim")).toHaveCount(await page.locator(".chart .pt").count() - 1);
  await point.locator("circle").click();
  await expect(page.locator(".side-panel h2")).toHaveText("gpt-6-luna");
  await expect(point).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Linear" }).click();
  await expect(page.getByText(/linear scale/)).toBeVisible();
  await page.goto("/tools/");
  await expect(page.locator(".metric")).toHaveCount(6);
  await page.locator(".hbar", { hasText: "claude-haiku-4-5" }).first().click();
  await expect(page.locator(".side-panel h2")).toHaveText("claude-haiku-4-5");
  await expect(page.locator(".hbar[aria-pressed=true]")).toHaveCount(6);
  expect(errors).toEqual([]);
});

test("phone layout: filter opens as a sheet and no page scrolls sideways", async ({ page }) => {
  const errors = await noErrors(page);
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "Filter", exact: true }).click();
  await expect(page.locator(".side-panel.is-open")).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.locator(".side-panel.is-open")).toHaveCount(0);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 800 });
    for (const path of PAGES) {
      await page.goto(path);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${path} at ${width}px`).toBe(true);
      // Every tab stays reachable: the phone tab row must not clip any of them.
      for (const tab of await page.locator(".tabs a").all()) {
        const box = await tab.boundingBox();
        expect(box && box.x >= 0 && box.x + box.width <= width, `${path} tab at ${width}px`).toBe(true);
      }
    }
  }
  expect(errors).toEqual([]);
});

test("every page passes axe in both themes", async ({ page }) => {
  const errors = await noErrors(page);
  for (const theme of ["dark", "light"]) {
    await page.addInitScript((t) => localStorage.setItem("gm-bench-theme", t), theme);
    for (const path of PAGES) {
      await page.goto(path);
      const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(result.violations.map((v) => `${path} ${theme}: ${v.id} ${v.nodes[0]?.target}`)).toEqual([]);
    }
  }
  expect(errors).toEqual([]);
});

test("every page has one h1", async ({ page }) => {
  for (const path of PAGES) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 }), path).toHaveCount(1);
  }
});

for (const costs of [[0, 0.2, null], [0, 0, null], [0.2, 2, null], [null, null, null]]) {
  test(`cost chart handles ${JSON.stringify(costs)} without invalid coordinates`, async ({ page }) => {
    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");
    const { default: CostView } = await import("../src/app/CostView");
    const fixture = structuredClone(data);
    fixture.agentic_lane = fixture.agentic_lane.slice(0, costs.length);
    fixture.agentic_lane.forEach((row: typeof data.agentic_lane[number], index: number) => {
      row.telemetry.cost_per_episode_usd = costs[index];
      row.telemetry.api_equivalent_cost_per_episode_usd = null;
    });
    await page.setContent(renderToStaticMarkup(createElement(CostView, { data: fixture })));
    const positions = await page.locator("circle").evaluateAll((nodes) => nodes.map((n) => Number(n.getAttribute("cx"))));
    expect(positions).toHaveLength(costs.filter((c) => c !== null).length);
    expect(positions.every(Number.isFinite)).toBe(true);
    expect(await page.content()).not.toMatch(/NaN|Infinity/);
    if (costs.includes(0)) {
      await expect(page.getByText("$0", { exact: true })).toBeVisible();
      await expect(page.getByText(/positive costs log scale; \$0 separate/)).toBeVisible();
      expect(await page.locator(".point-label").first().textContent()).toContain("$0.00");
      if (costs[1] && costs[1] > 0) expect(positions[1]).toBeGreaterThan(positions[0]);
    }
    if (costs.every((c) => c === null)) await expect(page.getByText(/No row in the current filter/)).toBeVisible();
    await expect(page.getByText(/Not shown, cost unmeasured:/)).toBeVisible();
  });
}

test("mobile sheets contain focus, restore triggers, and survive navigation and resizing", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  const filter = page.getByRole("button", { name: "Filter", exact: true });
  const close = page.getByRole("button", { name: "Close", exact: true });
  const dialog = page.getByRole("dialog");
  for (const exit of ["Escape", "close", "scrim"]) {
    await filter.click();
    await expect(dialog).toHaveAttribute("aria-modal", "true");
    await expect(close).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(dialog.getByRole("checkbox", { name: "Show bots" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(close).toBeFocused();
    await page.locator(".wordmark").evaluate((el: HTMLElement) => el.focus());
    await expect(close).toBeFocused();
    if (exit === "Escape") await page.keyboard.press("Escape");
    else if (exit === "close") await close.click();
    else await page.locator(".sheet-scrim").click({ position: { x: 5, y: 5 } });
    await expect(dialog).toHaveCount(0);
    await expect(filter).toBeFocused();
    await expect(page.locator("[inert]")).toHaveCount(0);
  }
  const row = page.locator(".row-name", { hasText: "gpt-6-luna" });
  await row.click();
  await expect(close).toBeFocused();
  await dialog.getByRole("button", { name: "← Filters" }).click();
  await expect(close).toBeFocused();
  await close.click();
  await expect(row).toBeFocused();
  await row.click();
  await dialog.getByRole("button", { name: "← Filters" }).click();
  await dialog.getByRole("checkbox", { name: /OpenAI/ }).uncheck();
  await close.click();
  await expect(filter).toBeFocused();
  await filter.click();
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(dialog).toHaveCount(0);
  await expect(page.locator("[inert]")).toHaveCount(0);
  await page.locator(".wordmark").focus();
  await expect(page.locator(".wordmark")).toBeFocused();
  await page.setViewportSize({ width: 390, height: 800 });
  await expect(dialog).toBeVisible();
  await expect(close).toBeFocused();
  await page.goto("/cost/");
  await expect(page.locator("[inert]")).toHaveCount(0);
  await page.getByRole("link", { name: "Standings", exact: true }).click();
  await filter.click();
  await expect(close).toBeFocused();
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(result.violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(filter).toBeFocused();
});
