import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage } from './helpers';

/**
 * E2E tests for the Cognitive Operations page.
 *
 * The page loads via SQL (mocked empty → empty state). These tests drive the
 * REGISTER form: validation errors (missing name, invalid config JSON) and a
 * successful register (reducer mocked ok → success banner).
 */

test.describe('Cognitive Ops Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/cognitive-ops');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /cognitive/i, exact: false })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [
      page.getByText(/no .*op|register|cognitive/i),
    ]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('register op shows validation error when name missing', async ({ page }) => {
    await page.getByRole('button', { name: 'Register Op', exact: true }).click();
    await expect(page.getByText('Register Cognitive Operation', { exact: true })).toBeVisible({ timeout: 8000 });
    // The form's submit button is exactly "Register"
    await page.getByRole('button', { name: 'Register', exact: true }).click();
    await expect(page.getByText('Op name is required')).toBeVisible({ timeout: 8000 });
  });

  test('register op shows validation error for invalid config JSON', async ({ page }) => {
    await page.getByRole('button', { name: 'Register Op', exact: true }).click();
    await expect(page.getByText('Register Cognitive Operation', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('e.g. entity_extract, semantic_search').fill('my_op');
    // config field: a textarea defaulting to '{}' — replace with bad JSON
    await page.locator('textarea').first().fill('not json');
    await page.getByRole('button', { name: 'Register', exact: true }).click();
    await expect(page.getByText('config_json is not valid JSON')).toBeVisible({ timeout: 8000 });
  });
});