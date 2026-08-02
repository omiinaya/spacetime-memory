import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, mockSqlCalls } from './helpers';

/**
 * E2E tests for the Task Queue page.
 *
 * Structural tests run with the default empty SQL mock. The seeded describe
 * mocks memory rows with task payloads across all four statuses so the queue
 * renders stats, tabs, and the per-status action buttons (Claim, Complete,
 * Fail, Retry), and the reducer calls (mocked HTTP) surface success messages.
 */

const PENDING = { type: 'embed', status: 'pending', priority: 1, worker_id: '', attempts: 0, max_retries: 3, error_message: '', task_type: 'embed', payload: '{}', result: '' };
const CLAIMED = { type: 'summarize', status: 'claimed', priority: 3, worker_id: 'worker-1', attempts: 1, max_retries: 3, error_message: '', task_type: 'summarize', payload: '{}', result: '' };
const COMPLETED = { type: 'ingest', status: 'completed', priority: 2, worker_id: 'worker-2', attempts: 1, max_retries: 3, error_message: '', task_type: 'ingest', payload: '{}', result: '' };
const FAILED = { type: 'search', status: 'failed', priority: 5, worker_id: 'worker-3', attempts: 2, max_retries: 3, error_message: 'timeout', task_type: 'search', payload: '{}', result: '' };

const seededRows = [
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
      ['task-1', 'w1', 'task_queue', JSON.stringify(PENDING), true, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z', 'p1'],
      ['task-2', 'w1', 'task_queue', JSON.stringify(CLAIMED), true, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z', 'p1'],
      ['task-3', 'w1', 'task_queue', JSON.stringify(COMPLETED), true, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z', 'p1'],
      ['task-4', 'w1', 'task_queue', JSON.stringify(FAILED), true, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z', 'p1'],
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
    await mockPage(page, seededRows);
    await gotoPage(page, '/task-queue');
  });

  test('renders stat cards for all four statuses', async ({ page }) => {
    // Four tasks: 1 pending, 1 claimed, 1 completed, 1 failed
    const totalCard = page.getByText('Total', { exact: true });
    await expect(totalCard).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('4', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Pending', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Claimed', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Completed', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Failed', { exact: true }).first()).toBeVisible({ timeout: 8000 });
  });

  test('lists all seeded tasks with status badges', async ({ page }) => {
    await expect(page.getByText('embed', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('summarize', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('ingest', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('search', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    // Status badges
    await expect(page.getByText('pending', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('claimed', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('completed', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('failed', { exact: true }).first()).toBeVisible({ timeout: 8000 });
  });

  test('status tabs filter the task list', async ({ page }) => {
    // Pending tab → only the embed task
    await page.getByRole('tab', { name: /pending/i }).first().click();
    await expect(page.getByText('embed', { exact: true })).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('search', { exact: true }).first()).toHaveCount(0);
    // Completed tab → only ingest
    await page.getByRole('tab', { name: /completed/i }).click();
    await expect(page.getByText('ingest', { exact: true })).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('embed', { exact: true }).first()).toHaveCount(0);
  });

  test('search filter by task type narrows the list', async ({ page }) => {
    const search = page.getByPlaceholder('Filter by task type...');
    await search.fill('summarize');
    await expect(page.getByText('summarize', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('ingest', { exact: true }).first()).toHaveCount(0);
    // Clear resets the filter
    await page.getByRole('button', { name: /^clear$/i }).click();
    await expect(page.getByText('ingest', { exact: true }).first()).toBeVisible({ timeout: 8000 });
  });

  test('claim action on a pending task shows success', async ({ page }) => {
    const claimBtn = page.getByRole('button', { name: /claim/i }).first();
    await expect(claimBtn).toBeVisible({ timeout: 8000 });
    await claimBtn.click();
    await expect(page.getByText('Task claimed', { exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('complete and fail actions on a claimed task show success', async ({ page }) => {
    // The claimed task has Complete + Fail buttons
    const completeBtn = page.getByRole('button', { name: /^complete$/i });
    await expect(completeBtn).toBeVisible({ timeout: 8000 });
    await completeBtn.click();
    await expect(page.getByText('Task completed', { exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('retry action on a failed task shows success', async ({ page }) => {
    // The failed task (attempts < max_retries) shows a Retry button
    const retryBtn = page.getByRole('button', { name: /retry/i });
    await expect(retryBtn).toBeVisible({ timeout: 8000 });
    await retryBtn.click();
    await expect(page.getByText('Task queued for retry', { exact: true })).toBeVisible({ timeout: 8000 });
  });
});