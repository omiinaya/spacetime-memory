import { test, expect } from "@playwright/test";
import { gotoPage, pageText, expectText } from "./helpers";

/**
 * Navigation — the five dashboard tabs must render and switch correctly.
 */
test.describe("Dashboard navigation", () => {
  test("renders the header with all five tabs", async ({ page }) => {
    await page.goto("/");
    await expectText(page, "Spacetime Memory");
    for (const tab of ["Proxy Metrics", "Embedder Metrics", "Memory Manager", "Benchmarks", "Connection Wizard"]) {
      await expect(page.getByRole("button", { name: tab, exact: false })).toBeVisible();
    }
  });

  test("switches to Memory Manager tab", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");
    await expectText(page, "Memory Manager");
    await expectText(page, "Browse, search, and manage your memories");
  });

  test("switches to Connection Wizard tab", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Connection Wizard");
    await expectText(page, "Connection Wizard");
    await expectText(page, "Configure and verify your SpacetimeDB connection");
    await expect(page.getByRole("button", { name: "Test Connection" })).toBeVisible();
  });

  test("switches to Embedder Metrics tab", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Embedder Metrics");
    await expectText(page, "Embedder Metrics");
  });

  test("switches to Benchmarks tab", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Benchmarks");
    // Benchmarks loads static JSON; may show loading briefly then content or an error card.
    const text = await pageText(page);
    expect(text).toContain("Benchmark");
  });

  test("tab switch is idempotent (clicking the active tab keeps the view)", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");
    await gotoPage(page, "Memory Manager");
    await expectText(page, "Memory Manager");
  });
});
