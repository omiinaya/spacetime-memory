import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Documents page — verifies the page renders its heading and
 * deterministic structural/empty-state content. Data-dependent features are
 * not asserted (the dashboard connects to STDB over WS, so pages may show
 * either fully-loaded data, the empty state, or the loading indicator).
 */


test.describe('Documents Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/documents');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Documents', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('All Documents', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Documents — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      document: [
        { id: 'd1', workspaceId: 'ws1', title: 'Architecture Notes', content: 'System design', contentType: 'markdown', filePath: '/docs/arch.md', sourceUrl: '', metadataJson: '{}', chunkCount: 3, createdAt: 1785600000000, updatedAt: 1785600000000 },
        { id: 'd2', workspaceId: 'ws1', title: 'Benchmark Report', content: 'Results', contentType: 'text', filePath: '/reports/bench.md', sourceUrl: '', metadataJson: '{}', chunkCount: 1, createdAt: 1785600000000, updatedAt: 1785600000000 },
      ],
    });
    await gotoPage(page, '/documents');
  });

  test('lists seeded document titles', async ({ page }) => {
    await expect(page.getByText('Architecture Notes')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Benchmark Report')).toBeVisible({ timeout: 5000 });
  });

  test('renders document type badges', async ({ page }) => {
    await expect(page.getByText('markdown', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('text', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });
});
