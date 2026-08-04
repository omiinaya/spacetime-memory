import { useState } from 'react'
import ProxyMetricsDashboard from './ProxyMetricsDashboard'
import EmbedderMetricsDashboard from './EmbedderMetricsDashboard'
import MemoryManager from './MemoryManager'
import BenchmarkDashboard from './BenchmarkDashboard'
import KGExplorer from './KGExplorer'
import KGVisualizer from './KGVisualizer'

type Page = 'proxy' | 'embedder' | 'memories' | 'benchmark' | 'kg' | 'wizard'

/* ------------------------------------------------------------------ */
/*  Connection settings (shared across pages)                          */
/* ------------------------------------------------------------------ */

const DEFAULT_HOST = '127.0.0.1'
const DEFAULT_PROXY_PORT = '5190'
const DEFAULT_DB = 'spacetime-memory-v2'
const DEFAULT_WORKSPACE = 'default'

function App() {
  const [page, setPage] = useState<Page>('proxy')
  const [workspaceId, setWorkspaceId] = useState(DEFAULT_WORKSPACE)

  const tabs: { id: Page; label: string }[] = [
    { id: 'proxy', label: 'Proxy Metrics' },
    { id: 'embedder', label: 'Embedder Metrics' },
    { id: 'memories', label: 'Memory Manager' },
    { id: 'kg', label: '🕸 Knowledge Graph' },
    { id: 'benchmark', label: '🏆 Benchmarks' },
    { id: 'wizard', label: 'Connection Wizard' },
  ]

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      {/* Nav */}
      <header className="border-b border-neutral-800">
        <div className="max-w-6xl mx-auto px-4 flex items-center justify-between h-12">
          <div className="flex items-center gap-2">
            <span className="text-white font-bold text-sm">Spacetime Memory</span>
          </div>
          <nav className="flex gap-1">
            {tabs.map(t => (
              <button
                key={t.id}
                onClick={() => setPage(t.id)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  page === t.id
                    ? 'bg-neutral-800 text-white'
                    : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/50'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-6xl mx-auto px-4 py-6">
        {page === 'proxy' ? (
          <ProxyMetricsDashboard />
        ) : page === 'embedder' ? (
          <EmbedderMetricsDashboard />
        ) : page === 'memories' ? (
          <MemoryManager
            stdbHost={DEFAULT_HOST}
            stdbPort={DEFAULT_PROXY_PORT}
            stdbDb={DEFAULT_DB}
          />
        ) : page === 'kg' ? (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Knowledge Graph</h2>
              <input
                value={workspaceId}
                onChange={(e) => setWorkspaceId(e.target.value)}
                placeholder="Workspace ID"
                className="bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-1.5 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500 w-64"
              />
            </div>
            <KGExplorer host={DEFAULT_HOST} port={DEFAULT_PROXY_PORT} db={DEFAULT_DB} workspaceId={workspaceId} />
            <KGVisualizer host={DEFAULT_HOST} port={DEFAULT_PROXY_PORT} db={DEFAULT_DB} workspaceId={workspaceId} />
          </div>
        ) : page === 'benchmark' ? (
          <BenchmarkDashboard />
        ) : (
          <ConnectionWizard />
        )}
      </main>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Connection Wizard                                                  */
/* ------------------------------------------------------------------ */

type ConnectionStatus = 'idle' | 'testing' | 'success' | 'error'

function ConnectionWizard() {
  // The browser cannot reach STDB directly (no CORS headers on :3001) — all
  // dashboard traffic routes through the native stdb-sql-proxy (:5190), which
  // adds CORS + auth. The wizard therefore tests through the proxy and
  // generates config for the proxy endpoint.
  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState('5190')
  const [database, setDatabase] = useState('spacetime-memory-v2')
  const [embedderUrl, setEmbedderUrl] = useState('http://127.0.0.1:4000')
  const [status, setStatus] = useState<ConnectionStatus>('idle')
  const [statusMsg, setStatusMsg] = useState('')
  const [latency, setLatency] = useState<number | null>(null)
  const [configYaml, setConfigYaml] = useState('')

  async function testConnection() {
    setStatus('testing')
    setStatusMsg('Testing connection...')
    setConfigYaml('')

    const start = performance.now()
    try {
      const res = await fetch(`http://${host}:${port}/health`, {
        signal: AbortSignal.timeout(5000),
      })
      const elapsed = Math.round((performance.now() - start) * 10) / 10
      setLatency(elapsed)

      if (res.status === 200 || res.status === 404) {
        setStatus('success')
        setStatusMsg(`SpacetimeDB is running (${elapsed}ms)`)

        const dbRes = await fetch(`http://${host}:${port}/v1/database`, {
          signal: AbortSignal.timeout(3000),
        })
        if (dbRes.ok) {
          const dbs = await dbRes.json()
          const found = Array.isArray(dbs) && dbs.some((d: any) =>
            d.name === database || d.database_address === database
          )
          if (found) {
            setStatusMsg(`SpacetimeDB is running (${elapsed}ms) — module "${database}" found`)
            generateConfig(host, port, database, embedderUrl)
          } else {
            setStatusMsg(`SpacetimeDB is running (${elapsed}ms) — module "${database}" not found, publish first`)
            generateConfig(host, port, database, embedderUrl, true)
          }
        } else {
          generateConfig(host, port, database, embedderUrl, true)
        }
      } else {
        setStatus('error')
        setStatusMsg(`Unexpected response: HTTP ${res.status}`)
      }
    } catch (err: any) {
      setStatus('error')
      setStatusMsg(err?.message || 'Connection failed — is SpacetimeDB running?')
      setLatency(null)
    }
  }

  function generateConfig(h: string, p: string, db: string, emb: string, warn = false) {
    const yaml = [
      '# Spacetime Memory Configuration',
      '# Generated by Spacetime Memory Connection Wizard',
      '',
      'spacetimedb:',
      `  host: ${h}`,
      `  port: ${p}`,
      `  database: ${db}`,
      '',
      'embedder:',
      `  url: ${emb}`,
      `  model: bge-m3`,
      '',
      '---',
      '',
      '# Environment variables (export these or add to .env)',
      `export SPACETIMEDB_HOST=${h}`,
      `export SPACETIMEDB_PORT=${p}`,
      `export SPACETIMEDB_DB=${db}`,
      `export EMBEDDER_URL=${emb}`,
      `export EMBEDDING_MODEL=bge-m3`,
      '',
    ]
    if (warn) {
      yaml.push(
        '# ⚠️ Module not found — run: stmem publish --server http://' + h + ':' + p + ' -y ' + db
      )
    }
    yaml.push('# Then verify: stmem doctor')
    setConfigYaml(yaml.join('\n'))
  }

  function downloadConfig() {
    const blob = new Blob([configYaml], { type: 'text/yaml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'spacetime-memory.yaml'
    a.click()
    URL.revokeObjectURL(url)
  }

  function copyToClipboard() {
    navigator.clipboard.writeText(configYaml)
  }

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-white">Connection Wizard</h1>
        <p className="text-neutral-400 mt-1 text-sm">Configure and verify your SpacetimeDB connection</p>
      </div>

      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 space-y-5">
        <div>
          <label className="block text-xs font-medium text-neutral-400 mb-1.5">SpacetimeDB Host</label>
          <input type="text" value={host}
            onChange={(e) => { setHost(e.target.value); setStatus('idle'); setConfigYaml('') }}
            className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
            placeholder="127.0.0.1"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-neutral-400 mb-1.5">Port</label>
          <input type="text" value={port}
            onChange={(e) => { setPort(e.target.value); setStatus('idle'); setConfigYaml('') }}
            className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
            placeholder="3001"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-neutral-400 mb-1.5">Database Name</label>
          <input type="text" value={database}
            onChange={(e) => { setDatabase(e.target.value); setStatus('idle'); setConfigYaml('') }}
            className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
            placeholder="spacetime-memory-v2"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-neutral-400 mb-1.5">Embedder URL</label>
          <input type="text" value={embedderUrl}
            onChange={(e) => { setEmbedderUrl(e.target.value); setStatus('idle'); setConfigYaml('') }}
            className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500"
            placeholder="http://127.0.0.1:4000"
          />
        </div>

        <button onClick={testConnection}
          disabled={status === 'testing'}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-neutral-700 disabled:text-neutral-500 text-white font-medium rounded-lg px-4 py-2.5 text-sm transition-colors"
        >
          {status === 'testing' ? 'Testing...' : 'Test Connection'}
        </button>

        {status !== 'idle' && (
          <div className={`rounded-lg px-4 py-3 text-sm border ${
            status === 'testing' ? 'bg-neutral-800 border-neutral-700 text-neutral-300' :
            status === 'success' ? 'bg-green-950/50 border-green-800 text-green-300' :
            'bg-red-950/50 border-red-800 text-red-300'
          }`}>
            <div className="flex items-center gap-2">
              <span>{status === 'testing' ? '⟳' : status === 'success' ? '✓' : '✗'}</span>
              <span>{statusMsg}</span>
              {latency !== null && status === 'success' && (
                <span className="text-neutral-500 text-xs ml-auto">{latency}ms</span>
              )}
            </div>
          </div>
        )}

        {configYaml && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-400">Configuration</span>
              <div className="flex gap-2">
                <button onClick={copyToClipboard} className="text-xs text-blue-400 hover:text-blue-300">Copy</button>
                <button onClick={downloadConfig} className="text-xs text-blue-400 hover:text-blue-300">Download</button>
              </div>
            </div>
            <pre className="bg-neutral-950 border border-neutral-800 rounded-lg p-4 text-xs text-neutral-300 overflow-x-auto whitespace-pre-wrap">{configYaml}</pre>
          </div>
        )}
      </div>

      <p className="text-center text-xs text-neutral-600">
        After setup, run <code className="text-neutral-400 bg-neutral-900 px-1 rounded">stmem doctor</code> to verify
      </p>
    </div>
  )
}

export default App
