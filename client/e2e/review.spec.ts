import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, mockSqlCalls } from './helpers';

/**
 * E2E tests for the Review page.
 *
 * Structural tests run with the default empty SQL mock. The seeded describe
 * mocks review_result to return an items_json blob so the spaced-repetition
 * card renders.
 */

const reviewSqlRows = [
  {
    schema: { elements: [{ name: { some: 'items_json' } }, { name: { some: 'due_count' } }] },
    rows: [
      [JSON.stringify([
        {
          id: 'rev-1', workspace_id: '', memory_id: 'm1', user_id: '',
          easiness_factor: 2.5, interval_days: 3, repetitions: 2,
          next_review_at: '2026-08-01T00:00:00Z',
        },
      ]), 1],
    ],
  },
];

test.describe('Review Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/review');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Review', exact: true }).first()).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText(/spaced repetition|review/i).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText(/no .*review|all done|nothing due/i)]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Review — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page, reviewSqlRows);
    await gotoPage(page, '/review');
  });

  test('shows seeded review card with interval detail', async ({ page }) => {
    await expect(page.getByText(/Interval:\s*3d/, { exact: false }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText(/EF:\s*2\.50/, { exact: false }).first()).toBeVisible({ timeout: 3000 });
  });

  test('schedule button disabled until memory id entered', async ({ page }) => {
    const schedule = page.getByRole('button', { name: /^schedule$/i });
    await expect(schedule).toBeDisabled({ timeout: 8000 });
    const input = page.getByPlaceholder('Enter memory ID to schedule');
    await input.fill('mem-x');
    await expect(schedule).toBeEnabled();
    await schedule.click();
    // Reducer mocked ok → success message
    await expect(page.getByText('Memory scheduled for review', { exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('full review flow: show answer then grade fires the reducer', async ({ page }) => {
    // Show Answer / Grade reveals grade buttons
    const showAnswer = page.getByRole('button', { name: /show answer|grade/i }).first();
    await expect(showAnswer).toBeVisible({ timeout: 8000 });
    await showAnswer.click();
    // Grade buttons appear as labeled buttons (0..5); click the first one
    const gradeBtn = page.locator('button').filter({ has: page.locator('span.text-lg') }).first();
    await expect(gradeBtn).toBeVisible({ timeout: 8000 });
    await gradeBtn.click();
    // perform_review reducer (mocked ok) advances or completes
    await expect(page.getByText(/Review Complete|Item \d of \d/i).first()).toBeVisible({ timeout: 8000 });
  });
});
