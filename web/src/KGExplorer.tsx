import { useState } from 'react'
import { stdbSql } from './lib/stdb'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface KGNode {
  id: string
  label: string
  node_type: string
  summary: string
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function KGExplorer({ host, port, db, workspaceId }: { host: string; port: string; db: string; workspaceId: string }) {
  const [nodes, setNodes] = useState<KGNode[]>([])
  const [searchLabel, setSearchLabel] = useState('')
  const [loadingN, setLoadingN] = useState(false)

  async function loadNodes() {
    setLoadingN(true)
    try {
      let sql = `SELECT id, label, node_type, summary FROM kg_node WHERE workspace_id='${workspaceId}'`
      if (searchLabel) {
        const esc = searchLabel.replace(/'/g, "''")
        sql += ` AND label LIKE '%${esc}%'`
      }
      sql += ' LIMIT 100'
      const data = await stdbSql<KGNode>({ host, port, database: db }, sql)
      setNodes(data)
    } catch {
      setNodes([])
    } finally {
      setLoadingN(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <input
          value={searchLabel}
          onChange={(e) => setSearchLabel(e.target.value)}
          placeholder="Search nodes by label..."
          className="flex-1 bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
        />
        <button onClick={loadNodes} disabled={loadingN}
          className="bg-neutral-700 hover:bg-neutral-600 disabled:bg-neutral-800 text-white rounded-lg px-4 py-2 text-sm transition-colors"
        >{loadingN ? '...' : 'Search'}</button>
      </div>

      {nodes.length === 0 ? (
        <p className="text-neutral-500 text-sm text-center py-8">No nodes found. {!searchLabel && 'Click Search to load all.'}</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 max-h-96 overflow-y-auto">
          {nodes.map((n) => (
            <div key={n.id} className="bg-neutral-800/50 border border-neutral-700 rounded-lg p-3 text-sm">
              <div className="font-medium text-white truncate">{n.label}</div>
              <div className="text-xs text-neutral-400 mt-0.5">{n.node_type}</div>
              {n.summary && <div className="text-xs text-neutral-500 mt-1 line-clamp-2">{n.summary}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
