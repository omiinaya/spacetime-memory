import { test, expect } from '@playwright/test';
import { mockPage, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Proxy Metrics page.
 *
 * Structural tests (heading/main) run against the empty mock. Seeded tests
 * inject proxy_metrics_snapshot rows via __MOCK_DATA__ so every overview
 * stat card, latency percentile card, trend chart, per-model breakdown, and
 * the recent snapshots table can be asserted deterministically.
 *
 * Seed shapes mirror src/pages/ProxyMetricsDashboard.tsx:
 *   - latest = metrics[0]; errorRate = errors/requests*100; avgDuration micros.
 *   - latency_percentiles_json & per_model_json are JSON STRINGS.
 *   - per-model breakdown uses parsePerModel -> label, count, pct.
 */

const nowUs = () => Date.now() * 1000;

const proxyRows = [
  {
    id: 'proxy-1',
    requests_total: 16000,
    tokens_total: 220000,
    errors_total: 320,
    duration_sum_micros: 8000000,
    duration_count: 200,
    per_model_json: JSON.stringify({ 'openai|gpt-4o': 60, 'anthropic|claude-3': 40 }),
    latency_percentiles_json: JSON.stringify({
      overall: { p50: 0.06, p95: 0.22, p99: 0.42, mean: 0.13, samples: 250 },
      per_model: {},
    }),
    raw_metrics_text: '',
    created_at: nowUs(),
  },
  {
    id: 'pm-2',
    requests_total: 9000,
    tokens_total: 120000,
    errors_total: 180,
    duration_sum_micros: 4500000,
    duration_count: 90,
    per_model_json: JSON.stringify({ 'openai|gpt-4o': 60, 'anthropic|claude-3': 40 }),
    latency_percentiles_json: JSON.stringify({
      overall: { p50: 0.05, p95: 0.2, p99: 0.4, mean: 0.12, samples: 137 },
      per_model: {},
    }),
    raw_metrics_text: '',
    created_at: nowUs() - 2_000_000,
  },
];

test.describe('Proxy Metrics Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/proxy-metrics');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Proxy Metrics', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Proxy Metrics — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      proxy_metrics_snapshot: proxyRows,
    });
    await gotoPage(page, '/proxy-metrics');
  });

  test('shows overview stat cards from seeded snapshot', async ({ page }) => {
    // Snapshots = 2; latest = rows[0]: requests=16000 -> "16.0K"; tokens=220000 -> "220.0K"
    await expect(page.getByText('Snapshots').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('2', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Total Requests').first()).toBeVisible();
    await expect(page.getByText('16.0K', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('220.0K', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    // Error Rate = 320/16000*100 = 2.00%; Avg Duration = 8000000/200 = 40000us -> "40.0ms"
    await expect(page.getByText('2.00%', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('40.0ms', { exact: true }).first()).toBeVisible({ timeout: 3000 });
  });

  test('shows latency percentile cards', async ({ page }) => {
    // overall from rows[0]: p50=0.06->"60.0ms", p95=0.22->"220.0ms", p99=0.42->"420.0ms", mean=0.13->"130.0ms"
    await expect(page.getByText('P50 Latency').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('60.0ms', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('P95 Latency').first()).toBeVisible();
    await expect(page.getByText('220.0ms', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('P99 Latency').first()).toBeVisible();
    await expect(page.getByText('420.0ms', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Mean Latency').first()).toBeVisible();
  });

  test('shows trend chart section', async ({ page }) => {
    await expect(page.getByText('Trends', { exact: false }).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Requests', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Tokens', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Errors', { exact: true }).first()).toBeVisible();
  });

  test('shows per-model breakdown', async ({ page }) => {
    await expect(page.getByText('Per-Model Breakdown').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('openai|gpt-4o', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('anthropic|claude-3', { exact: true }).first()).toBeVisible();
    // 60% of 100 requests = 60.0%
    await expect(page.getByText('60.0%', { exact: true }).first()).toBeVisible();
  });

  test('shows recent snapshots table rows', async ({ page }) => {
    await expect(page.getByText('Recent Snapshots', { exact: true }).first()).toBeVisible({ timeout: 8000 });
    // The table lists both seeded snapshots
    const table = page.locator('table');
    await expect(table).toBeVisible({ timeout: 3000 });
    await expect(table.locator('tbody tr')).toHaveCount(2, { timeout: 3000 });
    // Row values: requests 16,000 -> "16.0K"; tokens 220,000 -> "220.0K"
    await expect(table.locator('tbody').getByText('16.0K', { exact: true }).first()).toBeVisible();
  });
});