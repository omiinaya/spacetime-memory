import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Memory Meta page — structural rendering plus interactive
 * corner coverage: seeded categories/immutable badges, search filtering,
 * inline edit (Save → reducer call, success message), cancel, and the batch
 * edit panel (selection checkboxes, Apply to All → reducer + success).
 */

const SEED = {
  memory: [
    { id: 'mem-1', workspace_id: 'ws1', content: 'alpha meta memory', summary: 'Alpha summary', memory_type: 'fact', tier: 'L0', is_active: true, created_at: 1785600000000000, updated_at: 1785600000000000 },
    { id: 'mem-2', workspace_id: 'ws1', content: 'beta meta memory', summary: 'Beta summary', memory_type: 'experience', tier: 'L1', is_active: true, created_at: 1785600000000000, updated_at: 1785600000000000 },
    { id: 'mem-3', workspace_id: 'ws1', content: 'gamma inactive memory', summary: 'Gamma summary', memory_type: 'mental_model', tier: 'L2', is_active: false, created_at: 1785600000000000, updated_at: 1785600000000000 },
  ],
  memory_meta: [
    { id: 'meta-1', workspace_id: 'ws1', memory_id: 'mem-1', category: 'important', immutable: true, extra_json: '{}', created_at: 1785600000000000, updated_at: 1785600000000000 },
    { id: 'meta-2', workspace_id: 'ws1', memory_id: 'mem-2', category: 'preferences', immutable: false, extra_json: '{}', created_at: 1785600000000000, updated_at: 1785600000000000 },
  ],
};

test.describe('Memory Meta Editor Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/memory-meta');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Memory Meta Editor', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Memory Metadata', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Memory Meta — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, SEED);
    await gotoPage(page, '/memory-meta');
  });

  test('shows seeded categories and immutable badge', async ({ page }) => {
    await expect(page.getByText('important', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('preferences', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    // mem-1 has immutable: true → Immutable badge visible
    await expect(page.getByText('Immutable', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    // mem-3 inactive badge
    await expect(page.getByText('inactive', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });

  test('search filters memories and categories', async ({ page }) => {
    const search = page.getByPlaceholder('Search memories and categories...');
    await expect(search).toBeVisible({ timeout: 5000 });
    // By content
    await search.fill('alpha');
    await expect(page.getByText('Alpha summary', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Beta summary', { exact: true })).toHaveCount(0);
    // By category
    await search.fill('preferences');
    await expect(page.getByText('Beta summary', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Alpha summary', { exact: true })).toHaveCount(0);
    // No match
    await search.fill('zzz-no-match');
    await expect(page.getByText('No matching memories', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('inline edit saves via reducer and shows success', async ({ page }) => {
    // Click the edit (shield) button on the mem-1 row
    const row = page.getByText('Alpha summary', { exact: true }).first().locator('xpath=ancestor::div[contains(@class,"rounded-lg")]');
    await row.locator('button').last().click();
    // Edit form opens
    const categoryInput = page.getByPlaceholder('Category label');
    await expect(categoryInput).toBeVisible({ timeout: 5000 });
    await categoryInput.fill('updated-category');
    // Save → reducer intercepted → success message
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText('Metadata updated', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('inline edit cancel closes the form without saving', async ({ page }) => {
    const row = page.getByText('Beta summary', { exact: true }).first().locator('xpath=ancestor::div[contains(@class,"rounded-lg")]');
    await row.locator('button').last().click();
    await expect(page.getByPlaceholder('Category label')).toBeVisible({ timeout: 5000 });
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(page.getByPlaceholder('Category label')).toHaveCount(0);
  });

  test('batch edit selects memories and applies category', async ({ page }) => {
    await page.getByRole('button', { name: /batch edit/i }).click();
    // Checkboxes appear on rows
    await expect(page.getByRole('checkbox').first()).toBeVisible({ timeout: 5000 });
    // Apply to All is disabled with no selection
    await expect(page.getByRole('button', { name: 'Apply to All', exact: true })).toBeDisabled();
    // Select mem-1 and mem-2
    await page.getByRole('checkbox').nth(0).check();
    await page.getByRole('checkbox').nth(1).check();
    await expect(page.getByText('2 memory(ies) selected.', { exact: false })).toBeVisible({ timeout: 5000 });
    // Fill category and apply → reducer intercepted → success
    const batchInput = page.getByPlaceholder('e.g. preferences, history, facts');
    await batchInput.fill('batch-category');
    await page.getByRole('button', { name: 'Apply to All', exact: true }).click();
    await expect(page.getByText('Updated 2 memories', { exact: true })).toBeVisible({ timeout: 5000 });
    // Batch panel closes after apply
    await expect(page.getByRole('button', { name: 'Apply to All', exact: true })).toHaveCount(0);
  });

  test('batch edit cancel clears selection', async ({ page }) => {
    await page.getByRole('button', { name: /batch edit/i }).click();
    await page.getByRole('checkbox').first().check();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Apply to All', exact: true })).toHaveCount(0);
  });
});