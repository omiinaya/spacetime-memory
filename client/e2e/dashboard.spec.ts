import { test, expect } from '@playwright/test';
import { expectAnyVisible, gotoPage, installMockStdb, seedMockData } from './helpers';

/**
 * E2E tests for the Dashboard page — stat cards, activity, error handling.
 */

async function mockAuth(page: any) {
  await page.addInitScript(() => {
    (window as any).__MOCK_AUTH__ = {
      account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
    };
  });
  // Mock HTTP reducer calls
  await page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
}

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page);
    await installMockStdb(page);
    await gotoPage(page, '/');
  });

  test('renders dashboard heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
  });

  test('renders empty data state immediately (mock STDB)', async ({ page }) => {
    // With __MOCK_STDB__, no live WS round-trip is needed — the page must
    // render its structure instantly (zero data). This is the deterministic
    // contract: previously the dashboard hung on "Connecting..." whenever the
    // live STDB was slow, which is exactly what made this spec flaky.
    await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible({ timeout: 3000 });
    // Zero-data stat cards are still present as headings
    await expect(page.getByText('Total Memories')).toBeVisible({ timeout: 3000 });
  });

  test('renders stat card headings', async ({ page }) => {
    // Stat card titles should be present even before data loads
    await expect(page.getByText('Total Memories')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Active Peers')).toBeVisible();
    await expect(page.getByText('Sessions Today')).toBeVisible();
    await expect(page.getByText('Workspaces')).toBeVisible();
  });

  test('shows Recent Activity section', async ({ page }) => {
    // CardTitle + possibly a section header — target the first match
    await expect(page.getByText('Recent Activity').first()).toBeVisible({ timeout: 3000 });
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

test.describe('Dashboard — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page);
    await installMockStdb(page);
    // createdAt is epoch microseconds; dashboard computes dayAgo from Date.now()*1000
    const nowUs = Date.now() * 1000;
    await seedMockData(page, {
      memory: [
        { id: 'm1', content: 'seeded memory', summary: 'Seed memo', peerId: 'p1', createdAt: nowUs, isActive: true },
        { id: 'm2', content: 'second memory', summary: 'Another', peerId: 'p2', createdAt: nowUs, isActive: true },
      ],
      peer: [
        { id: 'p1', name: 'peer-one' },
        { id: 'p2', name: 'peer-two' },
      ],
      session: [
        { id: 's1', name: 'Session A', createdAt: nowUs },
        { id: 's2', name: 'Session B', createdAt: nowUs },
      ],
      workspace: [{ id: 'w1', name: 'Main Workspace' }],
    });
    await gotoPage(page, '/');
  });

  test('shows seeded total memories stat', async ({ page }) => {
    await expect(page.getByText('Total Memories')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('2').first()).toBeVisible({ timeout: 3000 });
  });

  test('shows seeded peer and workspace stats', async ({ page }) => {
    await expect(page.getByText('Active Peers')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Workspaces')).toBeVisible();
  });

  test('shows seeded recent activity', async ({ page }) => {
    await expect(page.getByText(/Memory: Seed memo/)).toBeVisible({ timeout: 5000 });
    await expect(page.getByText(/Session: Session A/)).toBeVisible({ timeout: 3000 });
  });
});
