import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Trust Dashboard page — structural rendering plus full
 * interactive corner coverage: stat cards, trust distribution, trust-by-tier,
 * low-trust table with Reinforce/Deactivate actions, search/tier/sort filters,
 * feedback activity and decay-ready sections. All data comes from the mock STDB
 * seam (seeded rows), and reducer calls are intercepted by the HTTP mock, so
 * the tests are deterministic and load-independent.
 */

const MEM = (over: Record<string, unknown> = {}) => ({
  id: 'mem-1', workspace_id: 'ws1', content: 'trust memory', summary: 'Trust memory summary',
  memory_type: 'fact', tier: 'L0', confidence: 0.9, trust_score: 0.85, feedback_count: 2,
  access_count: 5, strength: 0.8, is_active: true, created_at: 1785600000000000,
  updated_at: 1785600000000000, ...over,
});

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
        MEM({ id: 'mem-1', content: 'alpha high trust', summary: 'Alpha memory', tier: 'L0', trust_score: 0.85, confidence: 0.9, strength: 0.8, feedback_count: 2 }),
        MEM({ id: 'mem-2', content: 'beta low trust', summary: 'Beta memory', tier: 'L1', trust_score: 0.25, confidence: 0.5, strength: 0.3, feedback_count: 1 }),
        MEM({ id: 'mem-3', content: 'gamma inactive', summary: 'Gamma memory', tier: 'L2', trust_score: 0.9, confidence: 0.9, strength: 0.9, feedback_count: 0, is_active: false }),
      ],
      memory_feedback: [
        { id: 'fb-1', memory_id: 'mem-1', rating: 'helpful', peer_id: 'p1', created_at: 1785600000000000 },
        { id: 'fb-2', memory_id: 'mem-2', rating: 'not_helpful', peer_id: 'p2', created_at: 1785590000000000 },
      ],
    });
    await gotoPage(page, '/trust-dashboard');
  });

  test('renders stat cards with seeded aggregates', async ({ page }) => {
    // 2 active memories → Total Active Memories = 2
    await expect(page.getByText('Total Active Memories', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('2', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    // Avg trust = (0.85 + 0.25)/2 = 0.55
    await expect(page.getByText('Avg Trust Score', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('0.55', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    // Avg confidence = (0.9 + 0.5)/2 = 0.7 → 70%
    await expect(page.getByText('Avg Confidence', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('70%', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    // Total feedback = 2+1 = 3
    await expect(page.getByText('Total Feedback', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('3', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    // Avg strength = (0.8+0.3)/2 = 0.55
    await expect(page.getByText('Avg Strength', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('renders trust distribution buckets', async ({ page }) => {
    // trust < 0.4 → low (mem-2), 0.4-0.7 → medium (0), >= 0.7 → high (mem-1)
    await expect(page.getByText('Trust Score Distribution', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Needs attention', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Highly trusted', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('renders trust by tier rows with averages', async ({ page }) => {
    await expect(page.getByText('Trust by Tier', { exact: true })).toBeVisible({ timeout: 5000 });
    // L0 row (1 memory, avg 0.85)
    await expect(page.getByText('L0', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('0.85', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    // L1 row (1 memory, avg 0.25)
    await expect(page.getByText('L1', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('0.25', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });

  test('renders feedback activity feed', async ({ page }) => {
    await expect(page.getByText('Feedback Activity', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('2 recent', { exact: true })).toBeVisible({ timeout: 5000 });
    // Both seeded feedback rows surface the memory summary (may appear in
    // the browse list too, so scope to first)
    await expect(page.getByText('Alpha memory', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Beta memory', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });

  test('lists low-trust memories in the table with actions', async ({ page }) => {
    // Only mem-2 has trust < 0.5 (title includes "(score < 0.5)")
    await expect(page.getByText('Low-Trust Memories', { exact: false }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('1 low-trust', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Beta memory', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    // Reinforce + deactivate buttons exist
    await expect(page.getByRole('button', { name: /reinforce/i })).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole('button', { name: /reinforce/i })).toHaveCount(1);
  });

  test('reinforce and deactivate trigger reducers without error', async ({ page }) => {
    await expect(page.getByRole('button', { name: /reinforce/i })).toBeVisible({ timeout: 5000 });
    await page.getByRole('button', { name: /reinforce/i }).click();
    // The HTTP mock fulfills the reducer; no error banner should appear
    await expect(page.getByText('Low-Trust Memories', { exact: false }).first()).toBeVisible({ timeout: 5000 });
    // Deactivate button (ghost trash icon next to reinforce, no accessible name)
    const deactivate = page.locator('button[title="Deactivate memory"]');
    await expect(deactivate).toBeVisible({ timeout: 5000 });
    await deactivate.click();
    await expect(page.getByText('Low-Trust Memories', { exact: false }).first()).toBeVisible({ timeout: 5000 });
  });

  test('search filter narrows the browse list', async ({ page }) => {
    const search = page.getByPlaceholder('Search by content, summary, or type...');
    await expect(search).toBeVisible({ timeout: 5000 });
    await search.fill('alpha');
    // Only 1 of 2 active memories match (content lines are unique to browse rows)
    await expect(page.getByText('1 / 2 memories', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('alpha high trust', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('beta low trust', { exact: true })).toHaveCount(0);
    // Empty search → no matching state
    await search.fill('zzz-no-match');
    await expect(page.getByText('No matching memories', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('tier filter narrows the browse list', async ({ page }) => {
    const tierSelect = page.locator('select').first();
    await expect(tierSelect).toBeVisible({ timeout: 5000 });
    await tierSelect.selectOption('L1');
    await expect(page.getByText('1 / 2 memories', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('beta low trust', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('alpha high trust', { exact: true })).toHaveCount(0);
    await tierSelect.selectOption('L0');
    await expect(page.getByText('1 / 2 memories', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('alpha high trust', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('sort dropdown switches sort key', async ({ page }) => {
    const sortSelect = page.locator('select').nth(1);
    await expect(sortSelect).toBeVisible({ timeout: 5000 });
    // Default trust_score: Alpha (0.85) first, Beta (0.25) second
    const firstRow = page.getByText('Alpha memory', { exact: true }).first();
    await expect(firstRow).toBeVisible({ timeout: 5000 });
    // Switch to confidence sort — Alpha still first (0.9 vs 0.5)
    await sortSelect.selectOption('confidence');
    await expect(firstRow).toBeVisible({ timeout: 5000 });
    // Switch to updated sort — no crash
    await sortSelect.selectOption('updated_at');
    await expect(firstRow).toBeVisible({ timeout: 5000 });
  });

  test('shows decay-ready section with all fresh memories up-to-date', async ({ page }) => {
    await expect(page.getByText('Decay-Ready Memories', { exact: true })).toBeVisible({ timeout: 5000 });
    // Seeded memories are fresh (recent updated_at) → no decay-ready
    await expect(page.getByText('All memories are up-to-date', { exact: true })).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Trust Dashboard — Decay-Ready Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    // updated_at 40 days in the past (microseconds) → isDecayReady() true
    const fortyDaysAgoUs = Date.now() * 1000 - 40 * 24 * 60 * 60 * 1000 * 1000;
    await seedMockData(page, {
      memory: [
        MEM({ id: 'mem-old', content: 'old stale memory', summary: 'Old memory', tier: 'L2', trust_score: 0.8, updated_at: fortyDaysAgoUs }),
      ],
    });
    await gotoPage(page, '/trust-dashboard');
  });

  test('flags idle memories as decay-ready', async ({ page }) => {
    await expect(page.getByText('Decay-Ready Memories', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('1 affected', { exact: true })).toBeVisible({ timeout: 5000 });
    // Old memory appears in both the decay list and the browse list → scope first
    await expect(page.getByText('Old memory', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });
});
