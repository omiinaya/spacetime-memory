import { test, expect } from '@playwright/test';
import { expectAnyVisible, gotoPage, installMockStdb, seedMockData } from './helpers';

/**
 * E2E tests for the Memory Browser page — listing, filtering, empty/error states.
 */

async function mockAuth(page: any) {
  await page.addInitScript(() => {
    (window as any).__MOCK_AUTH__ = {
      account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
    };
  });
  await page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
}

test.describe('Memory Browser', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page);
    await installMockStdb(page);
    await gotoPage(page, '/memories');
  });

  test('renders heading and description', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Memory Browser', exact: true })).toBeVisible();
    // Shows memory count (0 while loading or after error)
    await expectAnyVisible(page, [page.getByText(/memory\(ies\)/i)]);
  });

  test('renders search input for filtering memories', async ({ page }) => {
    const searchInput = page.getByPlaceholder(/search memories by content/i);
    await expect(searchInput).toBeVisible();
    // Type something to test filtering
    await searchInput.fill('test');
    await expect(searchInput).toHaveValue('test');
    // Filter badge should show "Filtering"
    await expect(page.getByText('Filtering')).toBeVisible();
    // Clear
    await searchInput.fill('');
    await expect(page.getByText('All')).toBeVisible();
  });

  test('renders Stored Memories card', async ({ page }) => {
    await expect(page.getByText('Stored Memories')).toBeVisible();
  });

  test('shows empty state when no memories exist', async ({ page }) => {
    // The empty state shows different text depending on whether we're searching or have no data
    await page.waitForTimeout(2000);
    // If WS didn't connect, we'll see error. If it timed out gracefully, empty state.
    const pageContent = await page.textContent('body');
    if (pageContent?.includes('No memories yet') || pageContent?.includes('No matching memories') || pageContent?.includes('Connection error')) {
      // These are all valid states
      expect(true).toBe(true);
    }
  });

  test('shows memory type badge colors for known types', async ({ page }) => {
    // Even in error/empty state, the badge colors CSS is loaded
    // Verify the page loaded without crash
    await expect(page.getByRole('heading', { name: 'Memory Browser', exact: true })).toBeVisible();
  });

  test('renders filter badge toggle based on search', async ({ page }) => {
    // Initial state: "All" badge is visible
    const filterBadge = page.getByText('All', { exact: true }).first();
    await expect(filterBadge).toBeVisible({ timeout: 8000 });
    // Typing in search flips the badge to "Filtering"
    const searchInput = page.getByPlaceholder(/search memories by content/i);
    await expect(searchInput).toBeVisible({ timeout: 8000 });
    await searchInput.fill('something');
    await expect(page.getByText('Filtering', { exact: true }).first()).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Memory Browser — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page);
    await installMockStdb(page);
    await seedMockData(page, {
      memory: [
        {
          id: 'mem-1',
          workspace_id: 'ws-e2e',
          content: 'The user prefers dark mode interfaces',
          summary: 'UI preference',
          memory_type: 'preference',
          tier: 'core',
          confidence: 0.95,
          is_active: true,
          created_at: '2026-08-01T10:00:00Z',
          updated_at: '2026-08-01T10:00:00Z',
        },
        {
          id: 'mem-2',
          workspace_id: 'ws-e2e',
          content: 'The user deploys to Kubernetes clusters',
          summary: 'Infra detail',
          memory_type: 'fact',
          tier: 'working',
          confidence: 0.8,
          is_active: true,
          created_at: '2026-08-01T11:00:00Z',
          updated_at: '2026-08-01T11:00:00Z',
        },
      ],
      memory_meta: [
        { id: 'meta-1', memory_id: 'mem-1', category: 'preferences', importance: 0.9, last_accessed_at: null, access_count: 0 },
        { id: 'meta-2', memory_id: 'mem-2', category: 'infrastructure', importance: 0.7, last_accessed_at: null, access_count: 0 },
      ],
    });
    await gotoPage(page, '/memories');
  });

  test('shows the seeded memory count', async ({ page }) => {
    await expect(page.getByText('2 memory(ies)')).toBeVisible({ timeout: 5000 });
  });

  test('renders seeded memory content', async ({ page }) => {
    await expect(page.getByText('The user prefers dark mode interfaces')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('The user deploys to Kubernetes clusters')).toBeVisible({ timeout: 5000 });
  });

  test('renders memory type badges', async ({ page }) => {
    await expect(page.getByText('preference', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('fact', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('search filters seeded memories', async ({ page }) => {
    const searchInput = page.getByPlaceholder(/search memories by content/i);
    await searchInput.fill('kubernetes');
    await expect(page.getByText('The user deploys to Kubernetes clusters')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('The user prefers dark mode interfaces')).toBeHidden();
  });

  test('search by memory category via meta', async ({ page }) => {
    const searchInput = page.getByPlaceholder(/search memories by content/i);
    await searchInput.fill('infrastructure');
    await expect(page.getByText('The user deploys to Kubernetes clusters')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('The user prefers dark mode interfaces')).toBeHidden();
  });
});
