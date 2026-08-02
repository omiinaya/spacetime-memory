import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Block Graph page — verifies the page renders its heading and
 * deterministic structural/empty-state content. Data-dependent features are
 * not asserted (the dashboard connects to STDB over WS, so pages may show
 * either fully-loaded data, the empty state, or the loading indicator).
 */


test.describe('Block Graph Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/block-graph');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Block Graph', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    // Mock STDB renders the empty state ("No block refs yet") instantly; with
    // a live DB the loading text may appear briefly. Accept either.
    await expectAnyVisible(page, [page.getByText('No block refs yet', { exact: false }).first(),
                                  page.getByText('Loading block data', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Block Graph — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      note: [
        { id: 'n1', title: 'Seeded Block Note', content: 'block content', note_date: '2026-08-02', embedding_json: '[]', backlink_count: 0, block_ref_count: 0, created_at: 1785600000000, updated_at: 1785600000000, is_active: true },
      ],
      note_block: [
        { id: 'b1', note_id: 'n1', block_type: 'list', content: 'a block', source: 'n1', block_order: 0, heading_level: 0, task_state: 'none', properties_json: '{}', is_active: true, created_at: 1785600000000 },
        { id: 'b2', note_id: 'n1', block_type: 'heading', content: 'second block', source: 'n1', block_order: 1, heading_level: 1, task_state: 'none', properties_json: '{}', is_active: true, created_at: 1785600000000 },
      ],
      block_reference: [
        { id: 'br1', source_block_id: 'b1', target_block_id: 'b2', target_note_id: 'n1', ref_type: 'connection', created_at: 1785600000000 },
      ],
    });
    await gotoPage(page, '/block-graph');
  });

  test('renders block graph with seeded note', async ({ page }) => {
    // Block graph renders DOM block cards; the seeded note's block content
    // should appear as a card (truncated at 80 chars).
    await expect(page.getByText('a block').first()).toBeVisible({ timeout: 5000 });
  });
});
