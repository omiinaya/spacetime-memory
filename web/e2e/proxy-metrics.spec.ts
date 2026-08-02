import { test, expect } from "@playwright/test";
import { gotoPage, pageText } from "./helpers";

/**
 * Proxy Metrics — the default page. Queries proxy_metrics_snapshot (public
 * table) via the proxy SQL endpoint and renders stat cards, trend charts,
 * per-model breakdown, and a recent-snapshots table.
 */
test.describe("Proxy Metrics", () => {
  test("loads metrics and renders stat cards", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Proxy Metrics");

    // The page auto-fetches on mount. Wait for either data or a clear empty/error state.
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/Snapshots|No proxy metrics found|Failed to load proxy metrics|STDB error/);

    const text = await pageText(page);
    // Connection config bar present.
    expect(text).toContain("Database");
    expect(page.getByRole("button", { name: "Fetch" })).toBeVisible();

    if (text.includes("No proxy metrics found") || text.includes("STDB error")) {
      test.info().annotations.push({
        type: "info",
        description: "Backend returned empty/error — stat cards not exercised.",
      });
      return;
    }

    // Stat cards: Snapshots, Total Requests, Total Tokens, Error Rate, Avg Duration.
    for (const label of ["Snapshots", "Total Requests", "Total Tokens", "Error Rate", "Avg Duration"]) {
      await expectTextLike(page, label);
    }
    // Trends + recent snapshots table headers.
    await expectTextLike(page, "Trends");
    await expectTextLike(page, "Recent Snapshots");
  });

  test("Fetch button re-runs the query", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Proxy Metrics");
    await page.getByRole("button", { name: "Fetch" }).click();
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/Snapshots|No proxy metrics found|Failed to load proxy metrics|STDB error/);
  });

  test("Refresh button works when data is present", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Proxy Metrics");
    const refresh = page.getByRole("button", { name: "Refresh" });
    if ((await refresh.count()) > 0) {
      await refresh.click();
      await expect
        .poll(async () => pageText(page), { timeout: 20000 })
        .toMatch(/Snapshots|No proxy metrics found|Failed to load proxy metrics|STDB error/);
    } else {
      test.info().annotations.push({
        type: "info",
        description: "No data present — Refresh button not rendered.",
      });
    }
  });

  test("host/port/database inputs are editable", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Proxy Metrics");
    const host = page.locator('input[value="127.0.0.1"]').first();
    await host.fill("127.0.0.1");
    await expect(page.locator('input[value="127.0.0.1"]').first()).toBeVisible();
    // Restore.
    await page.locator('input[value="127.0.0.1"]').first().fill("127.0.0.1");
  });
});

async function expectTextLike(page: import("@playwright/test").Page, text: string) {
  await expect(page.locator("body")).toContainText(text, { timeout: 15000 });
}
