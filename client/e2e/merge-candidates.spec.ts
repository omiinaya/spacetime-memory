import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Merge Candidates page.
 *
 * Structural tests run against the empty mock. The seeded describe injects
 * near-duplicate memories + a merge_suggestion row so the candidates list
 * renders and the empty state is replaced by actual suggestion content.
 */

test.describe('Merge Candidates Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/merge-candidates');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Merge Candidates', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('renders page description', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('Review and manage near-duplicate memories', { exact: false }).first()]);
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [page.getByText('No merge candidates', { exact: false }).first()]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Merge Candidates — Seeded', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    const now = Date.now() * 1000;
    await seedMockData(page, {
      memory: [
        {
          id: 'mem-1', workspace_id: 'w1', peer_id: 'p1', observer_id: 'p1',
          memory_type: 'experience', content: 'first memory about the project',
          summary: 'First memory', entities_json: '[]', confidence: 0.9,
          is_active: true, tier: 'L1', created_at: now, updated_at: now,
          access_count: 1, importance: 0.5,
        },
        {
          id: 'mem-2', workspace_id: 'w1', peer_id: 'p1', observer_id: 'p1',
          memory_type: 'experience', content: 'second memory about the project',
          summary: 'Second memory', entities_json: '[]', confidence: 0.85,
          is_active: true, tier: 'L1', created_at: now, updated_at: now,
          access_count: 1, importance: 0.5,
        },
      ],
      workspace: [{ id: 'w1', name: 'Main' }],
      merge_suggestion: [
        {
          id: 'sug-1', workspace_id: 'w1', source_id: 'mem-1', target_id: 'mem-2',
          cosine_similarity: 0.93, edit_distance: 4,
          content_overlap_preview: 'first memory ... second memory',
          status: 'pending', created_at: now,
        },
      ],
    });
    await gotoPage(page, '/merge-candidates');
  });

  test('shows seeded merge suggestion', async ({ page }) => {
    await expect(page.getByText('First memory', { exact: false }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Second memory', { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });

  test('shows similarity detail for the suggestion', async ({ page }) => {
    // 0.93 * 100 = "93.0%" — rendered as "Sim: 93.0%"
    await expect(page.getByText(/Sim:\s*93\.0%/, { exact: false }).first()).toBeVisible({ timeout: 8000 });
  });
});