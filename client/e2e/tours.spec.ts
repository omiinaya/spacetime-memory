import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Tours page — structural rendering plus full playback
 * corner coverage: opening a tour, advancing/rewinding stops, the stop count
 * badge, the Done state on the final stop, the back-to-list arrow, and the
 * empty-stop state for a tour with no stops.
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
        { id: 't1', workspace_id: 'ws1', title: 'Getting Started Tour', description: 'Learn the basics', created_at: 1785600000000000 },
        { id: 't2', workspace_id: 'ws1', title: 'Advanced Workflows', description: 'Deep dive', created_at: 1785600000000000 },
      ],
      tour_stop: [
        { id: 'ts1', tour_id: 't1', node_id: 'n1', stop_order: 0, heading: 'Welcome Stop', description: 'First stop description', created_at: 1785600000000000 },
        { id: 'ts2', tour_id: 't1', node_id: 'n2', stop_order: 1, heading: 'Conclusion Stop', description: 'Second stop description', created_at: 1785600000000000 },
        // t2 has no stops
      ],
      note: [
        { id: 'n1', title: 'Intro Note', content: 'Intro note body', created_at: 1785600000000000, updated_at: 1785600000000000, is_active: true },
        { id: 'n2', title: 'Advanced Note', content: 'Advanced note body', created_at: 1785600000000000, updated_at: 1785600000000000, is_active: true },
      ],
    });
    await gotoPage(page, '/tours');
  });

  test('lists seeded tour titles with stop counts', async ({ page }) => {
    await expect(page.getByText('Getting Started Tour').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Advanced Workflows').first()).toBeVisible({ timeout: 5000 });
    // Stop count badges
    await expect(page.getByText('2 stops', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('0 stops', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });

  test('opening a tour shows the first stop with play controls', async ({ page }) => {
    await page.getByText('Getting Started Tour').first().click();
    // Player view: heading switches to the tour title
    await expect(page.getByRole('heading', { name: 'Getting Started Tour', exact: true })).toBeVisible({ timeout: 5000 });
    // Stop count badge shows 1 / 2
    await expect(page.getByText('1 / 2', { exact: true })).toBeVisible({ timeout: 5000 });
    // First stop heading
    await expect(page.getByText('Welcome Stop', { exact: true })).toBeVisible({ timeout: 5000 });
    // Nav buttons present; Previous disabled on first stop
    await expect(page.getByRole('button', { name: /next/i })).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole('button', { name: /previous/i })).toBeDisabled();
  });

  test('advancing to the final stop shows Done and rewind works', async ({ page }) => {
    await page.getByText('Getting Started Tour').first().click();
    await expect(page.getByText('1 / 2', { exact: true })).toBeVisible({ timeout: 5000 });
    // Advance to stop 2
    await page.getByRole('button', { name: /next/i }).click();
    await expect(page.getByText('2 / 2', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Conclusion Stop', { exact: true })).toBeVisible({ timeout: 5000 });
    // On the last stop the button becomes "Done"
    await expect(page.getByRole('button', { name: /done/i })).toBeVisible({ timeout: 5000 });
    // Rewind back to stop 1
    await page.getByRole('button', { name: /previous/i }).click();
    await expect(page.getByText('1 / 2', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Welcome Stop', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('back arrow returns to the tour list', async ({ page }) => {
    await page.getByText('Getting Started Tour').first().click();
    await expect(page.getByRole('heading', { name: 'Getting Started Tour', exact: true })).toBeVisible({ timeout: 5000 });
    await page.locator('main button').first().click();
    await expect(page.getByRole('heading', { name: 'Guided Tours', exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('a tour with no stops shows the empty-stop message', async ({ page }) => {
    await page.getByText('Advanced Workflows').first().click();
    await expect(page.getByText('No stops in this tour yet.', { exact: true })).toBeVisible({ timeout: 5000 });
  });
});