import { test, expect } from '@playwright/test';

/**
 * E2E tests for the Dashboard page — stat cards, activity, error handling.
 */

function mockAuth(page: any) {
  page.addInitScript(() => {
    (window as any).__MOCK_AUTH__ = {
      account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
    };
  });
  // Mock HTTP reducer calls
  page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
}

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    mockAuth(page);
    await page.goto('/');
    await page.waitForTimeout(1000);
  });

  test('renders dashboard heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  });

  test('shows connecting state initially', async ({ page }) => {
    // Before WebSocket connects, "Connecting..." is shown
    await expect(page.getByText('Connecting...')).toBeVisible({ timeout: 3000 });
  });

  test('renders stat card headings', async ({ page }) => {
    // Stat card titles should be present even before data loads
    await expect(page.getByText('Total Memories')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Active Peers')).toBeVisible();
    await expect(page.getByText('Sessions Today')).toBeVisible();
    await expect(page.getByText('Workspaces')).toBeVisible();
  });

  test('renders skeleton loading for stats', async ({ page }) => {
    // Before WebSocket connects, skeletons are shown
    const skeletons = page.locator('[class*="animate-pulse"]');
    // At least one skeleton should exist while loading
    await expect(skeletons.first()).toBeVisible({ timeout: 3000 });
  });

  test('shows Recent Activity section', async ({ page }) => {
    await expect(page.getByText('Recent Activity')).toBeVisible({ timeout: 3000 });
  });

  test('navigates to dashboard on app root', async ({ page }) => {
    // Dashboard is the root route
    expect(page.url()).not.toContain('404');
    expect(page.url()).toBe(page.url().replace(/\/$/, '') + '/');
  });

  test('sidebar Dashboard link is active', async ({ page }) => {
    const dashLink = page.getByRole('link', { name: /^dashboard$/i });
    // Active link has 'bg-accent' class
    await expect(dashLink).toHaveClass(/bg-accent/);
  });
});
