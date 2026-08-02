import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Tours page — verifies the page renders its heading and
 * deterministic structural/empty-state content. Data-dependent features are
 * not asserted (the dashboard connects to STDB over WS, so pages may show
 * either fully-loaded data, the empty state, or the loading indicator).
 */


test.describe('Guided Tours Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/tours');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Guided Tours', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Curated walks through knowledge graph nodes', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Tours — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      tour: [
        { id: 't1', title: 'Getting Started Tour', description: 'Learn the basics', created_at: 1785600000000, updated_at: 1785600000000, is_active: true },
        { id: 't2', title: 'Advanced Workflows', description: 'Deep dive', created_at: 1785600000000, updated_at: 1785600000000, is_active: true },
      ],
      tour_stop: [
        { id: 'ts1', tour_id: 't1', note_id: 'n1', stop_order: 0, title: 'Welcome', content: 'First stop', created_at: 1785600000000 },
      ],
      note: [],
    });
    await gotoPage(page, '/tours');
  });

  test('lists seeded tour titles', async ({ page }) => {
    await expect(page.getByText('Getting Started Tour').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Advanced Workflows').first()).toBeVisible({ timeout: 5000 });
  });
});
