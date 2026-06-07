import { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable } from '@/lib/useReactiveDb';
import { callReducer, formatMemoryTimestamp } from '@/lib/spacetimedb';
import {
  Users,
  AlertCircle,
  Plus,
  Trash2,
  Search,
  X,
  User,
  Bot,
  RefreshCw,
  Building2,
  Clock,
} from 'lucide-react';

// ─────────────────────────────────────────────────
// Types matching auto-generated SpacetimeDB bindings (camelCase)
// ─────────────────────────────────────────────────
interface PeerRow {
  id: string;
  workspaceId: string;
  name: string;
  peerType: string;
  metadata: string;
  createdAt: number;
  updatedAt: number;
}

// ─────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────
function peerTypeIcon(type: string) {
  switch (type?.toLowerCase()) {
    case 'user':
      return <User className="h-4 w-4 text-blue-500" />;
    case 'agent':
      return <Bot className="h-4 w-4 text-green-500" />;
    case 'entity':
      return <Building2 className="h-4 w-4 text-amber-500" />;
    default:
      return <Users className="h-4 w-4 text-muted-foreground" />;
  }
}

function peerTypeColor(type: string): string {
  switch (type?.toLowerCase()) {
    case 'user':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300';
    case 'agent':
      return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300';
    case 'entity':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300';
    default:
      return 'bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-300';
  }
}

function tryParseMetadata(json: string): Record<string, unknown> | null {
  if (!json || json === '{}') return null;
  try {
    return JSON.parse(json);
  } catch {
    return null;
  }
}

// ─────────────────────────────────────────────────
// Loading skeleton
// ─────────────────────────────────────────────────
function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between rounded-lg border border-border p-3">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <Skeleton className="h-8 w-8 rounded-full" />
            <div className="space-y-1 flex-1">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-3 w-24" />
            </div>
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
export default function Peers() {
  const { data: peers, loading, error } = useTable<PeerRow>('peer');

  // Local state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedPeerId, setSelectedPeerId] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Create form state
  const [newName, setNewName] = useState('');
  const [newPeerType, setNewPeerType] = useState('user');
  const [newWorkspaceId, setNewWorkspaceId] = useState('default');

  // Filter + sort
  const filteredPeers = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    let list = peers;
    if (q) {
      list = list.filter(
        (p) =>
          p.name?.toLowerCase().includes(q) ||
          p.peerType?.toLowerCase().includes(q) ||
          p.id?.toLowerCase().includes(q) ||
          p.workspaceId?.toLowerCase().includes(q),
      );
    }
    // Sort by createdAt descending (recent first)
    return [...list].sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0));
  }, [peers, searchQuery]);

  const selectedPeer = useMemo(
    () => (selectedPeerId ? filteredPeers.find((p) => p.id === selectedPeerId) ?? null : null),
    [selectedPeerId, filteredPeers],
  );

  // Reset create form
  const resetCreateForm = () => {
    setNewName('');
    setNewPeerType('user');
    setNewWorkspaceId('default');
    setShowCreateForm(false);
    setActionError(null);
  };

  // Create peer handler
  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) {
      setActionError('Name is required');
      return;
    }
    if (!['user', 'agent', 'entity'].includes(newPeerType)) {
      setActionError('Peer type must be user, agent, or entity');
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      await callReducer('create_peer', [newWorkspaceId, name, newPeerType, '{}']);
      resetCreateForm();
    } catch (e: any) {
      setActionError(e.message || 'Failed to create peer');
    } finally {
      setSubmitting(false);
    }
  };

  // Delete peer handler
  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete peer "${name || id}"? This cannot be undone.`)) return;
    setActionError(null);
    try {
      await callReducer('delete_peer', [id]);
      if (selectedPeerId === id) setSelectedPeerId(null);
    } catch (e: any) {
      setActionError(e.message || 'Failed to delete peer');
    }
  };

  // Compute workspace summary
  const workspacePeers = useMemo(() => {
    const map = new Map<string, { count: number; types: Set<string> }>();
    for (const p of filteredPeers) {
      const ws = p.workspaceId || '(none)';
      if (!map.has(ws)) map.set(ws, { count: 0, types: new Set() });
      const entry = map.get(ws)!;
      entry.count++;
      if (p.peerType) entry.types.add(p.peerType);
    }
    return map;
  }, [filteredPeers]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Peers</h1>
          <p className="text-muted-foreground">
            {loading
              ? 'Loading...'
              : error
                ? 'Connection error'
                : `${filteredPeers.length} peer(s) registered`}
          </p>
        </div>
        <Button onClick={() => setShowCreateForm(true)}>
          <Plus className="mr-2 h-4 w-4" /> Create Peer
        </Button>
      </div>

      {/* Action error message */}
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
            placeholder="Search peers by name, type, or ID..."
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

      {/* Create form (inline modal / expandable card) */}
      {showCreateForm && (
        <Card className="border-primary/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Plus className="h-4 w-4" />
              New Peer
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Name *</label>
              <Input
                placeholder="e.g. Alice, assistant-bot, hr-system"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Peer Type</label>
              <div className="flex gap-2">
                {['user', 'agent', 'entity'].map((type) => (
                  <Button
                    key={type}
                    variant={newPeerType === type ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setNewPeerType(type)}
                    className="flex items-center gap-1.5"
                  >
                    {type === 'user' && <User className="h-3.5 w-3.5" />}
                    {type === 'agent' && <Bot className="h-3.5 w-3.5" />}
                    {type === 'entity' && <Building2 className="h-3.5 w-3.5" />}
                    {type.charAt(0).toUpperCase() + type.slice(1)}
                  </Button>
                ))}
              </div>
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
                {submitting ? 'Creating...' : 'Create Peer'}
              </Button>
              <Button variant="outline" onClick={resetCreateForm}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Detail panel */}
      {selectedPeer && (
        <Card className="border-primary/30 bg-primary/5">
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              {peerTypeIcon(selectedPeer.peerType)}
              <span>{selectedPeer.name || selectedPeer.id.slice(0, 24)}</span>
              <Badge className={peerTypeColor(selectedPeer.peerType)}>
                {selectedPeer.peerType || 'unknown'}
              </Badge>
            </CardTitle>
            <div className="flex items-center gap-2">
              <Button
                variant="destructive"
                size="sm"
                onClick={() => handleDelete(selectedPeer.id, selectedPeer.name)}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setSelectedPeerId(null)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-muted-foreground">ID</p>
                <p className="font-mono text-xs truncate">{selectedPeer.id}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Workspace</p>
                <p className="font-mono text-xs truncate">{selectedPeer.workspaceId || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Created</p>
                <p className="flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  {formatMemoryTimestamp(selectedPeer.createdAt)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Updated</p>
                <p className="flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  {formatMemoryTimestamp(selectedPeer.updatedAt)}
                </p>
              </div>
            </div>
            {selectedPeer.metadata && selectedPeer.metadata !== '{}' && (
              <div>
                <p className="text-xs text-muted-foreground mb-1">Metadata</p>
                <pre className="text-xs bg-muted/50 rounded p-2 overflow-x-auto max-h-32 font-mono">
                  {(() => {
                    const parsed = tryParseMetadata(selectedPeer.metadata);
                    return parsed ? JSON.stringify(parsed, null, 2) : selectedPeer.metadata;
                  })()}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Main content */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">All Peers</CardTitle>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              {workspacePeers.size > 0 && (
                <span>
                  {Array.from(workspacePeers.entries())
                    .map(([ws, info]) => `${ws}: ${info.count}`)
                    .join(' · ')}
                </span>
              )}
            </div>
          </div>
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
          ) : filteredPeers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
              <Users className="h-12 w-12 mb-4 opacity-20" />
              <p className="text-lg font-medium">
                {searchQuery ? 'No matching peers' : 'No peers yet'}
              </p>
              <p className="text-sm mt-1 max-w-sm">
                {searchQuery
                  ? `No peers match "${searchQuery}". Try a different search term.`
                  : 'Create a peer to start tracking users, agents, and entities in your workspace.'}
              </p>
              {!searchQuery && (
                <Button className="mt-4" onClick={() => setShowCreateForm(true)}>
                  <Plus className="mr-2 h-4 w-4" /> Create First Peer
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {filteredPeers.map((peer) => (
                <div
                  key={peer.id}
                  className={`flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-accent/50 cursor-pointer ${
                    selectedPeerId === peer.id
                      ? 'border-primary/50 bg-accent/30'
                      : 'border-border'
                  }`}
                  onClick={() =>
                    setSelectedPeerId(selectedPeerId === peer.id ? null : peer.id)
                  }
                >
                  <div className="flex items-center gap-3 min-w-0 flex-1 mr-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted shrink-0">
                      {peerTypeIcon(peer.peerType)}
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium truncate max-w-[300px]">
                        {peer.name || peer.id.slice(0, 24) + '…'}
                      </p>
                      <p className="text-xs text-muted-foreground flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatMemoryTimestamp(peer.createdAt)}
                        <span className="mx-1">·</span>
                        {peer.workspaceId ? peer.workspaceId.slice(0, 16) + '…' : '—'}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant="outline" className={peerTypeColor(peer.peerType)}>
                      {peer.peerType || 'unknown'}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(peer.id, peer.name);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
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
