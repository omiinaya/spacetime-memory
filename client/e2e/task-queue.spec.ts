import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, mockSqlCalls } from './helpers';

/**
 * E2E tests for the Task Queue page.
 *
 * Structural tests run with the default empty SQL mock. The seeded describe
 * mocks memory rows with a task payload so the queue renders a task with its
 * status badge.
 */

const taskSqlRows = [
  {
    schema: {
      elements: [
        { name: { some: 'id' } }, { name: { some: 'workspace_id' } },
        { name: { some: 'memory_type' } }, { name: { some: 'content' } },
        { name: { some: 'is_active' } }, { name: { some: 'created_at' } },
        { name: { some: 'updated_at' } }, { name: { some: 'peer_id' } },
      ],
    },
    rows: [
      ['task-1', 'w1', 'task_queue',
        JSON.stringify({ type: 'embed', status: 'pending', priority: 1, worker_id: '', attempts: 0, max_retries: 3, error_message: '', task_type: 'embed', payload: '{}', result: '' }),
        true, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z', 'p1'],
    ],
  },
];

test.describe('Task Queue Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/task-queue');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /task queue/i, exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText(/task queue|pending tasks/i).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('No tasks found', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Task Queue — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page, taskSqlRows);
    await gotoPage(page, '/task-queue');
  });

  test('shows seeded task with pending status', async ({ page }) => {
    await expect(page.getByText(/pending/i, { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });
});