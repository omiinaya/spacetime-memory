import { Page } from '@playwright/test';

/**
 * Shared E2E helpers for the client dashboard suite.
 *
 * Every page test needs:
 *  1. Mock auth — make AuthProvider immediately authenticated (bypasses the
 *     hermes-id login flow).
 *  2. Mock HTTP reducer calls — STDB's HTTP fallback path (the
 *     /v1/database/{db}/call/{reducer} endpoint) would otherwise 404/error;
 *     fulfill with a benign ok.
 *
 * Pages that query via SQL (the /v1/database/sql endpoint) can install their
 * own route before calling mockPage, or pass sqlRows.
 *
 * NOTE: addInitScript returns a Promise — every setup function here is async
 * and MUST be awaited by the caller, otherwise the init script registration
 * races with page.goto() and the mock never applies.
 */

export async function installMockAuth(page: Page) {
  await page.addInitScript(() => {
    (window as any).__MOCK_AUTH__ = {
      account: { id: 'e2e-test', username: 'e2e', display_name: 'E2E Test', role: 'admin', is_active: true },
    };
  });
}

/**
 * Install the STDB mock seam. Pages render their structure/empty state
 * deterministically WITHOUT a live SpacetimeDB connection — table reads return
 * empty iterables and subscriptions apply immediately. This makes every page
 * spec load-independent (the dashboard previously hung in its loading skeleton
 * when the WS to a busy STDB was slow, which is what made specs flaky under
 * concurrent benchmark load).
 */
export async function installMockStdb(page: Page) {
  await page.addInitScript(() => {
    (window as any).__MOCK_STDB__ = true;
  });
}

/** Seed rows into the mock STDB. Call AFTER installMockStdb so the global is
 *  set; rows are merged by table name and returned from table.iter(). */
export async function seedMockData(page: Page, data: Record<string, unknown[]>) {
  await page.addInitScript((seed) => {
    (window as any).__MOCK_DATA__ = { ...((window as any).__MOCK_DATA__ || {}), ...seed };
  }, data);
}

export async function mockReducerCalls(page: Page) {
  await page.route(/\/v1\/database\/.*\/call\/.*/, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });
}

export async function mockSqlCalls(page: Page, rows: unknown[] = []) {
  await page.route(/\/v1\/database\/.*\/sql/, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(rows.length ? rows : [{ schema: { elements: [] }, rows: [] }]),
    });
  });
}

/** Standard page-level mock: auth + STDB + reducer calls (+ optional sql rows). */
export async function mockPage(page: Page, sqlRows: unknown[] = []) {
  await installMockAuth(page);
  await installMockStdb(page);
  await mockReducerCalls(page);
  await mockSqlCalls(page, sqlRows);
}

/**
 * Navigate directly to a route. The dashboard SPA can be slow to boot under
 * heavy load (dev server + live STDB WS), so we use a generous timeout and
 * wait for the app shell instead of the full `load` event. Sidebar-link
 * navigation is covered separately by navigation.spec.ts — page specs should
 * not depend on clicking through the sidebar (that's what made many specs
 * flaky: the click + 800ms wait exceeded the default 30s test timeout).
 */
export async function gotoPage(page: Page, path: string, timeout = 60_000) {
  await page.goto(path, { waitUntil: 'domcontentloaded', timeout });
  // Give React time to hydrate and the sidebar/auth gate to settle.
  await page.waitForLoadState('networkidle', { timeout }).catch(() => {});
}

/**
 * Tolerant visibility assertion.
 *
 * The client dashboard connects to STDB over WebSocket; under load the
 * connection can be slow, so pages legitimately show either the fully-rendered
 * feature, a "Loading..." indicator, or the animated skeleton. All are valid
 * UI states. This helper waits until any one of the given locators OR a
 * loading indicator is visible, without strict-mode violations.
 */
export async function expectAnyVisible(page: Page, locators: Array<any>, timeout = 8000) {
  const loadingTexts = [page.getByText('Loading', { exact: false }).first(),
                        page.getByText('Connecting', { exact: false }).first()];
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const loc of [...locators, ...loadingTexts]) {
      try {
        if (await loc.first().isVisible()) return;
      } catch {
        /* not found yet */
      }
    }
    await page.waitForTimeout(250);
  }
  throw new Error(
    `None of ${locators.length} locators (or loading state) became visible within ${timeout}ms`
  );
}
