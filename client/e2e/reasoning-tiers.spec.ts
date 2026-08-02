import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, installMockAuth, installMockStdb, mockReducerCalls } from './helpers';

/**
 * E2E tests for the Reasoning Tiers page.
 *
 * Structural tests run with the default empty SQL mock. The seeded describe
 * mocks the reasoning_tier_result SQL query to return a JSON blob that
 * parses into tiers, so the tier list + priority badges render.
 */

const tierSqlRows = [
  {
    schema: { elements: [{ name: { some: 'data' } }] },
    rows: [
      [JSON.stringify([
        {
          id: 'tier-1', workspace_id: '', name: 'Fast', description: 'Quick responses',
          max_tokens: 1024, temperature: 0.7, top_p: 0.9, max_context_memories: 5,
          min_confidence: 0.5, requires_reflection: false, requires_graph_traversal: false,
          priority: 1,
        },
        {
          id: 'tier-2', workspace_id: '', name: 'Deep', description: 'Reflective reasoning',
          max_tokens: 4096, temperature: 0.3, top_p: 0.95, max_context_memories: 20,
          min_confidence: 0.9, requires_reflection: true, requires_graph_traversal: true,
          priority: 2,
        },
      ])],
    ],
  },
];

test.describe('Reasoning Tiers Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/reasoning-tiers');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Reasoning Tiers', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('No reasoning tiers configured', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Reasoning Tiers — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    // Tier list query returns the seeded blob; the detail/insight queries
    // (execution history etc.) return empty rows so detail rendering is safe.
    await page.route(/\/v1\/database\/.*\/sql/, async (route: any) => {
      const body = route.request().postData() ?? '';
      if (body.includes('reasoning_tier_result')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(tierSqlRows),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([{ schema: { elements: [] }, rows: [] }]),
        });
      }
    });
    await installMockAuth(page);
    await installMockStdb(page);
    await mockReducerCalls(page);
    await gotoPage(page, '/reasoning-tiers');
  });

  test('shows seeded tiers in the list', async ({ page }) => {
    await expect(page.getByText('Fast', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Deep', { exact: true }).first()).toBeVisible({ timeout: 3000 });
  });

  test('shows priority badges for seeded tiers', async ({ page }) => {
    // List shows tier names; click "Fast" to open the detail view with the badge
    await page.getByText('Fast', { exact: true }).first().click();
    await expect(page.getByText(/Priority:\s*1/).first()).toBeVisible({ timeout: 8000 });
  });

  test('create tier form validates name and submits', async ({ page }) => {
    await page.getByRole('button', { name: /create tier/i }).first().click();
    await expect(page.getByText('Create Reasoning Tier', { exact: true })).toBeVisible({ timeout: 8000 });
    // Submit empty → validation error (the form's submit is exactly "Create")
    const submit = page.getByRole('button', { name: 'Create', exact: true });
    await submit.click();
    await expect(page.getByText('Tier name is required', { exact: true })).toBeVisible({ timeout: 8000 });
    // Fill name → submit → reducer mocked ok → success banner
    await page.getByPlaceholder('e.g. quick, balanced, deep').fill('Balanced');
    await submit.click();
    await expect(page.getByText('Reasoning tier created', { exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('make default action on a seeded tier shows success', async ({ page }) => {
    // Click "Fast" row → detail view; the detail has a Make Default action
    // (tiers are seeded without is_default so the button is enabled)
    await page.getByText('Fast', { exact: true }).first().click();
    const makeDefault = page.getByRole('button', { name: /make default/i });
    await expect(makeDefault).toBeVisible({ timeout: 8000 });
    await makeDefault.click();
    await expect(page.getByText('Default tier updated', { exact: true })).toBeVisible({ timeout: 8000 });
  });
});
