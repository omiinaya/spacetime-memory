import { useState, useMemo, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Input } from '@/components/ui/input';
import { useTable } from '@/lib/useReactiveDb';
import { callReducer } from '@/lib/spacetimedb';
import {
  GitMerge, GitBranch, ArrowLeft, Eye, X,
  Filter, Calendar, AlertCircle, Sparkles, Layers, FileText,
  CheckCircle2, Clock, ThumbsUp, ThumbsDown, Search,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Data types (snake_case columns as returned by SDK's iter())
// ---------------------------------------------------------------------------
interface MemoryRow {
  id: string;
  workspace_id: string;
  peer_id: string;
  observer_id: string;
  memory_type: string;
  content: string;
  summary: string;
  entities_json: string;
  confidence: number;
  is_active: boolean;
  created_at: number;
  expires_at: number;
  updated_at: number;
  tier: string;
  access_count: number;
  strength: number;
  version: number;
  consolidated_to: string;
  trust_score: number;
  feedback_count: number;
}

interface WorkspaceRow {
  id: string;
  name: string;
  description: string;
  created_at: number;
  updated_at: number;
}

interface MergeSuggestionRow {
  id: string;
  workspace_id: string;
  source_id: string;
  target_id: string;
  cosine_similarity: number;
  edit_distance: number;
  content_overlap_preview: string;
  status: string; // "pending" | "approved" | "rejected"
  created_at: number;
}

// ---------------------------------------------------------------------------
// Merge group derived type
// ---------------------------------------------------------------------------
interface MergeGroup {
  survivor: MemoryRow;
  sources: MemoryRow[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function fmt(micros: number | string | null): string {
  if (micros == null) return 'unknown';
  const ms = (typeof micros === 'number' ? micros : Number(micros)) / 1000;
  const diff = Date.now() - ms;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function confidenceColor(c: number): string {
  if (c >= 0.8) return 'text-green-500';
  if (c >= 0.5) return 'text-yellow-500';
  return 'text-red-500';
}

function statusBadgeVariant(status: string): 'default' | 'secondary' | 'outline' {
  switch (status) {
    case 'approved': return 'default';
    case 'rejected': return 'secondary';
    default: return 'outline'; // pending
  }
}

function statusColor(status: string): string {
  switch (status) {
    case 'pending': return 'bg-amber-500/10 text-amber-600 border-amber-500/30';
    case 'approved': return 'bg-green-500/10 text-green-600 border-green-500/30';
    case 'rejected': return 'bg-gray-500/10 text-gray-500 border-gray-400/30';
    default: return '';
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatsBar({ groups, allMerged }: { groups: MergeGroup[]; allMerged: MemoryRow[] }) {
  const totalGroups = groups.length;
  const totalMerged = allMerged.length;
  const avgConfidence =
    totalMerged > 0
      ? allMerged.reduce((sum, m) => sum + m.confidence, 0) / totalMerged
      : 0;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Card>
        <CardContent className="p-4 flex items-center gap-3">
          <GitMerge className="h-8 w-8 text-primary shrink-0" />
          <div>
            <p className="text-2xl font-bold">{totalGroups}</p>
            <p className="text-xs text-muted-foreground">Merge groups</p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4 flex items-center gap-3">
          <Layers className="h-8 w-8 text-orange-500 shrink-0" />
          <div>
            <p className="text-2xl font-bold">{totalMerged}</p>
            <p className="text-xs text-muted-foreground">Merged memories</p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4 flex items-center gap-3">
          <Sparkles className="h-8 w-8 text-blue-500 shrink-0" />
          <div>
            <p className={`text-2xl font-bold ${confidenceColor(avgConfidence)}`}>
              {(avgConfidence * 100).toFixed(0)}%
            </p>
            <p className="text-xs text-muted-foreground">Avg confidence (merged)</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function MemoryContent({ memory, label }: { memory: MemoryRow; label: string }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Badge variant="outline" className="text-xs font-mono">{label}</Badge>
        <Badge
          variant={memory.tier === 'core' ? 'default' : 'secondary'}
          className="text-[10px]"
        >
          {memory.tier}
        </Badge>
      </div>
      <div>
        <p className="text-xs text-muted-foreground mb-1">Summary</p>
        <p className="text-sm font-medium">{memory.summary || '(no summary)'}</p>
      </div>
      <div>
        <p className="text-xs text-muted-foreground mb-1">Content</p>
        <p className="text-sm text-muted-foreground line-clamp-4 whitespace-pre-wrap">
          {memory.content || '(no content)'}
        </p>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span>Confidence: <span className={confidenceColor(memory.confidence)}>{(memory.confidence * 100).toFixed(0)}%</span></span>
        <span>Strength: {memory.strength.toFixed(2)}</span>
        <span>Access count: {memory.access_count}</span>
      </div>
    </div>
  );
}

function SideBySideComparison({
  survivor,
  candidate,
  onClose,
  onKeepBoth,
}: {
  survivor: MemoryRow;
  candidate: MemoryRow | null;
  onClose: () => void;
  onKeepBoth: (sourceId: string) => void;
}) {
  if (!candidate) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
          <h2 className="text-lg font-semibold">Side-by-side comparison</h2>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onKeepBoth(candidate.id)}
          >
            <GitBranch className="h-3.5 w-3.5 mr-1.5" />
            Keep both
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Survivor */}
        <Card className="border-l-4 border-l-green-500/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              Survivor
            </CardTitle>
            <CardDescription className="text-[10px]">
              ID: {survivor.id.slice(0, 12)}...
            </CardDescription>
          </CardHeader>
          <CardContent>
            <MemoryContent memory={survivor} label="Survivor" />
          </CardContent>
        </Card>

        {/* Candidate */}
        <Card className="border-l-4 border-l-yellow-500/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-yellow-500" />
              Merge candidate
            </CardTitle>
            <CardDescription className="text-[10px]">
              ID: {candidate.id.slice(0, 12)}...
            </CardDescription>
          </CardHeader>
          <CardContent>
            <MemoryContent memory={candidate} label="Candidate" />
          </CardContent>
        </Card>
      </div>

      {/* Diff highlights: summary and content side-by-side */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <FileText className="h-4 w-4 text-muted-foreground" />
            Field comparison
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div>
              <p className="text-xs text-muted-foreground mb-1 font-medium">Summary</p>
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded bg-muted/30 p-2 text-sm">{survivor.summary || '(none)'}</div>
                <div className="rounded bg-muted/30 p-2 text-sm">{candidate.summary || '(none)'}</div>
              </div>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1 font-medium">Content</p>
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded bg-muted/30 p-2 text-sm max-h-40 overflow-y-auto whitespace-pre-wrap">
                  {survivor.content || '(none)'}
                </div>
                <div className="rounded bg-muted/30 p-2 text-sm max-h-40 overflow-y-auto whitespace-pre-wrap">
                  {candidate.content || '(none)'}
                </div>
              </div>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1 font-medium">Metadata</p>
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded bg-muted/30 p-2 text-[11px] space-y-1">
                  <p>Type: {survivor.memory_type}</p>
                  <p>Confidence: {(survivor.confidence * 100).toFixed(0)}%</p>
                  <p>Strength: {survivor.strength.toFixed(2)}</p>
                  <p>Tier: {survivor.tier}</p>
                  <p>Created: {fmt(survivor.created_at)}</p>
                </div>
                <div className="rounded bg-muted/30 p-2 text-[11px] space-y-1">
                  <p>Type: {candidate.memory_type}</p>
                  <p>Confidence: {(candidate.confidence * 100).toFixed(0)}%</p>
                  <p>Strength: {candidate.strength.toFixed(2)}</p>
                  <p>Tier: {candidate.tier}</p>
                  <p>Created: {fmt(candidate.created_at)}</p>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function MergeGroupCard({
  group,
  selected,
  onSelect,
  onCompare,
  onViewSurvivor,
  onKeepBoth,
}: {
  group: MergeGroup;
  selected: boolean;
  onSelect: () => void;
  onCompare: (candidate: MemoryRow) => void;
  onViewSurvivor: (id: string) => void;
  onKeepBoth: (sourceId: string) => void;
}) {
  return (
    <Card
      className={`cursor-pointer transition-colors hover:bg-accent/40 ${
        selected ? 'ring-2 ring-primary/40 bg-accent/30' : ''
      }`}
      onClick={onSelect}
    >
      <CardContent className="p-5">
        <div className="flex items-start justify-between mb-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
              <h3 className="font-semibold truncate text-sm">
                {group.survivor.summary || group.survivor.content?.slice(0, 60) || '(no summary)'}
              </h3>
            </div>
            <p className="text-[11px] text-muted-foreground mt-0.5 ml-6">
              Survivor · {group.survivor.memory_type} · {fmt(group.survivor.created_at)}
            </p>
          </div>
          <Badge variant="secondary" className="shrink-0 ml-2">
            {group.sources.length} merged
          </Badge>
        </div>

        {/* Source memories */}
        <div className="space-y-1.5">
          {group.sources.map((src) => (
            <div
              key={src.id}
              className="flex items-center justify-between rounded bg-muted/30 px-3 py-1.5 text-xs"
            >
              <div className="flex items-center gap-2 min-w-0">
                <GitBranch className="h-3 w-3 text-yellow-500 shrink-0" />
                <span className="truncate text-muted-foreground">
                  {src.summary || src.content?.slice(0, 50) || '(no summary)'}
                </span>
              </div>
              <div className="flex items-center gap-1 shrink-0 ml-2">
                <Badge
                  variant="outline"
                  className="text-[10px] font-mono px-1.5"
                >
                  {(src.confidence * 100).toFixed(0)}%
                </Badge>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  title="Compare side-by-side"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCompare(src);
                  }}
                >
                  <Eye className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  title="Keep both (unmerge)"
                  onClick={(e) => {
                    e.stopPropagation();
                    onKeepBoth(src.id);
                  }}
                >
                  <GitBranch className="h-3 w-3 text-orange-500" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        {group.sources.length === 0 && (
          <p className="text-xs text-muted-foreground italic">No merged memories found</p>
        )}

        <div className="flex items-center justify-between mt-3 pt-2 border-t border-border">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Sparkles className="h-3 w-3" />
            <span>
              Avg confidence:{' '}
              {(
                [group.survivor, ...group.sources].reduce((s, m) => s + m.confidence, 0) /
                (group.sources.length + 1) *
                100
              ).toFixed(0)}
              %
            </span>
            <Clock className="h-3 w-3 ml-1" />
            <span>{fmt(group.survivor.created_at)}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={(e) => {
              e.stopPropagation();
              onViewSurvivor(group.survivor.id);
            }}
          >
            <Eye className="h-3 w-3 mr-1" />
            View survivor
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Suggestion Card sub-component
// ---------------------------------------------------------------------------

function SuggestionCard({
  suggestion,
  onApprove,
  onReject,
  memories,
}: {
  suggestion: MergeSuggestionRow;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  memories: MemoryRow[];
}) {
  const sourceMem = memories.find((m) => m.id === suggestion.source_id);
  const targetMem = memories.find((m) => m.id === suggestion.target_id);

  const isPending = suggestion.status === 'pending';

  return (
    <Card className={`border-l-4 ${
      suggestion.status === 'approved' ? 'border-l-green-500/60' :
      suggestion.status === 'rejected' ? 'border-l-gray-400/40' :
      'border-l-amber-500/60'
    }`}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <Badge
                variant={statusBadgeVariant(suggestion.status)}
                className={`text-[10px] uppercase tracking-wider ${statusColor(suggestion.status)}`}
              >
                {suggestion.status}
              </Badge>
              <Badge variant="outline" className="text-[10px] font-mono">
                Sim: {(suggestion.cosine_similarity * 100).toFixed(1)}%
              </Badge>
              <Badge variant="outline" className="text-[10px] font-mono">
                Edit: {(suggestion.edit_distance * 100).toFixed(1)}%
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">
              {suggestion.content_overlap_preview || '(no preview)'}
            </p>
          </div>
        </div>

        {/* Source → Target */}
        <div className="grid grid-cols-2 gap-3 mt-2">
          <div className="rounded bg-muted/30 p-2 text-xs">
            <p className="text-[10px] text-muted-foreground uppercase mb-1">Source (merged away)</p>
            <p className="font-medium truncate">{sourceMem?.summary || sourceMem?.content?.slice(0, 60) || '(unknown)'}</p>
          </div>
          <div className="rounded bg-green-500/5 p-2 text-xs border border-green-500/20">
            <p className="text-[10px] text-green-600 uppercase mb-1">Target (survivor)</p>
            <p className="font-medium truncate">{targetMem?.summary || targetMem?.content?.slice(0, 60) || '(unknown)'}</p>
          </div>
        </div>

        {/* Action buttons */}
        {isPending && (
          <div className="flex items-center gap-2 mt-3 pt-2 border-t border-border">
            <Button
              variant="default"
              size="sm"
              className="h-7 text-xs"
              onClick={() => onApprove(suggestion.id)}
            >
              <ThumbsUp className="h-3 w-3 mr-1" />
              Approve
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => onReject(suggestion.id)}
            >
              <ThumbsDown className="h-3 w-3 mr-1" />
              Reject
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MergeCandidates() {
  const { data: memories, loading, error } = useTable<MemoryRow>('memory');
  const { data: workspaces } = useTable<WorkspaceRow>('workspace');
  const { data: suggestions } = useTable<MergeSuggestionRow>('merge_suggestion');

  // State
  const [selectedSurvivorId, setSelectedSurvivorId] = useState<string | null>(null);
  const [compareCandidate, setCompareCandidate] = useState<MemoryRow | null>(null);
  const [workspaceFilter, setWorkspaceFilter] = useState<string>('');
  const [dateFrom, setDateFrom] = useState<string>('');
  const [dateTo, setDateTo] = useState<string>('');
  const [scanThreshold, setScanThreshold] = useState<string>('0.8');
  const [scanning, setScanning] = useState(false);

  // --- Derived data ---
  const { groups, allMerged } = useMemo(() => {
    if (!memories) return { groups: [] as MergeGroup[], allMerged: [] as MemoryRow[] };

    // Memories that have been merged into another (consolidated_to !== '')
    const merged = memories.filter(
      (m: MemoryRow) => m.consolidated_to && m.consolidated_to !== ''
    );
    // Build a map from survivor ID → source memories
    const sourceMap = new Map<string, MemoryRow[]>();
    for (const m of merged) {
      const list = sourceMap.get(m.consolidated_to) ?? [];
      list.push(m);
      sourceMap.set(m.consolidated_to, list);
    }

    // Build groups: for each survivor ID that has sources, find the survivor memory
    const groups: MergeGroup[] = [];
    for (const [survivorId, sources] of sourceMap) {
      const survivor = memories.find((m: MemoryRow) => m.id === survivorId);
      if (survivor) {
        groups.push({ survivor, sources });
      }
    }

    return { groups, allMerged: merged };
  }, [memories]);

  // Filtered merge suggestions
  const filteredSuggestions = useMemo(() => {
    if (!suggestions) return [];
    if (!workspaceFilter) return suggestions;
    return suggestions.filter((s) => s.workspace_id === workspaceFilter);
  }, [suggestions, workspaceFilter]);

  // Pending suggestions count
  const pendingCount = useMemo(() => {
    return filteredSuggestions.filter((s) => s.status === 'pending').length;
  }, [filteredSuggestions]);

  // --- Filtering ---
  const filteredGroups = useMemo(() => {
    let result = groups;

    if (workspaceFilter) {
      result = result.filter((g) => g.survivor.workspace_id === workspaceFilter);
    }

    if (dateFrom) {
      const fromMicros = new Date(dateFrom).getTime() * 1000;
      result = result.filter((g) => g.survivor.created_at >= fromMicros);
    }

    if (dateTo) {
      const toMicros = new Date(dateTo).getTime() * 1000;
      result = result.filter((g) => g.survivor.created_at <= toMicros);
    }

    return result;
  }, [groups, workspaceFilter, dateFrom, dateTo]);

  const selectedGroup = useMemo(() => {
    if (!selectedSurvivorId) return null;
    return filteredGroups.find((g) => g.survivor.id === selectedSurvivorId) ?? null;
  }, [filteredGroups, selectedSurvivorId]);

  // --- Actions ---
  const handleKeepBoth = useCallback(async (sourceId: string) => {
    try {
      await callReducer('unmerge_memories', [sourceId]);
    } catch (err: any) {
      console.error('Failed to unmerge:', err);
    }
  }, []);

  const handleViewSurvivor = useCallback((id: string) => {
    // Navigate to the memory browser with the survivor's ID
    window.location.href = `/memories?id=${id}`;
  }, []);

  const handleCompare = useCallback((candidate: MemoryRow) => {
    setCompareCandidate(candidate);
  }, []);

  const handleFindCandidates = useCallback(async () => {
    const ws = workspaceFilter;
    if (!ws) {
      alert('Please select a workspace first using the filter dropdown.');
      return;
    }
    const threshold = parseFloat(scanThreshold) || 0.8;
    setScanning(true);
    try {
      await callReducer('suggest_merges', [ws, threshold]);
    } catch (err: any) {
      console.error('Failed to scan for merge candidates:', err);
    } finally {
      setScanning(false);
    }
  }, [workspaceFilter, scanThreshold]);

  const handleApproveMerge = useCallback(async (suggestionId: string) => {
    try {
      await callReducer('approve_merge', [suggestionId]);
    } catch (err: any) {
      console.error('Failed to approve merge:', err);
    }
  }, []);

  const handleRejectMerge = useCallback(async (suggestionId: string) => {
    try {
      await callReducer('reject_merge', [suggestionId]);
    } catch (err: any) {
      console.error('Failed to reject merge:', err);
    }
  }, []);

  // --- Render ---

  // Loading state
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
              <GitMerge className="h-7 w-7 text-primary" />
              Merge Candidates
            </h1>
            <p className="text-muted-foreground">Review and manage near-duplicate memories</p>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="p-4 space-y-2">
                <Skeleton className="h-8 w-20" />
                <Skeleton className="h-3 w-28" />
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="p-5 space-y-3">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-2/3" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
              <GitMerge className="h-7 w-7 text-primary" />
              Merge Candidates
            </h1>
            <p className="text-muted-foreground">Review and manage near-duplicate memories</p>
          </div>
        </div>
        <Card>
          <CardContent className="py-12 text-center">
            <AlertCircle className="h-8 w-8 mx-auto mb-2 text-destructive/50" />
            <p className="text-sm text-muted-foreground">{error}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Side-by-side comparison overlays the group view
  if (compareCandidate && selectedGroup) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
              <GitMerge className="h-7 w-7 text-primary" />
              Merge Candidates
            </h1>
            <p className="text-muted-foreground">Review and manage near-duplicate memories</p>
          </div>
        </div>
        <SideBySideComparison
          survivor={selectedGroup.survivor}
          candidate={compareCandidate}
          onClose={() => setCompareCandidate(null)}
          onKeepBoth={handleKeepBoth}
        />
        <Button variant="outline" size="sm" onClick={() => setCompareCandidate(null)}>
          <ArrowLeft className="h-4 w-4 mr-1.5" />
          Back to group view
        </Button>
      </div>
    );
  }

  // Group detail view
  if (selectedGroup) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" onClick={() => { setSelectedSurvivorId(null); setCompareCandidate(null); }}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Merge Group</h1>
              <p className="text-sm text-muted-foreground">
                {selectedGroup.survivor.summary || selectedGroup.survivor.content?.slice(0, 80) || '(no summary)'}
              </p>
            </div>
          </div>
          <Badge variant="outline" className="text-xs">
            {selectedGroup.sources.length + 1} memories
          </Badge>
        </div>

        {/* Survivor card (highlighted) */}
        <Card className="border-l-4 border-l-green-500/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              Survivor memory
            </CardTitle>
            <CardDescription className="text-[11px]">
              ID: {selectedGroup.survivor.id} · {fmt(selectedGroup.survivor.created_at)}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Summary</p>
                <p className="text-sm font-medium">{selectedGroup.survivor.summary || '(no summary)'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Content</p>
                <p className="text-sm text-muted-foreground whitespace-pre-wrap line-clamp-6">
                  {selectedGroup.survivor.content || '(no content)'}
                </p>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>Type: {selectedGroup.survivor.memory_type}</span>
                <span>Confidence: <span className={confidenceColor(selectedGroup.survivor.confidence)}>
                  {(selectedGroup.survivor.confidence * 100).toFixed(0)}%</span></span>
                <span>Strength: {selectedGroup.survivor.strength.toFixed(2)}</span>
                <span>Tier: {selectedGroup.survivor.tier}</span>
              </div>
              <Button variant="outline" size="sm" onClick={() => handleViewSurvivor(selectedGroup.survivor.id)}>
                <Eye className="h-3.5 w-3.5 mr-1.5" />
                View full memory
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Source memories */}
        <div>
          <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-yellow-500" />
            Merged sources ({selectedGroup.sources.length})
          </h2>
          {selectedGroup.sources.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground">
                <p>No source memories in this group.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {selectedGroup.sources.map((src) => (
                <Card key={src.id} className="border-l-4 border-l-yellow-500/40">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between mb-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">
                          {src.summary || src.content?.slice(0, 80) || '(no summary)'}
                        </p>
                        <p className="text-[11px] text-muted-foreground mt-0.5">
                          {src.memory_type} · {fmt(src.created_at)}
                        </p>
                      </div>
                      <div className="flex items-center gap-1 shrink-0 ml-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => handleCompare(src)}
                        >
                          <Eye className="h-3 w-3 mr-1" />
                          Compare
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-orange-500"
                          onClick={() => handleKeepBoth(src.id)}
                        >
                          <GitBranch className="h-3 w-3 mr-1" />
                          Keep both
                        </Button>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                      <span>Confidence: <span className={confidenceColor(src.confidence)}>
                        {(src.confidence * 100).toFixed(0)}%</span></span>
                      <span>Strength: {src.strength.toFixed(2)}</span>
                      <span>Access count: {src.access_count}</span>
                      <span>Consolidated to: <span className="font-mono">{src.consolidated_to.slice(0, 12)}...</span></span>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // --- Main dashboard view ---
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <GitMerge className="h-7 w-7 text-primary" />
            Merge Candidates
          </h1>
          <p className="text-muted-foreground">Review and manage near-duplicate memories</p>
        </div>
      </div>

      {/* Stats */}
      <StatsBar groups={groups} allMerged={allMerged} />

      {/* ── Merge Suggestions Section ── */}
      {filteredSuggestions.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Search className="h-4 w-4 text-amber-500" />
              Merge suggestions
              <Badge variant="outline" className="ml-1 text-[10px]">
                {pendingCount} pending / {filteredSuggestions.length} total
              </Badge>
            </CardTitle>
            <CardDescription>
              Auto-detected near-duplicate pairs awaiting review
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {filteredSuggestions.map((s) => (
                <SuggestionCard
                  key={s.id}
                  suggestion={s}
                  onApprove={handleApproveMerge}
                  onReject={handleRejectMerge}
                  memories={memories || []}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty state (no groups, no suggestions) */}
      {groups.length === 0 && filteredSuggestions.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-muted-foreground">
            <CheckCircle2 className="h-12 w-12 mx-auto mb-3 text-green-500/50" />
            <p className="text-lg font-medium">No merge candidates</p>
            <p className="text-sm mt-1">
              All memories are unique — no near-duplicates detected.
            </p>
            <div className="mt-4 flex items-center justify-center gap-3">
              <select
                className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
                value={workspaceFilter}
                onChange={(e) => setWorkspaceFilter(e.target.value)}
              >
                <option value="">Select workspace...</option>
                {workspaces?.map((ws: WorkspaceRow) => (
                  <option key={ws.id} value={ws.id}>
                    {ws.name || ws.id.slice(0, 12)}
                  </option>
                ))}
              </select>
              <Button
                variant="default"
                size="sm"
                onClick={handleFindCandidates}
                disabled={scanning || !workspaceFilter}
              >
                <Search className="h-3.5 w-3.5 mr-1.5" />
                {scanning ? 'Scanning...' : 'Find New Candidates'}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Filters + Find Candidates */}
          <Card>
            <CardContent className="p-4">
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex items-center gap-2">
                  <Filter className="h-4 w-4 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground font-medium">Filters</span>
                </div>

                {/* Workspace filter */}
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] text-muted-foreground uppercase tracking-wider">Workspace</label>
                  <select
                    className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    value={workspaceFilter}
                    onChange={(e) => setWorkspaceFilter(e.target.value)}
                  >
                    <option value="">All workspaces</option>
                    {workspaces?.map((ws: WorkspaceRow) => (
                      <option key={ws.id} value={ws.id}>
                        {ws.name || ws.id.slice(0, 12)}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Date range */}
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] text-muted-foreground uppercase tracking-wider">From</label>
                  <div className="flex items-center gap-1">
                    <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
                    <Input
                      type="date"
                      className="h-9 w-40"
                      value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)}
                    />
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] text-muted-foreground uppercase tracking-wider">To</label>
                  <div className="flex items-center gap-1">
                    <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
                    <Input
                      type="date"
                      className="h-9 w-40"
                      value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)}
                    />
                  </div>
                </div>

                {(workspaceFilter || dateFrom || dateTo) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-9 text-xs"
                    onClick={() => { setWorkspaceFilter(''); setDateFrom(''); setDateTo(''); }}
                  >
                    <X className="h-3 w-3 mr-1" />
                    Clear filters
                  </Button>
                )}

                <div className="text-xs text-muted-foreground ml-auto flex items-center gap-3">
                  <span>
                    Showing {filteredGroups.length} of {groups.length} groups
                  </span>
                  {/* Find New Candidates */}
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      min="0"
                      max="1"
                      step="0.05"
                      className="h-8 w-20 text-xs"
                      placeholder="0.8"
                      value={scanThreshold}
                      onChange={(e) => setScanThreshold(e.target.value)}
                      title="Cosine similarity threshold"
                    />
                    <Button
                      variant="default"
                      size="sm"
                      className="h-8 text-xs"
                      onClick={handleFindCandidates}
                      disabled={scanning || !workspaceFilter}
                    >
                      <Search className="h-3 w-3 mr-1" />
                      {scanning ? 'Scanning...' : 'Find New Candidates'}
                    </Button>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Merge suggestions (if any) */}
          {filteredSuggestions.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Search className="h-4 w-4 text-amber-500" />
                  Pending Merge Suggestions
                  <Badge variant="outline" className="ml-1 text-[10px]">
                    {pendingCount} pending
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {filteredSuggestions.map((s) => (
                    <SuggestionCard
                      key={s.id}
                      suggestion={s}
                      onApprove={handleApproveMerge}
                      onReject={handleRejectMerge}
                      memories={memories || []}
                    />
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Merge group cards */}
          {filteredGroups.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center text-muted-foreground">
                <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-30" />
                <p>No merge groups match the current filters.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filteredGroups.map((group) => (
                <MergeGroupCard
                  key={group.survivor.id}
                  group={group}
                  selected={selectedSurvivorId === group.survivor.id}
                  onSelect={() => setSelectedSurvivorId(group.survivor.id)}
                  onCompare={handleCompare}
                  onViewSurvivor={handleViewSurvivor}
                  onKeepBoth={handleKeepBoth}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
