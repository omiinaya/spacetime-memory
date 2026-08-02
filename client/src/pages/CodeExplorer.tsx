import { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useTable } from '@/lib/useReactiveDb';
import {
  Code,
  FileJson,
  Search,
  Network,
  FolderTree,
  AlertCircle,
  X,
  Hash,
  ArrowRight,
  Layers,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Type definitions                                                   */
/* ------------------------------------------------------------------ */

interface KGNodeRow {
  id: string;
  workspace_id: string;
  label: string;
  node_type: string;
  summary: string;
  metadata_json: string;
  community_id: number;
  strength: number;
  created_at: number;
}

interface KGEdgeRow {
  id: string;
  workspace_id: string;
  source_node_id: string;
  target_node_id: string;
  relation: string;
  weight: number;
  confidence: string;
}

/* ------------------------------------------------------------------ */
/*  Colour helpers                                                     */
/* ------------------------------------------------------------------ */

const TIER_COLORS: Record<string, string> = {
  code: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
  concept: 'bg-green-500/10 text-green-600 border-green-500/20',
  entity: 'bg-orange-500/10 text-orange-600 border-orange-500/20',
  document: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
};

function nodeTypeBadge(type: string) {
  return TIER_COLORS[type] ?? 'bg-gray-500/10 text-gray-600 border-gray-500/20';
}

/* ------------------------------------------------------------------ */
/*  Skeleton                                                           */
/* ------------------------------------------------------------------ */

function ExplorerSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 rounded-lg border border-border p-3">
          <div className="h-4 w-4 rounded bg-muted animate-pulse" />
          <div className="flex-1 space-y-1">
            <div className="h-4 w-3/5 rounded bg-muted animate-pulse" />
            <div className="h-3 w-2/5 rounded bg-muted animate-pulse" />
          </div>
          <div className="h-5 w-14 rounded-full bg-muted animate-pulse" />
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function CodeExplorer() {
  const {
    data: rawNodes,
    loading: nodesLoading,
    error: nodesError,
  } = useTable<KGNodeRow>('kg_node');
  const {
    data: rawEdges,
    loading: edgesLoading,
  } = useTable<KGEdgeRow>('kg_edge');

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState('files');

  // Filter to code nodes only
  const codeNodes = useMemo(
    () => rawNodes.filter((n) => n.node_type === 'code'),
    [rawNodes],
  );

  // Filter by search
  const filteredNodes = useMemo(
    () =>
      searchQuery.trim()
        ? codeNodes.filter((n) =>
            n.label.toLowerCase().includes(searchQuery.toLowerCase()),
          )
        : codeNodes,
    [codeNodes, searchQuery],
  );

  const selectedNode = useMemo(
    () => (selectedNodeId ? codeNodes.find((n) => n.id === selectedNodeId) ?? null : null),
    [selectedNodeId, codeNodes],
  );

  // Connected edges for the selected node
  const connectedEdges = useMemo(() => {
    if (!selectedNode) return [];
    return rawEdges.filter(
      (e) =>
        e.source_node_id === selectedNode.id ||
        e.target_node_id === selectedNode.id,
    );
  }, [selectedNode, rawEdges]);

  // Connected nodes (the other end of each edge)
  const connectedNodes = useMemo(() => {
    const ids = new Set<string>();
    for (const e of connectedEdges) {
      if (e.source_node_id === selectedNode?.id) ids.add(e.target_node_id);
      if (e.target_node_id === selectedNode?.id) ids.add(e.source_node_id);
    }
    return rawNodes.filter((n) => ids.has(n.id));
  }, [connectedEdges, selectedNode, rawNodes]);

  // All edges relevant to displayed nodes (for Graph tab)
  const displayedNodeIds = useMemo(
    () => new Set(filteredNodes.map((n) => n.id)),
    [filteredNodes],
  );
  const relevantEdges = useMemo(
    () =>
      rawEdges.filter(
        (e) =>
          displayedNodeIds.has(e.source_node_id) &&
          displayedNodeIds.has(e.target_node_id),
      ),
    [rawEdges, displayedNodeIds],
  );

  const loading = nodesLoading || edgesLoading;
  const error = nodesError;

  /* ---------- Render helpers ---------- */

  function renderNodeListItem(node: KGNodeRow) {
    const isSelected = selectedNodeId === node.id;
    return (
      <button
        key={node.id}
        onClick={() => setSelectedNodeId(node.id)}
        className={`w-full text-left rounded-lg border p-3 transition-colors ${
          isSelected
            ? 'border-primary bg-accent'
            : 'border-border hover:bg-accent/50'
        }`}
      >
        <div className="flex items-start gap-3">
          <Code className="h-4 w-4 mt-0.5 shrink-0 text-blue-400" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate">{node.label}</p>
            {node.summary && (
              <p className="text-xs text-muted-foreground truncate mt-0.5">
                {node.summary}
              </p>
            )}
          </div>
          <Badge
            variant="outline"
            className={`text-[10px] shrink-0 ${nodeTypeBadge(node.node_type)}`}
          >
            {node.node_type}
          </Badge>
        </div>
      </button>
    );
  }

  function renderDetailsPanel() {
    if (!selectedNode) return null;

    return (
      <div className="space-y-4">
        {/* Node details */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Code className="h-4 w-4 text-blue-400" />
              Code Node
            </CardTitle>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setSelectedNodeId(null)}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-xs text-muted-foreground">Label</p>
              <p className="text-sm font-medium">{selectedNode.label}</p>
            </div>

            <div>
              <p className="text-xs text-muted-foreground">Type</p>
              <Badge
                variant="outline"
                className={`mt-0.5 capitalize ${nodeTypeBadge(selectedNode.node_type)}`}
              >
                {selectedNode.node_type}
              </Badge>
            </div>

            {selectedNode.community_id != null && (
              <div>
                <p className="text-xs text-muted-foreground">Community</p>
                <div className="mt-0.5 flex items-center gap-1">
                  <Hash className="h-3 w-3 text-muted-foreground" />
                  <span className="text-sm">{selectedNode.community_id}</span>
                </div>
              </div>
            )}

            {selectedNode.strength > 0 && (
              <div>
                <p className="text-xs text-muted-foreground">Strength</p>
                <div className="mt-0.5">
                  <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-blue-500"
                      style={{
                        width: `${Math.min(selectedNode.strength * 100, 100)}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs text-muted-foreground mt-0.5">
                    {(selectedNode.strength * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            )}

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

        {/* Connected nodes */}
        {connectedNodes.length > 0 && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Network className="h-4 w-4 text-muted-foreground" />
                Connections ({connectedNodes.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {connectedNodes.map((cn) => {
                const edge = connectedEdges.find(
                  (e) =>
                    (e.source_node_id === cn.id &&
                      e.target_node_id === selectedNode.id) ||
                    (e.target_node_id === cn.id &&
                      e.source_node_id === selectedNode.id),
                );
                const isSource =
                  edge?.source_node_id === selectedNode.id;
                return (
                  <button
                    key={cn.id}
                    onClick={() => setSelectedNodeId(cn.id)}
                    className="w-full text-left rounded-lg border border-border p-2.5 hover:bg-accent/50 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate flex-1">
                        {cn.label}
                      </span>
                      <Badge
                        variant="outline"
                        className="text-[10px] shrink-0"
                      >
                        {cn.node_type}
                      </Badge>
                    </div>
                    {edge && (
                      <div className="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
                        <Badge variant="secondary" className="text-[10px]">
                          {edge.relation}
                        </Badge>
                        <span className="text-muted-foreground/60">·</span>
                        <span>{(edge.weight * 100).toFixed(0)}%</span>
                        <ArrowRight
                          className={`h-3 w-3 ${
                            isSource ? 'text-green-400' : 'text-orange-400'
                          }`}
                        />
                        <span className="text-[10px]">
                          {isSource ? '→ target' : '← source'}
                        </span>
                      </div>
                    )}
                  </button>
                );
              })}
            </CardContent>
          </Card>
        )}
      </div>
    );
  }

  /* ---------- Loading skeleton ---------- */

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Code Explorer</h1>
          <p className="text-muted-foreground">
            Interactive code knowledge graph exploration.
          </p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Code Nodes</CardTitle>
          </CardHeader>
          <CardContent>
            <ExplorerSkeleton />
          </CardContent>
        </Card>
      </div>
    );
  }

  /* ---------- Error state ---------- */

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Code Explorer</h1>
          <p className="text-muted-foreground">
            Interactive code knowledge graph exploration.
          </p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <AlertCircle className="h-12 w-12 text-destructive" />
            <h2 className="mt-4 text-lg font-semibold">Failed to load</h2>
            <p className="mt-1 text-sm text-muted-foreground">{error}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  /* ---------- Empty state ---------- */

  if (codeNodes.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Code Explorer</h1>
          <p className="text-muted-foreground">
            Interactive code knowledge graph exploration.
          </p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Code className="h-12 w-12 text-muted-foreground/30 mb-4" />
            <p className="text-lg font-medium text-muted-foreground">
              No code nodes yet
            </p>
            <p className="text-sm text-muted-foreground/60 mt-1">
              Code nodes will appear as the knowledge graph processes source code.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  /* ---------- Main render ---------- */

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Code Explorer</h1>
        <p className="text-muted-foreground">
          {codeNodes.length} code node{codeNodes.length !== 1 ? 's' : ''} ·{' '}
          {rawEdges.length} edge{rawEdges.length !== 1 ? 's' : ''}
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="files" className="flex items-center gap-2">
            <FolderTree className="h-4 w-4" />
            Files
          </TabsTrigger>
          <TabsTrigger value="graph" className="flex items-center gap-2">
            <Network className="h-4 w-4" />
            Graph
          </TabsTrigger>
          <TabsTrigger value="search" className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            Search
          </TabsTrigger>
        </TabsList>

        {/* ============ Files tab ============ */}
        <TabsContent value="files">
          <div className="flex gap-4">
            {/* Left sidebar — node list */}
            <div className="w-80 shrink-0 space-y-3">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Filter code nodes…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 pr-8"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
              <div className="space-y-1.5 max-h-[60vh] overflow-y-auto pr-1">
                {filteredNodes.length === 0 ? (
                  <div className="text-center py-8 text-sm text-muted-foreground">
                    No nodes match your filter.
                  </div>
                ) : (
                  filteredNodes.map(renderNodeListItem)
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Showing {filteredNodes.length} of {codeNodes.length} code nodes
              </p>
            </div>

            {/* Right panel — details */}
            <div className="flex-1 min-w-0">
              {selectedNode ? (
                renderDetailsPanel()
              ) : (
                <Card>
                  <CardContent className="flex flex-col items-center justify-center py-16">
                    <FileJson className="h-12 w-12 text-muted-foreground/30 mb-4" />
                    <p className="text-lg font-medium text-muted-foreground">
                      Select a code node
                    </p>
                    <p className="text-sm text-muted-foreground/60 mt-1">
                      Click a node from the list to view its details and connections.
                    </p>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>

        {/* ============ Graph tab ============ */}
        <TabsContent value="graph">
          <div className="flex gap-4">
            {/* Left sidebar — search */}
            <div className="w-80 shrink-0 space-y-3">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Filter code nodes…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 pr-8"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {filteredNodes.length} node{filteredNodes.length !== 1 ? 's' : ''}{' '}
                · {relevantEdges.length} connection{relevantEdges.length !== 1 ? 's' : ''}
              </p>
            </div>

            {/* Right — connection list */}
            <div className="flex-1 min-w-0">
              {relevantEdges.length === 0 ? (
                <Card>
                  <CardContent className="flex flex-col items-center justify-center py-16">
                    <Network className="h-12 w-12 text-muted-foreground/30 mb-4" />
                    <p className="text-lg font-medium text-muted-foreground">
                      {searchQuery
                        ? 'No connections for filtered nodes'
                        : 'No connections yet'}
                    </p>
                    <p className="text-sm text-muted-foreground/60 mt-1">
                      Connections between code nodes appear as edges in the graph.
                    </p>
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-2 max-h-[65vh] overflow-y-auto pr-1">
                  {relevantEdges.map((edge) => {
                    const sourceNode = rawNodes.find(
                      (n) => n.id === edge.source_node_id,
                    );
                    const targetNode = rawNodes.find(
                      (n) => n.id === edge.target_node_id,
                    );
                    return (
                      <div
                        key={edge.id}
                        className="rounded-lg border border-border p-3 hover:bg-accent/50 transition-colors"
                      >
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium truncate min-w-0 flex-1">
                            {sourceNode?.label ?? edge.source_node_id.slice(0, 12)}
                          </span>
                          <Badge variant="secondary" className="text-[10px] shrink-0">
                            {edge.relation}
                          </Badge>
                          <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                          <span className="text-sm font-medium truncate min-w-0 flex-1 text-right">
                            {targetNode?.label ?? edge.target_node_id.slice(0, 12)}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                          <span>Weight: {(edge.weight * 100).toFixed(0)}%</span>
                          <span>·</span>
                          <span>Confidence: {edge.confidence}</span>
                          <span>·</span>
                          <Badge variant="outline" className="text-[10px]">
                            {sourceNode?.node_type ?? '?'} → {targetNode?.node_type ?? '?'}
                          </Badge>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </TabsContent>

        {/* ============ Search tab ============ */}
        <TabsContent value="search">
          <div className="flex gap-4">
            {/* Left sidebar */}
            <div className="w-80 shrink-0 space-y-3">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search code nodes…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 pr-8"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>

              {/* Search results */}
              <div className="space-y-1.5 max-h-[60vh] overflow-y-auto pr-1">
                {searchQuery.trim() ? (
                  filteredNodes.length === 0 ? (
                    <div className="text-center py-8 text-sm text-muted-foreground">
                      No code nodes match "{searchQuery}"
                    </div>
                  ) : (
                    filteredNodes.map(renderNodeListItem)
                  )
                ) : (
                  <div className="text-center py-8 text-sm text-muted-foreground">
                    <Search className="h-8 w-8 mx-auto mb-2 opacity-30" />
                    <p>Type a query to search code nodes</p>
                  </div>
                )}
              </div>
              {searchQuery.trim() && (
                <p className="text-xs text-muted-foreground">
                  {filteredNodes.length} result{filteredNodes.length !== 1 ? 's' : ''}
                </p>
              )}
            </div>

            {/* Right panel — details */}
            <div className="flex-1 min-w-0">
              {selectedNode ? (
                renderDetailsPanel()
              ) : (
                <Card>
                  <CardContent className="flex flex-col items-center justify-center py-16">
                    <Layers className="h-12 w-12 text-muted-foreground/30 mb-4" />
                    <p className="text-lg font-medium text-muted-foreground">
                      {searchQuery.trim()
                        ? 'Select a result'
                        : 'Search code nodes'}
                    </p>
                    <p className="text-sm text-muted-foreground/60 mt-1">
                      Use the search bar to find code nodes by label.
                    </p>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
