import { test, expect } from '@playwright/test';
import { mockPage, gotoPage, seedMockData } from './helpers';

/**
 * E2E tests for the Metrics Dashboard page.
 *
 * Structural tests (heading/main) run against the empty mock. Seeded tests
 * inject proxy_metrics_snapshot / embedder_metrics_snapshot / alert rows via
 * __MOCK_DATA__ so every stat card, health badge, snapshot table, latency
 * percentile card, and workspace-activity card can be asserted deterministically.
 *
 * NOTE on seed shapes (mirrors src/pages/MetricsDashboardPage.tsx):
 *   - created_at is microseconds (fmtTime divides by 1000).
 *   - latest = rawMetrics[0] (the mock returns rows in seed order, so row 0 is
 *     the "current" snapshot).
 *   - per_model_json / latency_percentiles_json are JSON STRINGS.
 *   - embedder_alert / tantivy_alert drive the System Health badges.
 *   - memory/peer/session/workspace drive the Workspace Activity stat cards.
 * fmtNum: 16000 -> "16.0K"; errorRate = errors/requests*100; avgDuration micros.
 */

const nowUs = () => Date.now() * 1000;

// One proxy snapshot with a healthy mix + latency percentiles + per-model json.
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

// latest = rows[0]. requests_total=16000 -> "16.0K"; errorRate = 320/16000*100 = 2.00%;
// avgDuration = 8000000/200 = 40000us -> "40.0ms".

const embedderRows = [
  {
    id: 'emb-2',
    rss_bytes: 3_000_000_000,
    embedding_count: 50000,
    uptime_seconds: 3600,
    dimension: 1024,
    model_name: 'bge-m3',
    raw_metrics_text: '',
    created_at: nowUs() - 2_000_000,
  },
  {
    id: 'emb-1',
    rss_bytes: 2_500_000_000,
    embedding_count: 90000,
    uptime_seconds: 7200,
    dimension: 1024,
    model_name: 'bge-m3',
    raw_metrics_text: '',
    created_at: nowUs(),
  },
];

const embAlert = {
  id: 'ea-1',
  severity: 0,
  message: 'Embedder reachable',
  consecutive_failures: 0,
  total_calls: 500,
  total_errors: 2,
  error_rate_pct: 0.4,
  degraded: false,
  recovery: false,
  reachable: true,
  embedder_url: 'http://localhost:9090',
  created_at: nowUs(),
};

const tanAlert = {
  id: 'ta-1',
  severity: 0,
  message: 'Tantivy healthy',
  consecutive_failures: 0,
  total_checks: 100,
  total_failures: 1,
  error_rate_pct: 1.0,
  degraded: false,
  recovery: false,
  reachable: true,
  tantivy_url: 'http://localhost:8080',
  created_at: nowUs(),
};

test.describe('Metrics Dashboard Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await gotoPage(page, '/metrics');
  });

  test('renders heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Metrics Dashboard', exact: true })).toBeVisible({ timeout: 8000 });
  });

  test('main content is reachable', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Metrics Dashboard — Seeded Data', () => {
  test.beforeEach(async ({ page }) => {
    await mockPage(page);
    await seedMockData(page, {
      proxy_metrics_snapshot: proxyRows,
      embedder_metrics_snapshot: embedderRows,
      embedder_alert: [embAlert],
      tantivy_alert: [tanAlert],
      memory: [
        { id: 'm1', content: 'seeded', summary: 'Memo', peerId: 'p1', createdAt: nowUs(), isActive: true },
      ],
      peer: [{ id: 'p1', name: 'peer-one' }],
      session: [{ id: 's1', name: 'Sess', createdAt: nowUs() }],
      workspace: [{ id: 'w1', name: 'Main' }],
    });
    await gotoPage(page, '/metrics');
  });

  test('shows proxy throughput stat cards from seeded snapshot', async ({ page }) => {
    // latest = rows[0]: requests_total=16000 -> "16.0K"
    await expect(page.getByText('Total Requests').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('16.0K', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    // Total Tokens = 220000 -> "220.0K"
    await expect(page.getByText('220.0K', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    // Error Rate card: 320/16000*100 = 2.00%
    await expect(page.getByText('2.00%', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    // Avg Duration = 8000000/200 = 40000us -> "40.0ms"
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

  test('shows embedding stats from seeded embedder snapshot', async ({ page }) => {
    // latestEmb = rows[0]: embedding_count=50000 -> "50.0K"; rss=3e9 -> "2.8GiB"; uptime=3600s -> "1.0h"; dim=1024
    await expect(page.getByText('Total Embeddings').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('50.0K', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('RSS Memory').first()).toBeVisible();
    await expect(page.getByText('Dimension').first()).toBeVisible();
    await expect(page.getByText('1024', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('bge-m3', { exact: true }).first()).toBeVisible();
  });

  test('shows workspace activity stat cards from seeded tables', async ({ page }) => {
    // memory=1 active, peer=1, workspace=1
    await expect(page.getByText('Active Workspaces').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Total Memories').first()).toBeVisible();
    await expect(page.getByText('1', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Active Peers').first()).toBeVisible();
  });

  test('shows system health badges as healthy', async ({ page }) => {
    await expect(page.getByText('Embedder Service').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Online', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Tantivy / Index Service').first()).toBeVisible();
  });

  test('shows per-model breakdown', async ({ page }) => {
    await expect(page.getByText('Per-Model Request Breakdown').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('openai|gpt-4o', { exact: true }).first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('anthropic|claude-3', { exact: true }).first()).toBeVisible();
  });
});