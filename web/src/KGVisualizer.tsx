import { useEffect, useRef, useState } from 'react'
import { stdbSql } from './lib/stdb'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface KGNode {
  id: string
  label: string
  node_type: string
  summary?: string
}

interface KGEdge {
  id: string
  source_node_id: string
  target_node_id: string
  relation: string
}

interface LayoutNode {
  id: string
  label: string
  node_type: string
  summary?: string
  x: number
  y: number
  vx: number
  vy: number
  radius: number
}

interface LayoutEdge {
  source: string
  target: string
  relation: string
}

/* ------------------------------------------------------------------ */
/*  Force Simulation (no deps)                                         */
/* ------------------------------------------------------------------ */

const NODE_RADIUS = 24
const REPULSION = 8000
const ATTRACTION = 0.005
const DAMPING = 0.85
const MIN_VELOCITY = 0.1
const CENTER_GRAVITY = 0.01

const TYPE_COLORS: Record<string, string> = {
  code: '#3b82f6',
  concept: '#a855f7',
  entity: '#22c55e',
  document: '#f59e0b',
  topic: '#06b6d4',
  memory: '#ec4899',
  session: '#6366f1',
  default: '#6b7280',
}

function simulateStep(nodes: LayoutNode[], edges: LayoutEdge[]): boolean {
  // Reset forces
  for (const n of nodes) {
    n.vx *= DAMPING
    n.vy *= DAMPING
  }

  // Repulsion (Coulomb's law)
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j]
      let dx = b.x - a.x, dy = b.y - a.y
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
      const force = REPULSION / (dist * dist)
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      a.vx -= fx; a.vy -= fy
      b.vx += fx; b.vy += fy
    }
  }

  // Attraction (Hooke's law along edges)
  const nodeMap = new Map(nodes.map(n => [n.id, n]))
  for (const e of edges) {
    const a = nodeMap.get(e.source), b = nodeMap.get(e.target)
    if (!a || !b) continue
    const dx = b.x - a.x, dy = b.y - a.y
    const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
    const force = (dist - 150) * ATTRACTION
    const fx = (dx / dist) * force
    const fy = (dy / dist) * force
    a.vx += fx; a.vy += fy
    b.vx -= fx; b.vy -= fy
  }

  // Center gravity
  for (const n of nodes) {
    n.vx -= n.x * CENTER_GRAVITY
    n.vy -= n.y * CENTER_GRAVITY
  }

  // Apply velocities
  let moving = false
  for (const n of nodes) {
    n.x += n.vx
    n.y += n.vy
    if (Math.abs(n.vx) > MIN_VELOCITY || Math.abs(n.vy) > MIN_VELOCITY) {
      moving = true
    }
  }
  return moving
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface KGVisualizerProps {
  host: string
  port: string
  db: string
  workspaceId: string
}

export default function KGVisualizer({ host, port, db, workspaceId }: KGVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef<number>(0)
  const [nodes, setNodes] = useState<KGNode[]>([])
  const [edges, setEdges] = useState<KGEdge[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedNode, setSelectedNode] = useState<KGNode | null>(null)
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)
  const layoutRef = useRef<LayoutNode[]>([])
  const edgeLayoutRef = useRef<LayoutEdge[]>([])

  // Fetch data
  useEffect(() => {
    async function fetchData() {
      setLoading(true)
      try {
        const client = { host, port, database: db }
        const [nodeData, edgeData] = await Promise.all([
          stdbSql<KGNode>(client, `SELECT id, label, node_type, summary FROM kg_node WHERE workspace_id = '${workspaceId}' LIMIT 200`),
          stdbSql<KGEdge>(client, `SELECT id, source_node_id, target_node_id, relation FROM kg_edge WHERE workspace_id = '${workspaceId}' LIMIT 500`),
        ])

        setNodes(nodeData)
        setEdges(edgeData)

        // Initialize layout positions
        const w = 800, h = 500
        const layout = (Array.isArray(nodeData) ? nodeData : []).map((n) => ({
          id: n.id,
          label: n.label,
          node_type: n.node_type,
          summary: n.summary,
          x: w / 2 + (Math.random() - 0.5) * w * 0.6,
          y: h / 2 + (Math.random() - 0.5) * h * 0.6,
          vx: 0, vy: 0,
          radius: NODE_RADIUS,
        }))
        layoutRef.current = layout

        const edgeLayout = (Array.isArray(edgeData) ? edgeData : []).map(e => ({
          source: e.source_node_id,
          target: e.target_node_id,
          relation: e.relation,
        }))
        edgeLayoutRef.current = edgeLayout
      } catch (e: any) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [host, port, db, workspaceId])

  // Animation loop
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || layoutRef.current.length === 0) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let running = true
    let frameCount = 0

    function render() {
      if (!running) return
      frameCount++

      // Run simulation for first 200 frames, then occasionally
      const shouldSimulate = frameCount < 200 || frameCount % 10 === 0
      if (shouldSimulate) {
        simulateStep(layoutRef.current, edgeLayoutRef.current)
      }

      // Clear
      ctx!.clearRect(0, 0, canvas!.width, canvas!.height)

      // Draw edges
      const nodeMap = new Map(layoutRef.current.map(n => [n.id, n]))
      for (const e of edgeLayoutRef.current) {
        const a = nodeMap.get(e.source), b = nodeMap.get(e.target)
        if (!a || !b) continue
        ctx!.beginPath()
        ctx!.moveTo(a.x, a.y)
        ctx!.lineTo(b.x, b.y)
        ctx!.strokeStyle = 'rgba(100, 116, 139, 0.3)'
        ctx!.lineWidth = 1
        ctx!.stroke()
      }

      // Draw nodes
      for (const n of layoutRef.current) {
        const isHovered = n.id === hoveredNode
        const isSelected = n.id === selectedNode?.id
        const color = TYPE_COLORS[n.node_type] || TYPE_COLORS.default
        const radius = isHovered || isSelected ? n.radius + 4 : n.radius

        // Glow for selected
        if (isSelected) {
          ctx!.beginPath()
          ctx!.arc(n.x, n.y, radius + 6, 0, Math.PI * 2)
          ctx!.fillStyle = 'rgba(59, 130, 246, 0.2)'
          ctx!.fill()
        }

        // Circle
        ctx!.beginPath()
        ctx!.arc(n.x, n.y, radius, 0, Math.PI * 2)
        ctx!.fillStyle = color + (isHovered ? '99' : '77')
        ctx!.fill()
        ctx!.strokeStyle = isHovered ? '#ffffff' : color
        ctx!.lineWidth = isHovered ? 2 : 1.5
        ctx!.stroke()

        // Label
        const label = n.label.length > 12 ? n.label.slice(0, 11) + '…' : n.label
        ctx!.fillStyle = isHovered ? '#ffffff' : '#d4d4d8'
        ctx!.font = '10px monospace'
        ctx!.textAlign = 'center'
        ctx!.fillText(label, n.x, n.y + radius + 14)
      }

      animRef.current = requestAnimationFrame(render)
    }

    render()

    return () => {
      running = false
      cancelAnimationFrame(animRef.current)
    }
  }, [nodes.length, edges.length, hoveredNode, selectedNode])

  // Mouse interaction
  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left, my = e.clientY - rect.top

    let found: string | null = null
    for (const n of layoutRef.current) {
      const dx = mx - n.x, dy = my - n.y
      if (dx * dx + dy * dy < (n.radius + 8) ** 2) {
        found = n.id
        break
      }
    }
    setHoveredNode(found)
    canvas.style.cursor = found ? 'pointer' : 'default'
  }

  function handleClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left, my = e.clientY - rect.top

    for (const n of layoutRef.current) {
      const dx = mx - n.x, dy = my - n.y
      if (dx * dx + dy * dy < n.radius ** 2) {
        const found = nodes.find(nn => nn.id === n.id)
        setSelectedNode(found || null)
        return
      }
    }
    setSelectedNode(null)
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="bg-red-950/50 border border-red-800 rounded-lg px-4 py-3 text-sm text-red-300">{error}</div>
      )}
      {loading ? (
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-12 text-center text-neutral-500">
          Loading knowledge graph...
        </div>
      ) : nodes.length === 0 ? (
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-12 text-center text-neutral-500">
          <p>No KG nodes found. Add entities via <code className="text-neutral-400 bg-neutral-800 px-1 rounded">client.create_node()</code></p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <div className="lg:col-span-3 bg-neutral-900 border border-neutral-800 rounded-xl overflow-hidden">
            <canvas
              ref={canvasRef}
              width={800}
              height={500}
              className="w-full h-[500px]"
              onMouseMove={handleMouseMove}
              onClick={handleClick}
            />
            <div className="px-4 py-2 border-t border-neutral-800 flex flex-wrap gap-3 text-xs text-neutral-500">
              <span>🟦 code</span>
              <span>🟪 concept</span>
              <span>🟩 entity</span>
              <span>🟨 document</span>
              <span>🟦 topic</span>
              <span>🟥 memory</span>
              <span className="ml-auto">{nodes.length} nodes, {edges.length} edges</span>
            </div>
          </div>

          {/* Node details panel */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 h-[500px] overflow-y-auto">
            {selectedNode ? (
              <div className="space-y-3">
                <h3 className="text-sm font-medium text-white">{selectedNode.label}</h3>
                <div className="space-y-2 text-xs">
                  <div>
                    <span className="text-neutral-500">ID:</span>
                    <span className="text-neutral-300 ml-2 font-mono">{selectedNode.id.slice(0, 16)}…</span>
                  </div>
                  <div>
                    <span className="text-neutral-500">Type:</span>
                    <span className={`ml-2 px-1.5 py-0.5 rounded ${
                      TYPE_COLORS[selectedNode.node_type]
                        ? 'bg-' + TYPE_COLORS[selectedNode.node_type].slice(1) + '/20 text-' + TYPE_COLORS[selectedNode.node_type].slice(1)
                        : 'bg-neutral-800 text-neutral-400'
                    }`}>
                      {selectedNode.node_type}
                    </span>
                  </div>
                  {selectedNode.summary && (
                    <div>
                      <span className="text-neutral-500">Summary:</span>
                      <p className="text-neutral-300 mt-1 leading-relaxed">{selectedNode.summary}</p>
                    </div>
                  )}
                </div>
                {/* Show connected nodes */}
                <div className="pt-2 border-t border-neutral-800">
                  <h4 className="text-xs font-medium text-neutral-400 mb-2">Connected To</h4>
                  {(() => {
                    const connected = edges
                      .filter(e => e.source_node_id === selectedNode.id || e.target_node_id === selectedNode.id)
                      .slice(0, 10)
                    return connected.length === 0 ? (
                      <p className="text-xs text-neutral-600">No edges</p>
                    ) : (
                      <div className="space-y-1.5">
                        {connected.map(e => {
                          const otherId = e.source_node_id === selectedNode.id ? e.target_node_id : e.source_node_id
                          const other = nodes.find(n => n.id === otherId)
                          return (
                            <div key={e.id} className="flex items-center gap-2 text-xs">
                              <span className="text-neutral-500 truncate max-w-[60px]">{e.relation}</span>
                              <span className="text-neutral-300">→</span>
                              <span className="text-neutral-300 truncate max-w-[100px]">{other?.label || otherId.slice(0, 8)}</span>
                            </div>
                          )
                        })}
                      </div>
                    )
                  })()}
                </div>
              </div>
            ) : (
              <div className="text-center py-12 text-neutral-500 text-sm">
                <p>Click a node to see details</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
