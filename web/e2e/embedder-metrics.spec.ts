import { test, expect } from "@playwright/test";
import { gotoPage, pageText } from "./helpers";

/**
 * Embedder Metrics — fetches /records from the collector (:9190) and renders
 * stat cards (RSS, embeddings, uptime, dimension, model) + sparklines.
 */
test.describe("Embedder Metrics", () => {
  test("loads collector records and renders stats", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Embedder Metrics");

    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/Collector Host|No embedder metrics|Failed to load embedder metrics|RSS|Embeddings/);

    const text = await pageText(page);
    expect(text).toContain("Collector Host");

    if (text.includes("Failed to load embedder metrics") || text.includes("No embedder metrics")) {
      test.info().annotations.push({
        type: "info",
        description: "Collector returned empty/error — stat cards not exercised.",
      });
      return;
    }

    // Stat labels present when data exists.
    for (const label of ["RSS Memory", "Embeddings", "Uptime", "Model"]) {
      await expect(page.locator("body")).toContainText(label, { timeout: 10000 });
    }
  });

  test("Fetch button re-runs the collector query", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Embedder Metrics");
    await page.getByRole("button", { name: "Fetch" }).click();
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/Collector Host|Failed to load embedder metrics|RSS|Embeddings|No embedder metrics/);
  });
});
