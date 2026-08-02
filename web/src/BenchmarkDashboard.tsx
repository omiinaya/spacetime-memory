import { useState, useEffect } from 'react'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface BenchmarkResult {
  accuracy_primary?: number
  accuracy_overall?: number | null
  correct?: number
  total?: number
  notes?: string
  per_category?: Record<string, { accuracy: number; correct: number; total: number }>
}

interface BeamResult {
  accuracy: number
  passed: number
  total: number
  latency_ms: number
}

interface CompetitivePosition {
  spacetime_memory_v11_pipeline: number
  spacetime_memory_v10_oracle: number
  mem0: number
  graphiti: number
  gbrain: number
  spacetime_memory_v9_pipeline: number
  notes: string
}

interface SummaryData {
  report_name: string
  timestamp: string
  benchmarks: {
    locomo: {
      description: string
      results: Record<string, BenchmarkResult>
    }
    beam: {
      description: string
      results: Record<string, BeamResult>
    }
  }
  competitive_position: CompetitivePosition & { beats_all_competitors: boolean }
  feature_coverage: {
    total_integration_tests: number
    tests_passed: number
    test_zero_failures: boolean
    sdk_modules: number
    sdk_compatibility_layers: Record<string, boolean>
    ui_pages: string
    cli_commands: string
    connectors: string[]
  }
  remaining_gaps: string[]
}

/* ------------------------------------------------------------------ */
/*  Colors                                                             */
/* ------------------------------------------------------------------ */

const COMP_COLORS: Record<string, string> = {
  'spacetime_memory_v11_pipeline': '#22c55e',
  'spacetime_memory_v10_oracle': '#a855f7',
  'spacetime_memory_v9_pipeline': '#3b82f6',
  'mem0': '#f59e0b',
  'graphiti': '#ec4899',
  'gbrain': '#06b6d4',
}

const COMP_LABELS: Record<string, string> = {
  'spacetime_memory_v11_pipeline': 'Spacetime v11',
  'spacetime_memory_v10_oracle': 'Spacetime v10 (oracle)',
  'spacetime_memory_v9_pipeline': 'Spacetime v9',
  'mem0': 'Mem0',
  'graphiti': 'Graphiti',
  'gbrain': 'GBrain',
}

/* ------------------------------------------------------------------ */
/*  Sub-Components                                                     */
/* ------------------------------------------------------------------ */

function Gauge({ value, max, label, color, size = 'md' }: {
  value: number; max: number; label: string; color: string; size?: 'sm' | 'md' | 'lg'
}) {
  // Robust against string values like "RUNNING" in live summary JSONs.
  const num = typeof value === 'number' && isFinite(value) ? value : 0
  const pct = max > 0 ? (num / max) * 100 : 0
  const dim = size === 'sm' ? 48 : size === 'md' ? 64 : 80
  const stroke = dim * 0.08
  const radius = (dim - stroke) / 2
  const circ = 2 * Math.PI * radius
  const offset = circ - (pct / 100) * circ

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={dim} height={dim} className="transform -rotate-90">
        <circle cx={dim / 2} cy={dim / 2} r={radius} fill="none"
          stroke="#27272a" strokeWidth={stroke} />
        <circle cx={dim / 2} cy={dim / 2} r={radius} fill="none"
          stroke={color} strokeWidth={stroke} strokeDasharray={circ}
          strokeDashoffset={offset} strokeLinecap="round" />
      </svg>
      <span className="text-lg font-bold" style={{ color }}>{num.toFixed(1)}%</span>
      <span className="text-xs text-neutral-500 text-center">{label}</span>
    </div>
  )
}

function Bar({ name, value, max, color }: { name: string; value: number; max: number; color: string }) {
  // Robust against non-numeric values (string notes, missing fields).
  const num = typeof value === 'number' && isFinite(value) ? value : 0
  const w = max > 0 ? (num / max) * 100 : 0
  const isWinner = num >= max * 0.99
  return (
    <div className="flex items-center gap-3 group">
      <span className="text-xs text-neutral-400 w-28 text-right shrink-0 truncate">{name}</span>
      <div className="flex-1 bg-neutral-800 rounded-full h-5 relative overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500"
          style={{ width: `${Math.max(w, 1)}%`, backgroundColor: color }} />
      </div>
      <span className={`text-xs font-mono w-14 shrink-0 ${isWinner ? 'text-green-400 font-bold' : 'text-neutral-400'}`}>
        {num.toFixed(1)}%
      </span>
      {isWinner && <span className="text-xs shrink-0">🏆</span>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function BenchmarkDashboard() {
  const [data, setData] = useState<SummaryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'locomo' | 'beam' | 'lmeval'>('locomo')
  const [lmeval, setLmeval] = useState<{ overall: { recall_at_all_5: number; hits: number; total: number }; per_type: Record<string, any> } | null>(null)

  useEffect(() => {
    fetch('/benchmark_results_summary.json')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })

    fetch('/benchmark_results_longmemeval_s.json')
      .then(r => r.json())
      .then(d => setLmeval(d))
      .catch(() => {})
  }, [])

  if (loading) return <div className="text-neutral-400 text-center py-12">Loading benchmark data...</div>
  if (error) return <div className="text-red-400 text-center py-12">Error loading benchmarks: {error}</div>
  if (!data) return <div className="text-neutral-500 text-center py-12">No benchmark data available.</div>

  const locomo = data.benchmarks.locomo
  const beam = data.benchmarks.beam
  const rawComp = data.competitive_position
  const features = data.feature_coverage

  // competitive_position may be a numeric struct (component's canonical shape)
  // OR a human-readable note dict (current summary JSON: note/locomo/longmemeval/beam strings).
  // Normalize: extract any numeric fields for the bars, keep notes for display.
  const comp: Record<string, number> = {}
  let compNote = ''
  if (rawComp && typeof rawComp === 'object') {
    for (const [k, v] of Object.entries(rawComp)) {
      if (k === 'notes' || k === 'note' || k === 'honest_note') {
        compNote = typeof v === 'string' ? v : ''
      } else if (typeof v === 'number' && isFinite(v)) {
        comp[k] = v
      }
    }
  }

  // Latest LoCoMo version
  const latestKey = Object.keys(locomo.results).pop() || ''
  const latest = locomo.results[latestKey]
  const bestPct = Math.max(
    ...Object.entries(comp)
      .filter(([k]) => k.startsWith('spacetime_') || k === 'mem0' || k === 'graphiti' || k === 'gbrain')
      .map(([, v]) => v as number),
    0,
  )

  // Top bar metrics — summary JSON keeps test counts in test_results, not
  // feature_coverage; normalize so the dashboard renders either shape.
  const testRes = (data as any).test_results || {}
  const totalTests = features.total_integration_tests ?? testRes.total ?? 0
  const testsPassed = features.tests_passed ?? testRes.passed ?? 0
  const testPct = totalTests > 0 ? (testsPassed / totalTests) * 100 : 0

  // connectors may be a count (summary JSON) or a list.
  const connectors: string[] = Array.isArray(features.connectors)
    ? features.connectors
    : typeof features.connectors === 'number' && features.connectors > 0
      ? [`${features.connectors} connectors`]
      : []

  // Feature coverage layers may be an array (summary JSON) or Record<string, boolean>.
  const compatLayers: Record<string, boolean> = {}
  if (Array.isArray(features.sdk_compatibility_layers)) {
    for (const l of features.sdk_compatibility_layers) compatLayers[String(l)] = true
  } else if (features.sdk_compatibility_layers && typeof features.sdk_compatibility_layers === 'object') {
    Object.assign(compatLayers, features.sdk_compatibility_layers)
  }
  const gaps: string[] = Array.isArray(data.remaining_gaps) ? data.remaining_gaps : []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Competitive Benchmarks</h1>
          <p className="text-neutral-400 text-sm mt-0.5">{data.report_name} — {new Date(data.timestamp).toLocaleDateString()}</p>
        </div>
        {(rawComp as any)?.beats_all_competitors && (
          <div className="bg-green-950/50 border border-green-800 rounded-lg px-4 py-2 text-green-400 text-sm font-medium">
            ✅ Beats all competitors
          </div>
        )}
      </div>

      {/* Score gauges */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
          <Gauge value={latest?.accuracy_primary || 0} max={100}
            label="LoCoMo v11" color="#22c55e" size="lg" />
        </div>
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
          <Gauge value={(comp.spacetime_memory_v10_oracle || 0)} max={100}
            label="v10 Oracle" color="#a855f7" size="lg" />
        </div>
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
          <Gauge value={lmeval?.overall?.recall_at_all_5 != null ? lmeval.overall.recall_at_all_5 * 100 : 0} max={100}
            label="LongMemEval" color="#06b6d4" size="lg" />
        </div>
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
          <Gauge value={testPct} max={100}
            label={`Tests (${testsPassed}/${totalTests})`} color="#f59e0b" size="lg" />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-neutral-800 pb-2">
        {(['locomo', 'beam', 'lmeval'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              tab === t ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:text-neutral-200'
            }`}>
            {t === 'locomo' ? '📋 LoCoMo' : t === 'beam' ? '🎯 BEAM' : '🧠 LongMemEval'}
          </button>
        ))}
      </div>

      {/* LoCoMo Tab */}
      {tab === 'locomo' && (
        <div className="space-y-6">
          {/* Competitive position */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-3">
            <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">LoCoMo — Competitive Position</h3>
            {Object.keys(comp).filter(k => k !== 'notes' && k !== 'note').length > 0 ? (
              <div className="space-y-2">
                {Object.entries(comp)
                  .filter(([k]) => k !== 'notes' && k !== 'note')
                  .sort(([, a], [, b]) => (b as number) - (a as number))
                  .map(([key, val]) => (
                    <Bar key={key}
                      name={COMP_LABELS[key] || key.replace(/_/g, ' ')}
                      value={val as number}
                      max={bestPct}
                      color={COMP_COLORS[key] || '#6366f1'} />
                  ))}
              </div>
            ) : (
              <p className="text-xs text-neutral-500">{compNote || 'Competitive position pending full benchmark run.'}</p>
            )}
            <p className="text-xs text-neutral-500 mt-2">{compNote || (rawComp as any)?.notes || ''}</p>
          </div>

          {/* Per-category breakdown */}
          {latest?.per_category && (
            <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-3">
              <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">Per-Category Accuracy</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-neutral-500 border-b border-neutral-800">
                      <th className="text-left py-2 pr-4">Category</th>
                      <th className="text-right px-2">Accuracy</th>
                      <th className="text-right px-2">Correct</th>
                      <th className="text-right px-2">Total</th>
                      <th className="text-right px-2">Bar</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(latest.per_category).map(([cat, v]) => (
                      <tr key={cat} className="border-b border-neutral-800/50 hover:bg-neutral-800/30">
                        <td className="py-2 pr-4 text-neutral-300 capitalize">{cat.replace(/-/g, ' ')}</td>
                        <td className="text-right px-2 font-mono">{v.accuracy.toFixed(1)}%</td>
                        <td className="text-right px-2 text-neutral-400">{v.correct}</td>
                        <td className="text-right px-2 text-neutral-400">{v.total}</td>
                        <td className="px-2">
                          <div className="bg-neutral-800 rounded-full h-2 w-20">
                            <div className="h-full rounded-full bg-blue-500"
                              style={{ width: `${v.accuracy}%` }} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Version history */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-3">
            <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">Version History</h3>
            <div className="space-y-2">
              {Object.entries(locomo.results).reverse().map(([ver, res]) => (
                <details key={ver} className="bg-neutral-800/30 border border-neutral-800 rounded-lg">
                  <summary className="px-4 py-2.5 cursor-pointer hover:bg-neutral-800/50 rounded-lg text-sm font-medium text-neutral-200 flex items-center justify-between">
                    <span>{ver.replace(/_/g, ' ').toUpperCase()}</span>
                    <span className="text-green-400 font-mono">{typeof (res as any).accuracy_primary === 'number' ? (res as any).accuracy_primary.toFixed(1) : '—'}%</span>
                  </summary>
                  <div className="px-4 pb-3 text-xs text-neutral-400 space-y-1">
                    <p>{res.notes}</p>
                    {typeof (res as any).correct === 'number' && typeof (res as any).total === 'number' && (
                      <p>Primary: {(res as any).correct}/{(res as any).total} = {typeof (res as any).accuracy_primary === 'number' ? (res as any).accuracy_primary.toFixed(1) : '—'}%</p>
                    )}
                    {typeof (res as any).accuracy_overall === 'number' && (
                      <p>Overall: {(res as any).accuracy_overall.toFixed(1)}%</p>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* BEAM Tab */}
      {tab === 'beam' && (
        <div className="space-y-6">
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-3">
            <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">BEAM Results</h3>
            <p className="text-sm text-neutral-400">{beam.description}</p>
            <div className="overflow-x-auto mt-4">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-neutral-500 border-b border-neutral-800">
                    <th className="text-left py-2 pr-4">Pipeline</th>
                    <th className="text-right px-2">Accuracy</th>
                    <th className="text-right px-2">Passed</th>
                    <th className="text-right px-2">Total</th>
                    <th className="text-right px-2">Latency</th>
                    <th className="px-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(beam.results).map(([key, r]) => (
                    <tr key={key} className="border-b border-neutral-800/50 hover:bg-neutral-800/30">
                      <td className="py-2 pr-4 text-neutral-300 capitalize">{key.replace(/_/g, ' ')}</td>
                      <td className="text-right px-2 font-mono">{typeof (r as BeamResult).accuracy === 'number' ? ((r as BeamResult).accuracy * 100).toFixed(1) : '—'}%</td>
                      <td className="text-right px-2 text-neutral-400">{(r as BeamResult).passed}</td>
                      <td className="text-right px-2 text-neutral-400">{(r as BeamResult).total}</td>
                      <td className="text-right px-2 text-neutral-400">{typeof (r as BeamResult).latency_ms === 'number' ? (r as BeamResult).latency_ms.toFixed(0) : '—'}ms</td>
                      <td className="px-2">
                        <div className="bg-neutral-800 rounded-full h-2 w-16">
                          <div className="h-full rounded-full bg-amber-500"
                            style={{ width: `${(r as BeamResult).accuracy * 100}%` }} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* LongMemEval Tab */}
      {tab === 'lmeval' && lmeval && (
        <div className="space-y-6">
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-3">
            <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">LongMemEval Results</h3>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mt-4">
              <Gauge value={lmeval.overall.recall_at_all_5 * 100} max={100}
                label="Recall@All@5" color="#06b6d4" size="lg" />
              <div className="bg-neutral-800 rounded-xl p-4 text-center">
                <div className="text-2xl font-bold text-white">{lmeval.overall.hits}</div>
                <div className="text-xs text-neutral-400 mt-1">Hits</div>
              </div>
              <div className="bg-neutral-800 rounded-xl p-4 text-center">
                <div className="text-2xl font-bold text-white">{lmeval.overall.total}</div>
                <div className="text-xs text-neutral-400 mt-1">Total Questions</div>
              </div>
            </div>
            {lmeval.per_type && Object.keys(lmeval.per_type).length > 0 && (
              <div className="overflow-x-auto mt-4">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-neutral-500 border-b border-neutral-800">
                      <th className="text-left py-2 pr-4">Question Type</th>
                      <th className="text-right px-2">Recall</th>
                      <th className="text-right px-2">Hits</th>
                      <th className="text-right px-2">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(lmeval.per_type).map(([qt, st]: [string, any]) => (
                      <tr key={qt} className="border-b border-neutral-800/50">
                        <td className="py-2 pr-4 text-neutral-300">{qt}</td>
                        <td className="text-right px-2 font-mono">{st.recall?.toFixed(1) || '0'}%</td>
                        <td className="text-right px-2 text-neutral-400">{st.hits}</td>
                        <td className="text-right px-2 text-neutral-400">{st.total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Feature coverage */}
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 space-y-3">
        <h3 className="text-sm font-semibold text-neutral-200 uppercase tracking-wide">Feature Coverage</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-neutral-800/50 rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-white">{((features as any)?.sdk_modules ?? (features as any)?.rust_modules) ?? '—'}</div>
            <div className="text-xs text-neutral-400">SDK Modules</div>
          </div>
          <div className="bg-neutral-800/50 rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-white">{totalTests}</div>
            <div className="text-xs text-neutral-400">Integration Tests</div>
          </div>
          <div className="bg-neutral-800/50 rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-white">{features.cli_commands}</div>
            <div className="text-xs text-neutral-400">CLI Commands</div>
          </div>
          <div className="bg-neutral-800/50 rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-white">{connectors.length}</div>
            <div className="text-xs text-neutral-400">Connectors</div>
          </div>
        </div>
        {connectors.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {connectors.map(c => (
              <span key={c} className="text-xs bg-neutral-800 text-neutral-300 px-2 py-0.5 rounded">{c}</span>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-2 mt-2">
          {Object.entries(compatLayers).map(([name, supported]) => (
            <span key={name}
              className={`text-xs px-2 py-0.5 rounded ${supported ? 'bg-green-950/50 text-green-400 border border-green-800' : 'bg-neutral-800 text-neutral-500'}`}>
              {supported ? '✅' : '❌'} {name}
            </span>
          ))}
        </div>
      </div>

      {/* Gaps */}
      {gaps.length > 0 && (
        <div className="bg-amber-950/30 border border-amber-800/50 rounded-xl p-5 space-y-2">
          <h3 className="text-sm font-semibold text-amber-300 uppercase tracking-wide">Remaining Gaps</h3>
          <ul className="space-y-1">
            {gaps.map((g, i) => (
              <li key={i} className="text-xs text-amber-400/80 flex items-start gap-2">
                <span>•</span>
                <span>{g}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
