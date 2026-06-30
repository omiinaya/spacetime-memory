# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: graph-viz.spec.ts >> Graph Visualization >> node type filter controls render after data loads
- Location: e2e/graph-viz.spec.ts:76:3

# Error details

```
Test timeout of 30000ms exceeded while running "beforeEach" hook.
```

```
Error: locator.click: Test timeout of 30000ms exceeded.
Call log:
  - waiting for getByRole('link', { name: /^graph viz$/i })

```

# Page snapshot

```yaml
- generic [ref=e2]:
  - generic [ref=e4]:
    - img [ref=e5]
    - img [ref=e7]
    - paragraph [ref=e9]: Loading...
  - region "Notifications alt+T"
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | /**
  4  |  * E2E tests for the Graph Visualization page — D3 force graph, controls, node search.
  5  |  */
  6  | 
  7  | function mockAuth(page: any) {
  8  |   page.addInitScript(() => {
  9  |     (window as any).__MOCK_AUTH__ = {
  10 |       account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
  11 |     };
  12 |   });
  13 |   page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
  14 |     await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  15 |   });
  16 | }
  17 | 
  18 | test.describe('Graph Visualization', () => {
  19 |   test.beforeEach(async ({ page }) => {
  20 |     mockAuth(page);
  21 |     await page.goto('/');
> 22 |     await page.getByRole('link', { name: /^graph viz$/i }).click();
     |                                                            ^ Error: locator.click: Test timeout of 30000ms exceeded.
  23 |     await page.waitForTimeout(1000);
  24 |   });
  25 | 
  26 |   test('renders heading and description', async ({ page }) => {
  27 |     await expect(page.getByRole('heading', { name: 'Graph Visualization' })).toBeVisible();
  28 |     await expect(page.getByText('Interactive force-directed knowledge graph')).toBeVisible({ timeout: 5000 });
  29 |   });
  30 | 
  31 |   test('shows loading state initially', async ({ page }) => {
  32 |     // Before graph data loads, shows spinner
  33 |     await expect(page.getByText('Building graph layout…')).toBeVisible({ timeout: 5000 });
  34 |   });
  35 | 
  36 |   test('shows node count indicator in loading', async ({ page }) => {
  37 |     await expect(page.getByText(/nodes?/i)).toBeVisible({ timeout: 5000 });
  38 |   });
  39 | 
  40 |   test('shows error state when data fetch fails', async ({ page }) => {
  41 |     // The fetchKG calls will fail since WS isn't connected
  42 |     await page.waitForTimeout(5000);
  43 |     const bodyText = await page.textContent('body');
  44 |     // Should show either loading (delayed) or error state
  45 |     const hasValidState = 
  46 |       (bodyText?.includes('Building graph layout') ?? false) ||
  47 |       (bodyText?.includes('Failed to load graph') ?? false) ||
  48 |       (bodyText?.includes('No graph data yet') ?? false);
  49 |     expect(hasValidState).toBe(true);
  50 |   });
  51 | 
  52 |   test('retry button appears on error', async ({ page }) => {
  53 |     await page.waitForTimeout(5000);
  54 |     const retryBtn = page.getByRole('button', { name: /retry/i });
  55 |     // If error state is shown, retry button exists
  56 |     const bodyText = await page.textContent('body');
  57 |     if (bodyText?.includes('Failed to load graph')) {
  58 |       await expect(retryBtn).toBeVisible();
  59 |     }
  60 |   });
  61 | 
  62 |   test('search input is present on the page', async ({ page }) => {
  63 |     // Even in loading state, the search input may not render until graph loads
  64 |     // But the overall page structure should be intact
  65 |     await expect(page.getByRole('heading', { name: 'Graph Visualization' })).toBeVisible();
  66 |   });
  67 | 
  68 |   test('zoom controls are present when graph loads', async ({ page }) => {
  69 |     // Zoom buttons are always present when graph is rendered
  70 |     // In loading/error state they may not be visible yet
  71 |     // Just verify the page didn't crash
  72 |     await page.waitForTimeout(2000);
  73 |     expect(true).toBe(true);
  74 |   });
  75 | 
  76 |   test('node type filter controls render after data loads', async ({ page }) => {
  77 |     // This is a structural test for the filter panel
  78 |     // The filter by type panel has checkboxes for code, concept, entity, document, topic
  79 |     await expect(page.getByRole('heading', { name: 'Graph Visualization' })).toBeVisible();
  80 |   });
  81 | });
  82 | 
  83 | test.describe('Graph Viz — Empty Data', () => {
  84 |   test('shows empty state with link to Knowledge Graph', async ({ page }) => {
  85 |     // Navigate directly — with no data cached, eventually shows empty
  86 |     mockAuth(page);
  87 |     await page.goto('/graph-viz');
  88 |     await page.waitForTimeout(3000);
  89 |     const bodyText = await page.textContent('body');
  90 |     if (bodyText?.includes('No graph data yet')) {
  91 |       await expect(page.getByText('Go to Knowledge Graph')).toBeVisible();
  92 |     }
  93 |   });
  94 | });
  95 | 
```