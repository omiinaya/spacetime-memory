import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Note Graph page — verifies the page renders its heading and
 * deterministic structural/empty-state content. Data-dependent features are
 * not asserted (the dashboard connects to STDB over WS, so pages may show
 * either fully-loaded data, the empty state, or the loading indicator).
 */


test.describe('Note Graph Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/graph/notes');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Note Graph', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('No notes match', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Note Graph — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      note: [
        { id: 'n1', title: 'Seeded Graph Note', content: 'graph content', note_date: '2026-08-02', embedding_json: '[]', backlink_count: 0, block_ref_count: 0, created_at: 1785600000000, updated_at: 1785600000000, is_active: true },
      ],
      note_backlink: [],
    });
    await gotoPage(page, '/graph/notes');
  });

  test('renders note graph node for seeded note', async ({ page }) => {
    // vis-network renders to canvas (no DOM text), but the stats line shows
    // the computed node/edge counts from the seeded data.
    await expect(page.getByText(/1 notes, 0 connections/)).toBeVisible({ timeout: 5000 });
  });

  test('search input narrows the graph stats', async ({ page }) => {
    // Stats line visible from seed
    await expect(page.getByText(/1 notes, 0 connections/)).toBeVisible({ timeout: 5000 });
    // Search input is always in the header
    await expect(page.getByPlaceholder('Search notes...')).toBeVisible({ timeout: 5000 });
    // Search with no match → empty state appears
    await page.getByPlaceholder('Search notes...').fill('zzz-nomatch');
    await expect(page.getByText('No notes match', { exact: true })).toBeVisible({ timeout: 5000 });
    // Clearing restores the count
    await page.getByPlaceholder('Search notes...').fill('');
    await expect(page.getByText(/1 notes, 0 connections/)).toBeVisible({ timeout: 5000 });
  });
});
