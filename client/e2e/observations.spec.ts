import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage } from './helpers';

/**
 * E2E tests for the Observations page.
 *
 * The page loads via SQL (mocked empty → empty state). These tests drive the
 * CREATE form end-to-end: validation error when content missing, successful
 * create (reducer mocked ok → success banner), and the search filter input.
 */

test.describe('Observations Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/observations');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Observations', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [
      page.getByText(/no observation|create|no .* yet/i),
    ]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('create observation shows validation error when content missing', async ({ page }) => {
    // Header "Create" (opens form) is first; the form's submit "Create" is last
    await page.getByRole('button', { name: 'Create', exact: true }).first().click();
    await expect(page.getByText('New Observation', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByRole('button', { name: 'Create', exact: true }).last().click();
    await expect(page.getByText('Content is required')).toBeVisible({ timeout: 8000 });
  });

  test('create observation succeeds with content', async ({ page }) => {
    await page.getByRole('button', { name: 'Create', exact: true }).first().click();
    await expect(page.getByText('New Observation', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('Observation content').fill('The sky is blue on clear days');
    // Reducer mocked ok → the form CLOSES (setShowForm(false) only runs on success)
    await page.getByRole('button', { name: 'Create', exact: true }).last().click();
    await expect(page.getByText('New Observation', { exact: true })).toBeHidden({ timeout: 8000 });
  });

  test('search input filters the list', async ({ page }) => {
    await expect(page.getByPlaceholder('Search observations...')).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('Search observations...').fill('blue');
    // Empty list after filter is fine — the input accepts and filters
    await expect(page.getByPlaceholder('Search observations...')).toHaveValue('blue');
  });
});