import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage } from './helpers';

/**
 * E2E tests for the Context Tree Editor page.
 *
 * The page loads via SQL (mocked empty → empty state). These tests drive the
 * CREATE form: validation error when path/content missing, and a successful
 * create (reducer mocked ok → success banner).
 */

test.describe('Context Tree Editor Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/context-tree');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /context tree/i, exact: false })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [
      page.getByText(/no .*context|create|no .* yet/i),
    ]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('create context entry shows validation error when path and content missing', async ({ page }) => {
    await page.getByRole('button', { name: /add context/i }).click();
    await expect(page.getByText('New Context Entry', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText('Path and content are required')).toBeVisible({ timeout: 8000 });
  });

  test('create context entry succeeds with path and content', async ({ page }) => {
    await page.getByRole('button', { name: /add context/i }).click();
    await expect(page.getByText('New Context Entry', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('/api/v2').fill('/api/v1');
    await page.getByPlaceholder('Context text for this path').fill('Context entry content');
    // Reducer mocked ok → the form CLOSES (setShowForm(false) only runs on success)
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText('New Context Entry', { exact: true })).toBeHidden({ timeout: 8000 });
  });
});