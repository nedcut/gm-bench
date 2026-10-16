import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";

const findings = JSON.parse(readFileSync(new URL("../src/data/v21-findings.json", import.meta.url), "utf8"));
const gap = findings.family_gap;

test("the footer links the Findings page, which shows the diagnostic's numbers", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/method/");
  await page.locator(".footer").getByRole("link", { name: "Findings" }).click();
  await expect(page).toHaveURL(/\/findings\/$/);
  await expect(page.locator(".footer a[aria-current=page]")).toHaveText("Findings");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Findings");
  await expect(page.locator(".lede")).toContainText(
    `${gap.final_score.mean.toFixed(1)} points of final score, paired seed by seed, and are ahead on ${gap.final_score.ahead} of ${gap.seeds} seeds`,
  );
  await expect(page.locator(".gap-row")).toHaveCount(gap.terms.length + 1);
  await expect(page.locator(".findings-table tbody tr")).toHaveCount(findings.models.length);
  await expect(page.getByRole("link", { name: "Diagnostic data" })).toHaveAttribute("href", /results\/diagnostics\/v21_behavior\/behavior\.json$/);
  expect(errors).toEqual([]);
});

test("the Findings page fits a phone and passes axe in both themes", async ({ page }) => {
  for (const theme of ["dark", "light"]) {
    await page.addInitScript((t) => localStorage.setItem("gm-bench-theme", t), theme);
    for (const width of [320, 390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/findings/");
      const wide = await page.evaluate(() =>
        document.documentElement.scrollWidth <= innerWidth
          ? []
          : [...document.querySelectorAll("body *")]
              .filter((el) => !el.closest(".table-scroll") && el.getBoundingClientRect().right > innerWidth + 0.5)
              .map((el) => `${el.tagName}.${el.className} ${Math.round(el.getBoundingClientRect().right)}`)
              .concat(`scrollWidth ${document.documentElement.scrollWidth}`),
      );
      expect(wide, `${theme} at ${width}px`).toEqual([]);
    }
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(result.violations.map((v) => `${theme}: ${v.id} ${v.nodes[0]?.target}`)).toEqual([]);
  }
});

test("a 2.1 row's details explain empty phases and show unused draft picks", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.locator("#standings .row-name", { hasText: "claude-opus-5-5" }).click();
  const panel = page.locator(".side-panel");
  const opus = findings.models.find((m: { model: string }) => m.model === "claude-opus-5-5");
  await expect(panel.locator(".stat", { hasText: "Unused draft picks" })).toContainText(`${opus.drafts_closed_holding_unused_pick} / ${opus.drafts}`);
  await expect(panel.getByRole("link", { name: "what it measures" })).toHaveAttribute("href", /\/findings\/$/);
});
