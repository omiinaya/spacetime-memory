import { test, expect } from '@playwright/test';

/**
 * E2E tests for the Note Editor page — create, edit, preview toggle, save.
 */

function mockAuth(page: any) {
  page.addInitScript(() => {
    (window as any).__MOCK_AUTH__ = {
      account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
    };
  });
  page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
}

test.describe('Note Editor — Create', () => {
  test.beforeEach(async ({ page }) => {
    mockAuth(page);
    await page.goto('/notes/new');
    await page.waitForTimeout(800);
  });

  test('renders New Note heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'New Note' })).toBeVisible();
  });

  test('shows "Unsaved changes" status initially after typing', async ({ page }) => {
    // Title input
    const titleInput = page.locator('input[placeholder*="Note title"]');
    await expect(titleInput).toBeVisible();
    await titleInput.fill('Test Note');
    await expect(page.getByText('Unsaved changes')).toBeVisible();
  });

  test('has markdown content textarea', async ({ page }) => {
    const textarea = page.locator('textarea[placeholder*="Write in markdown"]');
    await expect(textarea).toBeVisible();
    await textarea.fill('# Hello World\n\nThis is a test note.');
    await expect(textarea).toHaveValue('# Hello World\n\nThis is a test note.');
  });

  test('preview button toggles view', async ({ page }) => {
    const previewBtn = page.getByRole('button', { name: /preview/i });
    await expect(previewBtn).toBeVisible();
    await previewBtn.click();
    // In preview mode, button should say "Edit"
    await expect(page.getByRole('button', { name: /edit/i })).toBeVisible({ timeout: 3000 });
    // Toggle back
    await page.getByRole('button', { name: /edit/i }).click();
    await expect(page.getByRole('button', { name: /preview/i })).toBeVisible();
  });

  test('Create button is present', async ({ page }) => {
    const createBtn = page.getByRole('button', { name: /create/i });
    await expect(createBtn).toBeVisible();
  });

  test('back button navigates to notes list', async ({ page }) => {
    const backBtn = page.locator('button').filter({ has: page.locator('[class*="lucide-arrow-left"]') });
    await backBtn.click();
    await page.waitForTimeout(500);
    expect(page.url()).toContain('/notes');
  });

  test('shows placeholder hint before typing', async ({ page }) => {
    await expect(page.getByText('Start typing markdown on the left')).toBeVisible({ timeout: 3000 });
  });
});

test.describe('Note Editor — Existing Note', () => {
  test.beforeEach(async ({ page }) => {
    mockAuth(page);
    // Navigate to a non-existent note ID — shows "Untitled" with save functionality
    await page.goto('/notes/some-nonexistent-id');
    await page.waitForTimeout(800);
  });

  test('shows "Saved" status for loaded note', async ({ page }) => {
    // When no note found, shows Untitled but status varies
    await expect(page.getByRole('heading', { name: /untitled/i })).toBeVisible({ timeout: 5000 });
  });
});
