import { test, expect } from '@playwright/test';

/**
 * E2E tests for sidebar navigation — verifies all routes are accessible.
 */

function mockAuth(page: any) {
  page.addInitScript(() => {
    (window as any).__MOCK_AUTH__ = {
      account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
    };
  });
  // Mock HTTP reducer calls so clicking New Note etc. doesn't 404
  page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
}

test.describe('Sidebar Navigation', () => {
  test.beforeEach(async ({ page }) => {
    mockAuth(page);
    await page.goto('/');
    // Wait for sidebar to render
    await expect(page.getByText('Spacetime')).toBeVisible({ timeout: 5000 });
  });

  const NAV_LINKS = [
    { href: '/', label: 'Dashboard' },
    { href: '/daily', label: 'Daily Notes' },
    { href: '/notes', label: 'Notes' },
    { href: '/graph/notes', label: 'Note Graph' },
    { href: '/peers', label: 'Peers' },
    { href: '/sessions', label: 'Sessions' },
    { href: '/graph', label: 'Knowledge Graph' },
    { href: '/memories', label: 'Memory Browser' },
    { href: '/documents', label: 'Documents' },
    { href: '/search', label: 'Search' },
    { href: '/query', label: 'Smart Query' },
    { href: '/trust-dashboard', label: 'Trust Dashboard' },
    { href: '/tours', label: 'Tours' },
    { href: '/code-explorer', label: 'Code Explorer' },
    { href: '/trajectories', label: 'Trajectories' },
    { href: '/merge-candidates', label: 'Merge Candidates' },
    { href: '/graph-viz', label: 'Graph Viz' },
    { href: '/block-graph', label: 'Block Graph' },
    { href: '/session-reasoning', label: 'Session Reasoning' },
    { href: '/directory-browser', label: 'Directories' },
    { href: '/settings', label: 'Settings' },
  ];

  for (const { href, label } of NAV_LINKS) {
    test(`sidebar link "${label}" navigates to ${href}`, async ({ page }) => {
      const link = page.getByRole('link', { name: new RegExp(`^${label}$`, 'i') });
      await expect(link).toBeVisible();
      await link.click();
      await page.waitForTimeout(800);
      // Verify the URL changed
      expect(page.url()).toContain(href);
    });
  }

  test('sidebar can collapse and expand', async ({ page }) => {
    const toggleBtn = page.locator('aside button');
    await expect(toggleBtn).toBeVisible();
    // Collapse
    await toggleBtn.click();
    await page.waitForTimeout(300);
    // Check sidebar is narrower (collapsed class)
    const aside = page.locator('aside');
    await expect(aside).toHaveAttribute('class', /w-16/);
    // Expand again
    await toggleBtn.click();
    await page.waitForTimeout(300);
    await expect(aside).toHaveAttribute('class', /w-60/);
  });

  test('shows user info in sidebar footer', async ({ page }) => {
    await expect(page.getByText('E2E Test')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('admin')).toBeVisible();
  });

  test('404 page for unknown routes', async ({ page }) => {
    await page.goto('/nonexistent-route');
    await expect(page.getByText('404')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Page not found')).toBeVisible();
  });
});
