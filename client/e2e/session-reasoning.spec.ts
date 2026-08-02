import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Session Reasoning page.
 *
 * Structural tests (heading/empty state) run against the empty mock. The
 * seeded describe injects session + message rows so the session list and
 * stat cards render.
 */

test.describe('Session Reasoning Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/session-reasoning');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Session Reasoning', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    // Mock STDB renders the empty state ("No sessions yet") instantly; with a
    // live DB the loading text may appear briefly. Accept either.
    await expectAnyVisible(page, [page.getByText('No sessions yet', { exact: false }).first(),
                                  page.getByText('Loading sessions...', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Session Reasoning — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    const now = Date.now() * 1000;
    await seedMockData(page, {
      session: [
        { id: 's1', name: 'Planning Session', createdAt: now, updatedAt: now },
        { id: 's2', name: 'Debugging Session', createdAt: now, updatedAt: now },
      ],
      peer: [{ id: 'p1', name: 'peer-one' }],
    });
    await gotoPage(page, '/session-reasoning');
  });

  test('shows total sessions stat card', async ({ page }) => {
    await expect(page.getByText('Total Sessions', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('2', { exact: true }).first()).toBeVisible({ timeout: 3000 });
  });

  test('lists seeded sessions in the panel', async ({ page }) => {
    await expect(page.getByText('Planning Session', { exact: false }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Debugging Session', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('search narrows the session list', async ({ page }) => {
    const search = page.getByPlaceholder('Search sessions...');
    await expect(search).toBeVisible({ timeout: 8000 });
    await search.fill('planning');
    await expect(page.getByText('Planning Session', { exact: false })).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Debugging Session', { exact: false }).first()).toHaveCount(0);
    await search.fill('zzz-nope');
    await expect(page.getByText('No sessions match your search.', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('filters panel toggles open with date and participant controls', async ({ page }) => {
    await page.getByRole('button', { name: /filters/i }).first().click();
    // Date inputs + participant select + clear-filters appear
    const dateInputs = page.locator('input[type="date"]');
    await expect(dateInputs.first()).toBeVisible({ timeout: 8000 });
    await expect(dateInputs.nth(1)).toBeVisible({ timeout: 8000 });
    await expect(page.getByRole('combobox').first()).toBeVisible({ timeout: 8000 });
    // Selecting a participant from the seeded peer list (assert the select's
    // selected value equals p1 — the option text is inside a hidden <option>)
    await page.getByRole('combobox').first().selectOption('p1');
    await expect(page.getByRole('combobox').first()).toHaveValue('p1');
    // Clear filters resets the select
    await page.getByRole('button', { name: /clear filters/i }).click();
    await expect(page.getByRole('combobox').first()).toHaveValue('');
  });
});
