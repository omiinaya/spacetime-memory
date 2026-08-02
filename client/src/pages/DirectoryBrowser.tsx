import { useState, useMemo, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  FolderTree,
  Folder,
  FolderOpen,
  FileText,
  ChevronRight,
  ChevronDown,
  AlertCircle,
  SortAsc,
  Home,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTable } from '@/lib/useReactiveDb';

interface ContextDirectoryRow {
  id: string;
  workspaceId: string;
  name: string;
  path: string;
  parentId: string;
  description: string;
  createdAt: number;
  updatedAt: number;
}

interface MemoryRow {
  id: string;
  workspaceId: string;
  content: string;
  summary: string;
  memoryType: string;
  tier: string;
  confidence: number;
  accessCount: number;
  strength: number;
  isActive: boolean;
  createdAt: number;
}

interface DirectoryMemoryLinkRow {
  id: string;
  directoryId: string;
  memoryId: string;
  workspaceId: string;
}

interface TreeNode {
  id: string;
  name: string;
  path: string;
  parentId: string;
  description: string;
  children: TreeNode[];
  depth: number;
}

type SortKey = 'tier' | 'createdAt' | 'confidence';

const tierColors: Record<string, string> = {
  L0: 'bg-green-500/10 text-green-600 border-green-200',
  L1: 'bg-blue-500/10 text-blue-600 border-blue-200',
  L2: 'bg-gray-500/10 text-gray-600 border-gray-200',
};

const memoryTypeColors: Record<string, string> = {
  world_fact: 'bg-blue-500/10 text-blue-600',
  experience: 'bg-green-500/10 text-green-600',
  mental_model: 'bg-purple-500/10 text-purple-600',
  consolidated: 'bg-orange-500/10 text-orange-600',
};

function buildTree(directories: ContextDirectoryRow[]): TreeNode[] {
  const map = new Map<string, TreeNode>();
  const roots: TreeNode[] = [];

  // First pass: create nodes
  for (const dir of directories) {
    map.set(dir.id, {
      id: dir.id,
      name: dir.name,
      path: dir.path,
      parentId: dir.parentId,
      description: dir.description,
      children: [],
      depth: 0,
    });
  }

  // Second pass: link children
  for (const dir of directories) {
    const node = map.get(dir.id)!;
    if (dir.parentId && map.has(dir.parentId)) {
      const parent = map.get(dir.parentId)!;
      parent.children.push(node);
      node.depth = parent.depth + 1;
    } else if (!dir.parentId) {
      roots.push(node);
    }
  }

  return roots;
}

function getBreadcrumbs(
  dirId: string,
  dirMap: Map<string, ContextDirectoryRow>
): ContextDirectoryRow[] {
  const crumbs: ContextDirectoryRow[] = [];
  let current = dirMap.get(dirId);
  while (current) {
    crumbs.unshift(current);
    current = current.parentId ? dirMap.get(current.parentId) : undefined;
  }
  return crumbs;
}

// ---------------------------------------------------------------------------
// TreeItem — recursive tree node
// ---------------------------------------------------------------------------
interface TreeItemProps {
  node: TreeNode;
  selectedId: string | null;
  expandedIds: Set<string>;
  onSelect: (id: string) => void;
  onToggle: (id: string) => void;
}

function TreeItem({ node, selectedId, expandedIds, onSelect, onToggle }: TreeItemProps) {
  const hasChildren = node.children.length > 0;
  const isExpanded = expandedIds.has(node.id);
  const isSelected = selectedId === node.id;

  return (
    <div>
      <button
        onClick={() => onSelect(node.id)}
        className={cn(
          'flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-sm transition-colors',
          isSelected
            ? 'bg-accent text-accent-foreground font-medium'
            : 'text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground'
        )}
        style={{ paddingLeft: `${node.depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          <span
            onClick={(e) => {
              e.stopPropagation();
              onToggle(node.id);
            }}
            className="shrink-0 cursor-pointer"
          >
            {isExpanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </span>
        ) : (
          <span className="w-3.5 shrink-0" />
        )}
        {isExpanded ? (
          <FolderOpen className="h-4 w-4 shrink-0 text-amber-500" />
        ) : (
          <Folder className="h-4 w-4 shrink-0 text-amber-500" />
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {hasChildren && isExpanded && (
        <div>
          {node.children.map((child) => (
            <TreeItem
              key={child.id}
              node={child}
              selectedId={selectedId}
              expandedIds={expandedIds}
              onSelect={onSelect}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------
export default function DirectoryBrowser() {
  const { data: directories, loading: dirsLoading, error: dirsError } =
    useTable<ContextDirectoryRow>('contextDirectory');
  const { data: memories, loading: memsLoading } = useTable<MemoryRow>('memory');
  const { data: links, loading: linksLoading } = useTable<DirectoryMemoryLinkRow>('directoryMemoryLink');

  const [selectedDirId, setSelectedDirId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>('createdAt');
  const [tierFilters, setTierFilters] = useState<Set<string>>(new Set(['L0', 'L1', 'L2']));

  const dirMap = useMemo(() => {
    const map = new Map<string, ContextDirectoryRow>();
    for (const d of directories) map.set(d.id, d);
    return map;
  }, [directories]);

  const tree = useMemo(() => buildTree(directories), [directories]);

  const breadcrumbs = useMemo(
    () => (selectedDirId ? getBreadcrumbs(selectedDirId, dirMap) : []),
    [selectedDirId, dirMap]
  );

  const selectedDir = selectedDirId ? dirMap.get(selectedDirId) : null;

  const childCount = useMemo(
    () => directories.filter((d) => d.parentId === selectedDirId).length,
    [directories, selectedDirId]
  );

  const linkedMemoryIds = useMemo(
    () =>
      links
        .filter((l) => l.directoryId === selectedDirId)
        .map((l) => l.memoryId),
    [links, selectedDirId]
  );

  const linkedMemories = useMemo(() => {
    const memSet = new Set(linkedMemoryIds);
    return memories.filter((m) => memSet.has(m.id));
  }, [memories, linkedMemoryIds]);

  const filteredMemories = useMemo(() => {
    let result = linkedMemories.filter((m) => tierFilters.has(m.tier));
    result.sort((a, b) => {
      switch (sortKey) {
        case 'tier':
          return a.tier.localeCompare(b.tier);
        case 'confidence':
          return b.confidence - a.confidence;
        case 'createdAt':
        default:
          return (b.createdAt ?? 0) - (a.createdAt ?? 0);
      }
    });
    return result;
  }, [linkedMemories, tierFilters, sortKey]);

  const tierStats = useMemo(() => {
    const stats: Record<string, number> = { L0: 0, L1: 0, L2: 0 };
    for (const m of linkedMemories) {
      if (stats[m.tier] !== undefined) stats[m.tier]++;
    }
    return stats;
  }, [linkedMemories]);

  const handleSelect = useCallback((id: string) => {
    setSelectedDirId(id);
  }, []);

  const handleToggle = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleTierFilter = useCallback((tier: string) => {
    setTierFilters((prev) => {
      const next = new Set(prev);
      if (next.has(tier)) next.delete(tier);
      else next.add(tier);
      return next;
    });
  }, []);

  const loading = dirsLoading || memsLoading || linksLoading;
  const error = dirsError;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Directory Tree Browser</h1>
        <p className="text-muted-foreground">
          {loading ? 'Loading...' : `${directories.length} director${directories.length === 1 ? 'y' : 'ies'}`}
        </p>
      </div>

      <div className="flex gap-6">
        {/* ── Left panel — Tree view ── */}
        <Card className="w-80 shrink-0">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <FolderTree className="h-4 w-4" />
              Directories
            </CardTitle>
          </CardHeader>
          <CardContent className="p-2">
            {error ? (
              <div className="flex items-center gap-2 px-2 py-4 text-destructive text-sm">
                <AlertCircle className="h-4 w-4" />
                <p>{error}</p>
              </div>
            ) : loading ? (
              <div className="space-y-2 px-2 py-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="h-5 rounded bg-muted animate-pulse" />
                ))}
              </div>
            ) : tree.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                <FolderTree className="h-8 w-8 mb-2 opacity-30" />
                <p className="text-sm font-medium">No directories</p>
                <p className="text-xs mt-1">Create a directory to see it here.</p>
              </div>
            ) : (
              <div className="space-y-0.5">
                {tree.map((node) => (
                  <TreeItem
                    key={node.id}
                    node={node}
                    selectedId={selectedDirId}
                    expandedIds={expandedIds}
                    onSelect={handleSelect}
                    onToggle={handleToggle}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Right panel — Directory details ── */}
        <div className="flex-1 space-y-4">
          {!selectedDir ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                <FolderTree className="h-12 w-12 mb-4 opacity-30" />
                <p className="font-medium">Select a directory</p>
                <p className="text-sm mt-1">Choose a directory from the tree to view its details.</p>
              </CardContent>
            </Card>
          ) : (
            <>
              {/* Breadcrumb */}
              <nav className="flex items-center gap-1 text-sm text-muted-foreground">
                <Home className="h-3.5 w-3.5" />
                {breadcrumbs.map((crumb, i) => (
                  <span key={crumb.id} className="flex items-center gap-1">
                    <span className="mx-1">&rsaquo;</span>
                    <button
                      onClick={() => handleSelect(crumb.id)}
                      className={cn(
                        'hover:text-foreground transition-colors',
                        i === breadcrumbs.length - 1 ? 'text-foreground font-medium' : ''
                      )}
                    >
                      {crumb.name}
                    </button>
                  </span>
                ))}
              </nav>

              {/* Directory info card */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Folder className="h-5 w-5 text-amber-500" />
                    {selectedDir.name}
                  </CardTitle>
                  <CardDescription>
                    <span className="block text-xs font-mono text-muted-foreground/60">
                      {selectedDir.path}
                    </span>
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className="rounded-lg border border-border p-3 text-center">
                      <p className="text-2xl font-bold">{childCount}</p>
                      <p className="text-xs text-muted-foreground">Sub-directories</p>
                    </div>
                    <div className="rounded-lg border border-border p-3 text-center">
                      <p className="text-2xl font-bold">{linkedMemories.length}</p>
                      <p className="text-xs text-muted-foreground">Linked Memories</p>
                    </div>
                    <div className="rounded-lg border border-border p-3 text-center">
                      <p className="text-2xl font-bold">
                        {Object.values(tierStats).reduce((a, b) => a + b, 0)}
                      </p>
                      <p className="text-xs text-muted-foreground">Total</p>
                    </div>
                  </div>

                  {selectedDir.description && (
                    <p className="text-sm text-muted-foreground border-t border-border pt-3">
                      {selectedDir.description}
                    </p>
                  )}

                  {/* Tier stats */}
                  <div className="flex gap-3 mt-3 border-t border-border pt-3">
                    {(['L0', 'L1', 'L2'] as const).map((tier) => (
                      <div key={tier} className="flex items-center gap-1.5">
                        <Badge
                          variant="outline"
                          className={cn('text-xs px-2 py-0', tierColors[tier] ?? '')}
                        >
                          {tier}
                        </Badge>
                        <span className="text-sm font-medium">{tierStats[tier] ?? 0}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              {/* Memory list */}
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">Linked Memories</CardTitle>
                    <div className="flex items-center gap-2">
                      {/* Sort buttons */}
                      <div className="flex items-center gap-1">
                        <SortAsc className="h-3.5 w-3.5 text-muted-foreground" />
                        {(['createdAt', 'tier', 'confidence'] as SortKey[]).map((key) => (
                          <Button
                            key={key}
                            variant={sortKey === key ? 'secondary' : 'ghost'}
                            size="sm"
                            onClick={() => setSortKey(key)}
                            className="h-7 text-xs px-2"
                          >
                            {key === 'createdAt' ? 'Date' : key === 'tier' ? 'Tier' : 'Confidence'}
                          </Button>
                        ))}
                      </div>
                      {/* Tier filter checkboxes */}
                      <div className="flex items-center gap-1 ml-2 border-l border-border pl-2">
                        {(['L0', 'L1', 'L2'] as const).map((tier) => (
                          <button
                            key={tier}
                            onClick={() => toggleTierFilter(tier)}
                            className={cn(
                              'inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors',
                              tierFilters.has(tier)
                                ? 'bg-accent text-accent-foreground'
                                : 'text-muted-foreground hover:bg-accent/50'
                            )}
                          >
                            {tier}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {filteredMemories.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                      <FileText className="h-8 w-8 mb-2 opacity-30" />
                      <p className="text-sm font-medium">No memories linked</p>
                      <p className="text-xs mt-1">
                        {linkedMemories.length > 0
                          ? 'Try adjusting the tier filters.'
                          : 'Link memories to this directory to see them here.'}
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {filteredMemories.map((mem) => (
                        <div
                          key={mem.id}
                          className="flex items-start justify-between rounded-lg border border-border p-3"
                        >
                          <div className="min-w-0 flex-1 mr-3">
                            <p className="text-sm font-medium truncate max-w-[500px]">
                              {mem.summary || mem.content.slice(0, 120)}
                            </p>
                            <p className="text-xs text-muted-foreground mt-1 truncate max-w-[500px]">
                              {mem.content.slice(0, 150)}
                              {mem.content.length > 150 ? '…' : ''}
                            </p>
                            <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                              <span>{(mem.confidence * 100).toFixed(0)}% confidence</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <Badge
                              variant="outline"
                              className={cn('text-xs', memoryTypeColors[mem.memoryType] ?? '')}
                            >
                              {mem.memoryType}
                            </Badge>
                            <Badge
                              variant="outline"
                              className={cn('text-xs', tierColors[mem.tier] ?? '')}
                            >
                              {mem.tier}
                            </Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
