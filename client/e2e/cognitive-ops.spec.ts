import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, mockSqlCalls } from './helpers';

/**
 * E2E tests for the Cognitive Operations page.
 *
 * The page loads via SQL (mocked empty → empty state). These tests drive the
 * REGISTER form: validation errors (missing name, invalid config JSON) and a
 * successful register (reducer mocked ok → success banner).
 */

test.describe('Cognitive Ops Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/cognitive-ops');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /cognitive/i, exact: false })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [
      page.getByText(/no .*op|register|cognitive/i),
    ]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('register op shows validation error when name missing', async ({ page }) => {
    await page.getByRole('button', { name: 'Register Op', exact: true }).click();
    await expect(page.getByText('Register Cognitive Operation', { exact: true })).toBeVisible({ timeout: 8000 });
    // The form's submit button is exactly "Register"
    await page.getByRole('button', { name: 'Register', exact: true }).click();
    await expect(page.getByText('Op name is required')).toBeVisible({ timeout: 8000 });
  });

  test('register op shows validation error for invalid config JSON', async ({ page }) => {
    await page.getByRole('button', { name: 'Register Op', exact: true }).click();
    await expect(page.getByText('Register Cognitive Operation', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('e.g. entity_extract, semantic_search').fill('my_op');
    // config field: a textarea defaulting to '{}' — replace with bad JSON
    await page.locator('textarea').first().fill('not json');
    await page.getByRole('button', { name: 'Register', exact: true }).click();
    await expect(page.getByText('config_json is not valid JSON')).toBeVisible({ timeout: 8000 });
  });

  test('register op succeeds with valid name and config', async ({ page }) => {
    await page.getByRole('button', { name: 'Register Op', exact: true }).click();
    await expect(page.getByText('Register Cognitive Operation', { exact: true })).toBeVisible({ timeout: 8000 });
    await page.getByPlaceholder('e.g. entity_extract, semantic_search').fill('my_op');
    await page.getByPlaceholder('What this operation does').fill('Test op');
    // config textarea stays '{}' (valid) → submit
    await page.getByRole('button', { name: 'Register', exact: true }).click();
    await expect(page.getByText('Cognitive op registered', { exact: true })).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Cognitive Ops — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    // The page reads cognitive_op_result first (empty) then falls back to
    // cognitive_op; seed the fallback table so the op list renders.
    await mockPage(page, [
      {
        schema: {
          elements: [
            { name: { some: 'id' } }, { name: { some: 'name' } },
            { name: { some: 'op_type' } }, { name: { some: 'description' } },
            { name: { some: 'config_json' } }, { name: { some: 'is_active' } },
            { name: { some: 'created_at' } }, { name: { some: 'updated_at' } },
          ],
        },
        rows: [
          ['op-1', 'entity_extract', 'observe', 'Extracts entities', '{}', true, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z'],
        ],
      },
    ]);
    await gotoPage(page, '/cognitive-ops');
  });

  test('lists seeded op and opens its detail view', async ({ page }) => {
    await expect(page.getByText('entity_extract', { exact: false }).first()).toBeVisible({ timeout: 8000 });
    await page.getByText('entity_extract', { exact: false }).first().click();
    await expect(page.getByText('Extracts entities', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });
});