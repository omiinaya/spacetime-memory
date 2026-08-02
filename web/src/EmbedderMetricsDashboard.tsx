import { useState, useEffect, useCallback } from 'react'

/* ------------------------------------------------------------------ */
/*  Types — matches embedder_metrics_collector.py HTTP API             */
/* ------------------------------------------------------------------ */

interface CollectorRecord {
  timestamp: number       // ms epoch
  rss_bytes: number
  embedding_count: number
  uptime_seconds: number
  dimension: number
  model_name: string
}

/** Enriched record with id/created_at derived from timestamp */
interface EmbedderMetric {
  id: string
  rss_bytes: number
  embedding_count: number
  uptime_seconds: number
  dimension: number
  model_name: string
  raw_metrics_text: string
  created_at: number
}

type FetchStatus = 'idle' | 'loading' | 'success' | 'error'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function fmtBytes(b: number): string {
  if (b >= 1_073_741_824) return (b / 1_073_741_824).toFixed(2) + ' GiB'
  if (b >= 1_048_576) return (b / 1_048_576).toFixed(1) + ' MiB'
  if (b >= 1_024) return (b / 1_024).toFixed(0) + ' KiB'
  return b + ' B'
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString()
}

function fmtDuration(sec: number): string {
  if (sec >= 86400) return (sec / 86400).toFixed(1) + 'd'
  if (sec >= 3600) return (sec / 3600).toFixed(1) + 'h'
  if (sec >= 60) return (sec / 60).toFixed(0) + 'm'
  return sec + 's'
}

function fmtTime(ms: number): string {
  const d = new Date(ms)
  return d.toLocaleString()
}

/** Convert collector record → embedder metric shape */
function toMetric(r: CollectorRecord): EmbedderMetric {
  return {
    id: `col_${r.timestamp}`,
    rss_bytes: r.rss_bytes,
    embedding_count: r.embedding_count,
    uptime_seconds: r.uptime_seconds,
    dimension: r.dimension,
    model_name: r.model_name,
    raw_metrics_text: '',
    created_at: r.timestamp,
  }
}

/* ------------------------------------------------------------------ */
/*  Mini bar chart (pure div)                                          */
/* ------------------------------------------------------------------ */

function MiniBar({ data, valueKey, color, label }: {
  data: EmbedderMetric[]
  valueKey: 'rss_bytes' | 'embedding_count' | 'uptime_seconds'
  color: string
  label: string
}) {
  const max = Math.max(...data.map(d => d[valueKey]), 1)
  return (
    <div className="space-y-1">
      <div className="text-xs text-neutral-400 uppercase tracking-wide">{label}</div>
      <div className="flex items-end gap-0.5 h-24">
        {data.slice(-30).map(d => {
          const h = (d[valueKey] / max) * 100
          return (
            <div
              key={d.id}
              className="flex-1 rounded-t relative group"
              style={{ height: `${Math.max(h, 1)}%`, backgroundColor: color }}
              title={`${fmtTime(d.created_at)}: ${valueKey === 'rss_bytes' ? fmtBytes(d[valueKey]) : fmtNum(d[valueKey])}`}
            />
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  SVG Sparkline                                                      */
/* ------------------------------------------------------------------ */

function Sparkline({ data, valueKey, color }: {
  data: EmbedderMetric[]
  valueKey: 'rss_bytes' | 'embedding_count' | 'uptime_seconds'
  color: string
}) {
  if (data.length < 2) return null
  const vals = data.map(d => d[valueKey])
  const max = Math.max(...vals, 1)
  const min = Math.min(...vals, 0)
  const range = max - min || 1
  const w = 240
  const h = 48
  const step = w / (vals.length - 1)
  const pts = vals.map((v, i) => `${i * step},${h - ((v - min) / range) * h}`).join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-12" preserveAspectRatio="none">
      <polyline fill="none" stroke={color} strokeWidth="2" points={pts} />
    </svg>
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

export default function EmbedderMetricsDashboard() {
  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState('9190')
  const [metrics, setMetrics] = useState<EmbedderMetric[]>([])
  const [status, setStatus] = useState<FetchStatus>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const fetchMetrics = useCallback(async (h: string, p: string) => {
    setStatus('loading')
    setErrorMsg('')
    try {
      const res = await fetch(`http://${h}:${p}/records`, {
        signal: AbortSignal.timeout(5000),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`HTTP ${res.status}${text ? ': ' + text.slice(0, 120) : ''}`)
      }
      const data: CollectorRecord[] = await res.json()
      const enriched = (Array.isArray(data) ? data : []).map(toMetric)
      // Sort chronologically (oldest first for rendering)
      enriched.sort((a, b) => a.created_at - b.created_at)
      setMetrics(enriched)
      setStatus('success')
    } catch (err: any) {
      setStatus('error')
      setErrorMsg(err?.message || 'Failed to fetch embedder metrics from collector')
    }
  }, [])

  useEffect(() => {
    fetchMetrics(host, port)
  }, [])

  function handleRefresh() {
    fetchMetrics(host, port)
  }

  /* Compute derived values */
  const snapshots = metrics  // already chronological
  const latest = metrics[metrics.length - 1]
  const snapCount = metrics.length

  let latestRss = 0
  let latestEmbeddings = 0
  let latestUptime = 0
  let latestDim = 0
  let latestModel = ''

  if (latest) {
    latestRss = latest.rss_bytes
    latestEmbeddings = latest.embedding_count
    latestUptime = latest.uptime_seconds
    latestDim = latest.dimension
    latestModel = latest.model_name
  }

  // Diff-based rates
  let rssDelta = 0
  let embedRate = 0
  if (snapshots.length >= 2) {
    const first = snapshots[0]
    const last = snapshots[snapshots.length - 1]
    const timeSpan = Math.max((last.created_at - first.created_at) / 1000, 1)
    rssDelta = last.rss_bytes - first.rss_bytes
    embedRate = timeSpan > 0 ? (last.embedding_count - first.embedding_count) / timeSpan : 0
  }

  return (
    <div className="space-y-6">

      {/* Connection config bar */}
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
        <div className="flex items-end gap-3 flex-wrap">
          <div className="flex-1 min-w-[120px]">
            <label className="block text-xs font-medium text-neutral-400 mb-1">Collector Host</label>
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
          <button onClick={() => fetchMetrics(host, port)}
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
          Loading embedder metrics from collector…
        </div>
      )}

      {status === 'error' && (
        <div className="bg-red-950/50 border border-red-800 rounded-xl p-4 text-red-300 text-sm flex items-center gap-2">
          <span>✗</span>
          <span>{errorMsg || 'Failed to load embedder metrics. Is the collector service running on port 9190?'}</span>
        </div>
      )}

      {status === 'success' && metrics.length === 0 && (
        <div className="bg-amber-950/50 border border-amber-800 rounded-xl p-4 text-amber-300 text-sm">
          No embedder metrics found. Ensure the embedder sidecar is running and the collector
          cron has pushed data via <code className="text-amber-200">embedder_metrics_collector.py collect</code>.
        </div>
      )}

      {/* Stat cards */}
      {status === 'success' && metrics.length > 0 && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <StatCard label="Snapshots" value={fmtNum(snapCount)} color="text-white" />
            <StatCard label="RSS Memory" value={fmtBytes(latestRss)}
              sub={rssDelta !== 0 ? `${rssDelta > 0 ? '+' : ''}${fmtBytes(Math.abs(rssDelta))} over window` : undefined}
              color={latestRss > 2_684_354_560 ? 'text-red-400' : latestRss > 1_073_741_824 ? 'text-amber-400' : 'text-emerald-400'} />
            <StatCard label="Embeddings" value={fmtNum(latestEmbeddings)}
              sub={embedRate > 0 ? `~${fmtNum(Math.round(embedRate))}/s` : undefined} color="text-blue-400" />
            <StatCard label="Uptime" value={fmtDuration(latestUptime)} color="text-violet-400" />
            <StatCard label="Model" value={latestModel || 'N/A'}
              sub={`${latestDim}d`} color="text-cyan-400" />
          </div>

          {/* Trend charts */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-5">
            <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">Memory Trends (last {Math.min(snapshots.length, 30)} snapshots)</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <MiniBar data={snapshots} valueKey="rss_bytes" label="RSS Memory" color="#ef4444" />
              <MiniBar data={snapshots} valueKey="embedding_count" label="Embeddings" color="#3b82f6" />
              <MiniBar data={snapshots} valueKey="uptime_seconds" label="Uptime" color="#10b981" />
            </div>
          </div>

          {/* Sparklines */}
          {snapshots.length >= 2 && (
            <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-4">
              <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">Sparklines</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <div className="text-xs text-neutral-400 mb-1">RSS Memory</div>
                  <Sparkline data={snapshots} valueKey="rss_bytes" color="#ef4444"  />
                </div>
                <div>
                  <div className="text-xs text-neutral-400 mb-1">Embeddings</div>
                  <Sparkline data={snapshots} valueKey="embedding_count" color="#3b82f6"  />
                </div>
                <div>
                  <div className="text-xs text-neutral-400 mb-1">Uptime</div>
                  <Sparkline data={snapshots} valueKey="uptime_seconds" color="#10b981"  />
                </div>
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
                    <th className="text-right px-2">RSS</th>
                    <th className="text-right px-2">Embeddings</th>
                    <th className="text-right px-2">Uptime</th>
                    <th className="text-right px-2">Dim</th>
                    <th className="text-right px-2">Model</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.slice(-20).reverse().map(m => (
                    <tr key={m.id} className="border-b border-neutral-800/50 hover:bg-neutral-800/30">
                      <td className="py-2 pr-3 text-neutral-300 whitespace-nowrap">{fmtTime(m.created_at)}</td>
                      <td className="text-right px-2 text-red-400 font-mono">{fmtBytes(m.rss_bytes)}</td>
                      <td className="text-right px-2 text-neutral-200">{fmtNum(m.embedding_count)}</td>
                      <td className="text-right px-2 text-neutral-200">{fmtDuration(m.uptime_seconds)}</td>
                      <td className="text-right px-2 text-neutral-400">{m.dimension}d</td>
                      <td className="text-right px-2 text-neutral-400">{m.model_name || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
