import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Peers page — verifies the page renders its heading and
 * deterministic structural/empty-state content. Data-dependent features are
 * not asserted (the dashboard connects to STDB over WS, so pages may show
 * either fully-loaded data, the empty state, or the loading indicator).
 */


test.describe('Peers Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/peers');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Peers', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('All Peers', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Peers — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      peer: [
        { id: 'p1', workspaceId: 'ws1', name: 'Alice Agent', peerType: 'agent', metadata: '{}', createdAt: 1785600000000, updatedAt: 1785600000000 },
        { id: 'p2', workspaceId: 'ws1', name: 'Bob User', peerType: 'user', metadata: '{}', createdAt: 1785600000000, updatedAt: 1785600000000 },
      ],
    });
    await gotoPage(page, '/peers');
  });

  test('lists seeded peers by name', async ({ page }) => {
    await expect(page.getByText('Alice Agent')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Bob User')).toBeVisible({ timeout: 5000 });
  });

  test('shows peer type badges', async ({ page }) => {
    await expect(page.getByText('agent', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('user', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });
});
