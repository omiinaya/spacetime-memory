import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage } from './helpers';

/**
 * E2E tests for the Pattern Detection page.
 *
 * Structural tests run against the empty mock. An additional corner test
 * drives the detection form: clicking "Run Detection" without a workspace ID
 * surfaces the validation error.
 */

test.describe('Pattern Detection Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/pattern-detection');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Pattern Detection', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Discover temporal, entity, and topic patterns', { exact: false }).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Temporal Clust', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('run detection without workspace id shows validation error', async ({ page }) => {
    // Leave workspace ID empty, click Run Detection
    await page.getByRole('button', { name: /run detection/i }).first().click();
    await expect(page.getByText('Workspace ID is required').first()).toBeVisible({ timeout: 8000 });
  });
});
