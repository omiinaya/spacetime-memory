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
});