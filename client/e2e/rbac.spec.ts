import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Rbac page — verifies the page renders its heading and
 * deterministic structural/empty-state content. The seeded describe injects a
 * space_permission row so typing a workspace ID reveals the member table.
 */

test.describe('Role-Based Access Control Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/rbac');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Role-Based Access Control', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Manage workspace members, roles, and permissions', { exact: false }).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Workspace Members', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Role-Based Access Control — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      space_permission: [
        {
          id: 'sp-1',
          workspaceId: 'w1',
          peerId: '0xpeer1',
          permission: 'owner',
          grantedBy: '0xadmin',
          createdAt: Date.now() * 1000,
        },
      ],
      peer: [{ id: '0xpeer1', name: 'peer-one' }],
    });
    await gotoPage(page, '/rbac');
  });

  test('typing workspace id shows seeded member row', async ({ page }) => {
    await page.getByPlaceholder(/enter a workspace id/i).first().fill('w1');
    await expect(page.getByText('0xpeer1', { exact: false }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Owner', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });
});
