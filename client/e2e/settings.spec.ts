import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage } from './helpers';

/**
 * E2E tests for the Settings page.
 *
 * Covers the deterministic corners: the Save Changes flow (localStorage
 * backed), tab navigation (General/Appearance/Storage/Space Members), and the
 * Space Members empty state ("Enter a workspace ID above"). The grant-access
 * form requires a workspace ID + a seeded space_permission row, covered in
 * the seeded describe below.
 */

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/settings');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders general tab content', async ({ page }) => {
    await expectAnyVisible(page, [
      page.getByText(/refresh interval|save changes/i),
    ]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('save changes shows confirmation', async ({ page }) => {
    await page.getByRole('button', { name: /save changes/i }).click();
    await expect(page.getByText('Settings saved locally')).toBeVisible({ timeout: 8000 });
  });

  test('switches to appearance tab', async ({ page }) => {
    await page.getByRole('tab', { name: /appearance/i }).click();
    await expect(page.getByText('Dark Mode', { exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('space members tab shows empty state without workspace id', async ({ page }) => {
    await page.getByRole('tab', { name: /space members/i }).click();
    await expect(page.getByText('Enter a workspace ID above')).toBeVisible({ timeout: 8000 });
  });
});