import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, installMockAuth, installMockStdb, mockReducerCalls } from './helpers';

/**
 * E2E tests for the Reflection Loop page.
 *
 * Structural tests run with the default empty SQL mock. The seeded describe
 * mocks reflection_session_result to return a JSON blob that parses into
 * reflection sessions, so the session list renders. Corner tests cover the
 * create-session form, opening a session detail view, and the row-level
 * action buttons (Start Cycle / Complete / Delete).
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
        {
          id: 'ref-2', workspace_id: '', peer_id: 'p2', config_json: '{"cycles":2}',
          cycles_completed: 0, status: 'active', insight_count: 0,
          started_at: '2026-08-01T02:00:00Z', completed_at: null,
          created_at: '2026-08-01T02:00:00Z',
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
    // Sessions query returns the seeded sessions blob; the insights query must
    // return EMPTY rows (the sessions blob would crash insight rendering).
    await page.route(/\/v1\/database\/.*\/sql/, async (route: any) => {
      const body = route.request().postData() ?? '';
      if (body.includes('reflection_session_result')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(reflectionSqlRows),
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
    await gotoPage(page, '/reflection-loop');
  });

  test('shows seeded reflection session', async ({ page }) => {
    // Session renders with cycles_completed and status
    await expect(page.getByText(/completed/i, { exact: false }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Peer: p1', { exact: false })).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Cycles: 3', { exact: false })).toBeVisible({ timeout: 8000 });
  });

  test('create session form validates and submits', async ({ page }) => {
    await page.getByRole('button', { name: /new session/i }).first().click();
    // Form opens
    await expect(page.getByPlaceholder('workspace-id')).toBeVisible({ timeout: 5000 });
    // Submit with empty fields → validation error
    await page.getByRole('button', { name: 'Create Session', exact: true }).click();
    await expect(page.getByText('Workspace ID and Peer ID are required', { exact: true })).toBeVisible({ timeout: 8000 });
    // Fill fields and submit → reducer mocked ok, success message
    await page.getByPlaceholder('workspace-id').fill('ws-e2e');
    await page.getByPlaceholder('peer-id').fill('peer-e2e');
    await page.getByRole('button', { name: 'Create Session', exact: true }).click();
    await expect(page.getByText('Reflection session created', { exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('opening a session shows detail view with action buttons', async ({ page }) => {
    // Click the completed session row → detail view
    await page.getByText('Peer: p1', { exact: false }).click();
    await expect(page.getByRole('heading', { name: 'Reflection Session', exact: true })).toBeVisible({ timeout: 8000 });
    // Completed session → Start Cycle and Complete are disabled; Delete + Refresh enabled
    await expect(page.getByRole('button', { name: /start cycle/i })).toBeDisabled();
    await expect(page.getByRole('button', { name: /^complete$/i })).toBeDisabled();
    await expect(page.getByRole('button', { name: /^delete$/i })).toBeEnabled();
    await expect(page.getByRole('button', { name: /refresh/i })).toBeVisible({ timeout: 8000 });
  });

  test('active session shows enabled Start Cycle / Complete and row actions work', async ({ page }) => {
    // Click the active session row → detail view
    await page.getByText('Peer: p2', { exact: false }).click();
    await expect(page.getByRole('heading', { name: 'Reflection Session', exact: true })).toBeVisible({ timeout: 8000 });
    // Active session → Start Cycle and Complete enabled
    await expect(page.getByRole('button', { name: /start cycle/i })).toBeEnabled();
    await expect(page.getByRole('button', { name: /^complete$/i })).toBeEnabled();
    // Start cycle fires the reducer (mocked ok) → success message
    await page.getByRole('button', { name: /start cycle/i }).click();
    await expect(page.getByText('Cycle started for session', { exact: false })).toBeVisible({ timeout: 8000 });
  });
});