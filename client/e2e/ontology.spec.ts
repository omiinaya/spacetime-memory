import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, mockSqlCalls } from './helpers';

/**
 * E2E tests for the Ontology page.
 *
 * Structural tests run with the default empty SQL mock. The seeded describe
 * mocks memory rows of type entity_type so the Entity Types tab renders the
 * parsed type names.
 */

const ontologySqlRows = [
  {
    schema: {
      elements: [
        { name: { some: 'id' } }, { name: { some: 'workspace_id' } },
        { name: { some: 'memory_type' } }, { name: { some: 'content' } },
        { name: { some: 'summary' } }, { name: { some: 'is_active' } },
        { name: { some: 'created_at' } }, { name: { some: 'updated_at' } },
      ],
    },
    rows: [
      ['et-1', 'w1', 'entity_type',
        JSON.stringify({ name: 'Person', parent: '', properties: ['name', 'age'], description: 'A human' }),
        'Person type', true, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z'],
    ],
  },
];

test.describe('Ontology Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/ontology');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Ontology', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Manage entity types, relation types, and search recipes', { exact: false }).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Entity Types', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Ontology — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page, ontologySqlRows);
    await gotoPage(page, '/ontology');
  });

  test('shows seeded entity type name', async ({ page }) => {
    await expect(page.getByText('Person', { exact: true }).first()).toBeVisible({ timeout: 8000 });
  });

  test('shows entity type description', async ({ page }) => {
    await expect(page.getByText('A human', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('create entity type form validates and submits', async ({ page }) => {
    await page.getByRole('button', { name: /create entity type/i }).first().click();
    await expect(page.getByText('New Entity Type', { exact: false }).first()).toBeVisible({ timeout: 8000 });
    // Submit empty → validation error
    const submit = page.getByRole('button', { name: 'Create', exact: true }).last();
    await submit.click();
    await expect(page.getByText('Entity type name is required', { exact: true })).toBeVisible({ timeout: 8000 });
    // Fill name → submit → reducer mocked ok → success banner
    await page.getByPlaceholder('Person, Organization, Document, ...').fill('Animal');
    await submit.click();
    await expect(page.getByText('Entity type created', { exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('tabs switch between entity, relation, and recipe sections', async ({ page }) => {
    // Entity Types tab default; click Relation Types
    await page.getByRole('tab', { name: /relation types/i }).click();
    await expect(page.getByRole('button', { name: /create relation type/i })).toBeVisible({ timeout: 8000 });
    // Search Recipes tab
    await page.getByRole('tab', { name: /search recipes/i }).click();
    await expect(page.getByRole('button', { name: /create search recipe/i })).toBeVisible({ timeout: 8000 });
  });
});