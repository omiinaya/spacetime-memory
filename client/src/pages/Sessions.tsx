import { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable } from '@/lib/useReactiveDb';
import { callReducer, formatMemoryTimestamp } from '@/lib/spacetimedb';
import {
  MessageSquare,
  AlertCircle,
  Plus,
  Trash2,
  Search,
  X,
  Clock,
  RefreshCw,
  Activity,
} from 'lucide-react';

// ─────────────────────────────────────────────────
// Types matching auto-generated SpacetimeDB bindings (camelCase)
// ─────────────────────────────────────────────────
interface SessionRow {
  id: string;
  workspaceId: string;
  name: string;
  summary: string;
  metadata: string;
  createdAt: number;
  updatedAt: number;
}

// ─────────────────────────────────────────────────
// Loading skeleton
// ─────────────────────────────────────────────────
function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-start gap-3 rounded-lg border border-border p-3">
          <Skeleton className="h-8 w-8 rounded-full mt-0.5 shrink-0" />
          <div className="space-y-1 flex-1 min-w-0">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-3 w-56 mt-1" />
          </div>
          <Skeleton className="h-6 w-16 rounded-full shrink-0" />
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────
export default function Sessions() {
  const { data: sessions, loading, error } = useTable<SessionRow>('session');

  // Local state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Create form state
  const [newName, setNewName] = useState('');
  const [newWorkspaceId, setNewWorkspaceId] = useState('default');

  // Filter + sort (recent first)
  const filteredSessions = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    let list = sessions;
    if (q) {
      list = list.filter(
        (s) =>
          s.name?.toLowerCase().includes(q) ||
          s.summary?.toLowerCase().includes(q) ||
          s.id?.toLowerCase().includes(q) ||
          s.workspaceId?.toLowerCase().includes(q),
      );
    }
    return [...list].sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0));
  }, [sessions, searchQuery]);

  const selectedSession = useMemo(
    () => (selectedSessionId ? filteredSessions.find((s) => s.id === selectedSessionId) ?? null : null),
    [selectedSessionId, filteredSessions],
  );

  const resetCreateForm = () => {
    setNewName('');
    setNewWorkspaceId('default');
    setShowCreateForm(false);
    setActionError(null);
  };

  // Create session
  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) {
      setActionError('Session name is required');
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      await callReducer('create_session', [newWorkspaceId, name, '{}']);
      resetCreateForm();
    } catch (e: any) {
      setActionError(e.message || 'Failed to create session');
    } finally {
      setSubmitting(false);
    }
  };

  // Delete session — NOTE: no delete_session reducer exists in backend,
  // so this will fail gracefully
  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete session "${name || id}"? This cannot be undone.`)) return;
    setActionError(null);
    try {
      await callReducer('delete_session', [id]);
      if (selectedSessionId === id) setSelectedSessionId(null);
    } catch (e: any) {
      setActionError(e.message || 'Failed to delete session');
    }
  };

  // Duration helper for detail view
  const formatDuration = (startMicros: number, endMicros?: number): string => {
    const startMs = startMicros / 1000;
    const endMs = endMicros ? endMicros / 1000 : Date.now();
    const diffMs = endMs - startMs;
    const secs = Math.floor(diffMs / 1000);
    if (secs < 60) return `${secs}s`;
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins}m ${secs % 60}s`;
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ${mins % 60}m`;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Sessions</h1>
          <p className="text-muted-foreground">
            {loading
              ? 'Loading...'
              : error
                ? 'Connection error'
                : `${filteredSessions.length} session(s)`}
          </p>
        </div>
        <Button onClick={() => setShowCreateForm(true)}>
          <Plus className="mr-2 h-4 w-4" /> Create Session
        </Button>
      </div>

      {/* Action error */}
      {actionError && (
        <Card className="border-destructive/50">
          <CardContent className="flex items-center gap-3 py-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="flex-1">{actionError}</span>
            <Button variant="ghost" size="sm" onClick={() => setActionError(null)}>
              <X className="h-3 w-3" />
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Search bar */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search sessions by name, summary, or ID..."
            className="pl-9"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearchQuery('')}
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* Create form */}
      {showCreateForm && (
        <Card className="border-primary/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Plus className="h-4 w-4" />
              New Session
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Name *</label>
              <Input
                placeholder="e.g. Morning standup, Code review with Alice"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Workspace ID</label>
              <Input
                placeholder="default"
                value={newWorkspaceId}
                onChange={(e) => setNewWorkspaceId(e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2 pt-2">
              <Button onClick={handleCreate} disabled={submitting || !newName.trim()}>
                {submitting ? 'Creating...' : 'Create Session'}
              </Button>
              <Button variant="outline" onClick={resetCreateForm}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Detail panel */}
      {selectedSession && (
        <Card className="border-primary/30 bg-primary/5">
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <MessageSquare className="h-5 w-5 text-primary" />
              <span>{selectedSession.name || selectedSession.id.slice(0, 24) + '…'}</span>
              <Badge variant="outline" className="text-xs">
                <Clock className="h-3 w-3 mr-1" />
                {formatDuration(selectedSession.createdAt, selectedSession.updatedAt)}
              </Badge>
            </CardTitle>
            <div className="flex items-center gap-2">
              <Button
                variant="destructive"
                size="sm"
                onClick={() => handleDelete(selectedSession.id, selectedSession.name)}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setSelectedSessionId(null)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-muted-foreground">ID</p>
                <p className="font-mono text-xs truncate">{selectedSession.id}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Workspace</p>
                <p className="font-mono text-xs truncate">{selectedSession.workspaceId || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Created</p>
                <p className="flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  {formatMemoryTimestamp(selectedSession.createdAt)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Updated</p>
                <p className="flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  {formatMemoryTimestamp(selectedSession.updatedAt)}
                </p>
              </div>
            </div>
            {selectedSession.summary && (
              <div>
                <p className="text-xs text-muted-foreground mb-1">Summary</p>
                <p className="text-sm bg-muted/30 rounded p-2">{selectedSession.summary}</p>
              </div>
            )}
            {selectedSession.metadata && selectedSession.metadata !== '{}' && (
              <div>
                <p className="text-xs text-muted-foreground mb-1">Metadata</p>
                <pre className="text-xs bg-muted/50 rounded p-2 overflow-x-auto max-h-24 font-mono">
                  {(() => {
                    try {
                      return JSON.stringify(JSON.parse(selectedSession.metadata), null, 2);
                    } catch {
                      return selectedSession.metadata;
                    }
                  })()}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Sessions list */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Session Log</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <AlertCircle className="h-8 w-8 mb-2 text-destructive/50" />
              <p className="text-sm text-muted-foreground mb-4">{error}</p>
              <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
                <RefreshCw className="h-3 w-3 mr-2" /> Retry
              </Button>
            </div>
          ) : loading ? (
            <LoadingSkeleton />
          ) : filteredSessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
              <MessageSquare className="h-12 w-12 mb-4 opacity-20" />
              <p className="text-lg font-medium">
                {searchQuery ? 'No matching sessions' : 'No sessions yet'}
              </p>
              <p className="text-sm mt-1 max-w-sm">
                {searchQuery
                  ? `No sessions match "${searchQuery}". Try a different search term.`
                  : 'Create a session to start tracking conversations and interactions in your workspace.'}
              </p>
              {!searchQuery && (
                <Button className="mt-4" onClick={() => setShowCreateForm(true)}>
                  <Plus className="mr-2 h-4 w-4" /> Create First Session
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {filteredSessions.map((session) => (
                <div
                  key={session.id}
                  className={`flex items-start justify-between rounded-lg border p-3 transition-colors hover:bg-accent/50 cursor-pointer ${
                    selectedSessionId === session.id
                      ? 'border-primary/50 bg-accent/30'
                      : 'border-border'
                  }`}
                  onClick={() =>
                    setSelectedSessionId(selectedSessionId === session.id ? null : session.id)
                  }
                >
                  <div className="flex items-start gap-3 min-w-0 flex-1 mr-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted shrink-0 mt-0.5">
                      <MessageSquare className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium truncate max-w-[400px]">
                        {session.name || session.id.slice(0, 24) + '…'}
                      </p>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
                        <Clock className="h-3 w-3 shrink-0" />
                        <span>{formatMemoryTimestamp(session.createdAt)}</span>
                        <span className="text-muted-foreground/50">·</span>
                        <Activity className="h-3 w-3 shrink-0" />
                        <span>{formatDuration(session.createdAt, session.updatedAt)}</span>
                      </div>
                      {session.summary && (
                        <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2 max-w-[450px]">
                          {session.summary}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 mt-0.5">
                    <Badge variant={session.summary ? 'default' : 'secondary'} className="text-xs">
                      {session.summary ? 'Active' : 'Inactive'}
                    </Badge>
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
