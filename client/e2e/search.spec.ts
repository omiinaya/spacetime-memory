import { test, expect } from '@playwright/test';
import { expectAnyVisible, gotoPage, installMockStdb } from './helpers';

/**
 * E2E tests for the Search page — full interaction with mocked STDB + auth.
 */

const MOCK_RESULTS = [
  {
    schema: {
      elements: [
        { name: { some: 'id' } }, { name: { some: 'entity_type' } },
        { name: { some: 'entity_id' } }, { name: { some: 'content' } },
        { name: { some: 'score' } }, { name: { some: 'strategy' } },
        { name: { some: 'context_json' } }, { name: { some: 'created_at' } },
      ],
    },
    rows: [
      [
        'r1', 'memory', 'a1b2c3d4e5f6a7b8',
        'OAuth2 authentication flow using JWT tokens and refresh token rotation',
        0.95, 'keyword',
        JSON.stringify({ workspace_context: 'Auth module documentation', memory_context: 'Login flow details' }),
        1718234567000000,
      ],
      [
        'r2', 'memory', 'b2c3d4e5f6a7b8c9',
        'User login sequence: email, password, MFA code, session cookie',
        0.87, 'temporal',
        JSON.stringify({ workspace_context: 'Auth module documentation', memory_context: 'MFA setup guide' }),
        1718234567000000,
      ],
      [
        'r3', 'memory', 'c3d4e5f6a7b8c9d0',
        'Pizza Margherita recipe with fresh mozzarella and basil',
        0.22, 'keyword',
        JSON.stringify({ workspace_context: 'Cooking recipes', memory_context: 'Italian cuisine' }),
        1718234567000000,
      ],
    ],
  },
];

async function mockStdb(page: any) {
  // Mock auth: make AuthProvider immediately authenticated
  await page.addInitScript(() => {
    (window as any).__MOCK_AUTH__ = {
      account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
    };
  });
  // Mock HTTP reducer calls
  await page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
  // Mock SQL queries
  await page.route(/\/v1\/database\/.*\/sql/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESULTS) });
  });
}

test.describe('Search Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockStdb(page);
    await installMockStdb(page);
    await gotoPage(page, '/search');
  });

  test('renders search heading and input', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible();
    await expect(page.getByPlaceholder(/search across memories/i)).toBeVisible();
  });

  test('button disabled when input empty, enabled when typed', async ({ page }) => {
    const btn = page.getByRole('button', { name: /search/i });
    await expect(btn).toBeDisabled();
    await page.getByPlaceholder(/search across memories/i).fill('auth');
    await expect(btn).toBeEnabled();
  });

  test('performs search and shows results with strategy badges', async ({ page }) => {
    await page.getByPlaceholder(/search across memories/i).fill('auth');
    await page.getByRole('button', { name: /search/i }).click();
    await expect(page.getByText('Results (3)')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('keyword').first()).toBeVisible();
    await expect(page.getByText('temporal')).toBeVisible();
  });

  test('shows score percentages on results', async ({ page }) => {
    await page.getByPlaceholder(/search across memories/i).fill('auth');
    await page.getByRole('button', { name: /search/i }).click();
    await expect(page.getByText('95%')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('87%')).toBeVisible();
    await expect(page.getByText('22%')).toBeVisible();
  });

  test('displays context tree breadcrumbs in results', async ({ page }) => {
    await page.getByPlaceholder(/search across memories/i).fill('auth');
    await page.getByRole('button', { name: /search/i }).click();
    await expect(page.getByText('Auth module documentation').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Login flow details')).toBeVisible();
  });

  test('shows empty state when no results', async ({ page }) => {
    await page.unroute(/\/v1\/database\/.*\/sql/);
    await page.route(/\/v1\/database\/.*\/sql/, async (route: any) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
    await page.getByPlaceholder(/search across memories/i).fill('nonexistent');
    await page.getByRole('button', { name: /search/i }).click();
    await expect(page.getByText('No results')).toBeVisible({ timeout: 5000 });
  });

  test('search triggers on Enter key', async ({ page }) => {
    await page.getByPlaceholder(/search across memories/i).fill('auth');
    await page.getByPlaceholder(/search across memories/i).press('Enter');
    await expect(page.getByText('Results (3)')).toBeVisible({ timeout: 5000 });
  });


  test('handles special characters in search query', async ({ page }) => {
    await page.getByPlaceholder(/search across memories/i).fill('hello!@#$%^&*()world');
    await page.getByRole('button', { name: /search/i }).click();
    // Should not crash - either shows results or empty state
    await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('handles unicode characters in search query', async ({ page }) => {
    await page.getByPlaceholder(/search across memories/i).fill('こんにちは 世界');
    await page.getByRole('button', { name: /search/i }).click();
    await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('handles very long search query', async ({ page }) => {
    const longQuery = 'a'.repeat(10000);
    await page.getByPlaceholder(/search across memories/i).fill(longQuery);
    await page.getByRole('button', { name: /search/i }).click();
    // Should not crash
    await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('handles empty search gracefully', async ({ page }) => {
    // Button should be disabled when empty
    const btn = page.getByRole('button', { name: /search/i });
    await expect(btn).toBeDisabled();
    // Try pressing Enter on empty input
    await page.getByPlaceholder(/search across memories/i).press('Enter');
    // Should still be on same page without errors
    await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('handles concurrent rapid searches', async ({ page }) => {
    const searchInput = page.getByPlaceholder(/search across memories/i);
    // Rapid-fire searches
    await searchInput.fill('auth');
    await page.getByRole('button', { name: /search/i }).click();
    await searchInput.fill('memory');
    await page.getByRole('button', { name: /search/i }).click();
    await searchInput.fill('test');
    await page.getByRole('button', { name: /search/i }).click();
    // Should handle without crashing
    await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('handles network failure gracefully', async ({ page }) => {
    await page.route(/\/v1\/database\/.*\/sql/, async (route: any) => {
      await route.abort('connectionrefused');
    });
    await page.getByPlaceholder(/search across memories/i).fill('auth');
    await page.getByRole('button', { name: /search/i }).click();
    // Should show error state or remain functional
    await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible({ timeout: 5000 });
  });

});
