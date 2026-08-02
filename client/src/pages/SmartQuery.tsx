import { useState, useMemo, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useTable } from '@/lib/useReactiveDb';
import { callReducer, formatMemoryTimestamp } from '@/lib/spacetimedb';
import {
  Wand2,
  Search,
  Save,
  Play,
  FileJson,
  Database,
  FolderTree,
  Route,
  Sparkles,
  History,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Layers,
  CheckSquare,
  Square,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface MemoryRow {
  id: string;
  workspace_id: string;
  content: string;
  summary: string;
  memory_type: string;
  tier: string;
  confidence: number;
  trust_score: number;
  feedback_count: number;
  strength: number;
  is_active: boolean;
  created_at: number;
  updated_at: number;
}

interface KGNodeRow {
  id: string;
  workspace_id: string;
  label: string;
  node_type: string;
  summary: string;
  community_id: number;
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
  created_at: number;
}

interface ConsolidationLogRow {
  id: string;
  workspace_id: string;
  consolidation_type: string;
  source_memory_ids: string;
  target_memory_id: string;
  created_at: number;
}

interface SavedPreset {
  name: string;
  queryType: string;
  queryText: string;
  memoryTypes: string[];
  tiers: string[];
  nodeTypes: string[];
  limit: number;
  minConfidence: number;
  minStrength: number;
  dateFrom: string;
  dateTo: string;
  advanced: boolean;
}

interface QueryResult {
  id: string;
  entityType: 'memory' | 'kg_node' | 'kg_edge';
  label: string;
  excerpt: string;
  score: number;
  tier?: string;
  nodeType?: string;
  relation?: string;
  weight?: number;
  createdAt: number;
  raw: any;
}

// ---------------------------------------------------------------------------
// Default state
// ---------------------------------------------------------------------------
const defaultFilters = {
  memoryTypes: [] as string[],
  tiers: [] as string[],
  nodeTypes: [] as string[],
  limit: 20,
  minConfidence: 0,
  minStrength: 0,
  dateFrom: '',
  dateTo: '',
  advanced: false,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const memoryTypeOptions = ['world_fact', 'experience', 'mental_model'];
const tierOptions = ['L0', 'L1', 'L2'];
const nodeTypeOptions = ['concept', 'entity', 'event', 'document', 'person', 'place', 'organization'];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CheckboxGroup({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: string[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const toggle = (opt: string) => {
    if (selected.includes(opt)) {
      onChange(selected.filter((s) => s !== opt));
    } else {
      onChange([...selected, opt]);
    }
  };
  return (
    <div>
      <p className="text-xs text-muted-foreground mb-1.5">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => {
          const active = selected.includes(opt);
          return (
            <button
              key={opt}
              type="button"
              onClick={() => toggle(opt)}
              className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors ${
                active
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-input text-muted-foreground hover:bg-accent'
              }`}
            >
              {active ? <CheckSquare className="h-3 w-3" /> : <Square className="h-3 w-3" />}
              {opt}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ResultCard({
  result,
  selected,
  onToggleSelect,
}: {
  result: QueryResult;
  selected: boolean;
  onToggleSelect: (id: string) => void;
}) {
  const excerpt =
    result.excerpt.length > 120 ? result.excerpt.slice(0, 120) + '…' : result.excerpt;

  return (
    <div
      className={`flex items-start gap-3 rounded-lg border p-3 cursor-pointer transition-colors ${
        selected ? 'border-primary/50 bg-primary/5' : 'border-border hover:bg-muted/30'
      }`}
      onClick={() => onToggleSelect(result.id)}
    >
      {/* Selection check */}
      <div className="shrink-0 mt-0.5">
        {selected ? (
          <CheckSquare className="h-4 w-4 text-primary" />
        ) : (
          <Square className="h-4 w-4 text-muted-foreground" />
        )}
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate max-w-[400px]">{result.label}</p>
        <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-[400px]">{excerpt}</p>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <Badge variant="outline" className="text-[10px]">
            {result.entityType}
          </Badge>
          {result.tier && (
            <Badge variant="outline" className={`text-[10px] ${result.tier === 'L0' ? 'text-red-500 border-red-500/30' : result.tier === 'L1' ? 'text-blue-500 border-blue-500/30' : 'text-gray-500 border-gray-500/30'}`}>
              {result.tier}
            </Badge>
          )}
          {result.nodeType && (
            <Badge variant="secondary" className="text-[10px]">
              {result.nodeType}
            </Badge>
          )}
          {result.relation && (
            <Badge variant="outline" className="text-[10px] text-purple-500 border-purple-500/30">
              {result.relation}
            </Badge>
          )}
          <span className="text-[10px] text-muted-foreground">{formatMemoryTimestamp(result.createdAt)}</span>
        </div>
      </div>

      {/* Score */}
      <div className="shrink-0 text-right">
        <span className="text-sm font-mono font-medium">{result.score.toFixed(2)}</span>
        {result.weight !== undefined && (
          <p className="text-[10px] text-muted-foreground">w: {result.weight.toFixed(1)}</p>
        )}
      </div>
    </div>
  );
}

function CurationPanel({
  selectedIds,
  results,
  memoryData,
  onClose,
  onCurated,
}: {
  selectedIds: Set<string>;
  results: QueryResult[];
  memoryData: MemoryRow[];
  onClose: () => void;
  onCurated: () => void;
}) {
  const [action, setAction] = useState<'merge' | 'create_nodes' | 'link_directory' | 'create_tour'>('merge');
  const [targetDirId, setTargetDirId] = useState('');
  const [tourName, setTourName] = useState('');
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const selected = results.filter((r) => selectedIds.has(r.id));

  const handleCurate = async () => {
    setRunning(true);
    setMessage(null);
    try {
      // Get workspace ID from first memory
      const wsId = memoryData[0]?.workspace_id || '';
      if (!wsId) {
        setMessage('No workspace found');
        setRunning(false);
        return;
      }

      if (action === 'merge') {
        // Merge selected memories
        const memoryIds = selected.filter((r) => r.entityType === 'memory').map((r) => r.id);
        if (memoryIds.length > 0) {
          await callReducer('consolidate_memories', [wsId, memoryIds]);
          setMessage(`Consolidated ${memoryIds.length} memories`);
        } else {
          setMessage('No memories selected to merge');
        }
      } else if (action === 'create_nodes') {
        // Create KG nodes from selected memories
        for (const res of selected) {
          if (res.entityType === 'memory') {
            await callReducer('create_node', [
              wsId,
              res.label || res.excerpt.slice(0, 80),
              'concept',
              res.excerpt,
            ]);
          }
        }
        setMessage(`Created ${selected.length} KG nodes`);
      } else if (action === 'link_directory') {
        // Link results to a directory
        for (const res of selected) {
          if (res.entityType === 'memory') {
            await callReducer('add_to_directory', [wsId, targetDirId, res.id]);
          }
        }
        setMessage(`Linked ${selected.length} results to directory`);
      } else if (action === 'create_tour') {
        // Create a tour from selected KG nodes
        const nodeIds = selected.filter((r) => r.entityType === 'kg_node').map((r) => r.id);
        if (nodeIds.length > 0) {
          await callReducer('create_tour', [wsId, tourName || 'Curated Tour', nodeIds]);
          setMessage(`Created tour "${tourName || 'Curated Tour'}" with ${nodeIds.length} stops`);
        } else {
          setMessage('No KG nodes selected for tour');
        }
      }
    } catch (e: any) {
      setMessage(`Error: ${e.message || 'Curation failed'}`);
    } finally {
      setRunning(false);
      onCurated();
    }
  };

  return (
    <Card className="border-primary/30">
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Wand2 className="h-4 w-4 text-primary" />
          Curation — {selected.length} result{selected.length !== 1 ? 's' : ''} selected
        </CardTitle>
        <Button variant="ghost" size="sm" onClick={onClose} className="h-7 text-xs">
          ✕
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Action selector */}
        <div className="flex flex-wrap gap-2">
          {([
            { value: 'merge', label: 'Merge Memories', icon: Layers },
            { value: 'create_nodes', label: 'Create KG Nodes', icon: Database },
            { value: 'link_directory', label: 'Link to Directory', icon: FolderTree },
            { value: 'create_tour', label: 'Create Tour', icon: Route },
          ] as const).map(({ value, label, icon: Icon }) => (
            <Button
              key={value}
              variant={action === value ? 'default' : 'outline'}
              size="sm"
              onClick={() => setAction(value)}
              className="text-xs"
            >
              <Icon className="h-3 w-3 mr-1" />
              {label}
            </Button>
          ))}
        </div>

        {/* Extra fields */}
        {action === 'link_directory' && (
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Directory ID</label>
            <Input
              placeholder="Enter directory ID..."
              value={targetDirId}
              onChange={(e) => setTargetDirId(e.target.value)}
              className="text-sm"
            />
          </div>
        )}
        {action === 'create_tour' && (
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Tour Name</label>
            <Input
              placeholder="My Curated Tour"
              value={tourName}
              onChange={(e) => setTourName(e.target.value)}
              className="text-sm"
            />
          </div>
        )}

        {/* Selected summary */}
        <div className="text-xs text-muted-foreground">
          {selected.filter((r) => r.entityType === 'memory').length} memories,
          {selected.filter((r) => r.entityType === 'kg_node').length} KG nodes,
          {selected.filter((r) => r.entityType === 'kg_edge').length} edges
        </div>

        {/* Run */}
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={handleCurate} disabled={running || selected.length === 0}>
            {running ? 'Running...' : `Run Curation`}
          </Button>
          {message && (
            <span className="text-xs text-muted-foreground">{message}</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function SmartQuery() {
  // Reactive data
  const { data: memories } = useTable<MemoryRow>('memory');
  const { data: kgNodes } = useTable<KGNodeRow>('kg_node');
  const { data: kgEdges } = useTable<KGEdgeRow>('kg_edge');
  const { data: consolidationLogs } = useTable<ConsolidationLogRow>('consolidation_log');

  // Query builder state
  const [queryType, setQueryType] = useState<string>('hybrid');
  const [queryText, setQueryText] = useState('');
  const [filters, setFilters] = useState(defaultFilters);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Results
  const [results, setResults] = useState<QueryResult[]>([]);
  const [activeTab, setActiveTab] = useState('all');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showCuration, setShowCuration] = useState(false);

  // Saved presets
  const [presetName, setPresetName] = useState('');
  const [savedPresets, setSavedPresets] = useState<SavedPreset[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('smartQueryPresetsV2') || '[]');
    } catch {
      return [];
    }
  });

  // Derived result sets by type
  const memoryResults = useMemo(() => results.filter((r) => r.entityType === 'memory'), [results]);
  const nodeResults = useMemo(() => results.filter((r) => r.entityType === 'kg_node'), [results]);
  const edgeResults = useMemo(() => results.filter((r) => r.entityType === 'kg_edge'), [results]);


  // -----------------------------------------------------------------------
  // Query execution
  // -----------------------------------------------------------------------
  const runQuery = useCallback(async () => {
    if (!queryText.trim()) return;
    setRunning(true);
    setError(null);
    setSelectedIds(new Set());
    setShowCuration(false);

    try {
      const allResults: QueryResult[] = [];
      const q = queryText.toLowerCase();

      // Query based on type
      if (queryType === 'semantic' || queryType === 'hybrid' || queryType === 'keyword') {
        // Search memories
        let memList = memories.filter((m) => m.is_active);

        // Apply filters
        if (filters.memoryTypes.length > 0) {
          memList = memList.filter((m) => filters.memoryTypes.includes(m.memory_type));
        }
        if (filters.tiers.length > 0) {
          memList = memList.filter((m) => filters.tiers.includes(m.tier));
        }
        if (filters.minConfidence > 0) {
          memList = memList.filter((m) => m.confidence >= filters.minConfidence);
        }
        if (filters.minStrength > 0) {
          memList = memList.filter((m) => m.strength >= filters.minStrength);
        }
        if (filters.dateFrom) {
          const fromMs = new Date(filters.dateFrom).getTime() * 1000;
          memList = memList.filter((m) => (m.created_at ?? 0) >= fromMs);
        }
        if (filters.dateTo) {
          const toMs = (new Date(filters.dateTo).getTime() + 86400000) * 1000;
          memList = memList.filter((m) => (m.created_at ?? 0) <= toMs);
        }

        // Keyword scoring
        if (queryType === 'keyword' || queryType === 'hybrid') {
          const keywords = q.split(/\s+/).filter(Boolean);
          memList = memList
            .map((m) => {
              const content = (m.content + ' ' + m.summary).toLowerCase();
              let score = 0;
              for (const kw of keywords) {
                if (content.includes(kw)) score += 1;
              }
              if (score > 0) {
                // Boost by confidence
                score = score / keywords.length * m.confidence;
              }
              return { ...m, _score: score };
            })
            .filter((m) => m._score > 0);
        }

        if (queryType === 'semantic') {
          // Just score by confidence for semantic (placeholder — real semantic needs embeddings)
          memList = memList.map((m) => ({
            ...m,
            _score: m.confidence,
          }));
        }

        // Fallback: if hybrid/keyword produced no results, include everything scored by confidence
        if (memList.length === 0) {
          memList = memories
            .filter((m) => m.is_active)
            .slice(0, filters.limit)
            .map((m) => ({ ...m, _score: m.confidence }));
        }

        // Sort by score, limit
        memList.sort((a, b) => (b as any)._score - (a as any)._score);
        memList = memList.slice(0, filters.limit);

        allResults.push(
          ...memList.map((m) => ({
            id: m.id,
            entityType: 'memory' as const,
            label: m.summary || m.content.slice(0, 80),
            excerpt: m.content,
            score: (m as any)._score || m.confidence,
            tier: m.tier,
            createdAt: m.created_at,
            raw: m,
          })),
        );
      }

      if (queryType === 'graph' || queryType === 'hybrid') {
        // Search KG nodes
        let nodeList = kgNodes;
        if (filters.nodeTypes.length > 0) {
          nodeList = nodeList.filter((n) => filters.nodeTypes.includes(n.node_type));
        }
        if (filters.tiers.length > 0) {
          // Map tier filter meaningfully — kg nodes don't have tier, use node_type proxy
          // Skip tier filter for nodes
        }

        // Keyword search nodes
        const keywords = q.split(/\s+/).filter(Boolean);
        const scoredNodes = nodeList
          .map((n) => {
            const text = (n.label + ' ' + n.summary).toLowerCase();
            let score = 0;
            for (const kw of keywords) {
              if (text.includes(kw)) score += 1;
            }
            if (score === 0 && queryType !== 'graph') return null;
            score = score / Math.max(keywords.length, 1);
            return { ...n, _score: score > 0 ? score : 0.1 };
          })
          .filter((n): n is KGNodeRow & { _score: number } => n !== null)
          .sort((a, b) => b._score - a._score)
          .slice(0, Math.floor(filters.limit / 2));

        allResults.push(
          ...scoredNodes.map((n) => ({
            id: n.id,
            entityType: 'kg_node' as const,
            label: n.label,
            excerpt: n.summary,
            score: n._score,
            nodeType: n.node_type,
            createdAt: n.created_at,
            raw: n,
          })),
        );

        // Search edges
        const edgeKeywords = q.split(/\s+/).filter(Boolean);
        const scoredEdges = kgEdges
          .map((e) => {
            const text = (e.relation + ' ' + e.source_node_id + ' ' + e.target_node_id).toLowerCase();
            let score = 0;
            for (const kw of edgeKeywords) {
              if (text.includes(kw)) score += 1;
            }
            if (score === 0 && queryType !== 'graph') return null;
            score = score / Math.max(edgeKeywords.length, 1);
            return { ...e, _score: score > 0 ? score : 0.05 };
          })
          .filter((e): e is KGEdgeRow & { _score: number } => e !== null)
          .sort((a, b) => b._score - a._score)
          .slice(0, Math.floor(filters.limit / 3));

        allResults.push(
          ...scoredEdges.map((e) => ({
            id: e.id,
            entityType: 'kg_edge' as const,
            label: `${e.relation}: ${e.source_node_id} → ${e.target_node_id}`,
            excerpt: `Relation: ${e.relation} | Confidence: ${e.confidence}`,
            score: e._score,
            relation: e.relation,
            weight: e.weight,
            createdAt: e.created_at,
            raw: e,
          })),
        );
      }

      if (queryType === 'temporal') {
        // Search by date range
        let memList = memories.filter((m) => m.is_active);
        if (filters.dateFrom) {
          const fromMs = new Date(filters.dateFrom).getTime() * 1000;
          memList = memList.filter((m) => (m.created_at ?? 0) >= fromMs);
        }
        if (filters.dateTo) {
          const toMs = (new Date(filters.dateTo).getTime() + 86400000) * 1000;
          memList = memList.filter((m) => (m.created_at ?? 0) <= toMs);
        }
        memList.sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
        memList = memList.slice(0, filters.limit);

        allResults.push(
          ...memList.map((m) => ({
            id: m.id,
            entityType: 'memory' as const,
            label: m.summary || m.content.slice(0, 80),
            excerpt: m.content,
            score: m.confidence,
            tier: m.tier,
            createdAt: m.created_at,
            raw: m,
          })),
        );
      }

      // Sort all results by score descending
      allResults.sort((a, b) => b.score - a.score);
      setResults(allResults);
    } catch (e: any) {
      setError(e.message || 'Query failed');
    } finally {
      setRunning(false);
    }
  }, [queryType, queryText, filters, memories, kgNodes, kgEdges]);

  // -----------------------------------------------------------------------
  // Presets
  // -----------------------------------------------------------------------
  const savePreset = () => {
    if (!presetName.trim()) return;
    const preset: SavedPreset = {
      name: presetName,
      queryType,
      queryText,
      memoryTypes: filters.memoryTypes,
      tiers: filters.tiers,
      nodeTypes: filters.nodeTypes,
      limit: filters.limit,
      minConfidence: filters.minConfidence,
      minStrength: filters.minStrength,
      dateFrom: filters.dateFrom,
      dateTo: filters.dateTo,
      advanced: filters.advanced,
    };
    const updated = [...savedPresets, preset];
    setSavedPresets(updated);
    localStorage.setItem('smartQueryPresetsV2', JSON.stringify(updated));
    setPresetName('');
  };

  const loadPreset = (preset: SavedPreset) => {
    setQueryType(preset.queryType);
    setQueryText(preset.queryText);
    setFilters({
      memoryTypes: preset.memoryTypes,
      tiers: preset.tiers,
      nodeTypes: preset.nodeTypes,
      limit: preset.limit,
      minConfidence: preset.minConfidence,
      minStrength: preset.minStrength,
      dateFrom: preset.dateFrom,
      dateTo: preset.dateTo,
      advanced: preset.advanced,
    });
  };

  const deletePreset = (index: number) => {
    const updated = savedPresets.filter((_, i) => i !== index);
    setSavedPresets(updated);
    localStorage.setItem('smartQueryPresetsV2', JSON.stringify(updated));
  };

  const runAllSaved = async () => {
    for (const preset of savedPresets) {
      setQueryType(preset.queryType);
      setQueryText(preset.queryText);
      setFilters({
        memoryTypes: preset.memoryTypes,
        tiers: preset.tiers,
        nodeTypes: preset.nodeTypes,
        limit: preset.limit,
        minConfidence: preset.minConfidence,
        minStrength: preset.minStrength,
        dateFrom: preset.dateFrom,
        dateTo: preset.dateTo,
        advanced: preset.advanced,
      });
      // Small delay to let state settle
      await new Promise((r) => setTimeout(r, 50));
      await runQuery();
    }
  };

  // -----------------------------------------------------------------------
  // Selection
  // -----------------------------------------------------------------------
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    setSelectedIds(new Set(results.map((r) => r.id)));
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
  };

  // -----------------------------------------------------------------------
  // Export
  // -----------------------------------------------------------------------
  const exportResults = () => {
    const data = JSON.stringify(
      {
        query: queryText,
        queryType,
        timestamp: new Date().toISOString(),
        count: results.length,
        results,
      },
      null,
      2,
    );
    navigator.clipboard.writeText(data).then(() => {
      // Brief visual feedback handled by button
    });
  };

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Wand2 className="h-7 w-7 text-primary" />
            Smart Query Builder
          </h1>
          <p className="text-muted-foreground">
            ByteRover knowledge curation pipeline — build complex queries across memories, KG nodes, and edges
          </p>
        </div>
      </div>

      {/* Main grid: sidebar (presets) + content */}
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Saved queries sidebar */}
        {savedPresets.length > 0 && (
          <div className="lg:w-64 shrink-0">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Save className="h-4 w-4 text-muted-foreground" />
                  Saved Queries
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                {savedPresets.map((preset, i) => (
                  <div key={i} className="flex items-center gap-1">
                    <button
                      onClick={() => loadPreset(preset)}
                      className="flex-1 text-left text-xs py-1.5 px-2 rounded hover:bg-accent truncate"
                    >
                      {preset.name}
                    </button>
                    <button
                      onClick={() => deletePreset(i)}
                      className="text-[10px] text-muted-foreground hover:text-destructive px-1"
                    >
                      ✕
                    </button>
                  </div>
                ))}
                {savedPresets.length > 1 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={runAllSaved}
                    className="w-full mt-2 text-xs"
                  >
                    <Play className="h-3 w-3 mr-1" />
                    Run All Saved
                  </Button>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {/* Main content */}
        <div className="flex-1 space-y-6">
          {/* Query builder form */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Query Builder</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Query type + text row */}
              <div className="flex flex-col sm:flex-row gap-3">
                <div className="sm:w-40">
                  <label className="text-xs text-muted-foreground mb-1 block">Query Type</label>
                  <select
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={queryType}
                    onChange={(e) => setQueryType(e.target.value)}
                  >
                    <option value="hybrid">Hybrid</option>
                    <option value="semantic">Semantic</option>
                    <option value="keyword">Keyword</option>
                    <option value="temporal">Temporal</option>
                    <option value="graph">Graph</option>
                  </select>
                </div>
                <div className="flex-1">
                  <label className="text-xs text-muted-foreground mb-1 block">
                    {queryType === 'temporal' ? 'Description (optional)' : 'Query Text'}
                  </label>
                  <Input
                    placeholder={
                      queryType === 'temporal'
                        ? 'Find memories from a date range...'
                        : 'Search memories, concepts, entities...'
                    }
                    value={queryText}
                    onChange={(e) => setQueryText(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && runQuery()}
                    className="text-sm"
                  />
                </div>
              </div>

              {/* Filter toggles */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <CheckboxGroup
                  label="Memory Type"
                  options={memoryTypeOptions}
                  selected={filters.memoryTypes}
                  onChange={(v) => setFilters({ ...filters, memoryTypes: v })}
                />
                <CheckboxGroup
                  label="Tier"
                  options={tierOptions}
                  selected={filters.tiers}
                  onChange={(v) => setFilters({ ...filters, tiers: v })}
                />
                <CheckboxGroup
                  label="Node Type"
                  options={nodeTypeOptions}
                  selected={filters.nodeTypes}
                  onChange={(v) => setFilters({ ...filters, nodeTypes: v })}
                />
              </div>

              {/* Advanced toggle */}
              <button
                type="button"
                onClick={() => setFilters({ ...filters, advanced: !filters.advanced })}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                {filters.advanced ? (
                  <ChevronUp className="h-3 w-3" />
                ) : (
                  <ChevronDown className="h-3 w-3" />
                )}
                Advanced Settings
              </button>

              {filters.advanced && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 pt-2 border-t border-border">
                  {/* Limit slider */}
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">
                      Limit: {filters.limit}
                    </label>
                    <input
                      type="range"
                      min={5}
                      max={100}
                      step={5}
                      value={filters.limit}
                      onChange={(e) => setFilters({ ...filters, limit: Number(e.target.value) })}
                      className="w-full"
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>5</span>
                      <span>100</span>
                    </div>
                  </div>
                  {/* Min confidence */}
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">
                      Min Confidence: {filters.minConfidence.toFixed(2)}
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={filters.minConfidence}
                      onChange={(e) =>
                        setFilters({ ...filters, minConfidence: Number(e.target.value) })
                      }
                      className="w-full"
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>0</span>
                      <span>1</span>
                    </div>
                  </div>
                  {/* Min strength */}
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">
                      Min Strength: {filters.minStrength.toFixed(2)}
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={filters.minStrength}
                      onChange={(e) =>
                        setFilters({ ...filters, minStrength: Number(e.target.value) })
                      }
                      className="w-full"
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>0</span>
                      <span>1</span>
                    </div>
                  </div>
                  {/* Date range */}
                  <div className="sm:col-span-2 lg:col-span-1">
                    <label className="text-xs text-muted-foreground mb-1 block">Date Range</label>
                    <div className="flex items-center gap-2">
                      <Input
                        type="date"
                        value={filters.dateFrom}
                        onChange={(e) =>
                          setFilters({ ...filters, dateFrom: e.target.value })
                        }
                        className="text-xs h-9"
                      />
                      <span className="text-xs text-muted-foreground">→</span>
                      <Input
                        type="date"
                        value={filters.dateTo}
                        onChange={(e) =>
                          setFilters({ ...filters, dateTo: e.target.value })
                        }
                        className="text-xs h-9"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Run + save row */}
              <div className="flex items-center gap-2 pt-2">
                <Button onClick={runQuery} disabled={running || !queryText.trim()}>
                  {running ? (
                    <span className="flex items-center gap-1">
                      <span className="animate-spin inline-block">⟳</span> Running...
                    </span>
                  ) : (
                    <span className="flex items-center gap-1">
                      <Search className="h-4 w-4" /> Run Query
                    </span>
                  )}
                </Button>
                <div className="flex items-center gap-1">
                  <Input
                    placeholder="Save as preset..."
                    value={presetName}
                    onChange={(e) => setPresetName(e.target.value)}
                    className="h-9 text-xs w-36"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={savePreset}
                    disabled={!presetName.trim()}
                    className="h-9"
                  >
                    <Save className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Results area */}
          <div className="space-y-4">
            {/* Results header */}
            {results.length > 0 && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <p className="text-sm text-muted-foreground">
                    {results.length} result{results.length !== 1 ? 's' : ''}
                  </p>
                  <Button variant="ghost" size="sm" onClick={selectAll} className="text-xs h-7">
                    Select All
                  </Button>
                  <Button variant="ghost" size="sm" onClick={clearSelection} className="text-xs h-7">
                    Clear
                  </Button>
                </div>
                <div className="flex items-center gap-2">
                  {selectedIds.size > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setShowCuration(!showCuration)}
                      className="text-xs"
                    >
                      <Wand2 className="h-3 w-3 mr-1" />
                      Curate ({selectedIds.size})
                    </Button>
                  )}
                  <Button variant="outline" size="sm" onClick={exportResults} className="text-xs">
                    <FileJson className="h-3 w-3 mr-1" />
                    Export JSON
                  </Button>
                </div>
              </div>
            )}

            {/* Curation panel */}
            {showCuration && selectedIds.size > 0 && (
              <CurationPanel
                selectedIds={selectedIds}
                results={results}
                memoryData={memories}
                onClose={() => setShowCuration(false)}
                onCurated={() => setShowCuration(false)}
              />
            )}

            {/* Loading state */}
            {running && (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-16 w-full rounded-lg" />
                ))}
              </div>
            )}

            {/* Error state */}
            {error && !running && (
              <Card className="border-red-500/30">
                <CardContent className="flex items-center gap-3 py-4">
                  <AlertCircle className="h-5 w-5 text-destructive shrink-0" />
                  <p className="text-sm text-destructive">{error}</p>
                </CardContent>
              </Card>
            )}

            {/* Empty state */}
            {!running && !error && results.length === 0 && (
              <Card>
                <CardContent className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  <Sparkles className="h-12 w-12 mb-3 opacity-30" />
                  <p className="font-medium text-lg">Run a query to see results</p>
                  <p className="text-sm mt-1 max-w-md text-center">
                    Choose a query type, enter some text, optionally set filters, then click "Run Query".
                  </p>
                </CardContent>
              </Card>
            )}

            {/* Results tabs */}
            {!running && results.length > 0 && (
              <Tabs defaultValue="all" value={activeTab} onValueChange={setActiveTab}>
                <TabsList>
                  <TabsTrigger value="all">
                    All ({results.length})
                  </TabsTrigger>
                  <TabsTrigger value="memories" disabled={memoryResults.length === 0}>
                    Memories ({memoryResults.length})
                  </TabsTrigger>
                  <TabsTrigger value="nodes" disabled={nodeResults.length === 0}>
                    KG Nodes ({nodeResults.length})
                  </TabsTrigger>
                  <TabsTrigger value="edges" disabled={edgeResults.length === 0}>
                    Edges ({edgeResults.length})
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="all" className="space-y-2 mt-3">
                  {results.map((r) => (
                    <ResultCard
                      key={r.id}
                      result={r}
                      selected={selectedIds.has(r.id)}
                      onToggleSelect={toggleSelect}
                    />
                  ))}
                </TabsContent>

                <TabsContent value="memories" className="space-y-2 mt-3">
                  {memoryResults.map((r) => (
                    <ResultCard
                      key={r.id}
                      result={r}
                      selected={selectedIds.has(r.id)}
                      onToggleSelect={toggleSelect}
                    />
                  ))}
                </TabsContent>

                <TabsContent value="nodes" className="space-y-2 mt-3">
                  {nodeResults.map((r) => (
                    <ResultCard
                      key={r.id}
                      result={r}
                      selected={selectedIds.has(r.id)}
                      onToggleSelect={toggleSelect}
                    />
                  ))}
                </TabsContent>

                <TabsContent value="edges" className="space-y-2 mt-3">
                  {edgeResults.map((r) => (
                    <ResultCard
                      key={r.id}
                      result={r}
                      selected={selectedIds.has(r.id)}
                      onToggleSelect={toggleSelect}
                    />
                  ))}
                </TabsContent>
              </Tabs>
            )}
          </div>

          {/* Curation history */}
          {consolidationLogs.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <History className="h-4 w-4 text-muted-foreground" />
                  Curation History
                </CardTitle>
                <CardDescription>Recent consolidations and curations</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {[...consolidationLogs]
                    .sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))
                    .slice(0, 20)
                    .map((log) => (
                      <div
                        key={log.id}
                        className="flex items-start gap-3 rounded-lg border border-border p-2.5 text-sm"
                      >
                        <History className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium">{log.consolidation_type}</span>
                            <Badge variant="outline" className="text-[10px]">
                              {log.source_memory_ids ? log.source_memory_ids.split(',').length : 0} sources
                            </Badge>
                          </div>
                          <p className="text-[10px] text-muted-foreground mt-0.5">
                            Target: {log.target_memory_id?.slice(0, 20)}… ·{' '}
                            {formatMemoryTimestamp(log.created_at)}
                          </p>
                        </div>
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
