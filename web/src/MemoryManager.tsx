import { useCallback, useEffect, useState } from 'react'
import KGVisualizer from './KGVisualizer'
import KGExplorer from './KGExplorer'
import { stdbSql, stdbQuery, sortDesc } from './lib/stdb'

/* ------------------------------------------------------------------ */
/*  Types                                                              */

interface Workspace {
  id: string
  name?: string
  created_at?: string
}

interface Memory {
  id: string
  content: string
  summary?: string
  memory_type?: string
  created_at: number
  entities_json?: string
  confidence?: number
}

interface Stats {
  total_memories: number
  total_notes: number
  total_nodes: number
  total_edges: number
}

interface MemoryManagerProps {
  stdbHost: string
  stdbPort: string
  stdbDb: string
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function MemoryManager({ stdbHost, stdbPort, stdbDb }: MemoryManagerProps) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [activeWs, setActiveWs] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState('')
  const [memories, setMemories] = useState<Memory[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'memories' | 'stats' | 'graph' | 'explorer'>('memories')
  const [memoryType, setMemoryType] = useState('')
  const [storeContent, setStoreContent] = useState('')
  const [storeSummary, setStoreSummary] = useState('')
  const [storing, setStoring] = useState(false)
  const [storeMsg, setStoreMsg] = useState('')

  /* ---- Load workspaces (private table → reducer path via proxy) ---- */
  useEffect(() => {
    stdbQuery<Workspace>({ host: stdbHost, port: stdbPort, database: stdbDb }, 'workspace', '', {}, ['id', 'name', 'created_at'])
      .then(ws => setWorkspaces(sortDesc(ws, 'created_at')))
      .catch(e => setError(`Failed to load workspaces: ${e.message}`))
  }, [stdbHost, stdbPort, stdbDb])

  /* ---- Load memories when workspace or search changes ---- */
  const loadMemories = useCallback(async () => {
    if (!activeWs) return
    setLoading(true)
    setError('')
    try {
      // STDB SQL has no LIKE/contains — use the query_table reducer path
      // (also filters is_active, so soft-deleted memories disappear) and
      // apply search + type filtering client-side.
      const data = await stdbQuery<Memory>(
        { host: stdbHost, port: stdbPort, database: stdbDb },
        'memory',
        activeWs,
        {},
        ['id', 'content', 'summary', 'memory_type', 'created_at', 'entities_json', 'confidence'],
      )
      let rows = data
      if (searchQuery) {
        const q = searchQuery.toLowerCase()
        rows = rows.filter(
          (m) =>
            (m.content || '').toLowerCase().includes(q) ||
            (m.summary || '').toLowerCase().includes(q),
        )
      }
      if (memoryType) {
        rows = rows.filter((m) => m.memory_type === memoryType)
      }
      setMemories(sortDesc(rows, 'created_at').slice(0, 50))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [activeWs, searchQuery, memoryType, stdbHost, stdbPort, stdbDb])

  useEffect(() => {
    loadMemories()
  }, [loadMemories])

  /* ---- Load stats ---- */
  const loadStats = useCallback(async () => {
    if (!activeWs) return
    try {
      const client = { host: stdbHost, port: stdbPort, database: stdbDb }
      const [mem, notes, nodes, edges] = await Promise.all([
        stdbSql(client, `SELECT COUNT(*) as c FROM memory WHERE workspace_id='${activeWs}'`),
        // `note` is a private table — reducer path (proxy) then count client-side
        stdbQuery(client, 'note', activeWs, {}, ['id']),
        stdbSql(client, `SELECT COUNT(*) as c FROM kg_node WHERE workspace_id='${activeWs}'`),
        stdbSql(client, `SELECT COUNT(*) as c FROM kg_edge WHERE workspace_id='${activeWs}'`),
      ])
      setStats({
        total_memories: (mem[0] as any)?.c ?? 0,
        total_notes: Array.isArray(notes) ? notes.length : 0,
        total_nodes: (nodes[0] as any)?.c ?? 0,
        total_edges: (edges[0] as any)?.c ?? 0,
      })
    } catch (e: any) {
      setError(e.message)
    }
  }, [activeWs, stdbHost, stdbPort, stdbDb])

  useEffect(() => {
    if (tab === 'stats') loadStats()
  }, [tab, loadStats])

  /* ---- Store a memory ---- */
  async function handleStore() {
    if (!activeWs || !storeContent.trim()) return
    setStoring(true)
    setStoreMsg('')
    try {
      // Canonical reducer arg order (see client/_memories.py store()):
      // [workspace_id, peer_id, observer_id, memory_type, content, summary,
      //  entities_json, confidence, source_session_id, source_message_id, images_json]
      const body = JSON.stringify([
        activeWs,
        '',
        '',
        'experience',
        storeContent,
        storeSummary,
        '[]',
        0.8,
        '',
        '',
        '',
      ])
      const url = `http://${stdbHost}:${stdbPort}/v1/database/${stdbDb}/call/store_memory`
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        signal: AbortSignal.timeout(10000),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setStoreMsg('Memory stored ✓')
      setStoreContent('')
      setStoreSummary('')
      loadMemories()
    } catch (e: any) {
      setStoreMsg(`Error: ${e.message}`)
    } finally {
      setStoring(false)
    }
  }

  /* ---- Delete a memory ---- */
  async function handleDelete(id: string) {
    if (!confirm('Delete this memory?')) return
    try {
      const url = `http://${stdbHost}:${stdbPort}/v1/database/${stdbDb}/call/delete_memory`
      await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([id]),
        signal: AbortSignal.timeout(5000),
      })
      loadMemories()
    } catch (e: any) {
      setError(e.message)
    }
  }

  /* ---- Format date ---- */
  function fmtDate(ts: number): string {
    if (!ts) return ''
    return new Date(ts / 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  /* ================================================================== */
  /*  RENDER                                                             */
  /* ================================================================== */

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Memory Manager</h1>
          <p className="text-neutral-400 text-sm mt-0.5">Browse, search, and manage your memories</p>
        </div>
        <select
          value={activeWs}
          onChange={(e) => { setActiveWs(e.target.value); setMemories([]) }}
          className="bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white max-w-xs"
        >
          <option value="">— Select workspace —</option>
          {workspaces.map((ws) => (
            <option key={ws.id} value={ws.id}>{ws.name || ws.id.slice(0, 12)}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="bg-red-950/50 border border-red-800 rounded-lg px-4 py-3 text-sm text-red-300">{error}</div>
      )}

      {!activeWs && (
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-12 text-center">
          <p className="text-neutral-500">Select a workspace above to view its memories</p>
        </div>
      )}

      {activeWs && (
        <>
          {/* Tabs */}
          <div className="flex gap-2 border-b border-neutral-800 pb-2">
            {(['memories', 'stats', 'graph', 'explorer'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${tab === t ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:text-neutral-200'}`}
              >{t === 'memories' ? '📝 Memories' : t === 'stats' ? '📊 Stats' : t === 'graph' ? '🔗 Knowledge Graph' : '🔍 Explorer'}</button>
            ))}
          </div>

          {/* ---- Memories Tab ---- */}
          {tab === 'memories' && (
            <div className="space-y-4">
              {/* Store form */}
              <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 space-y-3">
                <h3 className="text-sm font-medium text-white">Store New Memory</h3>
                <textarea
                  value={storeContent}
                  onChange={(e) => setStoreContent(e.target.value)}
                  placeholder="Memory content..."
                  className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500 h-20 resize-none"
                />
                <div className="flex gap-3">
                  <input
                    value={storeSummary}
                    onChange={(e) => setStoreSummary(e.target.value)}
                    placeholder="Summary (optional)"
                    className="flex-1 bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
                  />
                  <button onClick={handleStore} disabled={storing || !storeContent.trim()}
                    className="bg-blue-600 hover:bg-blue-500 disabled:bg-neutral-700 disabled:text-neutral-500 text-white font-medium rounded-lg px-4 py-2 text-sm transition-colors"
                  >{storing ? 'Storing...' : 'Store'}</button>
                </div>
                {storeMsg && <p className={`text-xs ${storeMsg.includes('✓') ? 'text-green-400' : 'text-red-400'}`}>{storeMsg}</p>}
              </div>

              {/* Search */}
              <div className="flex gap-3">
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search memories..."
                  className="flex-1 bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
                />
                <select value={memoryType} onChange={(e) => setMemoryType(e.target.value)}
                  className="bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white"
                >
                  <option value="">All types</option>
                  <option value="experience">Experience</option>
                  <option value="fact">Fact</option>
                  <option value="preference">Preference</option>
                  <option value="world_fact">World Fact</option>
                </select>
                <button onClick={loadMemories} className="bg-neutral-700 hover:bg-neutral-600 text-white font-medium rounded-lg px-4 py-2 text-sm transition-colors">Refresh</button>
              </div>

              {/* Memory list */}
              {loading ? (
                <div className="text-center py-8 text-neutral-500">Loading...</div>
              ) : memories.length === 0 ? (
                <div className="bg-neutral-900/50 border border-neutral-800 rounded-xl p-8 text-center">
                  <p className="text-neutral-500 text-sm">No memories found</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {memories.map((m) => (
                    <div key={m.id} className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 hover:border-neutral-700 transition-colors">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm text-white leading-relaxed">{m.content || '<empty>'}</p>
                          {m.summary && <p className="text-xs text-neutral-400 mt-1 italic">{m.summary}</p>}
                          <div className="flex items-center gap-3 mt-2">
                            <span className="text-xs text-neutral-500">{fmtDate(m.created_at)}</span>
                            {m.memory_type && <span className="text-xs bg-neutral-800 text-neutral-400 px-2 py-0.5 rounded">{m.memory_type}</span>}
                            {m.confidence !== undefined && (
                              <span className={`text-xs ${(m.confidence ?? 0) >= 0.7 ? 'text-green-500' : 'text-yellow-500'}`}>
                                {(m.confidence ?? 0) * 100}%
                              </span>
                            )}
                            {m.entities_json && m.entities_json.length > 5 && (
                              <span className="text-xs text-blue-400">has entities</span>
                            )}
                          </div>
                        </div>
                        <button onClick={() => handleDelete(m.id)}
                          className="text-neutral-600 hover:text-red-400 text-xs transition-colors shrink-0 mt-1">✕</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ---- Stats Tab ---- */}
          {tab === 'stats' && (
            <div className="space-y-4">
              <button onClick={loadStats} className="bg-neutral-700 hover:bg-neutral-600 text-white rounded-lg px-4 py-2 text-sm transition-colors">Refresh Stats</button>
              {stats ? (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {([
                    ['📝', 'Memories', stats.total_memories],
                    ['📄', 'Notes', stats.total_notes],
                    ['🔗', 'KG Nodes', stats.total_nodes],
                    ['🔀', 'KG Edges', stats.total_edges],
                  ] as const).map(([icon, label, value]) => (
                    <div key={label} className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 text-center">
                      <div className="text-2xl mb-1">{icon}</div>
                      <div className="text-2xl font-bold text-white">{value.toLocaleString()}</div>
                      <div className="text-xs text-neutral-400 mt-1">{label}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-neutral-500">Loading stats...</div>
              )}
            </div>
          )}

          {/* ---- Knowledge Graph Tab ---- */}
          {tab === 'graph' && (
            <div className="space-y-4">
              <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6">
                <h3 className="text-sm font-medium text-white mb-4">Knowledge Graph Visualizer</h3>
                <KGVisualizer host={stdbHost} port={stdbPort} db={stdbDb} workspaceId={activeWs} />
              </div>
            </div>
          )}

          {/* ---- Explorer Tab ---- */}
          {tab === 'explorer' && (
            <div className="space-y-4">
              <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6">
                <h3 className="text-sm font-medium text-white mb-4">KG Node Explorer</h3>
                <KGExplorer host={stdbHost} port={stdbPort} db={stdbDb} workspaceId={activeWs} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
