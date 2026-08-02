import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Brain,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Play,
  StopCircle,
  Trash2,
  Plus,
  Layers,
  Lightbulb,
  Search,
  Zap,
  GitBranch,
  Eye,
  ArrowLeft,
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

interface ReflectionSession {
  id: string;
  workspace_id: string;
  peer_id: string;
  config_json: string;
  cycles_completed: number;
  status: string;
  insight_count: number;
  started_at: string;
  completed_at: string | null;
  created_at: string;
}

interface ReflectionInsight {
  id: string;
  workspace_id: string;
  session_id: string;
  content: string;
  confidence: number;
  insight_type: string;
  source_memory_ids: string;
  source_note_ids: string;
  cycle: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const INSIGHT_TYPES = [
  'pattern',
  'contradiction',
  'gap',
  'observation',
  'connection',
  'synthesis',
] as const;

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-500/10 text-green-600 border-green-500/30',
  completed: 'bg-blue-500/10 text-blue-600 border-blue-500/30',
  aborted: 'bg-red-500/10 text-red-600 border-red-500/30',
  archived: 'bg-gray-500/10 text-gray-600 border-gray-500/30',
};

const INSIGHT_TYPE_COLORS: Record<string, string> = {
  pattern: 'bg-purple-500/10 text-purple-600',
  contradiction: 'bg-red-500/10 text-red-600',
  gap: 'bg-amber-500/10 text-amber-600',
  observation: 'bg-blue-500/10 text-blue-600',
  connection: 'bg-emerald-500/10 text-emerald-600',
  synthesis: 'bg-cyan-500/10 text-cyan-600',
};

const INSIGHT_TYPE_ICONS: Record<string, React.ElementType> = {
  pattern: Search,
  contradiction: AlertCircle,
  gap: X,
  observation: Eye,
  connection: GitBranch,
  synthesis: Zap,
};

const DEFAULT_CONFIG = JSON.stringify(
  {
    depth: 3,
    types: ['pattern', 'contradiction', 'gap', 'observation', 'connection', 'synthesis'],
    max_insights_per_cycle: 10,
    min_confidence: 0.3,
  },
  null,
  2,
);

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

export default function ReflectionLoopPage() {
  const [sessions, setSessions] = useState<ReflectionSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Create form
  const [showForm, setShowForm] = useState(false);
  const [newWorkspaceId, setNewWorkspaceId] = useState('');
  const [newPeerId, setNewPeerId] = useState('');
  const [newConfigJson, setNewConfigJson] = useState(DEFAULT_CONFIG);
  const [creating, setCreating] = useState(false);

  // Session detail
  const [selectedSession, setSelectedSession] = useState<ReflectionSession | null>(null);
  const [insights, setInsights] = useState<ReflectionInsight[]>([]);
  const [loadingInsights, setLoadingInsights] = useState(false);

  // Actions
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  // -----------------------------------------------------------------------
  // Load sessions
  // -----------------------------------------------------------------------

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      await callReducer('get_reflection_sessions', ['']);
      const res = await executeSql(
        "SELECT * FROM reflection_session_result WHERE workspace_id = '' ORDER BY created_at DESC"
      );
      const rows = parseSqlResponse<Record<string, unknown>>(res);

      if (rows.length > 0 && rows[0].json_data) {
        try {
          const parsed = JSON.parse(rows[0].json_data as string) as ReflectionSession[];
          setSessions(parsed);
          return;
        } catch {
          // fall through
        }
      }

      // Map flat rows if no json_data
      const mapped = rows.map((r) => ({
        id: String(r.id ?? ''),
        workspace_id: String(r.workspace_id ?? ''),
        peer_id: String(r.peer_id ?? ''),
        config_json: String(r.config_json ?? '{}'),
        cycles_completed: Number(r.cycles_completed ?? 0),
        status: String(r.status ?? 'active'),
        insight_count: Number(r.insight_count ?? 0),
        started_at: String(r.started_at ?? ''),
        completed_at: r.completed_at ? String(r.completed_at) : null,
        created_at: String(r.created_at ?? ''),
      }));
      setSessions(mapped);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // -----------------------------------------------------------------------
  // Select session & load insights
  // -----------------------------------------------------------------------

  const selectSession = useCallback(async (session: ReflectionSession) => {
    setSelectedSession(session);
    setLoadingInsights(true);
    setError(null);
    try {
      await callReducer('get_reflection_insights', ['', session.id]);
      const res = await executeSql(
        "SELECT * FROM reflection_insight_result WHERE workspace_id = '' AND session_id = '" +
          session.id +
          "' ORDER BY created_at ASC"
      );
      const rows = parseSqlResponse<Record<string, unknown>>(res);

      if (rows.length > 0 && rows[0].json_data) {
        try {
          const parsed = JSON.parse(rows[0].json_data as string) as ReflectionInsight[];
          setInsights(parsed);
          return;
        } catch {
          // fall through
        }
      }

      const mapped = rows.map((r) => ({
        id: String(r.id ?? ''),
        workspace_id: String(r.workspace_id ?? ''),
        session_id: String(r.session_id ?? ''),
        content: String(r.content ?? ''),
        confidence: Number(r.confidence ?? 0),
        insight_type: String(r.insight_type ?? 'observation'),
        source_memory_ids: String(r.source_memory_ids ?? '[]'),
        source_note_ids: String(r.source_note_ids ?? '[]'),
        cycle: Number(r.cycle ?? 0),
        created_at: String(r.created_at ?? ''),
      }));
      setInsights(mapped);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load insights');
    } finally {
      setLoadingInsights(false);
    }
  }, []);

  const backToList = useCallback(() => {
    setSelectedSession(null);
    setInsights([]);
  }, []);

  // -----------------------------------------------------------------------
  // Create session
  // -----------------------------------------------------------------------

  const handleCreate = useCallback(async () => {
    clearMessages();
    if (!newWorkspaceId.trim() || !newPeerId.trim()) {
      setError('Workspace ID and Peer ID are required');
      return;
    }
    let config: Record<string, unknown>;
    try {
      config = JSON.parse(newConfigJson);
    } catch {
      setError('Invalid JSON in config');
      return;
    }
    setCreating(true);
    try {
      await callReducer('create_reflection_session', [
        newWorkspaceId.trim(),
        newPeerId.trim(),
        JSON.stringify(config),
      ]);
      setSuccessMsg('Reflection session created');
      setShowForm(false);
      setNewWorkspaceId('');
      setNewPeerId('');
      setNewConfigJson(DEFAULT_CONFIG);
      loadSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create session');
    } finally {
      setCreating(false);
    }
  }, [newWorkspaceId, newPeerId, newConfigJson, loadSessions]);

  // -----------------------------------------------------------------------
  // Actions: start cycle, complete, delete
  // -----------------------------------------------------------------------

  const handleStartCycle = useCallback(
    async (session: ReflectionSession) => {
      clearMessages();
      setActionLoading(session.id);
      try {
        await callReducer('start_reflection_cycle', [session.workspace_id, session.id]);
        setSuccessMsg(`Cycle started for session ${session.id.slice(0, 8)}`);
        loadSessions();
        if (selectedSession?.id === session.id) {
          selectSession(session);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to start cycle');
      } finally {
        setActionLoading(null);
      }
    },
    [loadSessions, selectedSession, selectSession],
  );

  const handleComplete = useCallback(
    async (session: ReflectionSession) => {
      clearMessages();
      setActionLoading(session.id);
      try {
        await callReducer('complete_reflection_session', [
          session.workspace_id,
          session.id,
          'completed',
        ]);
        setSuccessMsg(`Session ${session.id.slice(0, 8)} completed`);
        loadSessions();
        if (selectedSession?.id === session.id) {
          setSelectedSession((prev) =>
            prev ? { ...prev, status: 'completed' } : null,
          );
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to complete session');
      } finally {
        setActionLoading(null);
      }
    },
    [loadSessions, selectedSession],
  );

  const handleDelete = useCallback(
    async (session: ReflectionSession) => {
      clearMessages();
      if (!confirm(`Delete reflection session ${session.id.slice(0, 8)}?`)) return;
      setActionLoading(session.id);
      try {
        await callReducer('delete_reflection_session', [
          session.workspace_id,
          session.id,
        ]);
        setSuccessMsg(`Session ${session.id.slice(0, 8)} deleted`);
        if (selectedSession?.id === session.id) {
          setSelectedSession(null);
          setInsights([]);
        }
        loadSessions();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete session');
      } finally {
        setActionLoading(null);
      }
    },
    [loadSessions, selectedSession],
  );

  // -----------------------------------------------------------------------
  // Insight type chart data
  // -----------------------------------------------------------------------

  const insightTypeCounts = INSIGHT_TYPES.map((type) => ({
    type,
    count: insights.filter((i) => i.insight_type === type).length,
  }));

  const maxTypeCount = Math.max(...insightTypeCounts.map((t) => t.count), 1);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  // Detail view
  if (selectedSession) {
    return (
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={backToList}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
                <Brain className="h-7 w-7 text-primary" />
                Reflection Session
              </h1>
              <p className="text-sm text-muted-foreground">
                {selectedSession.id.slice(0, 16)}...
              </p>
            </div>
          </div>
          <Badge
            className={
              STATUS_COLORS[selectedSession.status] ??
              'bg-gray-500/10 text-gray-600'
            }
          >
            {selectedSession.status}
          </Badge>
        </div>

        {error && (
          <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-destructive text-sm">
            <AlertCircle className="h-5 w-5 shrink-0" />
            <span>{error}</span>
            <button onClick={() => setError(null)} className="ml-auto">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {successMsg && (
          <div className="flex items-center gap-3 rounded-lg border border-green-500/50 bg-green-500/10 p-3 text-green-600 text-sm">
            <Check className="h-5 w-5 shrink-0" />
            <span>{successMsg}</span>
            <button onClick={() => setSuccessMsg(null)} className="ml-auto">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Session Info */}
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Peer</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-mono text-sm">{selectedSession.peer_id}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Cycles</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{selectedSession.cycles_completed}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Insights</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{insights.length}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Started</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-muted-foreground">
                {formatMemoryTimestamp(selectedSession.started_at)}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => handleStartCycle(selectedSession)}
            disabled={actionLoading === selectedSession.id || selectedSession.status !== 'active'}
            variant="default"
          >
            <Play className="h-4 w-4 mr-1.5" />
            Start Cycle
          </Button>
          <Button
            onClick={() => handleComplete(selectedSession)}
            disabled={actionLoading === selectedSession.id || selectedSession.status !== 'active'}
            variant="secondary"
          >
            <StopCircle className="h-4 w-4 mr-1.5" />
            Complete
          </Button>
          <Button
            onClick={() => handleDelete(selectedSession)}
            disabled={actionLoading === selectedSession.id}
            variant="destructive"
          >
            <Trash2 className="h-4 w-4 mr-1.5" />
            Delete
          </Button>
          <Button variant="outline" onClick={loadSessions}>
            <RefreshCw className="h-4 w-4 mr-1.5" />
            Refresh
          </Button>
        </div>

        {/* Config */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="rounded-lg bg-muted p-3 text-xs overflow-x-auto">
              {(() => {
                try {
                  return JSON.stringify(JSON.parse(selectedSession.config_json), null, 2);
                } catch {
                  return selectedSession.config_json;
                }
              })()}
            </pre>
          </CardContent>
        </Card>

        {/* Insight Type Chart */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-lg flex items-center gap-2">
              <BarChart3 className="h-5 w-5" />
              Insights by Type
            </CardTitle>
            <CardDescription>
              Distribution of {insights.length} insight(s) across types
            </CardDescription>
          </CardHeader>
          <CardContent>
            {insightTypeCounts.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No insights yet. Start a cycle to generate insights.
              </p>
            ) : (
              <div className="space-y-3">
                {insightTypeCounts.map(({ type, count }) => {
                  const Icon = INSIGHT_TYPE_ICONS[type] ?? Lightbulb;
                  const pct = (count / maxTypeCount) * 100;
                  return (
                    <div key={type} className="flex items-center gap-3">
                      <div className="flex items-center gap-2 w-32 shrink-0">
                        <Icon className="h-4 w-4 text-muted-foreground" />
                        <span className="text-sm capitalize">{type}</span>
                      </div>
                      <div className="flex-1 h-5 rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full rounded-full bg-primary/60 transition-all duration-500"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="text-sm font-mono w-8 text-right shrink-0">
                        {count}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Insights List */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-lg flex items-center gap-2">
              <Lightbulb className="h-5 w-5" />
              Insights
            </CardTitle>
            <CardDescription>
              All insights generated during this reflection session
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loadingInsights ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-20 rounded-lg bg-muted animate-pulse" />
                ))}
              </div>
            ) : insights.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No insights recorded yet.
              </p>
            ) : (
              <div className="space-y-3">
                {insights.map((insight) => (
                  <div
                    key={insight.id}
                    className="rounded-lg border border-border p-4 space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge
                          className={
                            INSIGHT_TYPE_COLORS[insight.insight_type] ??
                            'bg-gray-500/10 text-gray-600'
                          }
                        >
                          {insight.insight_type}
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          Cycle {insight.cycle}
                        </Badge>
                        <Badge variant="secondary" className="text-xs">
                          {(insight.confidence * 100).toFixed(0)}% confidence
                        </Badge>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {formatMemoryTimestamp(insight.created_at)}
                      </span>
                    </div>
                    <p className="text-sm">{insight.content}</p>
                    <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
                      {insight.source_memory_ids !== '[]' && (
                        <span>
                          Memories: {JSON.parse(insight.source_memory_ids).length}
                        </span>
                      )}
                      {insight.source_note_ids !== '[]' && (
                        <span>
                          Notes: {JSON.parse(insight.source_note_ids).length}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // List view (default)
  // -----------------------------------------------------------------------

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="h-7 w-7 text-primary" />
            Reflection Loop
          </h1>
          <p className="text-muted-foreground">
            Structured self-reflection sessions for AI agents
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={loadSessions}>
            <RefreshCw className="h-4 w-4 mr-1.5" />
            Refresh
          </Button>
          <Button onClick={() => setShowForm(!showForm)}>
            <Plus className="h-4 w-4 mr-1.5" />
            New Session
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-destructive text-sm">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {successMsg && (
        <div className="flex items-center gap-3 rounded-lg border border-green-500/50 bg-green-500/10 p-3 text-green-600 text-sm">
          <Check className="h-5 w-5 shrink-0" />
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg(null)} className="ml-auto">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Create Session Form */}
      {showForm && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Plus className="h-5 w-5" />
              New Reflection Session
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Workspace ID
                </label>
                <input
                  placeholder="workspace-id"
                  value={newWorkspaceId}
                  onChange={(e) => setNewWorkspaceId(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Peer ID
                </label>
                <input
                  placeholder="peer-id"
                  value={newPeerId}
                  onChange={(e) => setNewPeerId(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Configuration (JSON)
              </label>
              <textarea
                rows={8}
                value={newConfigJson}
                onChange={(e) => setNewConfigJson(e.target.value)}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>
            <div className="flex gap-2">
              <Button onClick={handleCreate} disabled={creating}>
                {creating ? 'Creating...' : 'Create Session'}
              </Button>
              <Button variant="outline" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sessions List */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Layers className="h-5 w-5" />
            Active Sessions
          </CardTitle>
          <CardDescription>
            {sessions.length} reflection session(s)
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="h-24 rounded-lg bg-muted animate-pulse"
                />
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <Brain className="h-12 w-12 text-muted-foreground/30 mb-4" />
              <h3 className="text-xl font-semibold mb-2">No Reflection Sessions</h3>
              <p className="text-muted-foreground mb-6">
                Create a new session to start the reflection loop.
              </p>
              <Button onClick={() => setShowForm(true)}>
                <Plus className="h-4 w-4 mr-1.5" />
                New Session
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className="rounded-lg border border-border p-4 hover:bg-accent/50 transition-colors cursor-pointer"
                  onClick={() => selectSession(session)}
                >
                  <div className="flex items-start justify-between">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-medium">
                          {session.id.slice(0, 16)}...
                        </span>
                        <Badge
                          className={
                            STATUS_COLORS[session.status] ??
                            'bg-gray-500/10 text-gray-600'
                          }
                        >
                          {session.status}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground">
                        <span>Peer: {session.peer_id}</span>
                        <span>Cycles: {session.cycles_completed}</span>
                        <span>Insights: {session.insight_count}</span>
                        <span>
                          Started: {formatMemoryTimestamp(session.started_at)}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        title="Start Cycle"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleStartCycle(session);
                        }}
                        disabled={
                          actionLoading === session.id ||
                          session.status !== 'active'
                        }
                      >
                        <Play className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        title="Complete"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleComplete(session);
                        }}
                        disabled={
                          actionLoading === session.id ||
                          session.status !== 'active'
                        }
                      >
                        <StopCircle className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-destructive hover:text-destructive"
                        title="Delete"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(session);
                        }}
                        disabled={actionLoading === session.id}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Local helper (bar chart icon, not exported from lucide-react directly)
// ---------------------------------------------------------------------------

function BarChart3({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <line x1="3" y1="20" x2="21" y2="20" />
      <rect x="4" y="13" width="4" height="5" />
      <rect x="10" y="9" width="4" height="9" />
      <rect x="16" y="6" width="4" height="12" />
    </svg>
  );
}
