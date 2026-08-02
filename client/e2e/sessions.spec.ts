import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Sessions page — verifies the page renders its heading and
 * deterministic structural/empty-state content. Data-dependent features are
 * not asserted (the dashboard connects to STDB over WS, so pages may show
 * either fully-loaded data, the empty state, or the loading indicator).
 */


test.describe('Sessions Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/sessions');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Sessions', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Session Log', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Sessions — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      session: [
        { id: 's1', workspaceId: 'ws1', name: 'Morning Planning', summary: 'Planned the day', metadata: '{}', createdAt: 1785600000000, updatedAt: 1785600000000 },
        { id: 's2', workspaceId: 'ws1', name: 'Code Review', summary: 'Reviewed PRs', metadata: '{}', createdAt: 1785600000000, updatedAt: 1785600000000 },
      ],
    });
    await gotoPage(page, '/sessions');
  });

  test('lists seeded session names', async ({ page }) => {
    await expect(page.getByText('Morning Planning')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Code Review')).toBeVisible({ timeout: 5000 });
  });

  test('shows session summaries', async ({ page }) => {
    await expect(page.getByText('Planned the day')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Reviewed PRs')).toBeVisible({ timeout: 5000 });
  });
});
