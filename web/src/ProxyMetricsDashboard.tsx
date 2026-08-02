import { useCallback, useEffect, useState } from 'react'
import { stdbSql, sortDesc } from './lib/stdb'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ProxyMetric {
  id: string
  requests_total: number
  tokens_total: number
  errors_total: number
  duration_sum_micros: number
  duration_count: number
  per_model_json: string
  latency_percentiles_json: string
  raw_metrics_text: string
  created_at: number
}

type FetchStatus = 'idle' | 'loading' | 'success' | 'error'

interface LatencyPercentiles {
  overall: { p50: number; p95: number; p99: number; mean: number; samples: number }
  per_model: Record<string, { p50?: number; p95?: number; p99?: number; mean?: number; samples?: number }>
}

interface ModelBreakdown {
  label: string   // "provider|model"
  count: number
  pct: number
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString()
}

function fmtMicros(us: number): string {
  if (us >= 1_000_000) return (us / 1_000_000).toFixed(2) + 's'
  if (us >= 1_000) return (us / 1_000).toFixed(1) + 'ms'
  return us.toFixed(0) + 'µs'
}

function fmtTime(ms: number): string {
  const d = new Date(ms / 1000)
  return d.toLocaleString()
}

function parseLatencyPercentiles(json: string): LatencyPercentiles | null {
  try {
    return JSON.parse(json)
  } catch {
    return null
  }
}

function fmtSeconds(s: number): string {
  if (s >= 1) return s.toFixed(2) + 's'
  if (s >= 0.001) return (s * 1000).toFixed(1) + 'ms'
  if (s > 0) return (s * 1000).toFixed(0) + 'µs'
  return '—'
}

function parsePerModel(json: string): ModelBreakdown[] {
  try {
    const raw: Record<string, number> = JSON.parse(json)
    const total = Object.values(raw).reduce((a, b) => a + b, 0)
    if (total === 0) return []
    return Object.entries(raw)
      .map(([label, count]) => ({ label, count, pct: (count / total) * 100 }))
      .sort((a, b) => b.count - a.count)
  } catch {
    return []
  }
}

/* ------------------------------------------------------------------ */
/*  Mini bar chart (pure div)                                          */
/* ------------------------------------------------------------------ */

function MiniBar({ data, labelKey, valueKey, color }: {
  data: ProxyMetric[]
  labelKey: 'requests_total' | 'tokens_total' | 'errors_total'
  valueKey: 'requests_total' | 'tokens_total' | 'errors_total'
  color: string
}) {
  const max = Math.max(...data.map(d => d[valueKey]), 1)
  return (
    <div className="space-y-1">
      <div className="text-xs text-neutral-400 uppercase tracking-wide">
        {labelKey === 'requests_total' ? 'Requests' : labelKey === 'tokens_total' ? 'Tokens' : 'Errors'}
      </div>
      <div className="flex items-end gap-0.5 h-24">
        {data.slice(-30).map(d => {
          const h = (d[valueKey] / max) * 100
          return (
            <div
              key={d.id}
              className="flex-1 rounded-t relative group"
              style={{ height: `${Math.max(h, 1)}%`, backgroundColor: color }}
              title={`${fmtTime(d.created_at)}: ${fmtNum(d[valueKey])}`}
            />
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Stat Card                                                          */
/* ------------------------------------------------------------------ */

function StatCard({ label, value, sub, color }: {
  label: string
  value: string
  sub?: string
  color?: string
}) {
  return (
    <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex flex-col gap-1">
      <span className="text-xs font-medium text-neutral-400 uppercase tracking-wider">{label}</span>
      <span className={`text-2xl font-bold ${color || 'text-white'}`}>{value}</span>
      {sub && <span className="text-xs text-neutral-500">{sub}</span>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function ProxyMetricsDashboard() {
  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState('3001')
  const [database, setDatabase] = useState('spacetime-memory-v2')
  const [metrics, setMetrics] = useState<ProxyMetric[]>([])
  const [status, setStatus] = useState<FetchStatus>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const fetchMetrics = useCallback(async (h: string, p: string, db: string) => {
    setStatus('loading')
    setErrorMsg('')
    try {
      const rows = await stdbSql({ host: h, port: p, database: db }, 'SELECT * FROM proxy_metrics_snapshot LIMIT 100')
      setMetrics(sortDesc(rows, 'created_at'))
      setStatus('success')
    } catch (err: any) {
      setStatus('error')
      setErrorMsg(err?.message || 'Failed to fetch metrics')
    }
  }, [])

  useEffect(() => {
    fetchMetrics(host, port, database)
  }, [])

  function handleRefresh() {
    fetchMetrics(host, port, database)
  }

  /* Compute derived values */
  const snapshots = metrics.slice().reverse()          // chronological for charts
  const latest = metrics[0]
  const snapCount = metrics.length

  let totalRequests = 0
  let totalTokens = 0
  let totalErrors = 0
  let totalDurationMicros = 0
  let totalDurationCount = 0
  let perModelAgg: Record<string, number> = {}
  let latencyData: LatencyPercentiles | null = null

  if (latest) {
    // Use the latest snapshot as current state (cumulative counters)
    totalRequests = latest.requests_total
    totalTokens = latest.tokens_total
    totalErrors = latest.errors_total
    totalDurationMicros = latest.duration_sum_micros
    totalDurationCount = latest.duration_count
    try {
      perModelAgg = JSON.parse(latest.per_model_json)
    } catch { /* ignore */ }
    latencyData = parseLatencyPercentiles(latest.latency_percentiles_json)
  }

  const avgDuration = totalDurationCount > 0
    ? totalDurationMicros / totalDurationCount
    : 0

  const errorRate = totalRequests > 0
    ? ((totalErrors / totalRequests) * 100)
    : 0

  const perModel: ModelBreakdown[] = Object.entries(perModelAgg)
    .map(([label, count]) => ({ label, count, pct: (count / (totalRequests || 1)) * 100 }))
    .sort((a, b) => b.count - a.count)

  // Diff-based rates (between first and last snapshot for trend)
  let reqRate = 0
  let tokRate = 0
  if (snapshots.length >= 2) {
    const first = snapshots[0]
    const last = snapshots[snapshots.length - 1]
    const timeSpan = Math.max((last.created_at - first.created_at) / 1000, 1) // seconds
    reqRate = (last.requests_total - first.requests_total) / timeSpan
    tokRate = (last.tokens_total - first.tokens_total) / timeSpan
  }

  /* Per-model color palette */
  const modelColors = [
    'bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-violet-500',
    'bg-rose-500', 'bg-cyan-500', 'bg-lime-500', 'bg-pink-500',
    'bg-orange-500', 'bg-teal-500',
  ]

  return (
    <div className="space-y-6">

      {/* Connection config bar */}
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
        <div className="flex items-end gap-3 flex-wrap">
          <div className="flex-1 min-w-[120px]">
            <label className="block text-xs font-medium text-neutral-400 mb-1">Host</label>
            <input type="text" value={host}
              onChange={e => { setHost(e.target.value); setStatus('idle') }}
              className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div className="w-20">
            <label className="block text-xs font-medium text-neutral-400 mb-1">Port</label>
            <input type="text" value={port}
              onChange={e => { setPort(e.target.value); setStatus('idle') }}
              className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div className="flex-1 min-w-[150px]">
            <label className="block text-xs font-medium text-neutral-400 mb-1">Database</label>
            <input type="text" value={database}
              onChange={e => { setDatabase(e.target.value); setStatus('idle') }}
              className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <button onClick={() => fetchMetrics(host, port, database)}
            disabled={status === 'loading'}
            className="bg-blue-600 hover:bg-blue-500 disabled:bg-neutral-700 disabled:text-neutral-500 text-white font-medium rounded-lg px-4 py-2 text-sm transition-colors whitespace-nowrap"
          >
            {status === 'loading' ? 'Loading…' : 'Fetch'}
          </button>
        </div>
      </div>

      {/* Status */}
      {status === 'loading' && (
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 text-neutral-300 text-sm flex items-center gap-2">
          <span className="animate-spin inline-block w-4 h-4 border-2 border-neutral-500 border-t-blue-400 rounded-full" />
          Loading proxy metrics…
        </div>
      )}

      {status === 'error' && (
        <div className="bg-red-950/50 border border-red-800 rounded-xl p-4 text-red-300 text-sm flex items-center gap-2">
          <span>✗</span>
          <span>{errorMsg || 'Failed to load proxy metrics. Check connection settings above.'}</span>
        </div>
      )}

      {status === 'success' && metrics.length === 0 && (
        <div className="bg-amber-950/50 border border-amber-800 rounded-xl p-4 text-amber-300 text-sm">
          No proxy metrics found. Make sure the proxy is running and the cron scraper has pushed data.
        </div>
      )}

      {/* Stat cards */}
      {status === 'success' && metrics.length > 0 && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <StatCard label="Snapshots" value={fmtNum(snapCount)} color="text-white" />
            <StatCard label="Total Requests" value={fmtNum(totalRequests)}
              sub={reqRate > 0 ? `~${fmtNum(Math.round(reqRate))}/s` : undefined} color="text-blue-400" />
            <StatCard label="Total Tokens" value={fmtNum(totalTokens)}
              sub={tokRate > 0 ? `~${fmtNum(Math.round(tokRate))}/s` : undefined} color="text-emerald-400" />
            <StatCard label="Error Rate" value={`${errorRate.toFixed(2)}%`}
              sub={`${fmtNum(totalErrors)} errors`}
              color={errorRate > 5 ? 'text-red-400' : errorRate > 1 ? 'text-amber-400' : 'text-emerald-400'} />
            <StatCard label="Avg Duration" value={fmtMicros(Math.round(avgDuration))}
              sub={`from ${fmtNum(totalDurationCount)} samples`} color="text-violet-400" />
          </div>

          {/* Latency Percentile Cards */}
          {latencyData && latencyData.overall && latencyData.overall.samples > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="P50 Latency" value={fmtSeconds(latencyData.overall.p50)}
                sub={`${fmtNum(latencyData.overall.samples)} samples`} color="text-cyan-400" />
              <StatCard label="P95 Latency" value={fmtSeconds(latencyData.overall.p95)}
                sub="95th percentile" color="text-amber-400" />
              <StatCard label="P99 Latency" value={fmtSeconds(latencyData.overall.p99)}
                sub="99th percentile" color="text-rose-400" />
              <StatCard label="Mean Latency" value={fmtSeconds(latencyData.overall.mean)}
                sub="weighted avg" color="text-lime-400" />
            </div>
          )}

          {/* Trend charts */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-5">
            <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">Trends (last {Math.min(snapshots.length, 30)} snapshots)</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <MiniBar data={snapshots} labelKey="requests_total" valueKey="requests_total" color="#3b82f6" />
              <MiniBar data={snapshots} labelKey="tokens_total" valueKey="tokens_total" color="#10b981" />
              <MiniBar data={snapshots} labelKey="errors_total" valueKey="errors_total" color="#ef4444" />
            </div>
          </div>

          {/* Latency Percentile Trends */}
          {snapshots.some(s => {
            const p = parseLatencyPercentiles(s.latency_percentiles_json)
            return p && p.overall && p.overall.samples > 0
          }) && (
            <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-4">
              <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">Latency Percentile Trends</h3>
              <div className="space-y-3">
                {(['p50', 'p95', 'p99'] as const).map(pct => {
                  const vals = snapshots.map(s => {
                    const p = parseLatencyPercentiles(s.latency_percentiles_json)
                    return p?.overall?.[pct] ?? 0
                  })
                  const max = Math.max(...vals, 0.001)
                  if (max === 0) return null
                  return (
                    <div key={pct}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-neutral-400 font-medium uppercase">{pct}</span>
                        <span className="text-neutral-300">{fmtSeconds(vals[vals.length - 1])}</span>
                      </div>
                      <div className="flex items-end gap-0.5 h-12">
                        {vals.slice(-30).map((v, i) => (
                          <div
                            key={i}
                            className="flex-1 rounded-t"
                            style={{
                              height: `${Math.max((v / max) * 100, 1)}%`,
                              backgroundColor: pct === 'p50' ? '#22d3ee' : pct === 'p95' ? '#fbbf24' : '#fb7185',
                            }}
                            title={`${fmtSeconds(v)}`}
                          />
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Per-model breakdown */}
          {perModel.length > 0 && (
            <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-4">
              <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">Per-Model Breakdown</h3>
              <div className="space-y-2">
                {perModel.map((m, i) => (
                  <div key={m.label} className="flex items-center gap-3">
                    <span className="w-3 h-3 rounded-sm flex-shrink-0 ${modelColors[i % modelColors.length]}" />
                    <span className="text-sm text-neutral-200 flex-1 truncate" title={m.label}>{m.label}</span>
                    <span className="text-xs text-neutral-400 w-16 text-right">{fmtNum(m.count)}</span>
                    <div className="w-24 bg-neutral-800 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${modelColors[i % modelColors.length]}`}
                        style={{ width: `${Math.min(m.pct, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-neutral-500 w-12 text-right">{m.pct.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recent snapshots table */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">Recent Snapshots</h3>
              <button onClick={handleRefresh}
                className="text-xs text-blue-400 hover:text-blue-300 disabled:text-neutral-600"
              >
                ⟳ Refresh
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-neutral-500 border-b border-neutral-800">
                    <th className="text-left py-2 pr-3">Time</th>
                    <th className="text-right px-2">Requests</th>
                    <th className="text-right px-2">Tokens</th>
                    <th className="text-right px-2">Errors</th>
                    <th className="text-right px-2">P50</th>
                    <th className="text-right px-2">P95</th>
                    <th className="text-right px-2">Avg Dur</th>
                    <th className="text-right px-2">Models</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.slice(0, 20).map(m => {
                    const models = parsePerModel(m.per_model_json)
                    const avg = m.duration_count > 0 ? m.duration_sum_micros / m.duration_count : 0
                    const lat = parseLatencyPercentiles(m.latency_percentiles_json)
                    const p50 = lat?.overall?.p50 ?? 0
                    const p95 = lat?.overall?.p95 ?? 0
                    return (
                      <tr key={m.id} className="border-b border-neutral-800/50 hover:bg-neutral-800/30">
                        <td className="py-2 pr-3 text-neutral-300 whitespace-nowrap">{fmtTime(m.created_at)}</td>
                        <td className="text-right px-2 text-neutral-200">{fmtNum(m.requests_total)}</td>
                        <td className="text-right px-2 text-neutral-200">{fmtNum(m.tokens_total)}</td>
                        <td className="text-right px-2 text-red-400">{fmtNum(m.errors_total)}</td>
                        <td className="text-right px-2 text-cyan-400">{p50 > 0 ? fmtSeconds(p50) : '—'}</td>
                        <td className="text-right px-2 text-amber-400">{p95 > 0 ? fmtSeconds(p95) : '—'}</td>
                        <td className="text-right px-2 text-neutral-200">{fmtMicros(Math.round(avg))}</td>
                        <td className="text-right px-2 text-neutral-400">{models.length}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
