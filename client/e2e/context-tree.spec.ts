import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, installMockAuth, installMockStdb, mockReducerCalls } from './helpers';

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

test.describe('Context Tree — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    // The page reads context_tree_result (json blob) then falls back to
    // context_tree. Seed the fallback table so the entry list renders.
    await page.route(/\/v1\/database\/.*\/sql/, async (route: any) => {
      const body = route.request().postData() ?? '';
      if (body.includes('context_tree_result')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([{ schema: { elements: [] }, rows: [] }]),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              schema: {
                elements: [
                  { name: { some: 'id' } }, { name: { some: 'workspace_id' } },
                  { name: { some: 'path' } }, { name: { some: 'content' } },
                  { name: { some: 'priority' } }, { name: { some: 'is_global' } },
                  { name: { some: 'created_at' } }, { name: { some: 'updated_at' } },
                ],
              },
              rows: [
                ['ctx-1', '', '/api/v2', 'Context entry content', 1, false, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z'],
              ],
            },
          ]),
        });
      }
    });
    await installMockAuth(page);
    await installMockStdb(page);
    await mockReducerCalls(page);
    await gotoPage(page, '/context-tree');
  });

  test('lists seeded context entries', async ({ page }) => {
    await expect(page.getByText('/api/v2', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Context entry content', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('delete action on a seeded entry shows success', async ({ page }) => {
    await expect(page.getByText('/api/v2', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    // Trash button per entry (accessible-named)
    const deleteBtn = page.getByRole('button', { name: 'Delete entry' }).first();
    await expect(deleteBtn).toBeVisible({ timeout: 8000 });
    await deleteBtn.click();
    await expect(page.getByText('Context entry deleted', { exact: true })).toBeVisible({ timeout: 8000 });
  });
});