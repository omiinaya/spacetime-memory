import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, mockSqlCalls } from './helpers';

/**
 * E2E tests for the MemFS page.
 *
 * Structural tests run with the default empty SQL mock. The seeded describe
 * mocks memfs_result to return a JSON tree blob so the file browser renders
 * a directory entry.
 */

const memfsSqlRows = [
  {
    schema: { elements: [{ name: { some: 'id' } }, { name: { some: 'data' } }] },
    rows: [
      ['memfs-root', JSON.stringify({
        id: 'root-1', workspace_id: '', parent_id: '', name: 'notes',
        path: '/notes', entry_type: 'directory', mime_type: 'inode/directory',
        data: '', size: 0, is_mounted: true,
      })],
    ],
  },
];

test.describe('MemFS Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/memfs');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'MemFS', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Virtual file system for memory workspace data', { exact: false }).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('File Browser', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('MemFS — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page, memfsSqlRows);
    await gotoPage(page, '/memfs');
  });

  test('shows seeded directory in the file browser', async ({ page }) => {
    await expect(page.getByText('notes', { exact: true }).first()).toBeVisible({ timeout: 8000 });
  });
});
