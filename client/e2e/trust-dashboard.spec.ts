import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Trust Dashboard page — verifies the page renders its heading and
 * deterministic structural/empty-state content. Data-dependent features are
 * not asserted (the dashboard connects to STDB over WS, so pages may show
 * either fully-loaded data, the empty state, or the loading indicator).
 */


test.describe('Trust Dashboard Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/trust-dashboard');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Trust Dashboard', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Trust Dashboard — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      memory: [
        { id: 'mem-1', workspace_id: 'ws1', content: 'trust memory', summary: 's', memory_type: 'fact', tier: 'core', confidence: 0.9, trust_score: 0.85, feedback_count: 2, access_count: 5, strength: 0.8, is_active: true, created_at: 1785600000000, updated_at: 1785600000000 },
      ],
      memory_feedback: [
        { id: 'fb-1', memory_id: 'mem-1', rating: 'upvote', peer_id: 'p1', created_at: 1785600000000 },
      ],
    });
    await gotoPage(page, '/trust-dashboard');
  });

  test('renders trust dashboard with seeded feedback', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Trust Dashboard/i })).toBeVisible({ timeout: 5000 });
  });
});
