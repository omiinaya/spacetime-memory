import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Smart Query Builder page.
 *
 * Structural tests run against the empty mock. The seeded describe injects
 * memory rows so typing a query and clicking Run Query surfaces results.
 */

test.describe('Smart Query Builder Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/query');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Smart Query Builder', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('ByteRover knowledge curation pipeline', { exact: false }).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Query Builder', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Smart Query Builder — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    const now = Date.now() * 1000;
    await seedMockData(page, {
      memory: [
        {
          id: 'sq-1', workspace_id: 'w1', peer_id: 'p1', observer_id: 'p1',
          memory_type: 'experience', content: 'the user prefers vector search',
          summary: 'Vector preference', entities_json: '[]', confidence: 0.9,
          is_active: true, tier: 'L1', created_at: now, updated_at: now,
          access_count: 1, importance: 0.5,
        },
        {
          id: 'sq-2', workspace_id: 'w1', peer_id: 'p1', observer_id: 'p1',
          memory_type: 'insight', content: 'spatial reasoning works well here',
          summary: 'Spatial insight', entities_json: '[]', confidence: 0.7,
          is_active: true, tier: 'L2', created_at: now, updated_at: now,
          access_count: 1, importance: 0.5,
        },
      ],
    });
    await gotoPage(page, '/query');
  });

  test('run query returns seeded memory results', async ({ page }) => {
    await page.getByPlaceholder('Search memories, concepts, entities...').fill('vector');
    await page.getByRole('button', { name: /run query/i }).click();
    await expect(page.getByText('Vector preference', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('run query shows a result count header', async ({ page }) => {
    await page.getByPlaceholder('Search memories, concepts, entities...').fill('prefers');
    await page.getByRole('button', { name: /run query/i }).click();
    await expect(page.getByText(/1 result/, { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });
});
