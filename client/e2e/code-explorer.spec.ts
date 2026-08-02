import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Code Explorer page — verifies the page renders its heading and
 * deterministic structural/empty-state content. Data-dependent features are
 * not asserted (the dashboard connects to STDB over WS, so pages may show
 * either fully-loaded data, the empty state, or the loading indicator).
 */


test.describe('Code Explorer Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/code-explorer');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Code Explorer', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Interactive code knowledge graph exploration.', { exact: false }).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Code Nodes', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Code Explorer — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      kg_node: [
        { id: 'kn1', workspace_id: 'ws1', label: 'SeededFunction', node_type: 'code', summary: 'a function', embedding_json: '[]', created_at: 1785600000000, updated_at: 1785600000000, is_active: true },
        { id: 'kn2', workspace_id: 'ws1', label: 'SeededStruct', node_type: 'code', summary: 'a struct', embedding_json: '[]', created_at: 1785600000000, updated_at: 1785600000000, is_active: true },
      ],
      kg_edge: [],
    });
    await gotoPage(page, '/code-explorer');
  });

  test('lists seeded code nodes', async ({ page }) => {
    await expect(page.getByText('SeededFunction').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('SeededStruct').first()).toBeVisible({ timeout: 5000 });
  });
});
