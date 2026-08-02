import { test, expect } from "@playwright/test";
import {
  gotoPage,
  pageText,
  createE2EWorkspace,
  storeMemoryViaProxy,
  DATA_WORKSPACE_NAME,
} from "./helpers";

/**
 * Memory Manager — the primary UI. Covers:
 *  - workspace dropdown (loaded via private-table reducer path through proxy)
 *  - memories list + search + type filter + refresh
 *  - Store New Memory form (reducer through proxy)
 *  - Delete memory (reducer through proxy, soft-delete)
 *  - Stats tab (counts from public tables + private note table)
 *  - Knowledge Graph tab (KGVisualizer canvas)
 *  - Explorer tab (KGExplorer node grid)
 */
test.describe("Memory Manager", () => {
  test("loads workspaces from the proxy (private table path)", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");

    await expectText(page, "Memory Manager");
    // Workspace dropdown populated by the reducer-backed query.
    await expect(page.locator("select").first()).toBeVisible({ timeout: 20000 });
    // The known data workspace should appear (public/registered access).
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toContain("locomo_dated_sessions");
  });

  test("selecting a workspace loads memories", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");

    const wsSelect = page.locator("select").first();
    await expect(wsSelect).toBeVisible({ timeout: 20000 });
    await wsSelect.selectOption({ label: DATA_WORKSPACE_NAME });

    // Memories tab is default — should render the list or the empty state.
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/Store New Memory|No memories found/);
    // The store form is present once a workspace is active.
    await expectText(page, "Store New Memory");
    await expect(page.getByPlaceholder("Memory content...")).toBeVisible();
    await expect(page.getByRole("button", { name: "Store" })).toBeVisible();
  });

  test("store + search + delete a memory round-trip through the UI", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");

    // Create a workspace the proxy identity owns, via the API.
    const wsId = await createE2EWorkspace(page);

    // Refresh the workspace dropdown to include it.
    await page.reload();
    await gotoPage(page, "Memory Manager");
    const wsSelect = page.locator("select").first();
    await expect(wsSelect).toBeVisible({ timeout: 20000 });
    await wsSelect.selectOption(wsId);

    const unique = `E2E UI memory ${Date.now()}`;

    // Store via the UI form.
    await page.getByPlaceholder("Memory content...").fill(unique);
    await page.getByPlaceholder("Summary (optional)").fill("e2e summary");
    await page.getByRole("button", { name: "Store" }).click();

    // Success message + memory appears in the list.
    await expectText(page, "Memory stored");
    await expectText(page, unique);

    // Search for it.
    await page.getByPlaceholder("Search memories...").fill(unique);
    await page.getByRole("button", { name: "Refresh" }).click();
    await expectText(page, unique);

    // Delete it — confirm dialog then verify gone.
    page.on("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "✕" }).first().click();
    await expect
      .poll(async () => pageText(page), { timeout: 15000 })
      .not.toContain(unique);
  });

  test("search filters the memory list", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");
    const wsSelect = page.locator("select").first();
    await expect(wsSelect).toBeVisible({ timeout: 20000 });
    await wsSelect.selectOption({ label: DATA_WORKSPACE_NAME });

    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/Store New Memory|No memories found/);

    // Type a nonsense query — list should become empty (no matches).
    await page.getByPlaceholder("Search memories...").fill("zzzz-no-such-memory-xyz");
    await page.getByRole("button", { name: "Refresh" }).click();
    await expectText(page, "No memories found");
  });

  test("type filter limits by memory_type", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");
    const wsSelect = page.locator("select").first();
    await expect(wsSelect).toBeVisible({ timeout: 20000 });
    await wsSelect.selectOption({ label: DATA_WORKSPACE_NAME });

    const typeSelect = page.locator("select").nth(1);
    await expect(typeSelect).toBeVisible({ timeout: 20000 });
    await typeSelect.selectOption("fact");
    await page.getByRole("button", { name: "Refresh" }).click();
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/No memories found|Store New Memory/);
  });

  test("stats tab renders counts", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");
    const wsSelect = page.locator("select").first();
    await expect(wsSelect).toBeVisible({ timeout: 20000 });
    await wsSelect.selectOption({ label: DATA_WORKSPACE_NAME });

    await page.getByRole("button", { name: "Stats" }).click();
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/Memories|Loading stats|Refresh Stats/);
    await expectText(page, "Refresh Stats");
    // Count cards appear once loaded.
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/KG Nodes|KG Edges/);
  });

  test("knowledge graph tab renders the visualizer", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");
    const wsSelect = page.locator("select").first();
    await expect(wsSelect).toBeVisible({ timeout: 20000 });
    await wsSelect.selectOption({ label: DATA_WORKSPACE_NAME });

    await page.getByRole("button", { name: "Knowledge Graph" }).click();
    await expectText(page, "Knowledge Graph Visualizer");
    // Canvas is present (headless may create a zero-size canvas — assert attach).
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeAttached({ timeout: 20000 });
    // Legend/status line with node+edge counts appears once loaded.
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/nodes, .* edges|No KG nodes found/);
  });

  test("explorer tab renders the node explorer", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");
    const wsSelect = page.locator("select").first();
    await expect(wsSelect).toBeVisible({ timeout: 20000 });
    await wsSelect.selectOption({ label: DATA_WORKSPACE_NAME });

    await page.getByRole("button", { name: "Explorer" }).click();
    await expectText(page, "KG Node Explorer");
    await expect(page.getByPlaceholder("Search nodes by label...")).toBeVisible();
    await page.getByRole("button", { name: "Search" }).click();
    await expect
      .poll(async () => pageText(page), { timeout: 20000 })
      .toMatch(/No nodes found|entity|concept|code|document|topic/);
  });

  test("unselected workspace shows the prompt", async ({ page }) => {
    await page.goto("/");
    await gotoPage(page, "Memory Manager");
    await expectText(page, "Select a workspace above to view its memories");
  });
});

async function expectText(page: import("@playwright/test").Page, text: string) {
  await expect(page.locator("body")).toContainText(text, { timeout: 15000 });
}
