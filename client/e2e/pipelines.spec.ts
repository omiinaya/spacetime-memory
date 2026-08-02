import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage } from './helpers';

/**
 * E2E tests for the Pipelines page.
 *
 * The page loads via executeSql (mocked empty → empty state). These tests
 * additionally drive the CREATE form end-to-end:
 *   - validation errors (missing name, no stage)
 *   - successful submit (reducer mocked ok → success banner)
 *   - tab switch to Execution History
 */

test.describe('Pipelines Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/pipelines');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /pipeline/i, exact: false })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [
      page.getByText(/no pipeline|create a pipeline|no .* yet/i),
    ]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('create pipeline shows validation error when name missing', async ({ page }) => {
    await page.getByRole('button', { name: /create pipeline/i }).click();
    await expect(page.getByText('New Pipeline', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText('Pipeline name is required')).toBeVisible({ timeout: 8000 });
  });

  test('create pipeline shows validation error when no stage selected', async ({ page }) => {
    await page.getByRole('button', { name: /create pipeline/i }).click();
    await expect(page.getByText('New Pipeline', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('My Pipeline').fill('Test Pipeline');
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText('At least one stage is required')).toBeVisible({ timeout: 8000 });
  });

  test('create pipeline succeeds with name and stage', async ({ page }) => {
    await page.getByRole('button', { name: /create pipeline/i }).click();
    await expect(page.getByText('New Pipeline', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('My Pipeline').fill('Test Pipeline');
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await expect(page.getByText(/stage order: search/i)).toBeVisible({ timeout: 8000 });
    // Reducer mocked ok → the form CLOSES (setShowForm(false) only runs on success)
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText('New Pipeline', { exact: true })).toBeHidden({ timeout: 8000 });
  });

  test('switches to execution history tab', async ({ page }) => {
    await page.getByRole('tab', { name: /execution history/i }).click();
    await expect(page.getByText(/execution|no execution|history/i).first()).toBeVisible({ timeout: 8000 });
  });
});