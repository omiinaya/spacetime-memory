import { test, expect } from '@playwright/test';

/**
 * E2E tests for the AuthPage — the register/login gate shown when no
 * authenticated account exists. This is the one page the rest of the suite
 * bypasses via __MOCK_AUTH__.account, so it gets its own dedicated coverage:
 *   - needs_account status → register form (no account exists yet)
 *   - login status → sign-in form
 *   - client-side validation (required username, min password length,
 *     matching confirmation)
 *   - mode toggle (login ⇄ register) when an account exists
 *   - reducer wiring: register and login HTTP calls carry the right args
 */

const REGISTER_HEADING = /create your account to get started/i;
const LOGIN_HEADING = /sign in to access your memory/i;

async function forceAuthStatus(page: any, status: 'needs_account' | 'login') {
  await page.addInitScript((s: string) => {
    (window as any).__MOCK_AUTH__ = { status: s };
  }, status);
}

/** Intercept reducer HTTP calls, record bodies, fulfill ok. */
async function mockReducersAndCapture(page: any) {
  const calls: Array<{ name: string; args: unknown[] }> = [];
  await page.route(/\/v1\/database\/.*\/call\/(register|login|logout)/, async (route: any) => {
    const url = new URL(route.request().url());
    const name = url.pathname.split('/').pop() || '';
    let args: unknown[] = [];
    try { args = JSON.parse(route.request().postData() || '[]'); } catch { /* noop */ }
    calls.push({ name, args });
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
  return calls;
}

/** Also silence the generic reducer path so nothing else 500s. */
async function mockGenericReducers(page: any) {
  await page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
}

test.describe('AuthPage', () => {
  test('register mode renders when no account exists (needs_account)', async ({ page }) => {
    await forceAuthStatus(page, 'needs_account');
    await mockGenericReducers(page);
    await page.goto('/');

    await expect(page.getByRole('heading', { name: 'Spacetime Memory' })).toBeVisible({ timeout: 8000 });
    await expect(page.getByText(REGISTER_HEADING)).toBeVisible();
    // Register-only fields
    await expect(page.getByLabel('Display Name (optional)')).toBeVisible();
    await expect(page.getByLabel('Confirm Password')).toBeVisible();
    // No login toggle when account creation is mandatory
    await expect(page.getByText(/already have an account/i)).toHaveCount(0);
    // Submit button says Create Account
    await expect(page.getByRole('button', { name: /create account/i })).toBeVisible();
  });

  test('login mode renders when an account exists', async ({ page }) => {
    await forceAuthStatus(page, 'login');
    await mockGenericReducers(page);
    await page.goto('/');

    await expect(page.getByText(LOGIN_HEADING)).toBeVisible({ timeout: 8000 });
    // Login-only: no display name / confirm fields
    await expect(page.getByLabel('Display Name (optional)')).toHaveCount(0);
    await expect(page.getByLabel('Confirm Password')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();
    // Toggle to register is available
    await expect(page.getByRole('button', { name: /^register$/i })).toBeVisible();
  });

  test('empty username shows validation error', async ({ page }) => {
    await forceAuthStatus(page, 'login');
    await mockGenericReducers(page);
    await page.goto('/');

    await expect(page.getByText(LOGIN_HEADING)).toBeVisible({ timeout: 8000 });
    await page.getByLabel('Password').fill('secret1');
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page.getByText('Username is required')).toBeVisible();
  });

  test('password shorter than 6 chars shows validation error', async ({ page }) => {
    await forceAuthStatus(page, 'login');
    await mockGenericReducers(page);
    await page.goto('/');

    await expect(page.getByText(LOGIN_HEADING)).toBeVisible({ timeout: 8000 });
    await page.getByLabel('Username').fill('alice');
    await page.getByLabel('Password').fill('12345');
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page.getByText('Password must be at least 6 characters')).toBeVisible();
  });

  test('mismatched confirmation password blocks registration', async ({ page }) => {
    await forceAuthStatus(page, 'needs_account');
    await mockGenericReducers(page);
    await page.goto('/');

    await expect(page.getByText(REGISTER_HEADING)).toBeVisible({ timeout: 8000 });
    await page.getByLabel('Username').fill('bob');
    await page.getByLabel('Password', { exact: true }).fill('secret1');
    await page.getByLabel('Confirm Password').fill('secret2');
    await page.getByRole('button', { name: /create account/i }).click();
    await expect(page.getByText('Passwords do not match')).toBeVisible();
  });

  test('mode toggle switches between login and register forms', async ({ page }) => {
    await forceAuthStatus(page, 'login');
    await mockGenericReducers(page);
    await page.goto('/');

    await expect(page.getByText(LOGIN_HEADING)).toBeVisible({ timeout: 8000 });
    // Switch to register
    await page.getByRole('button', { name: /^register$/i }).click();
    await expect(page.getByText(REGISTER_HEADING)).toBeVisible();
    await expect(page.getByLabel('Display Name (optional)')).toBeVisible();
    // Switch back to login
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await expect(page.getByText(LOGIN_HEADING)).toBeVisible();
    await expect(page.getByLabel('Display Name (optional)')).toHaveCount(0);
  });

  test('register submits register reducer with username/displayName/password', async ({ page }) => {
    await forceAuthStatus(page, 'needs_account');
    const calls = await mockReducersAndCapture(page);
    await page.goto('/');

    await expect(page.getByText(REGISTER_HEADING)).toBeVisible({ timeout: 8000 });
    await page.getByLabel('Username').fill('carol');
    await page.getByLabel('Display Name (optional)').fill('Carol Dev');
    await page.getByLabel('Password', { exact: true }).fill('hunter22');
    await page.getByLabel('Confirm Password').fill('hunter22');
    await page.getByRole('button', { name: /create account/i }).click();

    // register → then auto-login
    await expect.poll(() => calls.filter(c => c.name === 'register').length).toBe(1);
    const reg = calls.find(c => c.name === 'register');
    expect(reg?.args).toEqual(['carol', 'Carol Dev', 'hunter22']);
    await expect.poll(() => calls.filter(c => c.name === 'login').length).toBe(1);
    const log = calls.find(c => c.name === 'login');
    expect(log?.args).toEqual(['carol', 'hunter22']);
  });

  test('login submits login reducer with username/password', async ({ page }) => {
    await forceAuthStatus(page, 'login');
    const calls = await mockReducersAndCapture(page);
    await page.goto('/');

    await expect(page.getByText(LOGIN_HEADING)).toBeVisible({ timeout: 8000 });
    await page.getByLabel('Username').fill('dave');
    await page.getByLabel('Password').fill('correct1');
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect.poll(() => calls.filter(c => c.name === 'login').length).toBe(1);
    const log = calls.find(c => c.name === 'login');
    expect(log?.args).toEqual(['dave', 'correct1']);
  });
});
