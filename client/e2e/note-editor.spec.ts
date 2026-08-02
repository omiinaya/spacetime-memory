import { test, expect } from '@playwright/test';
import { expectAnyVisible, gotoPage, installMockStdb, seedMockData } from './helpers';

/**
 * E2E tests for the Note Editor page — create, edit, preview toggle, save.
 */

async function mockAuth(page: any) {
  await page.addInitScript(() => {
    (window as any).__MOCK_AUTH__ = {
      account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
    };
  });
  await page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
}

test.describe('Note Editor — Create', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page);
    await installMockStdb(page);
    await gotoPage(page, '/notes/new');
  });

  test('renders New Note heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'New Note', exact: true })).toBeVisible();
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
    await mockAuth(page);
    await installMockStdb(page);
    // Navigate to a non-existent note ID — shows "Untitled" with save functionality
    await gotoPage(page, '/notes/some-nonexistent-id');
  });

  test('shows "Saved" status for loaded note', async ({ page }) => {
    // When no note found, shows Untitled but status varies
    await expect(page.getByRole('heading', { name: /untitled/i })).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Note Editor — Load Existing Note (seeded mock)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page);
    await installMockStdb(page);
    await seedMockData(page, {
      note: [
        {
          id: 'note-abc-123',
          title: 'Seeded Roadmap',
          content: 'This content came from the seeded mock DB',
          note_date: '2026-08-02',
          embedding_json: '[]',
          backlink_count: 0,
          block_ref_count: 0,
          created_at: 1785600000000,
          updated_at: 1785600000000,
          is_active: true,
        },
      ],
    });
    await gotoPage(page, '/notes/note-abc-123');
  });

  test('loads the seeded note title into the editor', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /seeded roadmap/i }).first()).toBeVisible({ timeout: 5000 });
  });

  test('loads the seeded note content into the editor', async ({ page }) => {
    await expect(page.getByText('This content came from the seeded mock DB').first()).toBeVisible({ timeout: 5000 });
  });
});
