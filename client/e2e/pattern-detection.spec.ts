import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, mockSqlCalls } from './helpers';

/**
 * E2E tests for the Pattern Detection page.
 *
 * Structural tests run against the empty mock. Corner tests drive the
 * detection form: missing workspace ID surfaces the validation error, and a
 * valid workspace ID fires the reducer + SQL read and shows the success
 * message for each of the three detection sections.
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

  test('all three detection sections run with a workspace id', async ({ page }) => {
    // SQL mock returns empty result rows so each section reports 0 results.
    await mockSqlCalls(page, []);
    const wsInput = page.getByPlaceholder('workspace-id');
    await wsInput.fill('ws-e2e');
    // Temporal
    await page.getByRole('button', { name: /run detection/i }).nth(0).click();
    await expect(page.getByText('Temporal cluster detection complete', { exact: false })).toBeVisible({ timeout: 8000 });
    // Co-occurrence
    await page.getByRole('button', { name: /run detection/i }).nth(1).click();
    await expect(page.getByText('Entity co-occurrence detection complete', { exact: false })).toBeVisible({ timeout: 8000 });
    // Topic
    await page.getByRole('button', { name: /run detection/i }).nth(2).click();
    await expect(page.getByText('Topic cluster detection complete', { exact: false })).toBeVisible({ timeout: 8000 });
  });
});
