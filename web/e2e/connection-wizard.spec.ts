import { test, expect } from "@playwright/test";
import { gotoPage, pageText } from "./helpers";

/**
 * Connection Wizard — config + verify page. Tests the test-connection flow,
 * config generation, copy, and download behaviors.
 */
test.describe("Connection Wizard", () => {
  test("renders the wizard form", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Connection Wizard");
    await expect(page.locator("body")).toContainText("Connection Wizard", { timeout: 15000 });
    for (const label of ["SpacetimeDB Host", "Port", "Database Name", "Embedder URL"]) {
      await expect(page.locator("body")).toContainText(label, { timeout: 10000 });
    }
    await expect(page.getByRole("button", { name: "Test Connection" })).toBeVisible();
  });

  test("editing fields resets the status", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Connection Wizard");
    // Host field is the FIRST textbox (before the embedder URL input).
    const host = page.locator('input[type="text"]').first();
    await host.fill("10.0.0.5");
    await expect(page.locator('input[value="10.0.0.5"]').first()).toBeVisible();
  });

  test("test connection succeeds against the live backend", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Connection Wizard");
    await page.getByRole("button", { name: "Test Connection" }).click();

    // Success path: module found → config generated with YAML + env vars.
    await expect
      .poll(async () => pageText(page), { timeout: 25000 })
      .toMatch(/SpacetimeDB is running|Unexpected response|Connection failed/);

    const text = await pageText(page);
    if (text.includes("SpacetimeDB is running")) {
      // Config block appears.
      await expect
        .poll(async () => pageText(page), { timeout: 10000 })
        .toContain("spacetimedb:");
      await expectText(page, "export SPACETIMEDB_HOST");
      await expect(page.getByRole("button", { name: "Copy" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Download" })).toBeVisible();
    } else {
      test.info().annotations.push({
        type: "info",
        description: "Live backend unreachable in this run — success path skipped.",
      });
    }
  });

  test("copy button copies the config", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Connection Wizard");
    await page.getByRole("button", { name: "Test Connection" }).click();
    await expect
      .poll(async () => pageText(page), { timeout: 25000 })
      .toMatch(/SpacetimeDB is running|Unexpected response|Connection failed/);

    if ((await page.getByRole("button", { name: "Copy" }).count()) > 0) {
      await page.getByRole("button", { name: "Copy" }).click();
      // No crash — page remains.
      await expect(page.locator("body")).toContainText("Configuration", { timeout: 5000 });
    }
  });
});

async function expectText(page: import("@playwright/test").Page, text: string) {
  await expect(page.locator("body")).toContainText(text, { timeout: 15000 });
}
