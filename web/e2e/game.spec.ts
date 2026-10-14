import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { version } from "pyodide";

const SAVE_KEY = "gm-bench-human-save-v1";
async function runtime(page: Page) {
  await page.route(
    `https://cdn.jsdelivr.net/pyodide/v${version}/full/*`,
    async (route) => {
      const filename = new URL(route.request().url()).pathname
        .split("/")
        .at(-1)!;
      const types: Record<string, string> = {
        "pyodide.asm.mjs": "text/javascript",
        "pyodide.asm.wasm": "application/wasm",
        "pyodide-lock.json": "application/json",
        "python_stdlib.zip": "application/zip",
      };
      if (!types[filename])
        throw new Error(`Unexpected runtime file: ${filename}`);
      await route.fulfill({
        body: readFileSync(
          new URL(`../node_modules/pyodide/${filename}`, import.meta.url),
        ),
        contentType: types[filename],
        headers: { "Access-Control-Allow-Origin": "*" },
      });
    },
  );
}
async function start(page: Page) {
  await runtime(page);
  await page.goto("/play/");
  await page
    .getByRole("button", { name: "Start challenge", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Anchorage Auroras", exact: true }),
  ).toBeVisible({ timeout: 45000 });
}
async function office(page: Page, name: string) {
  await page
    .getByRole("navigation", { name: "Front office" })
    .getByRole("button", { name, exact: true })
    .click();
}
async function confirm(page: Page) {
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(page.locator(".gm-game")).toHaveAttribute("aria-busy", "false");
}
async function advance(page: Page) {
  await page.locator(".gm-progress button").click();
  await confirm(page);
}

test("play a full challenge: roster, contracts, lineup, scouting, draft, scores and resume", async ({
  page,
}) => {
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await start(page);
  await expect(page.locator(".gm-scoreboard")).toContainText("$19.45M");
  await expect(page.locator(".gm-context tbody tr")).toHaveCount(23);
  await office(page, "Roster");
  await page.getByRole("button", { name: "Select best by rating" }).click();
  await page.getByRole("button", { name: "Save lineup", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("lineup set");
  await office(page, "Free agents");
  await page.getByRole("button", { name: "Negotiate Owen Olsen" }).click();
  await page.getByRole("button", { name: "Review signing" }).click();
  await expect(page.getByRole("dialog")).toContainText("$13.06M");
  await confirm(page);
  await expect(page.locator(".gm-context tbody tr")).toHaveCount(24);
  await expect(page.locator(".gm-scoreboard")).toContainText("$13.06M");
  await office(page, "Office");
  await page
    .getByLabel("Your plan", { exact: true })
    .fill("Win now, keep a young core.");
  await page.getByRole("button", { name: "Save notebook" }).click();
  await expect(page.getByRole("status")).toContainText("memo");
  const before = await page.evaluate(
    (key) => localStorage.getItem(key),
    SAVE_KEY,
  );
  await page.reload();
  await page.getByRole("button", { name: "Resume saved challenge" }).click();
  await expect(page.locator(".gm-context tbody tr")).toHaveCount(24, {
    timeout: 45000,
  });
  expect(
    await page.evaluate((key) => localStorage.getItem(key), SAVE_KEY),
  ).toBe(before);
  await expect(page.getByLabel("Your plan", { exact: true })).toHaveValue(
    "Win now, keep a young core.",
  );
  for (let season = 1; season <= 5; season++) {
    await advance(page); // midseason
    await expect(page.locator(".gm-scoreboard")).toContainText(
      `Season ${season} / 5 · Midseason`,
    );
    await advance(page); // deadline
    await expect(page.locator(".gm-scoreboard")).toContainText(
      "Trade deadline",
    );
    await advance(page); // draft
    await office(page, "Draft");
    const scout = page.getByRole("button", { name: /^Scout / }).first();
    await scout.click();
    await expect(page.getByRole("status")).toContainText("scouted");
    await page
      .getByRole("button", { name: /^Draft / })
      .first()
      .click();
    await confirm(page);
    await expect(page.getByRole("status")).toContainText("drafted");
    await advance(page);
  }
  await expect(page.locator(".gm-finale")).toContainText("Final score:");
  await expect(page.locator(".gm-finale")).toContainText(
    "Scripted GM on the same seed and five seasons",
  );
  await expect(page.locator(".gm-progress button")).toBeDisabled();
  await office(page, "History");
  await expect(page.locator(".gm-main table tbody tr")).toHaveCount(5);
  const finalSave = await page.evaluate(
    (key) => localStorage.getItem(key),
    SAVE_KEY,
  );
  await page.reload();
  await page.getByRole("button", { name: "Resume saved challenge" }).click();
  await expect(page.locator(".gm-finale")).toBeVisible({ timeout: 45000 });
  expect(
    await page.evaluate((key) => localStorage.getItem(key), SAVE_KEY),
  ).toBe(finalSave);
  expect(errors).toEqual([]);
});

test("trade builder, counteroffers, extensions, releases and waivers expose consequences", async ({
  page,
}) => {
  test.setTimeout(90000);
  await start(page);
  await office(page, "Roster");
  await page
    .getByRole("button", { name: "Manage Kai Anders", exact: true })
    .click();
  await page.getByRole("button", { name: "Review extension" }).click();
  await expect(page.getByRole("dialog")).toContainText("2 years");
  await confirm(page);
  await page
    .getByRole("button", { name: "Manage Kai Anders", exact: true })
    .click();
  await page.getByRole("button", { name: "Review release" }).click();
  await expect(page.getByRole("dialog")).toContainText("Dead cap:");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  await page.getByRole("button", { name: "Review release" }).click();
  await confirm(page);
  await expect(page.getByRole("status")).toContainText("released Kai Anders");
  await expect(page.locator(".gm-context tbody tr")).toHaveCount(22);
  await office(page, "Trades");
  await page.getByLabel("Trade partner").selectOption("1");
  await page
    .locator(".gm-trade-grid .gm-card")
    .first()
    .getByRole("checkbox")
    .first()
    .check();
  await page
    .locator(".gm-trade-grid .gm-card")
    .last()
    .getByRole("checkbox")
    .first()
    .check();
  await page.getByRole("button", { name: "Review trade", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("You give:");
  await expect(page.getByRole("dialog")).toContainText("You receive:");
  await confirm(page);
  await expect(page.getByRole("status")).toContainText(/trade|offer|partner/);
  await advance(page);
  await office(page, "Office");
  await expect(
    page.getByRole("heading", { name: "Waiver wire" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review claim" }).first().click();
  await confirm(page);
  await expect(page.getByRole("status")).toContainText("claimed");
  await advance(page);
  await office(page, "Trades");
  await page
    .getByRole("button", { name: "Build counteroffer" })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Counteroffer", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review counteroffer" }).click();
  await expect(page.getByRole("dialog")).toContainText("Send counteroffer?");
  await confirm(page);
});

test("imports validate without losing active game, exports and replacing saves require review", async ({
  page,
}) => {
  test.setTimeout(90000);
  await start(page);
  const stored = await page.evaluate(
    (key) => localStorage.getItem(key)!,
    SAVE_KEY,
  );
  await page.getByLabel("Import save", { exact: true }).setInputFiles({
    name: "bad.json",
    mimeType: "application/json",
    buffer: Buffer.from('{"schema":"bad"}'),
  });
  await confirm(page);
  await expect(page.getByRole("alert")).toContainText("not a GM-Bench");
  expect(
    await page.evaluate((key) => localStorage.getItem(key), SAVE_KEY),
  ).toBe(stored);
  await page
    .getByRole("button", { name: "New challenge", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  expect(
    await page.evaluate((key) => localStorage.getItem(key), SAVE_KEY),
  ).toBe(stored);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export save", exact: true }).click();
  expect((await download).suggestedFilename()).toBe(
    "gm-bench-challenge-1.json",
  );
  await advance(page);
  await page.getByLabel("Import save", { exact: true }).setInputFiles({
    name: "valid.json",
    mimeType: "application/json",
    buffer: Buffer.from(stored),
  });
  await confirm(page);
  await expect(page.locator(".gm-scoreboard")).toContainText("Preseason");
});

test("download failures are retryable, corrupt saves stay exportable", async ({
  page,
}) => {
  test.setTimeout(90000);
  await runtime(page);
  await page.route("**/replay/gm_bench.zip", (route) =>
    route.fulfill({ status: 503, body: "unavailable" }),
  );
  await page.goto("/play/");
  await page.getByRole("button", { name: "Start challenge" }).click();
  await expect(page.getByRole("alert")).toContainText("HTTP 503", {
    timeout: 45000,
  });
  await page.unroute("**/replay/gm_bench.zip");
  await page.getByRole("button", { name: "Start challenge" }).click();
  await expect(page.locator(".gm-scoreboard")).toBeVisible({ timeout: 45000 });
  await page.evaluate((key) => localStorage.setItem(key, "bad json"), SAVE_KEY);
  await page.reload();
  await page.getByRole("button", { name: "Resume saved challenge" }).click();
  await expect(page.getByRole("alert")).toContainText("not valid JSON");
  await expect(page.getByRole("button", { name: "Export save" })).toBeEnabled();
});

test("all game screens and confirmation are accessible in both themes and fit phones", async ({
  page,
}) => {
  test.setTimeout(120000);
  await start(page);
  for (const theme of ["dark", "light"]) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    for (const view of [
      "Office",
      "Roster",
      "Free agents",
      "Trades",
      "Draft",
      "League",
      "History",
      "Rules",
    ]) {
      await office(page, view);
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        result.violations.map(
          (v) => `${theme} ${view}: ${v.id} ${v.nodes[0]?.target}`,
        ),
      ).toEqual([]);
    }
  }
  await page.locator(".gm-progress button").click();
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(axe.violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const view of [
      "Office",
      "Roster",
      "Free agents",
      "Trades",
      "Draft",
      "League",
      "History",
      "Rules",
    ]) {
      await office(page, view);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `${view} at ${width}`,
      ).toBe(true);
    }
  }
});
