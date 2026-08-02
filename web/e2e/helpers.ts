import { Page, expect } from "@playwright/test";

/**
 * Shared helpers for the Spacetime Memory dashboard E2E suite.
 *
 * The dashboard is a single-page app — navigation is tab buttons in the
 * header, not URLs. All specs navigate by clicking the tab, then assert
 * on the rendered page structure.
 */

export const BASE_URL = "http://127.0.0.1:5187";

/** Known workspace with real data (272 memories, 2478 KG nodes). */
export const DATA_WORKSPACE_NAME = "locomo_dated_sessions";

/** Workspace the dashboard's proxy identity owns (created by tests via API). */
export const E2E_WORKSPACE_PREFIX = "e2e-ui-test";

/** Navigate to a dashboard tab by its visible label. */
export async function gotoPage(page: Page, label: string): Promise<void> {
  await page.getByRole("button", { name: label, exact: false }).click();
  // Give React a beat to swap the view.
  await page.waitForTimeout(300);
}

/** Robust text-content read of the whole page (survives class minification). */
export async function pageText(page: Page): Promise<string> {
  return (await page.textContent("body")) || "";
}

/** Assert the page shows a given headline/text anywhere. */
export async function expectText(page: Page, text: string): Promise<void> {
  await expect(page.locator("body")).toContainText(text, { timeout: 15000 });
}

/** Wait for any of the given texts to appear (first match wins). */
export async function expectAnyText(page: Page, texts: string[]): Promise<void> {
  for (const t of texts) {
    const body = await pageText(page);
    if (body.includes(t)) return;
  }
  // None matched yet — poll once more through Playwright's auto-wait.
  await expect
    .poll(async () => pageText(page), { timeout: 15000 })
    .toMatch(new RegExp(texts.map(escapeRegExp).join("|")));
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Create a fresh E2E workspace via the proxy reducer API and return its id.
 * The proxy identity owns the workspace, so the UI Store/Delete actions work.
 */
export async function createE2EWorkspace(
  page: Page,
  proxyHost = "127.0.0.1",
  proxyPort = 5190,
  db = "spacetime-memory-v2",
): Promise<string> {
  const wsId = `${E2E_WORKSPACE_PREFIX}-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6)}`;
  const res = await page.request.post(
    `http://${proxyHost}:${proxyPort}/v1/database/${db}/call/create_workspace`,
    { data: [`E2E UI Test ${wsId.slice(-6)}`, "created by Playwright E2E", wsId] },
  );
  expect(res.status()).toBe(200);
  return wsId;
}

/** Store a memory through the proxy reducer API (used for UI assertions). */
export async function storeMemoryViaProxy(
  page: Page,
  wsId: string,
  content: string,
  proxyHost = "127.0.0.1",
  proxyPort = 5190,
  db = "spacetime-memory-v2",
): Promise<string> {
  const res = await page.request.post(
    `http://${proxyHost}:${proxyPort}/v1/database/${db}/call/store_memory`,
    {
      data: [wsId, "", "", "experience", content, "", "[]", 0.8, "", "", ""],
    },
  );
  expect(res.status()).toBe(200);
  return wsId;
}
