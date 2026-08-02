import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, mockSqlCalls } from './helpers';

/**
 * E2E tests for the Reflection Loop page.
 *
 * Structural tests run with the default empty SQL mock. The seeded describe
 * mocks reflection_session_result to return a JSON blob that parses into
 * reflection sessions, so the session list renders.
 */

const reflectionSqlRows = [
  {
    schema: { elements: [{ name: { some: 'json_data' } }] },
    rows: [
      [JSON.stringify([
        {
          id: 'ref-1', workspace_id: '', peer_id: 'p1', config_json: '{}',
          cycles_completed: 3, status: 'completed', insight_count: 5,
          started_at: '2026-08-01T00:00:00Z', completed_at: '2026-08-01T01:00:00Z',
          created_at: '2026-08-01T00:00:00Z',
        },
      ])],
    ],
  },
];

test.describe('Reflection Loop Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/reflection-loop');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Reflection Loop', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Structured self-reflection sessions for AI agents', { exact: false }).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('No Reflection Sessions', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Reflection Loop — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page, reflectionSqlRows);
    await gotoPage(page, '/reflection-loop');
  });

  test('shows seeded reflection session', async ({ page }) => {
    // Session renders with cycles_completed and status
    await expect(page.getByText(/completed/i, { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });
});
