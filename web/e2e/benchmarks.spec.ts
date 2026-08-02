import { test, expect } from "@playwright/test";
import { gotoPage, pageText } from "./helpers";

/**
 * Benchmarks — loads static summary JSON (public/benchmark_results_summary.json)
 * and renders LoCoMo / BEAM / LongMemEval tabs with gauges and competitive bars.
 */
test.describe("Benchmarks", () => {
  test("renders the benchmark page with tabs", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Benchmarks");
    await expect(page.locator("body")).toContainText("Benchmark", { timeout: 15000 });
  });

  test("loads the summary JSON and renders gauges or an error card", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Benchmarks");

    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/LoCoMo|BEAM|LongMemEval|Failed to load|error/);

    const text = await pageText(page);
    expect(text).toMatch(/LoCoMo|BEAM|LongMemEval/);

    // Tab bar (if data loaded) or error card (if fetch failed).
    const hasTabs = await page.getByRole("button", { name: /LoCoMo|BEAM|LongMemEval/ }).count();
    if (hasTabs === 0) {
      test.info().annotations.push({
        type: "info",
        description: "Summary JSON missing or failed — tab bar not rendered.",
      });
    }
  });

  test("switches between benchmark tabs", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Benchmarks");
    const locomoTab = page.getByRole("button", { name: /LoCoMo/i }).first();
    const beamTab = page.getByRole("button", { name: /BEAM/i }).first();
    if ((await locomoTab.count()) === 0) {
      test.info().annotations.push({
        type: "info",
        description: "Summary JSON missing — cannot switch tabs.",
      });
      return;
    }
    await locomoTab.click();
    await page.waitForTimeout(300);
    await beamTab.click();
    await page.waitForTimeout(300);
    // No crash — page still shows benchmark content.
    await expect(page.locator("body")).toContainText("Benchmark", { timeout: 10000 });
  });
});
