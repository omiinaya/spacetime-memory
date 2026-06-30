# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: daily-notes.spec.ts >> Daily Notes >> sparkle icon shows for today
- Location: e2e/daily-notes.spec.ts:76:3

# Error details

```
Test timeout of 30000ms exceeded while running "beforeEach" hook.
```

```
Error: locator.click: Test timeout of 30000ms exceeded.
Call log:
  - waiting for getByRole('link', { name: /^daily notes$/i })

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
  4  |  * E2E tests for the Daily Notes page — date navigation, create, edit.
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
  18 | test.describe('Daily Notes', () => {
  19 |   test.beforeEach(async ({ page }) => {
  20 |     mockAuth(page);
  21 |     await page.goto('/');
> 22 |     await page.getByRole('link', { name: /^daily notes$/i }).click();
     |                                                              ^ Error: locator.click: Test timeout of 30000ms exceeded.
  23 |     await page.waitForTimeout(800);
  24 |   });
  25 | 
  26 |   test('renders heading with calendar icon', async ({ page }) => {
  27 |     await expect(page.getByRole('heading', { name: 'Daily Notes' })).toBeVisible();
  28 |   });
  29 | 
  30 |   test('shows formatted date string', async ({ page }) => {
  31 |     // Shows something like "Monday, June 29, 2026"
  32 |     const dateText = page.getByText(/, /);
  33 |     await expect(dateText).toBeVisible({ timeout: 5000 });
  34 |   });
  35 | 
  36 |   test('has date navigation arrows', async ({ page }) => {
  37 |     const leftArrow = page.getByRole('button', { name: '' }).first();
  38 |     await expect(leftArrow).toBeVisible();
  39 |     // Navigate backward
  40 |     await leftArrow.click();
  41 |     await page.waitForTimeout(300);
  42 |     // The date should have changed (still visible)
  43 |     await expect(page.getByText(/, /)).toBeVisible();
  44 |   });
  45 | 
  46 |   test('has Today button', async ({ page }) => {
  47 |     const todayBtn = page.getByRole('button', { name: /today/i });
  48 |     await expect(todayBtn).toBeVisible();
  49 |   });
  50 | 
  51 |   test('shows create button when no daily note exists', async ({ page }) => {
  52 |     // With no WebSocket data, shows "No note for this day yet"
  53 |     await page.waitForTimeout(1500);
  54 |     const bodyText = await page.textContent('body');
  55 |     if (bodyText?.includes('No note for this day yet')) {
  56 |       await expect(page.getByRole('button', { name: /create note/i })).toBeVisible();
  57 |     }
  58 |   });
  59 | 
  60 |   test('date navigation with right arrow', async ({ page }) => {
  61 |     // Get initial date text
  62 |     const datePattern = /\w+, \w+ \d+, \d{4}/;
  63 |     const initialText = await page.textContent('body');
  64 |     const initialMatch = initialText?.match(datePattern);
  65 |     
  66 |     // Click right arrow
  67 |     const buttons = page.getByRole('button');
  68 |     // The right arrow is typically the last icon button
  69 |     const rightArrow = buttons.filter({ hasNotText: /Today|Create|Chevron/ }).last();
  70 |     // Just verify we can navigate without crash
  71 |     await page.getByRole('button', { name: '' }).last().click();
  72 |     await page.waitForTimeout(300);
  73 |     await expect(page.getByText(/, /)).toBeVisible();
  74 |   });
  75 | 
  76 |   test('sparkle icon shows for today', async ({ page }) => {
  77 |     // Today's date gets a sparkles icon
  78 |     // This is visible regardless of data state
  79 |     const sparkles = page.locator('[class*="lucide-sparkles"]');
  80 |     await expect(sparkles).toBeVisible({ timeout: 3000 });
  81 |   });
  82 | });
  83 | 
```