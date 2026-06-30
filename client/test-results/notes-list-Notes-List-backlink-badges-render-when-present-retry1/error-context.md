# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: notes-list.spec.ts >> Notes List >> backlink badges render when present
- Location: e2e/notes-list.spec.ts:62:3

# Error details

```
Test timeout of 30000ms exceeded while running "beforeEach" hook.
```

```
Error: locator.click: Test timeout of 30000ms exceeded.
Call log:
  - waiting for getByRole('link', { name: /^notes$/i })

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
  4  |  * E2E tests for the Notes List page — listing, empty state, new note navigation.
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
  18 | test.describe('Notes List', () => {
  19 |   test.beforeEach(async ({ page }) => {
  20 |     mockAuth(page);
  21 |     await page.goto('/');
> 22 |     await page.getByRole('link', { name: /^notes$/i }).click();
     |                                                        ^ Error: locator.click: Test timeout of 30000ms exceeded.
  23 |     await page.waitForTimeout(800);
  24 |   });
  25 | 
  26 |   test('renders heading and note count', async ({ page }) => {
  27 |     await expect(page.getByRole('heading', { name: 'Notes' })).toBeVisible();
  28 |     await expect(page.getByText(/note\(s\)/i)).toBeVisible({ timeout: 5000 });
  29 |   });
  30 | 
  31 |   test('renders New Note button', async ({ page }) => {
  32 |     const newBtn = page.getByRole('button', { name: /new note/i });
  33 |     await expect(newBtn).toBeVisible();
  34 |   });
  35 | 
  36 |   test('navigates to new note on click', async ({ page }) => {
  37 |     await page.getByRole('button', { name: /new note/i }).click();
  38 |     await page.waitForTimeout(500);
  39 |     expect(page.url()).toContain('/notes/new');
  40 |   });
  41 | 
  42 |   test('renders All Notes card', async ({ page }) => {
  43 |     await expect(page.getByText('All Notes')).toBeVisible();
  44 |   });
  45 | 
  46 |   test('shows empty state when no notes exist', async ({ page }) => {
  47 |     await page.waitForTimeout(2000);
  48 |     const pageContent = await page.textContent('body');
  49 |     // Valid states: empty notes, error, or loading
  50 |     const validStates = ['No notes yet', 'Create your first note', 'Connection error', 'Loading...'];
  51 |     const hasValidState = validStates.some(s => pageContent?.includes(s));
  52 |     expect(hasValidState).toBe(true);
  53 |   });
  54 | 
  55 |   test('notes list items are clickable and navigate to editor', async ({ page }) => {
  56 |     // This test verifies the list items have click handlers
  57 |     // In empty state, this just verifies the page structure
  58 |     const items = page.locator('[class*="rounded-lg"][class*="border"]').first();
  59 |     await expect(items).toBeVisible();
  60 |   });
  61 | 
  62 |   test('backlink badges render when present', async ({ page }) => {
  63 |     // Validate the badge styling is loaded (even without data)
  64 |     await expect(page.getByRole('heading', { name: 'Notes' })).toBeVisible();
  65 |   });
  66 | });
  67 | 
```