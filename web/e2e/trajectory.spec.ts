import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
const original = JSON.parse(readFileSync(new URL("../public/replay/trajectory-demo.json", import.meta.url), "utf8"));
const endpoint = "**/replay/trajectory-demo.json";

test("all windows, reversed navigation, views, swapping and browser history", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/replays/");
  await expect(page.getByRole("heading", { name: "Inspect the decision window." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Previous decision", exact: true })).toBeDisabled();
  for (let i = 2; i <= 20; i++) {
    await page.getByRole("button", { name: "Next decision", exact: true }).click();
    await expect(page.getByText(`Window ${i} of 20`, { exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Next decision", exact: true })).toBeDisabled();
  for (let i = 19; i >= 1; i--) {
    await page.getByRole("button", { name: "Previous decision", exact: true }).click();
    await expect(page.getByText(`Window ${i} of 20`, { exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: "02 · First deadline: future picks" }).click();
  await expect(page.getByText("Pick ledger:")).toBeVisible();
  await page.getByRole("button", { name: "Roster & changes", exact: true }).click();
  await expect(page.locator(".tx-roster")).toHaveCount(2);
  await page.getByRole("button", { name: "Observations & tools", exact: true }).click();
  await expect(page.getByText("Tool retrieval trace: unavailable.", { exact: true })).toHaveCount(2);
  await page.locator(".tx-left").getByText("Inspect recorded observation", { exact: true }).first().click();
  await expect(page.locator(".tx-left .tx-json[open] pre")).toContainText('"scout_reports"');
  await page.getByRole("button", { name: "Swap left and right policies" }).click();
  await expect(page.locator(".tx-left h3")).toHaveText("Pick-trader");
  await page.goBack(); await expect(page.locator(".tx-left h3")).toHaveText("Conservative");
  await page.goForward(); await expect(page.locator(".tx-left h3")).toHaveText("Pick-trader");
  await page.reload(); await expect(page.locator(".tx-left h3")).toHaveText("Pick-trader");
  await page.getByLabel("B / Right policy").selectOption("pick-trader");
  await expect(page.getByRole("heading", { name: "Comparison paused." })).toBeVisible();
  await page.getByLabel("B / Right policy").selectOption("conservative");
  await expect(page.locator(".tx-lanes")).toBeVisible();
  expect(errors).toEqual([]);
});

test("keyboard, mobile and light/dark accessibility", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/replays/");
  const next = page.getByRole("button", { name: "Next decision", exact: true });
  await next.focus(); await page.keyboard.press("Enter");
  await expect(page.getByText("Window 2 of 20", { exact: true })).toBeVisible();
  for (const theme of ["dark", "light"]) {
    await page.evaluate(t => { document.documentElement.dataset.theme = t; }, theme);
    const result = await new AxeBuilder({ page }).include(".tx-explorer").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(result.violations).toEqual([]);
  }
  for (const width of [390, 320, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole("button", { name: "Roster & changes", exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator(".tx-right h3")).toBeVisible();
  }
});

test("loading, HTTP error, retry and malformed export", async ({ page }) => {
  let resolve: () => void = () => {};
  const gate = new Promise<void>(r => { resolve = r; });
  await page.route(endpoint, async route => { await gate; await route.fulfill({ status: 503, body: "unavailable" }); });
  await page.goto("/replays/");
  await expect(page.getByRole("heading", { name: "Opening the front-office ledger…" })).toBeVisible();
  resolve();
  await expect(page.getByRole("alert")).toContainText("HTTP 503");
  await page.unroute(endpoint);
  await page.getByRole("button", { name: "Retry loading" }).click();
  await expect(page.locator(".tx-lanes")).toBeVisible();
  await page.route(endpoint, route => route.fulfill({ json: { schema: "broken" } }));
  await page.reload(); await expect(page.getByRole("alert")).toContainText("Unsupported public trajectory export");
});

test("empty, mismatched, absent observations, corrupt render fields", async ({ page }) => {
  const cases = ["empty", "mismatch", "missing", "bad-roster", "bad-player", "no-results"];
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  for (const kind of cases) {
    const data = structuredClone(original);
    if (kind === "empty") data.episodes = [];
    if (kind === "mismatch") data.episodes[1].fixture.seed = 2;
    if (kind === "missing") delete data.episodes[0].fixture.decisions[1].interaction_rounds[0].observation;
    if (kind === "bad-roster") data.episodes[0].fixture.decisions[1].interaction_rounds[0].observation.team.roster[0].overall = "bad";
    if (kind === "bad-player") data.episodes[0].fixture.expected.state.players["1"] = null;
    if (kind === "no-results") data.episodes[0].fixture.decisions[1].results = [];
    await page.route(endpoint, route => route.fulfill({ json: data }));
    await page.goto("/replays/?window=2&view=observations");
    if (kind === "empty") await expect(page.getByRole("heading", { name: "No comparison available." })).toBeVisible();
    if (kind === "mismatch") await expect(page.getByText(/Starting scenarios do not match/)).toBeVisible();
    if (kind === "missing") await expect(page.getByText("Observation unavailable for this round. No reconstruction is shown.")).toBeVisible();
    if (kind.startsWith("bad-")) await expect(page.getByRole("alert")).toBeVisible();
    if (kind === "no-results") {
      await page.getByRole("button", { name: "Actions & outcomes", exact: true }).click();
      await expect(page.getByText("No action results were logged for this window.")).toBeVisible();
    }
    await page.unroute(endpoint);
  }
  expect(errors).toEqual([]);
});

test("retained browser verifier runs the original fixture with matching runtime", async ({ page }) => {
  // Use the installed runtime bytes to avoid CDN/certificate dependencies in CI.
  // The exact route also asserts that the worker requests the installed version.
  const { version } = await import("pyodide");
  const served: string[] = [];
  await page.route(`https://cdn.jsdelivr.net/pyodide/v${version}/full/*`, async route => {
    const filename = new URL(route.request().url()).pathname.split("/").at(-1)!;
    const types: Record<string, string> = {
      "pyodide.asm.mjs": "text/javascript", "pyodide.asm.wasm": "application/wasm",
      "pyodide-lock.json": "application/json", "python_stdlib.zip": "application/zip",
    };
    if (!types[filename]) throw new Error(`Unexpected runtime file: ${filename}`);
    served.push(filename);
    await route.fulfill({ body: readFileSync(new URL(`../node_modules/pyodide/${filename}`, import.meta.url)), contentType: types[filename], headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/replays/");
  await page.getByText("Original conservative replay & browser verifier", { exact: true }).click();
  await page.getByRole("button", { name: "verify fixture", exact: true }).click();
  await expect(page.locator(".replay-check")).toContainText("Verified 20 decision windows", { timeout: 45000 });
  expect(served).toContain("pyodide.asm.wasm");
  await page.getByRole("button", { name: "run again", exact: true }).click();
  await expect(page.locator(".replay-check")).toContainText("Verified 20 decision windows", { timeout: 45000 });
});
