import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useLocation } from 'wouter';
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from 'd3-force';
import { drag as d3Drag } from 'd3-drag';
import { zoom as d3Zoom, zoomIdentity } from 'd3-zoom';
import { select } from 'd3-selection';
import {
  Search,
  X,
  GitFork,
  Loader2,
  AlertCircle,
  Network,
  Layers,
  FileText,
  Code,
  GitBranch,
  MessageSquare,
  Maximize2,
  ZoomIn,
  ZoomOut,
  Eye,
  EyeOff,
  ToggleLeft,
  ToggleRight,
  Copy,
  ExternalLink,
  ChevronRight,
  Info,
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { fetchKgNodes as fetchNodes, fetchKgEdges as fetchEdges } from '@/lib/spacetimedb';

/* ------------------------------------------------------------------ */
/*  Type definitions                                                   */
/* ------------------------------------------------------------------ */

// KGNodeRow and KGEdgeRow are no longer declared here — types are inferred
// from fetchKgNodes/fetchKgEdges and mapped to internal snake_case shape.

interface GraphNode extends SimulationNodeDatum {
  id: string;
  label: string;
  node_type: string;
  summary: string;
  community_id: number;
  strength: number;
  degree: number;
}

interface GraphEdge extends SimulationLinkDatum<GraphNode> {
  id: string;
  relation: string;
  weight: number;
  confidence: string;
}

interface NeighborInfo {
  node: GraphNode;
  edge: GraphEdge;
}

/* ------------------------------------------------------------------ */
/*  Colour palette per node_type                                       */
/* ------------------------------------------------------------------ */

const NODE_TYPE_COLORS: Record<string, string> = {
  code: '#3b82f6',
  concept: '#22c55e',
  entity: '#f97316',
  document: '#a855f7',
  topic: '#ef4444',
};

const NODE_TYPE_DEFAULT = '#6b7280';

const RELATION_COLORS: Record<string, string> = {
  relates_to: '#6366f1',
  depends_on: '#f59e0b',
  part_of: '#10b981',
  similar_to: '#06b6d4',
  references: '#8b5cf6',
  implements: '#ec4899',
  extends: '#3b82f6',
  contains: '#14b8a6',
};

const COMMUNITY_PALETTE = [
  '#6366f1', '#ec4899', '#14b8a6', '#f59e0b', '#8b5cf6',
  '#06b6d4', '#84cc16', '#f97316', '#3b82f6', '#22c55e',
  '#ef4444', '#a855f7', '#0ea5e9', '#d946ef', '#10b981',
];

function getNodeColors(type: string): string {
  return NODE_TYPE_COLORS[type] ?? NODE_TYPE_DEFAULT;
}

function getCommunityColor(id: number): string {
  return COMMUNITY_PALETTE[id % COMMUNITY_PALETTE.length];
}

function getRelationColor(relation: string): string {
  return RELATION_COLORS[relation] ?? '#6b7280';
}

function truncateLabel(label: string, maxLen = 20): string {
  if (label.length <= maxLen) return label;
  return label.slice(0, maxLen - 1) + '…';
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const MAX_INITIAL_NODES = 500;
const NODE_TYPE_OPTIONS = ['code', 'concept', 'entity', 'document', 'topic'] as const;

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function GraphViz() {
  const [, navigate] = useLocation();

  // Refs
  const svgRef = useRef<SVGSVGElement>(null);
  const simulationRef = useRef<ReturnType<typeof forceSimulation<GraphNode>> | null>(null);
  const zoomBehaviorRef = useRef<any>(null);

  // Data state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [allNodes, setAllNodes] = useState<GraphNode[]>([]);
  const [allEdges, setAllEdges] = useState<GraphEdge[]>([]);
  const [showAll, setShowAll] = useState(false);

  // UI state
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; node: GraphNode } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showLabels, setShowLabels] = useState(true);
  const [physicsEnabled, setPhysicsEnabled] = useState(true);
  const [colorByCommunity, setColorByCommunity] = useState(false);
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set(NODE_TYPE_OPTIONS));
  const [nodeCount, setNodeCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);
  const [communityCount, setCommunityCount] = useState(0);

  /* ---------- Derived data ---------- */

  const filteredNodes = useMemo(() => {
    let result = showAll ? allNodes : allNodes.slice(0, MAX_INITIAL_NODES);
    result = result.filter((n) => selectedTypes.has(n.node_type));
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter((n) => n.label.toLowerCase().includes(q));
    }
    return result;
  }, [allNodes, showAll, selectedTypes, searchQuery]);

  const filteredNodeIds = useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes]);

  const filteredEdges = useMemo(() => {
    return allEdges.filter(
      (e) =>
        filteredNodeIds.has((e.source as GraphNode).id || (e.source as string)) &&
        filteredNodeIds.has((e.target as GraphNode).id || (e.target as string)),
    );
  }, [allEdges, filteredNodeIds]);

  /* ---------- Data loading ---------- */

  const loadGraphData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [fetchedNodes, fetchedEdges] = await Promise.all([
        fetchNodes(),
        fetchEdges(),
      ]);

      // Build degree map
      const degreeMap = new Map<string, number>();
      for (const e of fetchedEdges) {
        degreeMap.set(e.sourceNodeId, (degreeMap.get(e.sourceNodeId) || 0) + 1);
        degreeMap.set(e.targetNodeId, (degreeMap.get(e.targetNodeId) || 0) + 1);
      }

      // Build community set
      const communities = new Set<number>();

      const graphNodes: GraphNode[] = fetchedNodes.map((n) => {
        if (n.communityId) communities.add(Number(n.communityId));
        return {
          id: n.id,
          label: n.label,
          node_type: n.nodeType,
          summary: n.summary ?? '',
          community_id: Number(n.communityId) || 0,
          strength: 0,
          degree: 0,
        };
      });

      const nodeMap = new Map(graphNodes.map((n) => [n.id, n]));

      const graphEdges: GraphEdge[] = fetchedEdges
        .filter((e) => nodeMap.has(e.sourceNodeId) && nodeMap.has(e.targetNodeId))
        .map((e) => ({
          id: e.id,
          source: e.sourceNodeId,
          target: e.targetNodeId,
          relation: e.relation,
          weight: e.weight ?? 1,
          confidence: e.confidence ?? 'EXTRACTED',
        }))

      setAllNodes(graphNodes);
      setAllEdges(graphEdges);
      setCommunityCount(communities.size);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load graph data';
      setError(msg);
      console.error('GraphViz load error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadGraphData();
    return () => {
      if (simulationRef.current) {
        simulationRef.current.stop();
        simulationRef.current = null;
      }
    };
  }, [loadGraphData]);

  /* ---------- D3 graph rendering ---------- */

  useEffect(() => {
    if (loading || error || filteredNodes.length === 0 || !svgRef.current) return;

    setNodeCount(filteredNodes.length);
    setEdgeCount(filteredEdges.length);

    const svg = select(svgRef.current);
    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;

    // Clear previous
    svg.selectAll('*').remove();
    if (simulationRef.current) {
      simulationRef.current.stop();
      simulationRef.current = null;
    }

    // Build the main group for zoom/pan
    const g = svg.append('g').attr('class', 'graph-group');

    // Defs for arrow markers
    const defs = svg.append('defs');
    const relationTypes = [...new Set(filteredEdges.map((e) => e.relation))];
    relationTypes.forEach((rel) => {
      defs
        .append('marker')
        .attr('id', `arrow-${rel.replace(/\s+/g, '-')}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 22)
        .attr('refY', 0)
        .attr('markerWidth', 8)
        .attr('markerHeight', 8)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', getRelationColor(rel));
    });

    // Edges
    const edgeGroup = g.append('g').attr('class', 'edges');
    const edgeElements = edgeGroup
      .selectAll<SVGLineElement, GraphEdge>('line')
      .data(filteredEdges)
      .join('line')
      .attr('stroke', (d) => getRelationColor(d.relation))
      .attr('stroke-width', (d) => Math.max(0.5, Math.min(d.weight * 2, 5)))
      .attr('stroke-opacity', (d) => 0.3 + Math.min(d.weight, 1) * 0.5)
      .attr('marker-end', (d) => `url(#arrow-${d.relation.replace(/\s+/g, '-')})`)
      .attr('data-id', (d) => d.id);

    // Nodes group
    const nodeGroup = g.append('g').attr('class', 'nodes');

    // Create node visual elements
    const nodeElements = nodeGroup
      .selectAll<SVGGElement, GraphNode>('g.node')
      .data(filteredNodes)
      .join('g')
      .attr('class', 'node')
      .attr('data-id', (d) => d.id)
      .style('cursor', 'pointer');

    // Node circles
    nodeElements
      .append('circle')
      .attr('r', (d) => {
        const base = 5;
        const strengthBonus = Math.min(d.strength / 10, 10);
        const degreeBonus = Math.min(d.degree * 0.5, 5);
        return base + strengthBonus + degreeBonus;
      })
      .attr('fill', (d) =>
        colorByCommunity ? getCommunityColor(d.community_id) : getNodeColors(d.node_type),
      )
      .attr('stroke', (d) => {
        if (d.id === hoveredNode || d.id === selectedNode?.id) return '#fff';
        return colorByCommunity ? getCommunityColor(d.community_id) : getNodeColors(d.node_type);
      })
      .attr('stroke-width', (d) => {
        if (d.id === hoveredNode || d.id === selectedNode?.id) return 3;
        return 1.5;
      })
      .attr('stroke-opacity', 0.8);

    // Node labels
    const labelElements = nodeElements
      .append('text')
      .text((d) => truncateLabel(d.label))
      .attr('dx', (d) => {
        const r = 5 + Math.min(d.strength / 10, 10) + Math.min(d.degree * 0.5, 5);
        return r + 4;
      })
      .attr('dy', '0.35em')
      .attr('font-size', '11px')
      .attr('fill', '#e5e7eb')
      .attr('stroke', '#1f2937')
      .attr('stroke-width', 0.5)
      .attr('paint-order', 'stroke')
      .attr('pointer-events', 'none')
      .style('font-family', 'Inter, system-ui, sans-serif')
      .style('visibility', (d) => {
        // Hide label for very small/weak nodes if too many are visible
        if (filteredNodes.length > 200) {
          const r = 5 + Math.min(d.strength / 10, 10) + Math.min(d.degree * 0.5, 5);
          if (r < 10) return 'hidden';
        }
        return showLabels ? 'visible' : 'hidden';
      });

    // Also show labels on hover for hidden ones
    nodeElements.on('mouseenter', function (_event, d) {
      labelElements
        .filter((ld) => ld.id === d.id)
        .style('visibility', 'visible');
    });
    nodeElements.on('mouseleave', function () {
      if (!showLabels) {
        labelElements.style('visibility', 'hidden');
      } else if (filteredNodes.length > 200) {
        labelElements.style('visibility', (d) => {
          const r = 5 + Math.min(d.strength / 10, 10) + Math.min(d.degree * 0.5, 5);
          return r < 10 ? 'hidden' : 'visible';
        });
      }
    });

    // --- Drag behavior ---
    const drag = d3Drag<SVGGElement, GraphNode>()
      .on('start', (event, d) => {
        if (!event.active && simulationRef.current) simulationRef.current.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active && simulationRef.current) simulationRef.current.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeElements.call(drag as any);

    // --- Zoom behavior ---
    const zoom = d3Zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 8])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);
    zoomBehaviorRef.current = zoom;

    // --- Simulation ---
    const simulation = forceSimulation<GraphNode>(filteredNodes)
      .force(
        'link',
        forceLink<GraphNode, GraphEdge>(filteredEdges)
          .id((d) => d.id)
          .distance((d) => 80 + (1 - Math.min(d.weight, 1)) * 100)
          .strength((d) => 0.3 + Math.min(d.weight, 1) * 0.5),
      )
      .force('charge', forceManyBody().strength(-150))
      .force('center', forceCenter(width / 2, height / 2))
      .force('collide', forceCollide<GraphNode>().radius((d) => {
        const r = 5 + Math.min(d.strength / 10, 10) + Math.min(d.degree * 0.5, 5);
        return r + 5;
      }));

    simulationRef.current = simulation;

    simulation.on('tick', () => {
      edgeElements
        .attr('x1', (d) => (d.source as GraphNode).x ?? 0)
        .attr('y1', (d) => (d.source as GraphNode).y ?? 0)
        .attr('x2', (d) => (d.target as GraphNode).x ?? 0)
        .attr('y2', (d) => (d.target as GraphNode).y ?? 0);

      nodeElements.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Stop simulation if physics disabled
    if (!physicsEnabled) {
      simulation.stop();
    }

    return () => {
      simulation.stop();
      svg.selectAll('*').remove();
    };
  }, [filteredNodes, filteredEdges, loading, error, hoveredNode, selectedNode, showLabels, physicsEnabled, colorByCommunity]);

  /* ---------- Hover highlight ---------- */

  useEffect(() => {
    const svg = select(svgRef.current);
    if (!svg.node()) return;

    const edgeElements = svg.selectAll<SVGLineElement, GraphEdge>('.edges line');
    const nodeElements = svg.selectAll<SVGGElement, GraphNode>('.node');
    const labelElements = svg.selectAll<SVGTextElement, GraphNode>('.node text');

    if (!hoveredNode) {
      // Restore opacity
      nodeElements
        .select('circle')
        .attr('opacity', 1)
        .attr('stroke-width', (d: any) => (d.id === selectedNode?.id ? 3 : 1.5))
        .attr('stroke-opacity', 0.8);

      edgeElements.attr('stroke-opacity', (d) => 0.3 + Math.min(d.weight, 1) * 0.5).attr('opacity', 1);

      labelElements.attr('opacity', 1);
      return;
    }

    // Find connected node IDs
    const connectedIds = new Set<string>();
    connectedIds.add(hoveredNode);
    for (const e of allEdges) {
      const sourceId = (e.source as GraphNode).id || (e.source as string);
      const targetId = (e.target as GraphNode).id || (e.target as string);
      if (sourceId === hoveredNode) connectedIds.add(targetId);
      if (targetId === hoveredNode) connectedIds.add(sourceId);
    }

    // Dim non-connected, highlight connected
    nodeElements
      .select('circle')
      .attr('opacity', (d: any) => (connectedIds.has(d.id) ? 1 : 0.15))
      .attr('stroke-width', (d: any) => {
        if (d.id === hoveredNode) return 3;
        if (d.id === selectedNode?.id && connectedIds.has(d.id)) return 3;
        return connectedIds.has(d.id) ? 2 : 1;
      })
      .attr('stroke-opacity', (d: any) => (connectedIds.has(d.id) ? 1 : 0.2));

    edgeElements
      .attr('stroke-opacity', (d: any) => {
        const sourceId = (d.source as GraphNode).id || (d.source as string);
        const targetId = (d.target as GraphNode).id || (d.target as string);
        if (sourceId === hoveredNode || targetId === hoveredNode) return 0.8;
        return 0.05;
      })
      .attr('opacity', (d: any) => {
        const sourceId = (d.source as GraphNode).id || (d.source as string);
        const targetId = (d.target as GraphNode).id || (d.target as string);
        if (sourceId === hoveredNode || targetId === hoveredNode) return 1;
        return 0.1;
      });

    labelElements.attr('opacity', (d: any) => (connectedIds.has(d.id) ? 1 : 0.15));
  }, [hoveredNode, selectedNode, allEdges]);

  /* ---------- Event handlers (D3) ---------- */

  useEffect(() => {
    const svg = select(svgRef.current);
    if (!svg.node()) return;

    // Click handlers on nodes
    svg.selectAll<SVGGElement, GraphNode>('.node').on('click', function (event, d) {
      event.stopPropagation();
      setSelectedNode(d);
      setContextMenu(null);
    });

    // Click on background to deselect
    svg.on('click', function () {
      setSelectedNode(null);
      setContextMenu(null);
    });

    // Hover handlers
    svg.selectAll<SVGGElement, GraphNode>('.node').on('mouseenter', function (_event, d) {
      setHoveredNode(d.id);
    });

    svg.selectAll<SVGGElement, GraphNode>('.node').on('mouseleave', function () {
      setHoveredNode(null);
    });

    // Right-click context menu
    svg.selectAll<SVGGElement, GraphNode>('.node').on('contextmenu', function (event, d) {
      event.preventDefault();
      event.stopPropagation();
      setContextMenu({ x: event.offsetX || event.clientX, y: event.offsetY || event.clientY, node: d });
    });
  }, [filteredNodes, filteredEdges, loading, error]);

  /* ---------- Zoom handlers ---------- */

  const zoomIn = useCallback(() => {
    const el = svgRef.current;
    if (zoomBehaviorRef.current && el) {
      zoomBehaviorRef.current.scaleBy(select(el) as any, 1.3);
    }
  }, []);

  const zoomOut = useCallback(() => {
    const el = svgRef.current;
    if (zoomBehaviorRef.current && el) {
      zoomBehaviorRef.current.scaleBy(select(el) as any, 1 / 1.3);
    }
  }, []);

  const resetZoom = useCallback(() => {
    const el = svgRef.current;
    if (zoomBehaviorRef.current && el) {
      zoomBehaviorRef.current.transform(select(el) as any, zoomIdentity);
    }
  }, []);

  /* ---------- Neighbors for selected node ---------- */

  const neighbors = useMemo<NeighborInfo[]>(() => {
    if (!selectedNode) return [];
    const result: NeighborInfo[] = [];
    const nodeMap = new Map(allNodes.map((n) => [n.id, n]));
    for (const e of allEdges) {
      const sourceId = (e.source as GraphNode).id || (e.source as string);
      const targetId = (e.target as GraphNode).id || (e.target as string);
      if (sourceId === selectedNode.id) {
        const neighbor = nodeMap.get(targetId);
        if (neighbor) result.push({ node: neighbor, edge: e });
      } else if (targetId === selectedNode.id) {
        const neighbor = nodeMap.get(sourceId);
        if (neighbor) result.push({ node: neighbor, edge: e });
      }
    }
    return result;
  }, [selectedNode, allNodes, allEdges]);

  /* ---------- Toggle node type filter ---------- */

  const toggleType = useCallback((type: string) => {
    setSelectedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  /* ---------- Render ---------- */

  // --- Loading skeleton ---
  if (loading) {
    return (
      <div className="flex h-[calc(100vh-6rem)] flex-col gap-4">
        <div className="flex shrink-0 items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Graph Visualization</h1>
            <p className="text-muted-foreground">Interactive force-directed knowledge graph</p>
          </div>
        </div>
        <div className="flex flex-1 gap-4 overflow-hidden">
          <div className="relative flex-1 overflow-hidden rounded-lg border border-border bg-card">
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <Loader2 className="mx-auto h-10 w-10 animate-spin text-muted-foreground" />
                <p className="mt-3 text-sm text-muted-foreground">Building graph layout…</p>
                <p className="mt-1 text-xs text-muted-foreground/60">
                  Running force simulation on {allNodes.length || '…'} nodes
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // --- Error state ---
  if (error) {
    return (
      <div className="flex h-[calc(100vh-6rem)] flex-col gap-4">
        <div className="flex shrink-0 items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Graph Visualization</h1>
            <p className="text-muted-foreground">Interactive force-directed knowledge graph</p>
          </div>
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
  if (!loading && allNodes.length === 0) {
    return (
      <div className="flex h-[calc(100vh-6rem)] flex-col gap-4">
        <div className="flex shrink-0 items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Graph Visualization</h1>
            <p className="text-muted-foreground">Interactive force-directed knowledge graph</p>
          </div>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Network className="h-12 w-12 text-muted-foreground/40" />
            <h2 className="mt-4 text-lg font-semibold">No graph data yet</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Create some KG nodes to see the graph
            </p>
            <Button
              className="mt-4"
              variant="outline"
              onClick={() => navigate('/graph')}
            >
              <GitFork className="mr-2 h-4 w-4" />
              Go to Knowledge Graph
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const hasMore = allNodes.length > MAX_INITIAL_NODES && !showAll;

  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col gap-0">
      {/* Stats bar */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-card px-4 py-2">
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-1.5">
            <Network className="h-4 w-4 text-primary" />
            <span className="font-medium">{nodeCount}</span>
            <span className="text-muted-foreground">nodes</span>
          </div>
          <div className="flex items-center gap-1.5">
            <GitFork className="h-4 w-4 text-primary" />
            <span className="font-medium">{edgeCount}</span>
            <span className="text-muted-foreground">edges</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Layers className="h-4 w-4 text-primary" />
            <span className="font-medium">{communityCount}</span>
            <span className="text-muted-foreground">communities</span>
          </div>
          {selectedNode && (
            <div className="flex items-center gap-1.5 border-l border-border pl-3">
              <Info className="h-4 w-4 text-blue-400" />
              <span className="font-medium text-blue-400">
                {truncateLabel(selectedNode.label, 30)}
              </span>
              <Badge variant="outline" className="text-[10px] capitalize">
                {selectedNode.node_type}
              </Badge>
            </div>
          )}
        </div>
        {hasMore && (
          <Button variant="ghost" size="sm" className="text-xs h-7" onClick={() => setShowAll(true)}>
            Show all {allNodes.length} nodes
          </Button>
        )}
      </div>

      {/* Main area */}
      <div className="relative flex flex-1 overflow-hidden">
        {/* SVG canvas */}
        <div className="relative flex-1 overflow-hidden">
          <svg
            ref={svgRef}
            className="h-full w-full bg-background"
            style={{ cursor: 'grab' }}
          />

          {/* Search overlay */}
          <div className="absolute left-4 top-4 z-10 flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search nodes…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-9 w-52 pl-8 text-xs"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            {searchQuery && (
              <Badge variant="secondary" className="text-xs">
                {filteredNodes.length} match
                {filteredNodes.length !== 1 ? 'es' : ''}
              </Badge>
            )}
          </div>
        </div>

        {/* Controls panel (top-right overlay) */}
        <div className="absolute right-4 top-4 z-10 flex flex-col gap-2">
          {/* Zoom controls */}
          <Card className="shadow-lg">
            <CardContent className="flex flex-col gap-0.5 p-1">
              <button
                onClick={zoomIn}
                className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                title="Zoom in"
                type="button"
              >
                <ZoomIn className="h-4 w-4" />
              </button>
              <button
                onClick={zoomOut}
                className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                title="Zoom out"
                type="button"
              >
                <ZoomOut className="h-4 w-4" />
              </button>
              <button
                onClick={resetZoom}
                className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                title="Reset zoom"
                type="button"
              >
                <Maximize2 className="h-4 w-4" />
              </button>
            </CardContent>
          </Card>

          {/* View settings */}
          <Card className="w-48 shadow-lg">
            <CardContent className="space-y-2 p-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                View
              </p>

              {/* Toggle labels */}
              <button
                onClick={() => setShowLabels(!showLabels)}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              >
                {showLabels ? (
                  <Eye className="h-3.5 w-3.5" />
                ) : (
                  <EyeOff className="h-3.5 w-3.5" />
                )}
                Labels {showLabels ? 'on' : 'off'}
              </button>

              {/* Toggle physics */}
              <button
                onClick={() => setPhysicsEnabled(!physicsEnabled)}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              >
                {physicsEnabled ? (
                  <ToggleRight className="h-3.5 w-3.5 text-primary" />
                ) : (
                  <ToggleLeft className="h-3.5 w-3.5" />
                )}
                Physics {physicsEnabled ? 'on' : 'off'}
              </button>

              {/* Community color toggle */}
              <button
                onClick={() => setColorByCommunity(!colorByCommunity)}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              >
                <Layers className="h-3.5 w-3.5" />
                Color by
                {colorByCommunity ? ' community' : ' type'}
              </button>
            </CardContent>
          </Card>

          {/* Type filter */}
          <Card className="w-48 shadow-lg">
            <CardContent className="space-y-1.5 p-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                Filter by type
              </p>
              {NODE_TYPE_OPTIONS.map((type) => (
                <label
                  key={type}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                >
                  <input
                    type="checkbox"
                    checked={selectedTypes.has(type)}
                    onChange={() => toggleType(type)}
                    className="h-3 w-3 rounded border-border"
                    style={{ accentColor: getNodeColors(type) }}
                  />
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ backgroundColor: getNodeColors(type) }}
                  />
                  <span className="capitalize">{type}</span>
                  <span className="ml-auto text-[10px] text-muted-foreground/50">
                    {allNodes.filter((n) => n.node_type === type).length}
                  </span>
                </label>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Details panel (sliding sidebar) */}
        {selectedNode && (
          <div className="absolute bottom-0 right-0 top-0 z-20 w-80 border-l border-border bg-card shadow-lg overflow-y-auto">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold">
                {(() => {
                  const IconMap: Record<string, typeof Layers> = {
                    code: Code,
                    concept: Layers,
                    entity: GitBranch,
                    document: FileText,
                    topic: MessageSquare,
                  };
                  const Icon = IconMap[selectedNode.node_type] ?? Layers;
                  return <Icon className="h-4 w-4 text-muted-foreground" />;
                })()}
                Node Details
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => setSelectedNode(null)}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
            <div className="space-y-4 p-4">
              {/* Label */}
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">
                  Label
                </p>
                <p className="mt-0.5 text-sm font-medium">{selectedNode.label}</p>
              </div>

              {/* Type */}
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">
                  Type
                </p>
                <Badge
                  variant="outline"
                  className="mt-0.5 capitalize"
                  style={{
                    borderColor: getNodeColors(selectedNode.node_type),
                    color: getNodeColors(selectedNode.node_type),
                  }}
                >
                  {selectedNode.node_type}
                </Badge>
              </div>

              {/* Community */}
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">
                  Community
                </p>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <span
                    className="inline-block h-3 w-3 rounded-full"
                    style={{ backgroundColor: getCommunityColor(selectedNode.community_id) }}
                  />
                  <span className="text-xs text-muted-foreground">
                    Community #{selectedNode.community_id}
                  </span>
                </div>
              </div>

              {/* Strength / Degree */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">
                    Strength
                  </p>
                  <p className="mt-0.5 text-sm">{selectedNode.strength.toFixed(1)}</p>
                </div>
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">
                    Degree
                  </p>
                  <p className="mt-0.5 text-sm">{selectedNode.degree}</p>
                </div>
              </div>

              {/* Summary */}
              {selectedNode.summary && (
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">
                    Summary
                  </p>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                    {selectedNode.summary}
                  </p>
                </div>
              )}

              {/* Connected nodes */}
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">
                  Connections ({neighbors.length})
                </p>
                <div className="mt-1 max-h-40 space-y-1 overflow-y-auto">
                  {neighbors.slice(0, 30).map(({ node, edge }) => (
                    <button
                      key={`${node.id}-${edge.id}`}
                      onClick={() => setSelectedNode(node)}
                      className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-accent"
                    >
                      <span
                        className="inline-block h-2 w-2 shrink-0 rounded-full"
                        style={{
                          backgroundColor: colorByCommunity
                            ? getCommunityColor(node.community_id)
                            : getNodeColors(node.node_type),
                        }}
                      />
                      <span className="flex-1 truncate">{truncateLabel(node.label, 18)}</span>
                      <span className="shrink-0 text-[10px] text-muted-foreground/60">
                        {edge.relation}
                      </span>
                    </button>
                  ))}
                  {neighbors.length > 30 && (
                    <p className="text-[10px] text-muted-foreground/40 text-center">
                      +{neighbors.length - 30} more
                    </p>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div className="border-t border-border pt-3">
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full text-xs"
                  onClick={() => navigate(`/notes/${selectedNode.id}`)}
                >
                  <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                  Open in Notes
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Context menu */}
        {contextMenu && (
          <div
            className="fixed z-50 w-40 rounded-md border border-border bg-popover p-1 shadow-md"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <div className="px-2 py-1 text-xs font-medium text-muted-foreground/60 truncate">
              {truncateLabel(contextMenu.node.label, 24)}
            </div>
            <button
              onClick={() => {
                navigator.clipboard.writeText(contextMenu.node.id);
                setContextMenu(null);
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs text-foreground hover:bg-accent"
            >
              <Copy className="h-3.5 w-3.5" />
              Copy ID
            </button>
            <button
              onClick={() => {
                setSelectedNode(contextMenu.node);
                setContextMenu(null);
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs text-foreground hover:bg-accent"
            >
              <ChevronRight className="h-3.5 w-3.5" />
              Open Details
            </button>
            <button
              onClick={() => {
                navigate(`/notes/${contextMenu.node.id}`);
                setContextMenu(null);
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs text-foreground hover:bg-accent"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open in Notes
            </button>
          </div>
        )}

        {/* Click away handler for context menu */}
        {contextMenu && (
          <div
            className="fixed inset-0 z-40"
            onClick={() => setContextMenu(null)}
          />
        )}
      </div>
    </div>
  );
}
