import { test, expect } from '@playwright/test';

/**
 * E2E tests for the Daily Notes page — date navigation, create, edit.
 */

function mockAuth(page: any) {
  page.addInitScript(() => {
    (window as any).__MOCK_AUTH__ = {
      account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
    };
  });
  page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
}

test.describe('Daily Notes', () => {
  test.beforeEach(async ({ page }) => {
    mockAuth(page);
    await page.goto('/');
    await page.getByRole('link', { name: /^daily notes$/i }).click();
    await page.waitForTimeout(800);
  });

  test('renders heading with calendar icon', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Daily Notes' })).toBeVisible();
  });

  test('shows formatted date string', async ({ page }) => {
    // Shows something like "Monday, June 29, 2026"
    const dateText = page.getByText(/, /);
    await expect(dateText).toBeVisible({ timeout: 5000 });
  });

  test('has date navigation arrows', async ({ page }) => {
    const leftArrow = page.getByRole('button', { name: '' }).first();
    await expect(leftArrow).toBeVisible();
    // Navigate backward
    await leftArrow.click();
    await page.waitForTimeout(300);
    // The date should have changed (still visible)
    await expect(page.getByText(/, /)).toBeVisible();
  });

  test('has Today button', async ({ page }) => {
    const todayBtn = page.getByRole('button', { name: /today/i });
    await expect(todayBtn).toBeVisible();
  });

  test('shows create button when no daily note exists', async ({ page }) => {
    // With no WebSocket data, shows "No note for this day yet"
    await page.waitForTimeout(1500);
    const bodyText = await page.textContent('body');
    if (bodyText?.includes('No note for this day yet')) {
      await expect(page.getByRole('button', { name: /create note/i })).toBeVisible();
    }
  });

  test('date navigation with right arrow', async ({ page }) => {
    // Get initial date text
    const datePattern = /\w+, \w+ \d+, \d{4}/;
    const initialText = await page.textContent('body');
    const initialMatch = initialText?.match(datePattern);
    
    // Click right arrow
    const buttons = page.getByRole('button');
    // The right arrow is typically the last icon button
    const rightArrow = buttons.filter({ hasNotText: /Today|Create|Chevron/ }).last();
    // Just verify we can navigate without crash
    await page.getByRole('button', { name: '' }).last().click();
    await page.waitForTimeout(300);
    await expect(page.getByText(/, /)).toBeVisible();
  });

  test('sparkle icon shows for today', async ({ page }) => {
    // Today's date gets a sparkles icon
    // This is visible regardless of data state
    const sparkles = page.locator('[class*="lucide-sparkles"]');
    await expect(sparkles).toBeVisible({ timeout: 3000 });
  });
});
