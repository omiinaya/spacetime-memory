import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Block Graph page — structural rendering plus full
 * interactive corner coverage: node cards render from seeded blocks, type
 * filter chips toggle visibility, search narrows blocks, isolates toggle,
 * wiki-link/embed toggles, block selection opens the side panel with
 * content + outgoing/incoming refs, ref-count badges drive the filter-mode
 * badge, and the back arrow navigates to /notes.
 */

const SEED = {
  note: [
    { id: 'n1', title: 'Seeded Block Note', content: 'block content', note_date: '2026-08-02', embedding_json: '[]', backlink_count: 0, block_ref_count: 0, created_at: 1785600000000000, updated_at: 1785600000000000, is_active: true },
  ],
  note_block: [
    { id: 'b1', note_id: 'n1', block_type: 'list', content: 'alpha list block', source: 'n1', block_order: 0, heading_level: 0, task_state: 'none', properties_json: '{}', is_active: true, created_at: 1785600000000000 },
    { id: 'b2', note_id: 'n1', block_type: 'heading', content: 'beta heading block', source: 'n1', block_order: 1, heading_level: 1, task_state: 'none', properties_json: '{}', is_active: true, created_at: 1785600000000000 },
    { id: 'b3', note_id: 'n1', block_type: 'todo', content: 'gamma todo block', source: 'n1', block_order: 2, heading_level: 0, task_state: 'open', properties_json: '{}', is_active: true, created_at: 1785600000000000 },
    { id: 'b4', note_id: 'n1', block_type: 'quote', content: 'delta isolated quote', source: 'n1', block_order: 3, heading_level: 0, task_state: 'none', properties_json: '{}', is_active: true, created_at: 1785600000000000 },
  ],
  block_reference: [
    { id: 'br1', source_block_id: 'b1', target_block_id: 'b2', target_note_id: 'n1', ref_type: 'connection', created_at: 1785600000000000 },
    { id: 'br2', source_block_id: 'b1', target_block_id: 'b2', target_note_id: 'n1', ref_type: 'wiki_link', created_at: 1785600000000000 },
    { id: 'br3', source_block_id: 'b3', target_block_id: 'b2', target_note_id: 'n1', ref_type: 'connection', created_at: 1785600000000000 },
  ],
};

test.describe('Block Graph Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/block-graph');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Block Graph', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
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
    await seedMockData(page, SEED);
    await gotoPage(page, '/block-graph');
  });

  test('renders block cards with stats', async ({ page }) => {
    await expect(page.getByText('alpha list block').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('beta heading block').first()).toBeVisible({ timeout: 5000 });
    // Header stats: 3 visible blocks (b4 is an isolate, hidden by default),
    // 2 unique edges (br1+br2 share endpoints → deduped to 1, plus br3), 1 note
    await expect(page.getByText('3 blocks, 2 references, 1 notes', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('type filter chips toggle block visibility', async ({ page }) => {
    // Type chips present
    const headingChip = page.getByRole('button', { name: 'heading', exact: true });
    const todoChip = page.getByRole('button', { name: 'todo', exact: true });
    const quoteChip = page.getByRole('button', { name: 'quote', exact: true });
    await expect(headingChip).toBeVisible({ timeout: 5000 });
    await expect(todoChip).toBeVisible({ timeout: 5000 });
    await expect(quoteChip).toBeVisible({ timeout: 5000 });
    // Clicking "heading" hides the heading block; edges to it disappear too
    await headingChip.click();
    await expect(page.getByText('beta heading block').first()).toHaveCount(0);
    await expect(page.getByText('alpha list block').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('2 blocks, 0 references, 1 notes', { exact: true })).toBeVisible({ timeout: 5000 });
    // Clicking "todo" hides the connected todo block
    await todoChip.click();
    await expect(page.getByText('gamma todo block').first()).toHaveCount(0);
    await expect(page.getByText('1 blocks, 0 references, 1 notes', { exact: true })).toBeVisible({ timeout: 5000 });
    // Re-enable quote (isolate) with the isolate toggle still off → nothing new
    await quoteChip.click();
    await expect(page.getByText('delta isolated quote').first()).toHaveCount(0);
  });

  test('search narrows blocks', async ({ page }) => {
    const search = page.getByPlaceholder('Search blocks…');
    await expect(search).toBeVisible({ timeout: 5000 });
    await search.fill('beta');
    await expect(page.getByText('beta heading block').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('alpha list block').first()).toHaveCount(0);
    // No matches → empty-search state
    await search.fill('zzz-no-match');
    await expect(page.getByText('Try a different search term or check your filters.', { exact: false })).toBeVisible({ timeout: 5000 });
  });

  test('isolates toggle shows disconnected blocks', async ({ page }) => {
    // Default: isolates hidden → b4 (no refs) not shown → 3 blocks
    await expect(page.getByText('delta isolated quote').first()).toHaveCount(0);
    await expect(page.getByText('3 blocks, 2 references, 1 notes', { exact: true })).toBeVisible({ timeout: 5000 });
    // Enable isolates → b4 appears (edge count unchanged)
    await page.getByText('Isolates', { exact: true }).click();
    await expect(page.getByText('delta isolated quote').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('4 blocks, 2 references, 1 notes', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('wiki-link toggle filters the outgoing ref badge', async ({ page }) => {
    // Default: b1 has 2 outgoing refs (connection + wiki_link) → badge →2
    await expect(page.getByRole('button', { name: '→2', exact: true })).toBeVisible({ timeout: 5000 });
    // Disable wiki-link refs → only the connection ref remains → badge →1
    // (b1 via br1 and b3 via br3 both show →1, so scope to first)
    await page.getByText('((wiki-link))', { exact: true }).click();
    await expect(page.getByRole('button', { name: '→1', exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole('button', { name: '→2', exact: true })).toHaveCount(0);
  });

  test('selecting a block opens the side panel with refs', async ({ page }) => {
    // Click the alpha block card → panel shows content + outgoing refs.
    // The card lives in an absolutely-positioned canvas; dispatchEvent fires
    // React's onClick handler directly, bypassing hit-testing against the
    // layout container (which Playwright's coordinate click can't reach).
    const alphaCard = page.getByText('alpha list block').first();
    await expect(alphaCard).toBeVisible({ timeout: 5000 });
    await alphaCard.dispatchEvent('click');
    await expect(page.getByText('Outgoing Refs', { exact: false })).toBeVisible({ timeout: 5000 });
    // Outgoing target (beta heading block) listed
    await expect(page.getByText('beta heading block').first()).toBeVisible({ timeout: 5000 });
    // Parent note link present
    await expect(page.getByText('Seeded Block Note', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    // Close the panel via its accessible-named close button
    await page.getByRole('button', { name: 'Close panel' }).click();
    await expect(page.getByText('Outgoing Refs', { exact: false })).toHaveCount(0);
  });

  test('ref-count badges drive the filter mode badge', async ({ page }) => {
    // b1 has 2 outgoing refs → its "→2" badge exists
    const outgoingBadge = page.getByRole('button', { name: '→2', exact: true });
    await expect(outgoingBadge).toBeVisible({ timeout: 5000 });
    // dispatchEvent to reach the handler on the canvas-positioned badge
    await outgoingBadge.dispatchEvent('click');
    // Filter mode badge appears
    await expect(page.getByText('→ Outgoing', { exact: true })).toBeVisible({ timeout: 5000 });
    // Clear via the accessible-named clear button. The click also opened the
    // side panel (selectedBlockId set), which overlaps the filter bar in the
    // test viewport, so dispatch the click to reach the handler.
    const clearFilter = page.getByRole('button', { name: 'Clear filter' });
    await expect(clearFilter).toBeVisible({ timeout: 5000 });
    await clearFilter.dispatchEvent('click');
    await expect(page.getByText('→ Outgoing', { exact: true })).toHaveCount(0);
  });

  test('back arrow navigates to notes list', async ({ page }) => {
    // First icon button inside main is the back arrow (ArrowLeft)
    const backBtn = page.locator('main button').first();
    await backBtn.click();
    await expect(page).toHaveURL(/\/notes$/);
  });
});
