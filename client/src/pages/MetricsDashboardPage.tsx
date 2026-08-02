import { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable, useReactiveDb } from '@/lib/useReactiveDb';
import { AlertsPanel } from './AlertsPanel';
import {
  BarChart3,
  Activity,
  AlertTriangle,
  Gauge,
  Clock,
  Database,
  TrendingUp,
  AlertCircle,
  Layers,
  Zap,
  Cpu,
  HardDrive,
  Building2,
  CheckCircle2,
  XCircle,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types (snake_case from SpacetimeDB)
// ---------------------------------------------------------------------------

interface ProxyMetricsRow {
  id: string;
  requests_total: number;
  tokens_total: number;
  errors_total: number;
  duration_sum_micros: number;
  duration_count: number;
  per_model_json: string;
  latency_percentiles_json: string;
  raw_metrics_text: string;
  created_at: number;
}

interface EmbedderMetricsRow {
  id: string;
  rss_bytes: number;
  embedding_count: number;
  uptime_seconds: number;
  dimension: number;
  model_name: string;
  raw_metrics_text: string;
  created_at: number;
}

interface LatencyPercentiles {
  overall: {
    p50: number;
    p95: number;
    p99: number;
    mean: number;
    samples: number;
  };
  per_model: Record<string, {
    p50?: number;
    p95?: number;
    p99?: number;
    mean?: number;
    samples?: number;
  }>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtNum(n: number): string {
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'B';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}

function fmtBytes(bytes: number): string {
  if (bytes >= 1_073_741_824) return (bytes / 1_073_741_824).toFixed(1) + 'GiB';
  if (bytes >= 1_048_576) return (bytes / 1_048_576).toFixed(1) + 'MiB';
  if (bytes >= 1_024) return (bytes / 1_024).toFixed(1) + 'KiB';
  return bytes + 'B';
}

function fmtMicros(us: number): string {
  if (us >= 1_000_000) return (us / 1_000_000).toFixed(2) + 's';
  if (us >= 1_000) return (us / 1_000).toFixed(1) + 'ms';
  return us.toFixed(0) + 'µs';
}

function fmtSeconds(s: number): string {
  if (s >= 1) return s.toFixed(2) + 's';
  if (s >= 0.001) return (s * 1000).toFixed(1) + 'ms';
  if (s > 0) return (s * 1000).toFixed(0) + 'µs';
  return '—';
}

function fmtTime(ts: number): string {
  const d = new Date(ts / 1000);
  return d.toLocaleString();
}

function fmtDuration(secs: number): string {
  if (secs >= 86400) return (secs / 86400).toFixed(1) + 'd';
  if (secs >= 3600) return (secs / 3600).toFixed(1) + 'h';
  if (secs >= 60) return (secs / 60).toFixed(0) + 'm';
  return secs.toFixed(0) + 's';
}

function parseLatencyPercentiles(json: string): LatencyPercentiles | null {
  try {
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function parsePerModel(json: string): { label: string; count: number; pct: number }[] {
  try {
    const raw: Record<string, number> = JSON.parse(json);
    const total = Object.values(raw).reduce((a, b) => a + b, 0);
    if (total === 0) return [];
    return Object.entries(raw)
      .map(([label, count]) => ({ label, count, pct: (count / total) * 100 }))
      .sort((a, b) => b.count - a.count);
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

function StatCard({
  title,
  value,
  icon: Icon,
  loading,
  color,
  subtitle,
}: {
  title: string;
  value: string;
  icon: React.ElementType;
  loading: boolean;
  color: string;
  subtitle?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className={`h-4 w-4 ${color}`} />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-20" />
        ) : (
          <>
            <div className="text-2xl font-bold">{value}</div>
            {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Mini bar chart (pure div)
// ---------------------------------------------------------------------------

function MiniBar({
  data,
  valueKey,
  color,
  label,
}: {
  data: { id: string; created_at: number; [key: string]: any }[];
  valueKey: string;
  color: string;
  label: string;
}) {
  const max = Math.max(...data.map(d => d[valueKey] as number), 1);
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className="flex items-end gap-0.5 h-24">
        {data.slice(-30).map(d => {
          const h = ((d[valueKey] as number) / max) * 100;
          return (
            <div
              key={d.id}
              className="flex-1 rounded-t relative group"
              style={{ height: `${Math.max(h, 1)}%`, backgroundColor: color }}
              title={`${fmtTime(d.created_at)}: ${fmtNum(d[valueKey] as number)}`}
            />
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Health indicator
// ---------------------------------------------------------------------------

function HealthBadge({ label, healthy, detail }: { label: string; healthy: boolean; detail?: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
      <div className="flex items-center gap-2">
        {healthy ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        ) : (
          <XCircle className="h-4 w-4 text-red-500" />
        )}
        <span className="text-sm font-medium">{label}</span>
      </div>
      {detail && <span className="text-xs text-muted-foreground">{detail}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function MetricsDashboardPage() {
  // Reactive data
  const { ready, stats } = useReactiveDb();
  const { data: rawMetrics, loading: pmLoading, error: pmError } = useTable<ProxyMetricsRow>('proxy_metrics_snapshot');
  const { data: embMetrics, loading: embLoading } = useTable<EmbedderMetricsRow>('embedder_metrics_snapshot');
  const { data: embAlerts } = useTable<any>('embedder_alert');
  const { data: tanAlerts } = useTable<any>('tantivy_alert');

  const loading = pmLoading || embLoading || !ready;
  const error = pmError;

  // Chronological order for charts
  const snapshots = useMemo(() => [...rawMetrics].reverse(), [rawMetrics]);
  const embSnapshots = useMemo(() => [...embMetrics].reverse(), [embMetrics]);

  // Latest values
  const latest = rawMetrics[0];
  const latestEmb = embMetrics[0];

  // Compute derived proxy metrics
  const derived = useMemo(() => {
    let totalRequests = 0;
    let totalTokens = 0;
    let totalErrors = 0;
    let totalDurationMicros = 0;
    let totalDurationCount = 0;
    let latencyData: LatencyPercentiles | null = null;

    if (latest) {
      totalRequests = latest.requests_total;
      totalTokens = latest.tokens_total;
      totalErrors = latest.errors_total;
      totalDurationMicros = latest.duration_sum_micros;
      totalDurationCount = latest.duration_count;
      latencyData = parseLatencyPercentiles(latest.latency_percentiles_json);
    }

    const avgDuration = totalDurationCount > 0
      ? totalDurationMicros / totalDurationCount
      : 0;

    const errorRate = totalRequests > 0
      ? ((totalErrors / totalRequests) * 100)
      : 0;

    // Diff-based rates (first vs last snapshot)
    let reqRate = 0;
    let tokRate = 0;
    if (snapshots.length >= 2) {
      const first = snapshots[0];
      const last = snapshots[snapshots.length - 1];
      const timeSpan = Math.max((last.created_at - first.created_at) / 1_000_000, 1);
      reqRate = (last.requests_total - first.requests_total) / timeSpan;
      tokRate = (last.tokens_total - first.tokens_total) / timeSpan;
    }

    return {
      totalRequests,
      totalTokens,
      totalErrors,
      totalDurationMicros,
      totalDurationCount,
      avgDuration,
      errorRate,
      reqRate,
      tokRate,
      latencyData,
    };
  }, [latest, snapshots]);

  // Compute derived embedder metrics
  const embDerived = useMemo(() => {
    if (!latestEmb) return null;

    let embedRate = 0;
    if (embSnapshots.length >= 2) {
      const first = embSnapshots[0];
      const last = embSnapshots[embSnapshots.length - 1];
      const timeSpan = Math.max((last.created_at - first.created_at) / 1_000_000, 1);
      embedRate = (last.embedding_count - first.embedding_count) / timeSpan;
    }

    return {
      rss_bytes: latestEmb.rss_bytes,
      embedding_count: latestEmb.embedding_count,
      uptime_seconds: latestEmb.uptime_seconds,
      dimension: latestEmb.dimension,
      model_name: latestEmb.model_name,
      embedRate,
    };
  }, [latestEmb, embSnapshots]);

  // Check embedder health from alerts
  const embedderHealthy = useMemo(() => {
    if (!embAlerts || embAlerts.length === 0) return true;
    const latestAlert = embAlerts[0];
    return latestAlert.reachable !== false && !latestAlert.degraded;
  }, [embAlerts]);

  const tantivyHealthy = useMemo(() => {
    if (!tanAlerts || tanAlerts.length === 0) return true;
    const latestAlert = tanAlerts[0];
    return latestAlert.reachable !== false && !latestAlert.degraded;
  }, [tanAlerts]);

  // Workspace count
  const workspaceCount = stats?.totalWorkspaces ?? 0;

  // Has embedder data at all?
  const hasEmbData = embMetrics.length > 0;

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <BarChart3 className="h-7 w-7 text-primary" />
            Metrics Dashboard
          </h1>
          <p className="text-muted-foreground">
            {loading
              ? 'Loading...'
              : `Memory system metrics — ${rawMetrics.length} proxy snapshots, ${embMetrics.length} embedder snapshots`}
          </p>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <Card className="border-red-500/30">
          <CardContent className="flex items-center gap-3 py-6">
            <AlertCircle className="h-5 w-5 text-destructive shrink-0" />
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Loading state */}
      {loading && !error && (
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Card key={i}>
                <CardHeader className="pb-2">
                  <Skeleton className="h-4 w-24" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-8 w-16" />
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader><Skeleton className="h-5 w-40" /></CardHeader>
            <CardContent className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-lg" />
              ))}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && rawMetrics.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <BarChart3 className="h-12 w-12 mb-3 opacity-30" />
            <p className="font-medium text-lg">No metrics data yet</p>
            <p className="text-sm mt-1">
              Make sure the proxy and embedder are running and the cron scrapers have pushed data.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Main content — only when data exists */}
      {!loading && !error && rawMetrics.length > 0 && (
        <>
          {/* 1. Memory Operations Throughput — stat cards */}
          <div>
            <h2 className="text-xl font-semibold tracking-tight mb-3 flex items-center gap-2">
              <Activity className="h-5 w-5 text-muted-foreground" />
              Memory Operations Throughput
            </h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
              <StatCard
                title="Snapshots"
                value={fmtNum(rawMetrics.length)}
                icon={Database}
                loading={false}
                color="text-blue-500"
              />
              <StatCard
                title="Total Requests"
                value={fmtNum(derived.totalRequests)}
                icon={Activity}
                loading={false}
                color="text-blue-500"
                subtitle={derived.reqRate > 0 ? `~${fmtNum(Math.round(derived.reqRate))}/s` : undefined}
              />
              <StatCard
                title="Total Tokens"
                value={fmtNum(derived.totalTokens)}
                icon={Zap}
                loading={false}
                color="text-emerald-500"
                subtitle={derived.tokRate > 0 ? `~${fmtNum(Math.round(derived.tokRate))}/s` : undefined}
              />
              <StatCard
                title="Error Rate"
                value={`${derived.errorRate.toFixed(2)}%`}
                icon={AlertTriangle}
                loading={false}
                color={
                  derived.errorRate > 5
                    ? 'text-red-500'
                    : derived.errorRate > 1
                      ? 'text-amber-500'
                      : 'text-emerald-500'
                }
                subtitle={`${fmtNum(derived.totalErrors)} errors`}
              />
              <StatCard
                title="Avg Duration"
                value={fmtMicros(Math.round(derived.avgDuration))}
                icon={Clock}
                loading={false}
                color="text-violet-500"
                subtitle={derived.totalDurationCount > 0 ? `from ${fmtNum(derived.totalDurationCount)} samples` : undefined}
              />
            </div>
          </div>

          {/* 2. Search Latency Distribution */}
          <div>
            <h2 className="text-xl font-semibold tracking-tight mb-3 flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-muted-foreground" />
              Search Latency Distribution
            </h2>
            {derived.latencyData && derived.latencyData.overall && derived.latencyData.overall.samples > 0 ? (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                <StatCard
                  title="P50 Latency"
                  value={fmtSeconds(derived.latencyData.overall.p50)}
                  icon={TrendingUp}
                  loading={false}
                  color="text-cyan-500"
                  subtitle={`${fmtNum(derived.latencyData.overall.samples)} samples`}
                />
                <StatCard
                  title="P95 Latency"
                  value={fmtSeconds(derived.latencyData.overall.p95)}
                  icon={TrendingUp}
                  loading={false}
                  color="text-amber-500"
                  subtitle="95th percentile"
                />
                <StatCard
                  title="P99 Latency"
                  value={fmtSeconds(derived.latencyData.overall.p99)}
                  icon={TrendingUp}
                  loading={false}
                  color="text-rose-500"
                  subtitle="99th percentile"
                />
                <StatCard
                  title="Mean Latency"
                  value={fmtSeconds(derived.latencyData.overall.mean)}
                  icon={BarChart3}
                  loading={false}
                  color="text-lime-500"
                  subtitle="weighted avg"
                />
              </div>
            ) : (
              <Card>
                <CardContent className="py-6 text-sm text-muted-foreground">
                  <div className="flex items-center gap-2">
                    <Clock className="h-4 w-4" />
                    <span>No latency percentile data available yet.</span>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* 3. Embedding Stats */}
          <div>
            <h2 className="text-xl font-semibold tracking-tight mb-3 flex items-center gap-2">
              <Cpu className="h-5 w-5 text-muted-foreground" />
              Embedding Stats
            </h2>
            {hasEmbData && embDerived ? (
              <>
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                  <StatCard
                    title="Total Embeddings"
                    value={fmtNum(embDerived.embedding_count)}
                    icon={Database}
                    loading={false}
                    color="text-blue-500"
                    subtitle={embDerived.embedRate > 0 ? `~${fmtNum(Math.round(embDerived.embedRate))}/s` : undefined}
                  />
                  <StatCard
                    title="RSS Memory"
                    value={fmtBytes(embDerived.rss_bytes)}
                    icon={HardDrive}
                    loading={false}
                    color="text-purple-500"
                  />
                  <StatCard
                    title="Uptime"
                    value={fmtDuration(embDerived.uptime_seconds)}
                    icon={Clock}
                    loading={false}
                    color="text-emerald-500"
                    subtitle="embedder process"
                  />
                  <StatCard
                    title="Dimension"
                    value={embDerived.dimension.toString()}
                    icon={Layers}
                    loading={false}
                    color="text-cyan-500"
                    subtitle={embDerived.model_name || 'model'}
                  />
                </div>

                {/* Embedder trend chart */}
                {embSnapshots.length >= 2 && (
                  <Card className="mt-4">
                    <CardHeader>
                      <CardTitle className="text-lg flex items-center gap-2">
                        <Activity className="h-4 w-4 text-muted-foreground" />
                        Embedding Growth (last {Math.min(embSnapshots.length, 30)} snapshots)
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        <MiniBar data={embSnapshots} valueKey="embedding_count" label="Embeddings" color="#8b5cf6" />
                        <MiniBar data={embSnapshots} valueKey="rss_bytes" label="RSS Memory" color="#a855f7" />
                        <MiniBar data={embSnapshots} valueKey="uptime_seconds" label="Uptime" color="#22c55e" />
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            ) : (
              <Card>
                <CardContent className="py-6 text-sm text-muted-foreground">
                  <div className="flex items-center gap-2">
                    <Cpu className="h-4 w-4" />
                    <span>No embedder metrics available yet. Ensure the embedder sidecar is running and pushing snapshots.</span>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* 4. Workspace Activity */}
          <div>
            <h2 className="text-xl font-semibold tracking-tight mb-3 flex items-center gap-2">
              <Building2 className="h-5 w-5 text-muted-foreground" />
              Workspace Activity
            </h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              <StatCard
                title="Active Workspaces"
                value={workspaceCount.toLocaleString()}
                icon={Building2}
                loading={!ready}
                color="text-indigo-500"
              />
              <StatCard
                title="Total Memories"
                value={stats ? (stats.totalMemories ?? 0).toLocaleString() : '—'}
                icon={Database}
                loading={!ready}
                color="text-blue-500"
              />
              <StatCard
                title="Active Peers"
                value={stats ? (stats.activePeers ?? 0).toLocaleString() : '—'}
                icon={Activity}
                loading={!ready}
                color="text-green-500"
              />
            </div>
          </div>

          {/* 5. System Health */}
          <div>
            <h2 className="text-xl font-semibold tracking-tight mb-3 flex items-center gap-2">
              <Gauge className="h-5 w-5 text-muted-foreground" />
              System Health
            </h2>
            <div className="grid gap-4 md:grid-cols-2">
              {/* Embedder health */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Cpu className="h-4 w-4 text-muted-foreground" />
                    Embedder Service
                  </CardTitle>
                  <CardDescription>
                    {hasEmbData
                      ? 'Status based on latest alert and snapshot'
                      : 'No data — service may not be running'}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-1">
                    <HealthBadge
                      label="Reachability"
                      healthy={embedderHealthy}
                      detail={embedderHealthy ? 'Online' : 'Unreachable'}
                    />
                    {latestEmb && (
                      <>
                        <HealthBadge
                          label="Memory Usage"
                          healthy={latestEmb.rss_bytes < 4_000_000_000}
                          detail={fmtBytes(latestEmb.rss_bytes)}
                        />
                        <HealthBadge
                          label="Uptime"
                          healthy={latestEmb.uptime_seconds > 0}
                          detail={fmtDuration(latestEmb.uptime_seconds)}
                        />
                        <HealthBadge
                          label="Model"
                          healthy={!!latestEmb.model_name}
                          detail={latestEmb.model_name || 'unknown'}
                        />
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Tantivy health */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <HardDrive className="h-4 w-4 text-muted-foreground" />
                    Tantivy / Index Service
                  </CardTitle>
                  <CardDescription>
                    Based on latest tantivy alert status
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-1">
                    <HealthBadge
                      label="Reachability"
                      healthy={tantivyHealthy}
                      detail={tantivyHealthy ? 'Online' : 'Unreachable'}
                    />
                    {tanAlerts && tanAlerts.length > 0 && (
                      <>
                        <HealthBadge
                          label="Status"
                          healthy={!tanAlerts[0].degraded}
                          detail={tanAlerts[0].degraded ? 'Degraded' : 'Healthy'}
                        />
                        <HealthBadge
                          label="Error Rate"
                          healthy={tanAlerts[0].error_rate_pct < 5}
                          detail={`${tanAlerts[0].error_rate_pct.toFixed(1)}%`}
                        />
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Proxy health card */}
            <Card className="mt-4">
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Gauge className="h-4 w-4 text-muted-foreground" />
                  Proxy Health
                </CardTitle>
                <CardDescription>
                  LLM proxy request success rate and performance
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-1">
                  <HealthBadge
                    label="Request Error Rate"
                    healthy={derived.errorRate < 5}
                    detail={`${derived.errorRate.toFixed(2)}%`}
                  />
                  <HealthBadge
                    label="Data Available"
                    healthy={rawMetrics.length > 0}
                    detail={`${rawMetrics.length} snapshots`}
                  />
                  <HealthBadge
                    label="Requests Served"
                    healthy={derived.totalRequests > 0}
                    detail={fmtNum(derived.totalRequests)}
                  />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 6. Recent Alerts */}
          <div>
            <h2 className="text-xl font-semibold tracking-tight mb-3 flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-muted-foreground" />
              Recent Alerts
            </h2>
            <Card>
              <CardContent className="pt-6">
                <AlertsPanel />
              </CardContent>
            </Card>
          </div>

          {/* 7. Throughput trend charts */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Activity className="h-4 w-4 text-muted-foreground" />
                Throughput Trends (last {Math.min(snapshots.length, 30)} snapshots)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <MiniBar data={snapshots} valueKey="requests_total" label="Requests" color="#3b82f6" />
                <MiniBar data={snapshots} valueKey="tokens_total" label="Tokens" color="#10b981" />
                <MiniBar data={snapshots} valueKey="errors_total" label="Errors" color="#ef4444" />
              </div>
            </CardContent>
          </Card>

          {/* 8. Latency Percentile Trends */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-muted-foreground" />
                Latency Percentile Trends
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {(['p50', 'p95', 'p99'] as const).map(pct => {
                const vals = snapshots.map(s => {
                  const p = parseLatencyPercentiles(s.latency_percentiles_json);
                  return p?.overall?.[pct] ?? 0;
                });
                const max = Math.max(...vals, 0.001);
                if (max === 0) return (
                  <div key={pct} className="text-sm text-muted-foreground">
                    <span className="font-medium uppercase mr-2">{pct}</span>
                    <span>No data</span>
                  </div>
                );
                const color = pct === 'p50' ? '#22d3ee' : pct === 'p95' ? '#fbbf24' : '#fb7185';
                return (
                  <div key={pct}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-muted-foreground font-medium uppercase">{pct}</span>
                      <span>{fmtSeconds(vals[vals.length - 1])}</span>
                    </div>
                    <div className="flex items-end gap-0.5 h-12">
                      {vals.slice(-30).map((v, i) => (
                        <div
                          key={i}
                          className="flex-1 rounded-t"
                          style={{
                            height: `${Math.max((v / max) * 100, 1)}%`,
                            backgroundColor: color,
                          }}
                          title={fmtSeconds(v)}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          {/* 9. Per-model breakdown (from proxy metrics) */}
          {latest && parsePerModel(latest.per_model_json).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Layers className="h-4 w-4 text-muted-foreground" />
                  Per-Model Request Breakdown
                </CardTitle>
                <CardDescription>
                  Request distribution across providers and models
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {parsePerModel(latest.per_model_json).slice(0, 10).map((m, i) => {
                  const modelColors = [
                    'bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-violet-500',
                    'bg-rose-500', 'bg-cyan-500', 'bg-lime-500', 'bg-pink-500',
                    'bg-orange-500', 'bg-teal-500',
                  ];
                  return (
                    <div key={m.label} className="flex items-center gap-3">
                      <span className={`w-3 h-3 rounded-sm flex-shrink-0 ${modelColors[i % modelColors.length]}`} />
                      <span className="text-sm flex-1 truncate" title={m.label}>{m.label}</span>
                      <span className="text-xs text-muted-foreground w-16 text-right">{fmtNum(m.count)}</span>
                      <div className="w-24 bg-muted rounded-full h-2 overflow-hidden">
                        <div
                          className={`h-full rounded-full ${modelColors[i % modelColors.length]}`}
                          style={{ width: `${Math.min(m.pct, 100)}%` }}
                        />
                      </div>
                      <span className="text-xs text-muted-foreground w-12 text-right">{m.pct.toFixed(1)}%</span>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          )}

          {/* 10. Recent snapshots table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Database className="h-4 w-4 text-muted-foreground" />
                Recent Proxy Snapshots
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-muted-foreground border-b">
                      <th className="text-left py-2 pr-3">Time</th>
                      <th className="text-right px-2">Requests</th>
                      <th className="text-right px-2">Tokens</th>
                      <th className="text-right px-2">Errors</th>
                      <th className="text-right px-2">P50</th>
                      <th className="text-right px-2">P95</th>
                      <th className="text-right px-2">Avg Dur</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rawMetrics.slice(0, 20).map(m => {
                      const avg = m.duration_count > 0 ? m.duration_sum_micros / m.duration_count : 0;
                      const lat = parseLatencyPercentiles(m.latency_percentiles_json);
                      const p50 = lat?.overall?.p50 ?? 0;
                      const p95 = lat?.overall?.p95 ?? 0;
                      return (
                        <tr key={m.id} className="border-b border-border/50 hover:bg-accent/30">
                          <td className="py-2 pr-3 whitespace-nowrap">{fmtTime(m.created_at)}</td>
                          <td className="text-right px-2">{fmtNum(m.requests_total)}</td>
                          <td className="text-right px-2">{fmtNum(m.tokens_total)}</td>
                          <td className="text-right px-2 text-red-500">{fmtNum(m.errors_total)}</td>
                          <td className="text-right px-2 text-cyan-500">{p50 > 0 ? fmtSeconds(p50) : '—'}</td>
                          <td className="text-right px-2 text-amber-500">{p95 > 0 ? fmtSeconds(p95) : '—'}</td>
                          <td className="text-right px-2">{fmtMicros(Math.round(avg))}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
