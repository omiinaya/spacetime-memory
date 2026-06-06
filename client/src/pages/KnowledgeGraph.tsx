import { useEffect, useRef, useState, useCallback } from 'react';
import { Network as VisNetwork } from 'vis-network';
import { DataSet } from 'vis-data';
import {
  Search,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Loader2,
  AlertCircle,
  Network as NetworkIcon,
  X,
  Layers,
  Hash,
  FileText,
  Code,
  GitBranch,
  MessageSquare,
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { fetchNodes, fetchEdges, searchNodes, type KgNode } from '@/lib/spacetimedb';

/* ------------------------------------------------------------------ */
/*  Type definitions                                                   */
/* ------------------------------------------------------------------ */

interface GraphNode {
  id: number;
  label: string;
  node_type: string;
  summary: string;
  community_id: number | null;
}

interface GraphEdge {
  id: number;
  from: number;
  to: number;
  relation: string;
  weight: number;
}

/* ------------------------------------------------------------------ */
/*  Colour palette per node_type                                       */
/* ------------------------------------------------------------------ */

const NODE_TYPE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  code:     { bg: '#3b82f6', border: '#1d4ed8', text: '#eff6ff' },
  concept:  { bg: '#22c55e', border: '#16a34a', text: '#f0fdf4' },
  entity:   { bg: '#f97316', border: '#ea580c', text: '#fff7ed' },
  document: { bg: '#a855f7', border: '#9333ea', text: '#faf5ff' },
  topic:    { bg: '#ef4444', border: '#dc2626', text: '#fef2f2' },
};

const NODE_TYPE_DEFAULT = { bg: '#6b7280', border: '#4b5563', text: '#f9fafb' };

function nodeColors(type: string) {
  return NODE_TYPE_COLORS[type.toLowerCase()] ?? NODE_TYPE_DEFAULT;
}

const NODE_TYPE_ICONS: Record<string, typeof Layers> = {
  code: Code,
  concept: Layers,
  entity: GitBranch,
  document: FileText,
  topic: MessageSquare,
};

/* ------------------------------------------------------------------ */
/*  vis-network node/edge item shapes                                  */
/* ------------------------------------------------------------------ */

interface VisNodeItem {
  id: number;
  label: string;
  color: string;
  size: number;
  shape: string;
  title: string;
  borderWidth: number;
  font: { color: string; size: number };
  group: string;
  hidden?: boolean;
}

interface VisEdgeItem {
  id: number;
  from: number;
  to: number;
  label: string;
  color: { color: string; highlight: string };
  font: { color: string; size: number; strokeWidth: number; strokeColor: string };
  width: number;
  smooth: { type: string };
  hidden?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function KnowledgeGraph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<VisNetwork | null>(null);
  const allNodesRef = useRef<GraphNode[]>([]);
  const allEdgesRef = useRef<GraphEdge[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<KgNode[]>([]);

  /* ---------- build vis-network ---------- */

  const buildNetwork = useCallback(
    (graphNodes: GraphNode[], graphEdges: GraphEdge[], highlightLabel: string) => {
      if (!containerRef.current) return;

      // Destroy previous network
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }

      // Filter nodes by search highlight if needed
      let filteredIds: Set<number> | null = null;
      if (highlightLabel) {
        const matches = graphNodes
          .filter((n) => n.label.toLowerCase().includes(highlightLabel.toLowerCase()))
          .map((n) => n.id);
        // Show matching nodes + their neighbors
        const neighborIds = new Set(matches);
        for (const e of graphEdges) {
          if (matches.includes(e.from)) neighborIds.add(e.to);
          if (matches.includes(e.to)) neighborIds.add(e.from);
        }
        filteredIds = neighborIds;
      }

      const visNodes = new DataSet<VisNodeItem>();
      const visEdges = new DataSet<VisEdgeItem>();

      graphNodes.forEach((n) => {
        const colors = nodeColors(n.node_type);
        const visible = !filteredIds || filteredIds.has(n.id);
        const label = n.label.length > 25 ? n.label.slice(0, 24) + '…' : n.label;
        visNodes.add({
          id: n.id,
          label,
          color: visible ? colors.bg : '#374151',
          size: visible ? (n.label === highlightLabel ? 30 : 20) : 12,
          shape: 'dot',
          title: `${n.label}\nType: ${n.node_type}`,
          borderWidth: 2,
          font: { color: visible ? colors.text : '#6b7280', size: visible ? 12 : 0 },
          group: n.node_type,
        });
      });

      graphEdges.forEach((e) => {
        const visible = !filteredIds || (filteredIds.has(e.from) && filteredIds.has(e.to));
        visEdges.add({
          id: e.id,
          from: e.from,
          to: e.to,
          label: e.relation.length > 20 ? e.relation.slice(0, 19) + '…' : e.relation,
          color: { color: '#6b7280', highlight: '#60a5fa' },
          font: {
            color: '#9ca3af',
            size: 10,
            strokeWidth: 2,
            strokeColor: '#1f2937',
          },
          width: Math.min(e.weight, 4),
          smooth: { type: 'continuous' },
          hidden: !visible,
        });
      });

      const options = {
        nodes: {
          shape: 'dot' as const,
          size: 20,
          font: {
            size: 12,
            face: 'Inter, system-ui, sans-serif',
          },
          borderWidth: 2,
        },
        edges: {
          width: 1,
          smooth: { type: 'continuous' },
          font: {
            size: 10,
            align: 'middle' as const,
          },
          color: { inherit: false },
        },
        physics: {
          enabled: true,
          solver: 'forceAtlas2Based' as const,
          forceAtlas2Based: {
            gravitationalConstant: -32,
            centralGravity: 0.005,
            springLength: 160,
            springConstant: 0.02,
            damping: 0.4,
          },
          stabilization: { iterations: 150 },
        },
        interaction: {
          hover: true,
          tooltipDelay: 200,
          zoomView: true,
          dragView: true,
          dragNodes: true,
          navigationButtons: false,
          keyboard: true,
        },
        layout: {
          improvedLayout: true,
        },
        configure: {
          enabled: false,
        },
      };

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const network = new VisNetwork(containerRef.current, { nodes: visNodes as any, edges: visEdges as any }, options as any);

      network.on('click', (params: any) => {
        if (params.nodes && params.nodes.length > 0) {
          const nodeId = params.nodes[0] as number;
          const node = graphNodes.find((n) => n.id === nodeId);
          if (node) {
            setSelectedNode(node);
          }
        } else {
          setSelectedNode(null);
        }
      });

      network.on('oncontext', (params: any) => {
        params.event.preventDefault();
        setSelectedNode(null);
      });

      networkRef.current = network;
    },
    [],
  );

  /* ---------- load data ---------- */

  const loadGraphData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [fetchedNodes, fetchedEdges] = await Promise.all([
        fetchNodes(),
        fetchEdges(),
      ]);

      const graphNodes: GraphNode[] = fetchedNodes.map((n) => ({
        id: n.node_id,
        label: n.label,
        node_type: n.node_type,
        summary: n.summary ?? '',
        community_id: n.community_id,
      }));

      const graphEdges: GraphEdge[] = fetchedEdges.map((e) => ({
        id: e.edge_id,
        from: e.source_id,
        to: e.target_id,
        relation: e.relation,
        weight: e.weight ?? 1,
      }));

      allNodesRef.current = graphNodes;
      allEdgesRef.current = graphEdges;
      setNodes(graphNodes);
      setEdges(graphEdges);
      buildNetwork(graphNodes, graphEdges, '');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load graph data';
      setError(msg);
      console.error('KnowledgeGraph load error:', err);
    } finally {
      setLoading(false);
    }
  }, [buildNetwork]);

  /* ---------- initial load ---------- */

  useEffect(() => {
    loadGraphData();
    return () => {
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    };
  }, [loadGraphData]);

  /* ---------- search ---------- */

  const handleSearch = useCallback(
    async (query: string) => {
      setSearchQuery(query);
      if (!query.trim()) {
        setSearchResults([]);
        setSelectedNode(null);
        if (allNodesRef.current.length > 0) {
          buildNetwork(allNodesRef.current, allEdgesRef.current, '');
        }
        return;
      }

      try {
        const results = await searchNodes(query.trim());
        setSearchResults(results);
      } catch {
        // Fallback: filter locally
        const local = allNodesRef.current.filter((n) =>
          n.label.toLowerCase().includes(query.toLowerCase()),
        );
        setSearchResults(
          local.map((n) => ({
            node_id: n.id,
            label: n.label,
            node_type: n.node_type,
            summary: n.summary,
            community_id: n.community_id,
            properties: null,
            created_at: null,
          })),
        );
      }
      buildNetwork(allNodesRef.current, allEdgesRef.current, query.trim());
    },
    [buildNetwork],
  );

  /* ---------- zoom helpers ---------- */

  const zoomIn = () => {
    const scale = networkRef.current?.getScale() ?? 1;
    networkRef.current?.moveTo({ scale: scale * 1.3, animation: { duration: 200, easingFunction: 'easeInOutQuad' } });
  };

  const zoomOut = () => {
    const scale = networkRef.current?.getScale() ?? 1;
    networkRef.current?.moveTo({ scale: scale / 1.3, animation: { duration: 200, easingFunction: 'easeInOutQuad' } });
  };

  const fitView = () => networkRef.current?.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } });

  /* ---------- render ---------- */

  // --- Loading skeleton ---
  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Knowledge Graph</h1>
          <p className="text-muted-foreground">
            Visualize and explore the semantic memory network.
          </p>
        </div>
        <div className="flex h-[70vh] items-center justify-center rounded-lg border border-border bg-card">
          <div className="text-center">
            <Loader2 className="mx-auto h-10 w-10 animate-spin text-muted-foreground" />
            <p className="mt-3 text-sm text-muted-foreground">Loading graph data…</p>
            <p className="mt-1 text-xs text-muted-foreground/60">
              Fetching nodes and edges from SpacetimeDB
            </p>
          </div>
        </div>
      </div>
    );
  }

  // --- Error state ---
  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Knowledge Graph</h1>
          <p className="text-muted-foreground">
            Visualize and explore the semantic memory network.
          </p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <AlertCircle className="h-12 w-12 text-destructive" />
            <h2 className="mt-4 text-lg font-semibold">Failed to load graph</h2>
            <p className="mt-1 text-sm text-muted-foreground">{error}</p>
            <Button className="mt-4" onClick={loadGraphData}>
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // --- Empty state ---
  if (nodes.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Knowledge Graph</h1>
          <p className="text-muted-foreground">
            Visualize and explore the semantic memory network.
          </p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <NetworkIcon className="h-12 w-12 text-muted-foreground/40" />
            <h2 className="mt-4 text-lg font-semibold">No graph data yet</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              The knowledge graph will populate as memories are processed.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col gap-4">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Knowledge Graph</h1>
          <p className="text-muted-foreground">
            {nodes.length} node{nodes.length !== 1 ? 's' : ''} · {edges.length} edge{edges.length !== 1 ? 's' : ''}
          </p>
        </div>
      </div>

      {/* Toolbar: search + zoom + legend */}
      <div className="flex shrink-0 flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search nodes…"
            value={searchQuery}
            onChange={(e) => handleSearch(e.target.value)}
            className="pl-9 pr-8"
          />
          {searchQuery && (
            <button
              onClick={() => handleSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Zoom controls */}
        <div className="flex items-center rounded-md border border-border bg-card">
          <button
            onClick={zoomIn}
            className="rounded-l-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            title="Zoom in"
            type="button"
          >
            <ZoomIn className="h-4 w-4" />
          </button>
          <button
            onClick={zoomOut}
            className="border-x border-border p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            title="Zoom out"
            type="button"
          >
            <ZoomOut className="h-4 w-4" />
          </button>
          <button
            onClick={fitView}
            className="rounded-r-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            title="Fit view"
            type="button"
          >
            <Maximize2 className="h-4 w-4" />
          </button>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5">
          <span className="mr-1 text-xs text-muted-foreground">Legend:</span>
          {Object.entries(NODE_TYPE_COLORS).map(([type, colors]) => (
            <span key={type} className="flex items-center gap-1 text-xs">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: colors.bg }}
              />
              <span className="text-muted-foreground capitalize">{type}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Main area: graph + details panel */}
      <div className="flex flex-1 gap-4 overflow-hidden">
        {/* Graph canvas */}
        <div className="relative flex-1 overflow-hidden rounded-lg border border-border bg-card">
          <div ref={containerRef} className="h-full w-full" />

          {/* Search results indicator */}
          {searchResults.length > 0 && (
            <div className="absolute left-3 top-3 z-10 rounded-md bg-background/90 px-2.5 py-1 text-xs text-muted-foreground backdrop-blur-sm">
              {searchResults.length} node{searchResults.length !== 1 ? 's' : ''} found
              — click to inspect
            </div>
          )}
        </div>

        {/* Details panel */}
        {selectedNode && (
          <Card className="w-80 shrink-0 overflow-y-auto">
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                {(() => {
                  const Icon = NODE_TYPE_ICONS[selectedNode.node_type] ?? Layers;
                  return <Icon className="h-4 w-4 text-muted-foreground" />;
                })()}
                Node Details
              </CardTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => setSelectedNode(null)}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Label */}
              <div>
                <p className="text-xs text-muted-foreground">Label</p>
                <p className="text-sm font-medium">{selectedNode.label}</p>
              </div>

              {/* Type */}
              <div>
                <p className="text-xs text-muted-foreground">Type</p>
                <Badge
                  variant="outline"
                  className="mt-0.5 capitalize"
                >
                  {selectedNode.node_type}
                </Badge>
              </div>

              {/* Community ID */}
              {selectedNode.community_id != null && (
                <div>
                  <p className="text-xs text-muted-foreground">Community</p>
                  <div className="mt-0.5 flex items-center gap-1">
                    <Hash className="h-3 w-3 text-muted-foreground" />
                    <span className="text-sm">{selectedNode.community_id}</span>
                  </div>
                </div>
              )}

              {/* Summary */}
              {selectedNode.summary && (
                <div>
                  <p className="text-xs text-muted-foreground">Summary</p>
                  <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
                    {selectedNode.summary}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
