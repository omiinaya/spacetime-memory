import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage } from './helpers';

/**
 * E2E tests for the Webhooks page.
 *
 * The page loads via executeSql (mocked empty → empty state). These tests
 * additionally drive the CREATE form end-to-end:
 *   - validation error when name/URL missing
 *   - successful submit (reducer calls are mocked ok → success banner)
 *   - tab switch to the Delivery Log
 */

test.describe('Webhooks Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/webhooks');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /webhooks/i, exact: false })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [
      page.getByText(/no webhooks|create a webhook|no .* yet/i),
    ]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('create webhook shows validation error when name and URL missing', async ({ page }) => {
    await page.getByRole('button', { name: /create webhook/i }).click();
    await expect(page.getByText('New Webhook', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText('Name and URL are required')).toBeVisible({ timeout: 8000 });
  });

  test('create webhook succeeds with name and URL', async ({ page }) => {
    await page.getByRole('button', { name: /create webhook/i }).click();
    await expect(page.getByText('New Webhook', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('My Webhook').fill('Test Hook');
    await page.getByPlaceholder('https://example.com/webhook').fill('https://example.com/hook');
    // The reducer is mocked ok; the app clears messages on the follow-up reload,
    // so the deterministic success signal is the form CLOSING (setShowForm(false)
    // only runs after the reducer call resolves).
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText('New Webhook', { exact: true })).toBeHidden({ timeout: 8000 });
  });

  test('switches to delivery log tab', async ({ page }) => {
    await page.getByRole('tab', { name: /delivery log/i }).click();
    await expect(page.getByText(/delivery log|no deliveries|deliver/i).first()).toBeVisible({ timeout: 8000 });
  });
});
