import { test, expect } from '@playwright/test';
import { mockPage, expectAnyVisible, gotoPage } from './helpers';

/**
 * E2E tests for the Skills & Mods page.
 *
 * Covers the two CREATE forms: validation errors (missing fields / bad config
 * JSON) and successful submit (reducer mocked ok → success banner), plus the
 * tab switch between Skills and Mods.
 */

test.describe('Skills & Mods Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/skills-mods');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /skills/i, exact: false })).toBeVisible({ timeout: 8000 });
  });

  test('renders empty state or loading indicator', async ({ page }) => {
    await expectAnyVisible(page, [
      page.getByText(/no .*skill|create|no .* yet/i),
    ]);
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });

  test('create skill shows validation error when fields missing', async ({ page }) => {
    await page.getByRole('button', { name: /create skill/i }).click();
    await expect(page.getByText(/new skill/i, { exact: false }).first()).toBeVisible({ timeout: 8000 });
    // Header "Create Skill" hides when the form opens; submit is exactly "Create"
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText('Name, description, and code are required')).toBeVisible({ timeout: 8000 });
  });

  test('create skill succeeds with fields filled', async ({ page }) => {
    await page.getByRole('button', { name: /create skill/i }).click();
    await page.getByPlaceholder('My Skill').fill('test-skill');
    await page.getByPlaceholder('What this skill does').fill('A test skill');
    await page.getByPlaceholder('Skill code or instructions').fill('code goes here');
    // Reducer mocked ok → the form CLOSES (setShowForm(false) only runs on success)
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText(/new skill/i, { exact: false }).first()).toBeHidden({ timeout: 8000 });
  });

  test('switches to mods tab and validates bad config json', async ({ page }) => {
    await page.getByRole('tab', { name: /mods/i }).click();
    await page.getByRole('button', { name: /install mod/i }).click();
    // Fill name + version (placeholders), overwrite config with invalid JSON
    await page.getByPlaceholder('my-agent-mod').fill('test-mod');
    await page.getByPlaceholder('1.0.0').fill('1.0.0');
    await page.getByPlaceholder('{ "enabled": true, "settings": {} }').fill('not json');
    // Header "Install Mod" hides when form opens; submit is exactly "Install"
    await page.getByRole('button', { name: 'Install', exact: true }).click();
    await expect(page.getByText('Config must be valid JSON')).toBeVisible({ timeout: 8000 });
  });
});