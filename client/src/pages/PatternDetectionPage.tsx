import { useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  BarChart3,
  AlertCircle,
  Check,
  X,
  Play,
  Clock,
  Hash,
  Link2,
  FileText,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
} from '@/lib/spacetimedb';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TemporalClusterResult {
  id: string;
  workspace_id: string;
  start_time: number;
  end_time: number;
  count: number;
  /** JSON array of memory IDs */
  memory_ids: string;
  /** JSON array of top summary terms */
  summary_terms: string;
  created_at: number;
}

interface EntityCooccurrenceResult {
  id: string;
  workspace_id: string;
  entity_a: string;
  entity_b: string;
  count: number;
  strength: number;
  created_at: number;
}

interface TopicClusterResult {
  id: string;
  workspace_id: string;
  topic: string;
  count: number;
  /** JSON array of memory IDs */
  memory_ids: string;
  /** JSON array of top terms */
  top_terms: string;
  avg_confidence: number;
  created_at: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtTime(ts: number): string {
  const d = new Date(ts / 1000);
  return d.toLocaleString();
}

function fmtNum(n: number): string {
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'B';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}

function fmtPct(n: number): string {
  return (n * 100).toFixed(1) + '%';
}

function parseJsonArray(raw: string): string[] {
  try {
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Section State
// ---------------------------------------------------------------------------

interface SectionState<T> {
  data: T[];
  loading: boolean;
  error: string | null;
  running: boolean;
}

function initialSection<T>(): SectionState<T> {
  return { data: [], loading: false, error: null, running: false };
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function PatternDetectionPage() {
  const [workspaceId, setWorkspaceId] = useState('');
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Three section states
  const [temporal, setTemporal] = useState<SectionState<TemporalClusterResult>>(initialSection);
  const [cooccurrence, setCooccurrence] = useState<SectionState<EntityCooccurrenceResult>>(initialSection);
  const [topic, setTopic] = useState<SectionState<TopicClusterResult>>(initialSection);

  const clearErrors = () => {
    setTemporal((s) => ({ ...s, error: null }));
    setCooccurrence((s) => ({ ...s, error: null }));
    setTopic((s) => ({ ...s, error: null }));
    setSuccessMsg(null);
  };

  // -----------------------------------------------------------------------
  // Run Detection — Temporal Clusters
  // -----------------------------------------------------------------------

  const runTemporalDetection = useCallback(async () => {
    clearErrors();
    if (!workspaceId.trim()) {
      setTemporal((s) => ({ ...s, error: 'Workspace ID is required' }));
      return;
    }
    setTemporal((s) => ({ ...s, running: true, loading: true, error: null }));
    try {
      await callReducer('detect_temporal_clusters', [workspaceId.trim()]);
      const res = await executeSql(
        `SELECT * FROM temporal_cluster_result WHERE workspace_id = '${workspaceId.trim()}' ORDER BY start_time DESC`
      );
      const rows = parseSqlResponse<TemporalClusterResult>(res);
      const mapped = rows.map((r) => ({
        id: String(r.id ?? ''),
        workspace_id: String(r.workspace_id ?? ''),
        start_time: Number(r.start_time ?? 0),
        end_time: Number(r.end_time ?? 0),
        count: Number(r.count ?? 0),
        memory_ids: String(r.memory_ids ?? '[]'),
        summary_terms: String(r.summary_terms ?? '[]'),
        created_at: Number(r.created_at ?? 0),
      }));
      setTemporal((s) => ({ ...s, data: mapped, loading: false, error: null }));
      setSuccessMsg(`Temporal cluster detection complete — ${mapped.length} cluster(s) found`);
    } catch (err) {
      setTemporal((s) => ({
        ...s,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to detect temporal clusters',
      }));
    } finally {
      setTemporal((s) => ({ ...s, running: false }));
    }
  }, [workspaceId]);

  // -----------------------------------------------------------------------
  // Run Detection — Entity Co-occurrences
  // -----------------------------------------------------------------------

  const runCooccurrenceDetection = useCallback(async () => {
    clearErrors();
    if (!workspaceId.trim()) {
      setCooccurrence((s) => ({ ...s, error: 'Workspace ID is required' }));
      return;
    }
    setCooccurrence((s) => ({ ...s, running: true, loading: true, error: null }));
    try {
      await callReducer('detect_entity_cooccurrences', [workspaceId.trim()]);
      const res = await executeSql(
        `SELECT * FROM entity_cooccurrence_result WHERE workspace_id = '${workspaceId.trim()}' ORDER BY count DESC`
      );
      const rows = parseSqlResponse<EntityCooccurrenceResult>(res);
      const mapped = rows.map((r) => ({
        id: String(r.id ?? ''),
        workspace_id: String(r.workspace_id ?? ''),
        entity_a: String(r.entity_a ?? ''),
        entity_b: String(r.entity_b ?? ''),
        count: Number(r.count ?? 0),
        strength: Number(r.strength ?? 0),
        created_at: Number(r.created_at ?? 0),
      }));
      setCooccurrence((s) => ({ ...s, data: mapped, loading: false, error: null }));
      setSuccessMsg(`Entity co-occurrence detection complete — ${mapped.length} pair(s) found`);
    } catch (err) {
      setCooccurrence((s) => ({
        ...s,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to detect entity co-occurrences',
      }));
    } finally {
      setCooccurrence((s) => ({ ...s, running: false }));
    }
  }, [workspaceId]);

  // -----------------------------------------------------------------------
  // Run Detection — Topic Clusters
  // -----------------------------------------------------------------------

  const runTopicDetection = useCallback(async () => {
    clearErrors();
    if (!workspaceId.trim()) {
      setTopic((s) => ({ ...s, error: 'Workspace ID is required' }));
      return;
    }
    setTopic((s) => ({ ...s, running: true, loading: true, error: null }));
    try {
      await callReducer('detect_topic_clusters', [workspaceId.trim()]);
      const res = await executeSql(
        `SELECT * FROM topic_cluster_result WHERE workspace_id = '${workspaceId.trim()}' ORDER BY count DESC`
      );
      const rows = parseSqlResponse<TopicClusterResult>(res);
      const mapped = rows.map((r) => ({
        id: String(r.id ?? ''),
        workspace_id: String(r.workspace_id ?? ''),
        topic: String(r.topic ?? ''),
        count: Number(r.count ?? 0),
        memory_ids: String(r.memory_ids ?? '[]'),
        top_terms: String(r.top_terms ?? '[]'),
        avg_confidence: Number(r.avg_confidence ?? 0),
        created_at: Number(r.created_at ?? 0),
      }));
      setTopic((s) => ({ ...s, data: mapped, loading: false, error: null }));
      setSuccessMsg(`Topic cluster detection complete — ${mapped.length} cluster(s) found`);
    } catch (err) {
      setTopic((s) => ({
        ...s,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to detect topic clusters',
      }));
    } finally {
      setTopic((s) => ({ ...s, running: false }));
    }
  }, [workspaceId]);

  // -----------------------------------------------------------------------
  // Render helpers
  // -----------------------------------------------------------------------

  const renderError = (error: string | null) =>
    error ? (
      <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-destructive text-sm">
        <AlertCircle className="h-5 w-5 shrink-0" />
        <span>{error}</span>
        <button onClick={() => setTemporal((s) => ({ ...s, error: null }))} className="ml-auto">
          <X className="h-4 w-4" />
        </button>
      </div>
    ) : null;

  const renderSectionHeader = (
    title: string,
    description: string,
    icon: React.ElementType,
    running: boolean,
    onRun: () => void,
  ) => {
    const Icon = icon;
    return (
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <Icon className="h-6 w-6 text-primary mt-1 shrink-0" />
          <div>
            <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        <Button onClick={onRun} disabled={running} size="sm">
          <Play className="h-4 w-4 mr-1.5" />
          {running ? 'Running...' : 'Run Detection'}
        </Button>
      </div>
    );
  };

  // -----------------------------------------------------------------------
  // Section: Temporal Clusters
  // -----------------------------------------------------------------------

  const renderTemporalClusters = () => (
    <Card>
      <CardHeader>
        {renderSectionHeader(
          'Temporal Clusters',
          'Groups of memories stored close together in time (30-minute buckets)',
          Clock,
          temporal.running,
          runTemporalDetection,
        )}
      </CardHeader>
      <CardContent>
        {renderError(temporal.error)}
        {temporal.loading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-16 rounded-lg bg-muted animate-pulse" />
            ))}
          </div>
        ) : temporal.data.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <Clock className="h-10 w-10 text-muted-foreground/30 mb-3" />
            <p className="font-medium">No temporal clusters</p>
            <p className="text-sm text-muted-foreground mt-1">
              Run detection to find time-based memory clusters.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {temporal.data.map((cluster) => {
              const terms = parseJsonArray(cluster.summary_terms);
              return (
                <div
                  key={cluster.id}
                  className="rounded-lg border border-border p-4 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary" className="font-mono">
                        {fmtNum(cluster.count)} memories
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {fmtTime(cluster.start_time)} – {fmtTime(cluster.end_time)}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {formatMemoryTimestamp(cluster.created_at)}
                    </span>
                  </div>
                  {terms.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {terms.map((term) => (
                        <Badge key={term} variant="outline" className="text-xs">
                          {term}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );

  // -----------------------------------------------------------------------
  // Section: Entity Co-occurrences
  // -----------------------------------------------------------------------

  const renderCooccurrences = () => (
    <Card>
      <CardHeader>
        {renderSectionHeader(
          'Entity Co-occurrences',
          'Pairs of entities that frequently appear together in the same memory',
          Link2,
          cooccurrence.running,
          runCooccurrenceDetection,
        )}
      </CardHeader>
      <CardContent>
        {renderError(cooccurrence.error)}
        {cooccurrence.loading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-16 rounded-lg bg-muted animate-pulse" />
            ))}
          </div>
        ) : cooccurrence.data.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <Link2 className="h-10 w-10 text-muted-foreground/30 mb-3" />
            <p className="font-medium">No entity co-occurrences</p>
            <p className="text-sm text-muted-foreground mt-1">
              Run detection to find entity co-occurrence patterns.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="pb-2 pr-4 font-medium">Entity A</th>
                  <th className="pb-2 pr-4 font-medium">Entity B</th>
                  <th className="pb-2 pr-4 font-medium text-right">Co-occurrences</th>
                  <th className="pb-2 pr-4 font-medium text-right">Strength</th>
                  <th className="pb-2 font-medium">Detected</th>
                </tr>
              </thead>
              <tbody>
                {cooccurrence.data.map((pair) => (
                  <tr key={pair.id} className="border-b border-border/50 hover:bg-muted/50 transition-colors">
                    <td className="py-2 pr-4 font-medium">{pair.entity_a}</td>
                    <td className="py-2 pr-4 font-medium">{pair.entity_b}</td>
                    <td className="py-2 pr-4 text-right">
                      <Badge variant="secondary" className="font-mono">
                        {fmtNum(pair.count)}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-2 rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full rounded-full bg-primary/60"
                            style={{ width: `${pair.strength * 100}%` }}
                          />
                        </div>
                        <span className="text-xs font-mono text-muted-foreground">
                          {fmtPct(pair.strength)}
                        </span>
                      </div>
                    </td>
                    <td className="py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {formatMemoryTimestamp(pair.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );

  // -----------------------------------------------------------------------
  // Section: Topic Clusters
  // -----------------------------------------------------------------------

  const renderTopicClusters = () => (
    <Card>
      <CardHeader>
        {renderSectionHeader(
          'Topic Clusters',
          'Groups of memories organised by shared term frequency',
          FileText,
          topic.running,
          runTopicDetection,
        )}
      </CardHeader>
      <CardContent>
        {renderError(topic.error)}
        {topic.loading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-20 rounded-lg bg-muted animate-pulse" />
            ))}
          </div>
        ) : topic.data.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <FileText className="h-10 w-10 text-muted-foreground/30 mb-3" />
            <p className="font-medium">No topic clusters</p>
            <p className="text-sm text-muted-foreground mt-1">
              Run detection to find topic-based memory clusters.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {topic.data.map((cluster) => {
              const topTerms = parseJsonArray(cluster.top_terms);
              return (
                <div
                  key={cluster.id}
                  className="rounded-lg border border-border p-4 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge className="bg-primary/10 text-primary border-primary/20">
                        {cluster.topic}
                      </Badge>
                      <Badge variant="secondary" className="font-mono">
                        {fmtNum(cluster.count)} memories
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {(cluster.avg_confidence * 100).toFixed(0)}% avg confidence
                      </Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {formatMemoryTimestamp(cluster.created_at)}
                    </span>
                  </div>
                  {topTerms.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {topTerms.slice(0, 5).map((term) => (
                        <Badge key={term} variant="outline" className="text-xs">
                          {term}
                        </Badge>
                      ))}
                      {topTerms.length > 5 && (
                        <Badge variant="outline" className="text-xs text-muted-foreground">
                          +{topTerms.length - 5} more
                        </Badge>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );

  // -----------------------------------------------------------------------
  // Main render
  // -----------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <BarChart3 className="h-7 w-7 text-primary" />
            Pattern Detection
          </h1>
          <p className="text-muted-foreground">
            Discover temporal, entity, and topic patterns across your memories
          </p>
        </div>
      </div>

      {/* Workspace ID input */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Hash className="h-5 w-5" />
            Workspace
          </CardTitle>
          <CardDescription>
            Enter a workspace ID to run pattern detection against its memories.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <input
              placeholder="workspace-id"
              value={workspaceId}
              onChange={(e) => setWorkspaceId(e.target.value)}
              className="flex h-10 w-full max-w-sm rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
          </div>
        </CardContent>
      </Card>

      {/* Success message */}
      {successMsg && (
        <div className="flex items-center gap-3 rounded-lg border border-green-500/50 bg-green-500/10 p-3 text-green-600 text-sm">
          <Check className="h-5 w-5 shrink-0" />
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg(null)} className="ml-auto">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Three detection sections */}
      {renderTemporalClusters()}
      {renderCooccurrences()}
      {renderTopicClusters()}
    </div>
  );
}
