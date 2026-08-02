import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Knowledge Graph page.
 *
 * Structural tests run against the empty mock (empty state). The seeded
 * describe injects kg_node + kg_edge rows so the graph populates and the
 * deterministic "N nodes · M edges" header count line renders (the vis
 * canvas itself can't be text-asserted, same as note-graph).
 */

test.describe('Knowledge Graph Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/graph');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Knowledge Graph', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Visualize and explore the semantic memory network.', { exact: false }).first()]);
  });

  test('renders empty state', async ({ page }) => {
    await expect(page.getByText('No graph data yet', { exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Knowledge Graph — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    const now = Date.now() * 1000;
    await seedMockData(page, {
      kg_node: [
        {
          id: 'n1', workspaceId: 'w1', label: 'GraphQL', nodeType: 'concept',
          summary: 'A query language', communityId: 1, createdAt: now,
        },
        {
          id: 'n2', workspaceId: 'w1', label: 'Rust', nodeType: 'concept',
          summary: 'A systems language', communityId: 1, createdAt: now,
        },
      ],
      kg_edge: [
        { id: 'e1', sourceId: 'n1', targetId: 'n2', relation: 'related_to', createdAt: now },
      ],
    });
    await gotoPage(page, '/graph');
  });

  test('shows node and edge counts in the header', async ({ page }) => {
    // Header renders "2 nodes · 1 edge"
    await expect(page.getByText(/2 nodes\s*·\s*1 edge/)).toBeVisible({ timeout: 8000 });
  });

  test('graph tab is reachable with data', async ({ page }) => {
    await expect(page.getByRole('tab', { name: /graph/i })).toBeVisible({ timeout: 8000 });
    await expect(page.getByRole('tab', { name: /hierarchy/i })).toBeVisible({ timeout: 8000 });
  });
});
