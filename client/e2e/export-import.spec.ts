import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, mockSqlCalls } from './helpers';

/**
 * E2E tests for the Export / Import page.
 *
 * The page loads memories via executeSql. Structural tests run with the
 * default empty SQL mock (empty state). The export flow tests mock SQL rows
 * so the export actually renders JSON; the import flow tests drive the JSON
 * paste → import button and assert the success banner (reducer mocked ok).
 */

const memorySqlRows = [
  {
    schema: {
      elements: [
        { name: { some: 'id' } },
        { name: { some: 'content' } },
        { name: { some: 'summary' } },
        { name: { some: 'memory_type' } },
        { name: { some: 'created_at' } },
      ],
    },
    rows: [
      ['m1', 'first memory content', 'First Memory', 'experience', 1712000000000],
      ['m2', 'second memory content', 'Second Memory', 'insight', 1712000000000],
    ],
  },
];

test.describe('Export / Import Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/export-import');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Export / Import', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [
      page.getByText(/export|import|no memory/i),
    ]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('export shows error when no memories found', async ({ page }) => {
    await page.getByRole('button', { name: /export/i }).first().click();
    await expect(page.getByText('No memories found to export')).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Export / Import — With Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page, memorySqlRows);
    await gotoPage(page, '/export-import');
  });

  test('export renders JSON preview with seeded memories', async ({ page }) => {
    await page.getByRole('button', { name: /export/i }).first().click();
    await expect(page.getByText('Exported 2 memories', { exact: false })).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('first memory content', { exact: false }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('second memory content', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('import shows error when pasted data is empty', async ({ page }) => {
    await page.getByRole('tab', { name: /import/i }).click();
    await page.getByRole('button', { name: /import/i }).first().click();
    await expect(page.getByText('Paste export data first')).toBeVisible({ timeout: 8000 });
  });

  test('import shows error for invalid JSON', async ({ page }) => {
    await page.getByRole('tab', { name: /import/i }).click();
    await page.getByPlaceholder(/content/).fill('not json');
    await page.getByRole('button', { name: /import/i }).first().click();
    await expect(page.getByText('Invalid JSON format')).toBeVisible({ timeout: 8000 });
  });

  test('import succeeds with valid memory array', async ({ page }) => {
    await page.getByRole('tab', { name: /import/i }).click();
    const payload = JSON.stringify([
      { content: 'imported memory one', workspace_id: 'w1' },
      { content: 'imported memory two', workspace_id: 'w1' },
    ]);
    await page.getByPlaceholder(/content/).fill(payload);
    await page.getByRole('button', { name: /import/i }).first().click();
    await expect(page.getByText('Imported 2 memories (0 skipped)', { exact: false })).toBeVisible({ timeout: 8000 });
  });
});