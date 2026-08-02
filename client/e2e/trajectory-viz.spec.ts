import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Trajectory Visualization page.
 *
 * Structural tests run against the empty mock (empty state). The seeded
 * describe injects memory rows so the deterministic stats bar renders
 * (Total / tier counts / Avg Confidence) — the vis canvas itself can't be
 * text-asserted.
 */

test.describe('Trajectory Visualization Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/trajectories');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Trajectory Visualization', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Retrieval trajectories and memory reinforcement paths.', { exact: false }).first()]);
  });

  test('renders empty state', async ({ page }) => {
    await expect(page.getByText('No memories available', { exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Trajectory Visualization — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    const now = Date.now() * 1000;
    await seedMockData(page, {
      memory: [
        {
          id: 't1', workspace_id: 'w1', peer_id: 'p1', observer_id: 'p1',
          memory_type: 'experience', content: 'first trajectory memory',
          summary: 'First', entities_json: '[]', confidence: 0.8,
          is_active: true, tier: 'L1', created_at: now, updated_at: now,
          access_count: 1, importance: 0.5,
        },
        {
          id: 't2', workspace_id: 'w1', peer_id: 'p1', observer_id: 'p1',
          memory_type: 'insight', content: 'second trajectory memory',
          summary: 'Second', entities_json: '[]', confidence: 0.6,
          is_active: true, tier: 'L2', created_at: now, updated_at: now,
          access_count: 1, importance: 0.5,
        },
      ],
    });
    await gotoPage(page, '/trajectories');
  });

  test('shows total memory stat', async ({ page }) => {
    await expect(page.getByText('Total', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('2', { exact: true }).first()).toBeVisible({ timeout: 3000 });
  });

  test('shows tier breakdown stat cards', async ({ page }) => {
    await expect(page.getByText('Working (L1)', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Ephemeral (L2)', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    // 2 memories → header "2 memories across 2 tier(s)"
    await expect(page.getByText(/2 memor.*across 2 tier/)).toBeVisible({ timeout: 8000 });
  });

  test('search input is present in filter bar', async ({ page }) => {
    await expect(page.getByPlaceholder('Search memories…')).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('Search memories…').fill('first');
    await expect(page.getByPlaceholder('Search memories…')).toHaveValue('first');
  });
});
