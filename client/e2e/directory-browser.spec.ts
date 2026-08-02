import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Directory Browser page.
 *
 * Structural tests (heading/empty state) run against the empty mock. The
 * seeded describe injects a context directory + memory + link so the tree
 * renders an entry and selecting it shows the linked memory.
 */

test.describe('Directory Tree Browser Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/directory-browser');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Directory Tree Browser', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Select a directory', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Directory Tree Browser — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      contextDirectory: [
        {
          id: 'dir-1',
          workspaceId: 'w1',
          name: 'Research',
          path: '/research',
          parentId: '',
          description: 'Research notes',
          createdAt: Date.now() * 1000,
          updatedAt: Date.now() * 1000,
        },
      ],
      memory: [
        {
          id: 'mem-1',
          workspaceId: 'w1',
          content: 'Directory linked memory content',
          summary: 'Linked memory',
          memoryType: 'experience',
          tier: 'L1',
          confidence: 0.9,
          accessCount: 3,
          isActive: true,
          peerId: 'p1',
          createdAt: Date.now() * 1000,
        },
      ],
      directoryMemoryLink: [
        { id: 'link-1', directoryId: 'dir-1', memoryId: 'mem-1', workspaceId: 'w1' },
      ],
    });
    await gotoPage(page, '/directory-browser');
  });

  test('shows seeded directory in the tree', async ({ page }) => {
    await expect(page.getByText('Research', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('selecting a directory shows its path detail', async ({ page }) => {
    await page.getByText('Research', { exact: false }).first().click();
    await expect(page.getByText('/research', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('selecting a directory shows linked memory', async ({ page }) => {
    await page.getByText('Research', { exact: false }).first().click();
    await expect(page.getByText('Linked memory', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });
});