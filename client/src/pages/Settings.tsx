import { useState, useEffect, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable } from '@/lib/useReactiveDb';
import { callReducer, formatMemoryTimestamp } from '@/lib/spacetimedb';
import {
  Palette,
  Database,
  Sliders,
  Check,
  Users,
  Shield,
  Plus,
  Trash2,
  AlertCircle,
  X,
  RefreshCw,
} from 'lucide-react';

const SETTINGS_KEY = 'spacetime-memory-settings';

interface Settings {
  nodeName: string;
  apiEndpoint: string;
  refreshInterval: number;
}

function defaultSettings(): Settings {
  return {
    nodeName: 'spacetime-memory-node',
    apiEndpoint: 'http://localhost:3001',
    refreshInterval: 5,
  };
}

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return { ...defaultSettings(), ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return defaultSettings();
}

function saveSettings(s: Settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
}

// ── Space Permission types ───────────────────────────────────────

interface SpacePermissionRow {
  id: string;
  workspaceId: string;
  peerId: string;
  permission: string; // 'owner', 'editor', 'viewer'
  grantedBy: string;
  createdAt: number;
}

// ── Helpers ──────────────────────────────────────────────────────

const PERMISSION_ORDER: Record<string, number> = {
  owner: 3,
  editor: 2,
  viewer: 1,
};

const PERMISSION_COLORS: Record<string, string> = {
  owner: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  editor: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  viewer: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
};

function formatPeerId(id: string): string {
  if (!id) return '—';
  if (id.length <= 16) return id;
  return id.slice(0, 8) + '…' + id.slice(-6);
}

// ── Loading skeleton ─────────────────────────────────────────────

function MembersSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between rounded-lg border border-border p-3">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
          <Skeleton className="h-6 w-16 shrink-0" />
        </div>
      ))}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────

export default function Settings() {
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setSettings(loadSettings());
  }, []);

  const handleSave = () => {
    saveSettings(settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const update = (key: keyof Settings, value: string | number) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  // ── Space members state ─────────────────────────────────────

  const {
    data: permissions,
    loading: permLoading,
    error: permError,
  } = useTable<SpacePermissionRow>('space_permission');

  const [workspaceId, setWorkspaceId] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Add form state
  const [newPeerId, setNewPeerId] = useState('');
  const [newPermission, setNewPermission] = useState('viewer');

  // Filter members for the selected workspace
  const members = useMemo(() => {
    if (!workspaceId.trim()) return [];
    const ws = workspaceId.trim();
    return permissions
      .filter((p) => p.workspaceId === ws)
      .sort((a, b) => {
        // Sort by permission rank descending (owner first), then by createdAt
        const rankDiff = (PERMISSION_ORDER[b.permission] ?? 0) - (PERMISSION_ORDER[a.permission] ?? 0);
        if (rankDiff !== 0) return rankDiff;
        return (b.createdAt ?? 0) - (a.createdAt ?? 0);
      });
  }, [permissions, workspaceId]);

  // Reset add form
  const resetAddForm = () => {
    setNewPeerId('');
    setNewPermission('viewer');
    setShowAddForm(false);
    setActionError(null);
  };

  // Add member handler
  const handleAddMember = async () => {
    const pid = newPeerId.trim();
    if (!pid) {
      setActionError('Peer ID is required');
      return;
    }
    if (!['owner', 'editor', 'viewer'].includes(newPermission)) {
      setActionError('Permission must be owner, editor, or viewer');
      return;
    }
    if (!workspaceId.trim()) {
      setActionError('Workspace ID is required');
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      await callReducer('grant_space_access', [workspaceId.trim(), pid, newPermission]);
      resetAddForm();
    } catch (e: any) {
      setActionError(e.message || 'Failed to grant access');
    } finally {
      setSubmitting(false);
    }
  };

  // Remove member handler
  const handleRemoveMember = async (peerId: string, permission: string) => {
    if (
      !confirm(
        `Remove ${formatPeerId(peerId)} (${permission}) from this space?\n\nThis will revoke all access for this peer.`,
      )
    )
      return;
    setActionError(null);
    try {
      await callReducer('revoke_space_access', [workspaceId.trim(), peerId]);
    } catch (e: any) {
      setActionError(e.message || 'Failed to revoke access');
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Configure your spacetime memory node preferences.</p>
      </div>

      <Tabs defaultValue="general">
        <TabsList className="flex-wrap">
          <TabsTrigger value="general">
            <Sliders className="mr-2 h-4 w-4" />
            General
          </TabsTrigger>
          <TabsTrigger value="appearance">
            <Palette className="mr-2 h-4 w-4" />
            Appearance
          </TabsTrigger>
          <TabsTrigger value="storage">
            <Database className="mr-2 h-4 w-4" />
            Storage
          </TabsTrigger>
          <TabsTrigger value="space-members">
            <Users className="mr-2 h-4 w-4" />
            Space Members
          </TabsTrigger>
        </TabsList>

        {/* General */}
        <TabsContent value="general">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">General Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">SpacetimeDB Endpoint</label>
                <Input
                  placeholder="http://localhost:3001"
                  className="max-w-md font-mono text-sm"
                  value={settings.apiEndpoint}
                  onChange={(e) => update('apiEndpoint', e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  HTTP URL of the SpacetimeDB standalone server.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Polling Interval (seconds)</label>
                <Input
                  placeholder="5"
                  type="number"
                  min={1}
                  max={60}
                  className="max-w-[120px]"
                  value={settings.refreshInterval}
                  onChange={(e) => update('refreshInterval', Math.max(1, Math.min(60, parseInt(e.target.value) || 5)))}
                />
                <p className="text-xs text-muted-foreground">
                  How often the dashboard refreshes data from SpacetimeDB.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={handleSave}>
                  {saved ? (
                    <span className="flex items-center gap-1">
                      <Check className="h-4 w-4" /> Saved
                    </span>
                  ) : (
                    'Save Changes'
                  )}
                </Button>
                {saved && (
                  <span className="text-xs text-green-500 flex items-center gap-1">
                    <Check className="h-3 w-3" /> Settings saved locally
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Appearance */}
        <TabsContent value="appearance">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Appearance</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between rounded-lg border border-border p-4">
                <div>
                  <p className="font-medium">Dark Mode</p>
                  <p className="text-sm text-muted-foreground">Currently active (default)</p>
                </div>
                <Badge>Dark</Badge>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Storage */}
        <TabsContent value="storage">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Storage</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Storage is managed by SpacetimeDB. Check the SpacetimeDB data directory
                for database size and maintenance.
              </p>
              <div className="mt-4 rounded-lg border border-border p-3 bg-muted/30">
                <p className="text-xs font-mono text-muted-foreground">
                  ~/.local/share/spacetime/data/
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Space Members */}
        <TabsContent value="space-members">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Shield className="h-5 w-5 text-primary" />
                Space Members
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Workspace ID input */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Workspace ID</label>
                <Input
                  placeholder="Enter a workspace ID to manage its members..."
                  className="max-w-md font-mono text-sm"
                  value={workspaceId}
                  onChange={(e) => setWorkspaceId(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Enter the workspace ID whose members you want to view and manage.
                </p>
              </div>

              {/* Action error */}
              {actionError && (
                <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span className="flex-1">{actionError}</span>
                  <Button variant="ghost" size="sm" onClick={() => setActionError(null)}>
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              )}

              {/* Connection error */}
              {permError && (
                <div className="flex items-center gap-3 rounded-lg border border-red-500/30 p-3 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span className="flex-1">{permError}</span>
                  <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
                    <RefreshCw className="h-3 w-3 mr-1" /> Retry
                  </Button>
                </div>
              )}

              {/* Member content */}
              {!workspaceId.trim() ? (
                <div className="flex flex-col items-center justify-center py-8 text-center text-muted-foreground">
                  <Users className="h-10 w-10 mb-3 opacity-20" />
                  <p className="text-sm font-medium">Enter a workspace ID above</p>
                  <p className="text-xs mt-1">
                    Type a workspace ID to view and manage space members.
                  </p>
                </div>
              ) : permLoading ? (
                <MembersSkeleton />
              ) : members.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center text-muted-foreground">
                  <Shield className="h-10 w-10 mb-3 opacity-20" />
                  <p className="text-sm font-medium">No members yet</p>
                  <p className="text-xs mt-1 max-w-sm">
                    Add the first member to share this space.
                  </p>
                  <Button
                    className="mt-4"
                    size="sm"
                    onClick={() => setShowAddForm(true)}
                  >
                    <Plus className="mr-1.5 h-3.5 w-3.5" /> Add Member
                  </Button>
                </div>
              ) : (
                <>
                  {/* Members table */}
                  <div className="space-y-1.5">
                    {/* Header row */}
                    <div className="hidden md:flex items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      <div className="flex-1 min-w-0">Peer ID</div>
                      <div className="w-24 shrink-0 text-center">Permission</div>
                      <div className="w-28 shrink-0 text-center">Granted By</div>
                      <div className="w-24 shrink-0 text-right">Created</div>
                      <div className="w-16 shrink-0" />
                    </div>
                    {members.map((member) => (
                      <div
                        key={member.id}
                        className="flex flex-col md:flex-row items-start md:items-center gap-2 md:gap-0 rounded-lg border border-border p-3 transition-colors hover:bg-accent/30"
                      >
                        {/* Peer ID */}
                        <div className="flex-1 min-w-0">
                          <p className="font-mono text-xs md:text-sm font-medium break-all">
                            {member.peerId || '—'}
                          </p>
                        </div>

                        {/* Permission */}
                        <div className="md:w-24 shrink-0 md:text-center">
                          <Badge
                            variant="outline"
                            className={PERMISSION_COLORS[member.permission] ?? ''}
                          >
                            {member.permission
                              ? member.permission.charAt(0).toUpperCase() +
                                member.permission.slice(1)
                              : 'Unknown'}
                          </Badge>
                        </div>

                        {/* Granted By */}
                        <div className="md:w-28 shrink-0 md:text-center text-xs text-muted-foreground font-mono">
                          {member.grantedBy ? formatPeerId(member.grantedBy) : '—'}
                        </div>

                        {/* Created */}
                        <div className="md:w-24 shrink-0 md:text-right text-xs text-muted-foreground flex items-center gap-1 md:justify-end">
                          <span>{formatMemoryTimestamp(member.createdAt)}</span>
                        </div>

                        {/* Remove button */}
                        <div className="md:w-16 shrink-0 flex justify-end">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            onClick={() => handleRemoveMember(member.peerId, member.permission)}
                            title={`Remove ${formatPeerId(member.peerId)}`}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Add member button (when not showing form) */}
                  {!showAddForm && (
                    <div className="pt-2">
                      <Button size="sm" onClick={() => setShowAddForm(true)}>
                        <Plus className="mr-1.5 h-3.5 w-3.5" /> Add Member
                      </Button>
                    </div>
                  )}
                </>
              )}

              {/* Add member form */}
              {showAddForm && (
                <Card className="border-primary/50">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Plus className="h-4 w-4" />
                      Grant Access
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Peer ID *</label>
                      <Input
                        placeholder="e.g. 0xabc123... or full identity hash"
                        className="font-mono text-sm"
                        value={newPeerId}
                        onChange={(e) => setNewPeerId(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Permission</label>
                      <div className="flex gap-2">
                        {['viewer', 'editor', 'owner'].map((perm) => (
                          <Button
                            key={perm}
                            variant={newPermission === perm ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => setNewPermission(perm)}
                            className="flex items-center gap-1.5"
                          >
                            {perm === 'owner' && <Shield className="h-3.5 w-3.5" />}
                            {perm.charAt(0).toUpperCase() + perm.slice(1)}
                          </Button>
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        <strong>Viewer:</strong> read only &middot;{' '}
                        <strong>Editor:</strong> read &amp; write &middot;{' '}
                        <strong>Owner:</strong> full control
                      </p>
                    </div>
                    <div className="flex items-center gap-2 pt-2">
                      <Button
                        onClick={handleAddMember}
                        disabled={submitting || !newPeerId.trim()}
                      >
                        {submitting ? 'Granting...' : 'Grant Access'}
                      </Button>
                      <Button variant="outline" onClick={resetAddForm}>
                        Cancel
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
