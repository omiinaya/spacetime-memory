import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Memory Meta page — verifies the page renders its heading and
 * deterministic structural/empty-state content. Data-dependent features are
 * not asserted (the dashboard connects to STDB over WS, so pages may show
 * either fully-loaded data, the empty state, or the loading indicator).
 */


test.describe('Memory Meta Editor Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/memory-meta');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Memory Meta Editor', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Memory Metadata', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Memory Meta — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      memory: [
        { id: 'mem-1', workspace_id: 'ws1', content: 'meta test memory', summary: 's', memory_type: 'fact', tier: 'core', confidence: 0.9, is_active: true, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z' },
      ],
      memory_meta: [
        { id: 'meta-1', memory_id: 'mem-1', category: 'important', importance: 0.9, last_accessed_at: null, access_count: 0, immutable: false },
      ],
    });
    await gotoPage(page, '/memory-meta');
  });

  test('shows seeded meta category', async ({ page }) => {
    await expect(page.getByText('important', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });
});
