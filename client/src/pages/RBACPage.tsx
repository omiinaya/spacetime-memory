import { useState, useEffect, useMemo, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useTable } from '@/lib/useReactiveDb';
import { callReducer, executeSql, parseSqlResponse, formatMemoryTimestamp } from '@/lib/spacetimedb';
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  Users,
  UserPlus,
  UserMinus,
  UserCog,
  Plus,
  Trash2,
  Pencil,
  Check,
  X,
  AlertCircle,
  RefreshCw,
  Search,
  Copy,
  Settings2,
  Crown,
  Eye,
  Edit,
  Star,
  Download,
  Upload,
  CheckSquare,
  Square,
} from 'lucide-react';

// ─────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────

interface SpacePermissionRow {
  id: string;
  workspaceId: string;
  peerId: string;
  permission: string; // 'owner', 'editor', 'viewer'
  grantedBy: string;
  createdAt: number;
}

interface PeerRow {
  id: string;
  workspaceId: string;
  name: string;
  peerType: string;
  metadata: string;
  createdAt: number;
  updatedAt: number;
}

interface AdminRow {
  peerId: string;
  promotedAt?: number;
  promotedBy?: string;
}

interface CustomRole {
  id: string;
  name: string;
  description: string;
  permissions: string[];
  color: string;
  createdAt: number;
}

interface BulkEntry {
  peerId: string;
  permission: string;
  selected: boolean;
}

// ─────────────────────────────────────────────────
// Permission constants
// ─────────────────────────────────────────────────

const PERMISSION_ORDER: Record<string, number> = {
  owner: 3,
  admin: 3,
  editor: 2,
  viewer: 1,
};

const PERMISSION_COLORS: Record<string, string> = {
  owner: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  admin: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
  editor: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  viewer: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
};

const PERMISSION_ICONS: Record<string, React.ReactNode> = {
  owner: <Crown className="h-3.5 w-3.5" />,
  admin: <Shield className="h-3.5 w-3.5" />,
  editor: <Edit className="h-3.5 w-3.5" />,
  viewer: <Eye className="h-3.5 w-3.5" />,
};

const PERMISSION_LABELS: Record<string, string> = {
  owner: 'Owner',
  admin: 'Admin',
  editor: 'Editor',
  viewer: 'Viewer',
};

const AVAILABLE_PERMISSIONS = ['viewer', 'editor', 'owner'] as const;

// ─────────────────────────────────────────────────
// Permission breakdown matrix
// ─────────────────────────────────────────────────

interface PermissionEntry {
  action: string;
  description: string;
  viewer: boolean;
  editor: boolean;
  owner: boolean;
  admin: boolean;
}

const PERMISSION_BREAKDOWN: PermissionEntry[] = [
  {
    action: 'View memories',
    description: 'Read and browse stored memories and documents',
    viewer: true,
    editor: true,
    owner: true,
    admin: true,
  },
  {
    action: 'Search workspace',
    description: 'Perform semantic and keyword searches',
    viewer: true,
    editor: true,
    owner: true,
    admin: true,
  },
  {
    action: 'Create memories',
    description: 'Add new memories and documents',
    viewer: false,
    editor: true,
    owner: true,
    admin: true,
  },
  {
    action: 'Edit content',
    description: 'Modify existing memories and documents',
    viewer: false,
    editor: true,
    owner: true,
    admin: true,
  },
  {
    action: 'Delete content',
    description: 'Remove memories and documents permanently',
    viewer: false,
    editor: false,
    owner: true,
    admin: true,
  },
  {
    action: 'Invite members',
    description: 'Add new members to the workspace',
    viewer: false,
    editor: false,
    owner: true,
    admin: true,
  },
  {
    action: 'Remove members',
    description: 'Revoke access for existing members',
    viewer: false,
    editor: false,
    owner: true,
    admin: true,
  },
  {
    action: 'Change roles',
    description: 'Change permission level of other members',
    viewer: false,
    editor: false,
    owner: true,
    admin: true,
  },
  {
    action: 'Manage roles',
    description: 'Create, edit, and delete custom roles',
    viewer: false,
    editor: false,
    owner: true,
    admin: true,
  },
  {
    action: 'Export data',
    description: 'Export workspace data and backups',
    viewer: false,
    editor: true,
    owner: true,
    admin: true,
  },
  {
    action: 'View analytics',
    description: 'Access workspace analytics and dashboards',
    viewer: true,
    editor: true,
    owner: true,
    admin: true,
  },
  {
    action: 'Configure integrations',
    description: 'Set up webhooks, API keys, and external connections',
    viewer: false,
    editor: false,
    owner: true,
    admin: true,
  },
  {
    action: 'Delete workspace',
    description: 'Permanently delete the entire workspace',
    viewer: false,
    editor: false,
    owner: true,
    admin: false,
  },
];

// ─────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────

const CUSTOM_ROLES_KEY = 'spacetime-memory-custom-roles';

function formatPeerId(id: string): string {
  if (!id) return '—';
  if (id.length <= 16) return id;
  return id.slice(0, 8) + '…' + id.slice(-6);
}

function loadCustomRoles(): CustomRole[] {
  try {
    const raw = localStorage.getItem(CUSTOM_ROLES_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return [];
}

function saveCustomRoles(roles: CustomRole[]) {
  localStorage.setItem(CUSTOM_ROLES_KEY, JSON.stringify(roles));
}

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

const CUSTOM_ROLE_COLORS = [
  'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300',
  'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',
  'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300',
  'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
  'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300',
];

const CUSTOM_ROLE_PERMISSIONS = [
  { id: 'read', label: 'Read', description: 'View memories and documents' },
  { id: 'write', label: 'Write', description: 'Create and edit memories' },
  { id: 'delete', label: 'Delete', description: 'Remove memories and documents' },
  { id: 'invite', label: 'Invite', description: 'Add new members to workspace' },
  { id: 'manage_members', label: 'Manage Members', description: 'Remove members and change roles' },
  { id: 'export', label: 'Export', description: 'Export workspace data' },
  { id: 'configure', label: 'Configure', description: 'Manage integrations and settings' },
  { id: 'manage_roles', label: 'Manage Roles', description: 'Create and edit custom roles' },
];

// ─────────────────────────────────────────────────
// Loading skeleton
// ─────────────────────────────────────────────────

function MembersSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center justify-between rounded-lg border border-border p-3"
        >
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <Skeleton className="h-8 w-8 rounded-full" />
            <div className="space-y-1.5 flex-1">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-24" />
            </div>
          </div>
          <Skeleton className="h-6 w-20 rounded-full shrink-0" />
          <Skeleton className="h-8 w-8 shrink-0 ml-2" />
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────

function RoleBadge({ role }: { role: string }) {
  const color = PERMISSION_COLORS[role] ?? 'bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-300';
  const icon = PERMISSION_ICONS[role] ?? null;
  const label = PERMISSION_LABELS[role] ?? role;
  return (
    <Badge variant="outline" className={`inline-flex items-center gap-1 ${color}`}>
      {icon}
      {label}
    </Badge>
  );
}

function PermissionCheck({ allowed }: { allowed: boolean }) {
  return allowed ? (
    <Check className="h-4 w-4 text-green-500" />
  ) : (
    <X className="h-4 w-4 text-muted-foreground/40" />
  );
}

function ErrorBanner({
  message,
  onDismiss,
  onRetry,
}: {
  message: string;
  onDismiss?: () => void;
  onRetry?: () => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive">
      <AlertCircle className="h-4 w-4 shrink-0" />
      <span className="flex-1">{message}</span>
      <div className="flex items-center gap-1">
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="h-3 w-3 mr-1" /> Retry
          </Button>
        )}
        {onDismiss && (
          <Button variant="ghost" size="sm" onClick={onDismiss}>
            <X className="h-3 w-3" />
          </Button>
        )}
      </div>
    </div>
  );
}

function InfoBox({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center text-muted-foreground">
      <Icon className="h-10 w-10 mb-3 opacity-20" />
      <p className="text-sm font-medium">{title}</p>
      <p className="text-xs mt-1 max-w-sm">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ─────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────

export default function RBACPage() {
  // ── Data ─────────────────────────────────────
  const {
    data: permissions,
    loading: permLoading,
    error: permError,
  } = useTable<SpacePermissionRow>('space_permission');

  const {
    data: peers,
  } = useTable<PeerRow>('peer');

  // ── Admin state ──────────────────────────────
  const [admins, setAdmins] = useState<AdminRow[]>([]);

  const fetchAdmins = useCallback(async () => {
    try {
      await callReducer('list_admins', []);
      // list_admins may write results to a temp table; attempt SQL read
      try {
        const result = await executeSql('SELECT * FROM admin_list');
        const rows = parseSqlResponse<AdminRow>(result);
        setAdmins(rows);
      } catch {
        // If temp table doesn't exist, fall back to empty
        setAdmins([]);
      }
    } catch (e: any) {
      // Admin list unavailable; not a critical error
      setAdmins([]);
    }
  }, []);

  useEffect(() => {
    fetchAdmins();
  }, [fetchAdmins]);

  // ── Workspace & members ─────────────────────
  const [workspaceId, setWorkspaceId] = useState('');

  const members = useMemo(() => {
    if (!workspaceId.trim()) return [];
    const ws = workspaceId.trim();
    return permissions
      .filter((p) => p.workspaceId === ws)
      .sort((a, b) => {
        const rankDiff =
          (PERMISSION_ORDER[b.permission] ?? 0) -
          (PERMISSION_ORDER[a.permission] ?? 0);
        if (rankDiff !== 0) return rankDiff;
        return (b.createdAt ?? 0) - (a.createdAt ?? 0);
      });
  }, [permissions, workspaceId]);

  const workspaceAdmins = useMemo(
    () =>
      admins.filter((a) =>
        members.some((m) => m.peerId === a.peerId),
      ),
    [admins, members],
  );

  // Build a peerId → name map for display
  const peerNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of peers) {
      if (p.name) map.set(p.id, p.name);
      if (p.workspaceId && p.name) map.set(`${p.workspaceId}:${p.id}`, p.name);
    }
    return map;
  }, [peers]);

  function getPeerDisplay(peerId: string): string {
    return peerNameMap.get(peerId) || formatPeerId(peerId);
  }

  // ── Action state ────────────────────────────
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const showFeedback = (msg: string, isError = false) => {
    if (isError) {
      setActionError(msg);
      setActionSuccess(null);
    } else {
      setActionSuccess(msg);
      setActionError(null);
      setTimeout(() => setActionSuccess(null), 3000);
    }
  };

  const clearFeedback = () => {
    setActionError(null);
    setActionSuccess(null);
  };

  // ── Add member form ─────────────────────────
  const [showAddForm, setShowAddForm] = useState(false);
  const [newPeerId, setNewPeerId] = useState('');
  const [newPermission, setNewPermission] = useState<string>('viewer');

  const resetAddForm = () => {
    setNewPeerId('');
    setNewPermission('viewer');
    setShowAddForm(false);
    clearFeedback();
  };

  const handleAddMember = async () => {
    const pid = newPeerId.trim();
    if (!pid) {
      setActionError('Peer ID is required');
      return;
    }
    if (!AVAILABLE_PERMISSIONS.includes(newPermission as any)) {
      setActionError('Permission must be viewer, editor, or owner');
      return;
    }
    if (!workspaceId.trim()) {
      setActionError('Workspace ID is required');
      return;
    }
    setSubmitting(true);
    clearFeedback();
    try {
      await callReducer('grant_space_access', [
        workspaceId.trim(),
        pid,
        newPermission,
      ]);
      showFeedback(`Granted ${newPermission} access to ${getPeerDisplay(pid)}`);
      resetAddForm();
    } catch (e: any) {
      setActionError(e.message || 'Failed to grant access');
    } finally {
      setSubmitting(false);
    }
  };

  // ── Remove member ───────────────────────────
  const handleRemoveMember = async (peerId: string, permission: string) => {
    const display = getPeerDisplay(peerId);
    if (
      !confirm(
        `Remove ${display} (${permission}) from this workspace?\n\nThis will revoke all access for this peer.`,
      )
    )
      return;
    clearFeedback();
    try {
      await callReducer('revoke_space_access', [workspaceId.trim(), peerId]);
      showFeedback(`Revoked access for ${display}`);
    } catch (e: any) {
      setActionError(e.message || 'Failed to revoke access');
    }
  };

  // ── Change role ─────────────────────────────
  const handleChangeRole = async (peerId: string, newRole: string) => {
    if (!AVAILABLE_PERMISSIONS.includes(newRole as any)) return;
    clearFeedback();
    setSubmitting(true);
    try {
      // Revoke then re-grant (atomic-like)
      await callReducer('revoke_space_access', [workspaceId.trim(), peerId]);
      await callReducer('grant_space_access', [
        workspaceId.trim(),
        peerId,
        newRole,
      ]);
      showFeedback(`Changed ${getPeerDisplay(peerId)} to ${newRole}`);
    } catch (e: any) {
      setActionError(e.message || 'Failed to change role');
    } finally {
      setSubmitting(false);
    }
  };

  // ── Promote/demote admin ────────────────────
  const handlePromoteAdmin = async (peerId: string) => {
    clearFeedback();
    try {
      await callReducer('promote_admin', [peerId]);
      showFeedback(`Promoted ${getPeerDisplay(peerId)} to admin`);
      fetchAdmins();
    } catch (e: any) {
      setActionError(e.message || 'Failed to promote admin');
    }
  };

  const handleDemoteAdmin = async (peerId: string) => {
    clearFeedback();
    try {
      await callReducer('demote_admin', [peerId]);
      showFeedback(`Demoted ${getPeerDisplay(peerId)} from admin`);
      fetchAdmins();
    } catch (e: any) {
      setActionError(e.message || 'Failed to demote admin');
    }
  };

  // ── Custom roles state ──────────────────────
  const [customRoles, setCustomRoles] = useState<CustomRole[]>(() =>
    loadCustomRoles(),
  );
  const [showRoleForm, setShowRoleForm] = useState(false);
  const [editingRoleId, setEditingRoleId] = useState<string | null>(null);
  const [roleFormName, setRoleFormName] = useState('');
  const [roleFormDescription, setRoleFormDescription] = useState('');
  const [roleFormPermissions, setRoleFormPermissions] = useState<string[]>([]);
  const [roleFormColor, setRoleFormColor] = useState(CUSTOM_ROLE_COLORS[0]);

  const resetRoleForm = () => {
    setRoleFormName('');
    setRoleFormDescription('');
    setRoleFormPermissions([]);
    setRoleFormColor(CUSTOM_ROLE_COLORS[0]);
    setEditingRoleId(null);
    setShowRoleForm(false);
    clearFeedback();
  };

  const openEditRole = (role: CustomRole) => {
    setRoleFormName(role.name);
    setRoleFormDescription(role.description);
    setRoleFormPermissions([...role.permissions]);
    setRoleFormColor(role.color);
    setEditingRoleId(role.id);
    setShowRoleForm(true);
    clearFeedback();
  };

  const handleSaveRole = () => {
    const name = roleFormName.trim();
    if (!name) {
      setActionError('Role name is required');
      return;
    }
    if (roleFormPermissions.length === 0) {
      setActionError('Select at least one permission');
      return;
    }

    const updated: CustomRole[] = [...customRoles];
    if (editingRoleId) {
      const idx = updated.findIndex((r) => r.id === editingRoleId);
      if (idx >= 0) {
        updated[idx] = {
          ...updated[idx],
          name,
          description: roleFormDescription.trim(),
          permissions: roleFormPermissions,
          color: roleFormColor,
        };
      }
      showFeedback(`Role "${name}" updated`);
    } else {
      const newRole: CustomRole = {
        id: generateId(),
        name,
        description: roleFormDescription.trim(),
        permissions: roleFormPermissions,
        color: roleFormColor,
        createdAt: Date.now(),
      };
      updated.push(newRole);
      showFeedback(`Role "${name}" created`);
    }

    setCustomRoles(updated);
    saveCustomRoles(updated);
    resetRoleForm();
  };

  const handleDeleteRole = (roleId: string, roleName: string) => {
    if (!confirm(`Delete custom role "${roleName}"? This cannot be undone.`))
      return;
    const updated = customRoles.filter((r) => r.id !== roleId);
    setCustomRoles(updated);
    saveCustomRoles(updated);
    showFeedback(`Role "${roleName}" deleted`);
  };

  const toggleRolePermission = (permId: string) => {
    setRoleFormPermissions((prev) =>
      prev.includes(permId)
        ? prev.filter((p) => p !== permId)
        : [...prev, permId],
    );
  };

  // ── Bulk operations state ───────────────────
  const [showBulkForm, setShowBulkForm] = useState(false);
  const [bulkInput, setBulkInput] = useState('');
  const [bulkPermission, setBulkPermission] = useState('viewer');
  const [bulkEntries, setBulkEntries] = useState<BulkEntry[]>([]);
  const [bulkSelectAll, setBulkSelectAll] = useState(false);

  const handleBulkParse = () => {
    const lines = bulkInput
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean);
    const entries: BulkEntry[] = lines.map((line) => {
      // Support format: "peerId" or "peerId,role"
      const parts = line.split(/[,;\t]+/);
      const pid = parts[0].trim();
      const perm = parts[1]?.trim().toLowerCase() || bulkPermission;
      return {
        peerId: pid,
        permission: ['viewer', 'editor', 'owner'].includes(perm) ? perm : bulkPermission,
        selected: true,
      };
    });
    setBulkEntries(entries);
    setBulkSelectAll(true);
  };

  const toggleBulkSelect = (idx: number) => {
    setBulkEntries((prev) =>
      prev.map((e, i) => (i === idx ? { ...e, selected: !e.selected } : e)),
    );
  };

  const toggleBulkSelectAll = () => {
    const next = !bulkSelectAll;
    setBulkSelectAll(next);
    setBulkEntries((prev) => prev.map((e) => ({ ...e, selected: next })));
  };

  const handleBulkApply = async () => {
    const selected = bulkEntries.filter((e) => e.selected);
    if (selected.length === 0) {
      setActionError('No entries selected');
      return;
    }
    if (!workspaceId.trim()) {
      setActionError('Workspace ID is required');
      return;
    }
    setSubmitting(true);
    clearFeedback();
    let success = 0;
    let fail = 0;
    for (const entry of selected) {
      try {
        await callReducer('grant_space_access', [
          workspaceId.trim(),
          entry.peerId,
          entry.permission,
        ]);
        success++;
      } catch {
        fail++;
      }
    }
    setSubmitting(false);
    showFeedback(
      `Bulk operation complete: ${success} succeeded, ${fail} failed`,
      fail > 0 && success === 0,
    );
    if (fail === 0) {
      setBulkEntries([]);
      setBulkInput('');
      setShowBulkForm(false);
    }
  };

  const handleBulkExport = () => {
    if (members.length === 0) {
      setActionError('No members to export');
      return;
    }
    const csv = ['peerId,permission']
      .concat(members.map((m) => `${m.peerId},${m.permission}`))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `rbac-${workspaceId.trim()}-members.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showFeedback(`Exported ${members.length} members to CSV`);
  };

  // ── Active tab ──────────────────────────────
  const [activeTab, setActiveTab] = useState('members');

  // ── Render ──────────────────────────────────
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
          <ShieldCheck className="h-7 w-7 text-primary" />
          Role-Based Access Control
        </h1>
        <p className="text-muted-foreground">
          Manage workspace members, roles, and permissions for your SpacetimeDB
          nodes.
        </p>
      </div>

      {/* Global feedback banner */}
      {actionError && (
        <ErrorBanner
          message={actionError}
          onDismiss={() => setActionError(null)}
        />
      )}
      {actionSuccess && (
        <div className="flex items-center gap-3 rounded-lg border border-green-500/50 bg-green-500/5 p-3 text-sm text-green-600 dark:text-green-400">
          <Check className="h-4 w-4 shrink-0" />
          <span className="flex-1">{actionSuccess}</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setActionSuccess(null)}
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="members">
            <Users className="mr-2 h-4 w-4" />
            Members
          </TabsTrigger>
          <TabsTrigger value="permissions">
            <Shield className="mr-2 h-4 w-4" />
            Permissions
          </TabsTrigger>
          <TabsTrigger value="custom-roles">
            <UserCog className="mr-2 h-4 w-4" />
            Custom Roles
          </TabsTrigger>
          <TabsTrigger value="bulk">
            <Settings2 className="mr-2 h-4 w-4" />
            Bulk Operations
          </TabsTrigger>
        </TabsList>

        {/* ═══════════════════════════════════════
            MEMBERS TAB
            ═══════════════════════════════════════ */}
        <TabsContent value="members" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Users className="h-5 w-5 text-primary" />
                Workspace Members
              </CardTitle>
              <CardDescription>
                View and manage access for workspace members.
              </CardDescription>
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
                  Enter the workspace ID whose members you want to view and
                  manage.
                </p>
              </div>

              {/* Connection error */}
              {permError && (
                <ErrorBanner
                  message={permError}
                  onRetry={() => window.location.reload()}
                />
              )}

              {/* Member content */}
              {!workspaceId.trim() ? (
                <InfoBox
                  icon={Users}
                  title="Enter a workspace ID above"
                  description="Type a workspace ID to view and manage space members."
                />
              ) : permLoading ? (
                <MembersSkeleton />
              ) : members.length === 0 ? (
                <InfoBox
                  icon={Shield}
                  title="No members yet"
                  description="Add the first member to share this workspace."
                  action={
                    <Button size="sm" onClick={() => setShowAddForm(true)}>
                      <UserPlus className="mr-1.5 h-3.5 w-3.5" /> Add Member
                    </Button>
                  }
                />
              ) : (
                <>
                  {/* Members table */}
                  <div className="space-y-1.5">
                    {/* Header row */}
                    <div className="hidden lg:flex items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      <div className="flex-1 min-w-0">Peer</div>
                      <div className="w-28 shrink-0 text-center">Role</div>
                      <div className="w-28 shrink-0 text-center">Admin</div>
                      <div className="w-24 shrink-0 text-center">Granted By</div>
                      <div className="w-20 shrink-0 text-right">Created</div>
                      <div className="w-44 shrink-0 text-right">Actions</div>
                    </div>
                    {members.map((member) => {
                      const isAdmin = workspaceAdmins.some(
                        (a) => a.peerId === member.peerId,
                      );
                      return (
                        <div
                          key={member.id}
                          className="flex flex-col lg:flex-row items-start lg:items-center gap-2 lg:gap-0 rounded-lg border border-border p-3 transition-colors hover:bg-accent/30"
                        >
                          {/* Peer */}
                          <div className="flex-1 min-w-0">
                            <p className="font-mono text-xs md:text-sm font-medium break-all">
                              {member.peerId || '—'}
                            </p>
                            {peerNameMap.has(member.peerId) && (
                              <p className="text-xs text-muted-foreground mt-0.5">
                                {peerNameMap.get(member.peerId)}
                              </p>
                            )}
                          </div>

                          {/* Role */}
                          <div className="lg:w-28 shrink-0 lg:text-center">
                            <RoleBadge role={member.permission} />
                          </div>

                          {/* Admin badge */}
                          <div className="lg:w-28 shrink-0 lg:text-center">
                            {isAdmin ? (
                              <Badge
                                variant="outline"
                                className="bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300"
                              >
                                <Shield className="h-3 w-3 mr-1" />
                                Admin
                              </Badge>
                            ) : (
                              <span className="text-xs text-muted-foreground">
                                —
                              </span>
                            )}
                          </div>

                          {/* Granted by */}
                          <div className="lg:w-24 shrink-0 lg:text-center text-xs text-muted-foreground font-mono">
                            {member.grantedBy
                              ? formatPeerId(member.grantedBy)
                              : '—'}
                          </div>

                          {/* Created */}
                          <div className="lg:w-20 shrink-0 lg:text-right text-xs text-muted-foreground">
                            {formatMemoryTimestamp(member.createdAt)}
                          </div>

                          {/* Actions */}
                          <div className="lg:w-44 shrink-0 flex items-center justify-end gap-1">
                            {/* Role change dropdown (inline buttons) */}
                            <div className="flex items-center gap-0.5">
                              {AVAILABLE_PERMISSIONS.map((role) => (
                                <button
                                  key={role}
                                  disabled={
                                    submitting || role === member.permission
                                  }
                                  onClick={() =>
                                    handleChangeRole(member.peerId, role)
                                  }
                                  className={`inline-flex items-center gap-1 rounded px-1.5 py-1 text-[10px] font-medium uppercase tracking-wider transition-colors
                                    ${
                                      role === member.permission
                                        ? 'bg-primary/10 text-primary cursor-default'
                                        : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                                    }
                                    disabled:opacity-40 disabled:cursor-not-allowed`}
                                  title={`Change to ${role}`}
                                >
                                  {role === 'owner' && (
                                    <Crown className="h-3 w-3" />
                                  )}
                                  {role === 'editor' && (
                                    <Edit className="h-3 w-3" />
                                  )}
                                  {role === 'viewer' && (
                                    <Eye className="h-3 w-3" />
                                  )}
                                </button>
                              ))}
                            </div>

                            {/* Promote/demote admin */}
                            {isAdmin ? (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-amber-500"
                                onClick={() =>
                                  handleDemoteAdmin(member.peerId)
                                }
                                title="Demote from admin"
                              >
                                <Star className="h-3.5 w-3.5" />
                              </Button>
                            ) : (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-purple-500"
                                onClick={() =>
                                  handlePromoteAdmin(member.peerId)
                                }
                                title="Promote to admin"
                              >
                                <Shield className="h-3.5 w-3.5" />
                              </Button>
                            )}

                            {/* Remove */}
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground hover:text-destructive"
                              onClick={() =>
                                handleRemoveMember(
                                  member.peerId,
                                  member.permission,
                                )
                              }
                              title={`Remove ${getPeerDisplay(member.peerId)}`}
                            >
                              <UserMinus className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Add member button */}
                  {!showAddForm && (
                    <div className="flex items-center gap-2 pt-2">
                      <Button size="sm" onClick={() => setShowAddForm(true)}>
                        <UserPlus className="mr-1.5 h-3.5 w-3.5" /> Add Member
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleBulkExport}
                      >
                        <Download className="mr-1.5 h-3.5 w-3.5" /> Export CSV
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
                      <UserPlus className="h-4 w-4" />
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
                      <label className="text-sm font-medium">Role</label>
                      <div className="flex flex-wrap gap-2">
                        {AVAILABLE_PERMISSIONS.map((perm) => (
                          <Button
                            key={perm}
                            variant={
                              newPermission === perm ? 'default' : 'outline'
                            }
                            size="sm"
                            onClick={() => setNewPermission(perm)}
                            className="flex items-center gap-1.5"
                          >
                            {PERMISSION_ICONS[perm]}
                            {PERMISSION_LABELS[perm]}
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

        {/* ═══════════════════════════════════════
            PERMISSIONS TAB
            ═══════════════════════════════════════ */}
        <TabsContent value="permissions" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Shield className="h-5 w-5 text-primary" />
                Role Permissions Breakdown
              </CardTitle>
              <CardDescription>
                What each role can do in a workspace. Admins have system-wide
                privileges.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2.5 px-3 font-medium text-muted-foreground text-xs uppercase tracking-wider">
                        Action
                      </th>
                      <th className="text-left py-2.5 px-3 font-medium text-muted-foreground text-xs uppercase tracking-wider hidden md:table-cell">
                        Description
                      </th>
                      <th className="text-center py-2.5 px-3 font-medium text-muted-foreground text-xs uppercase tracking-wider">
                        <span className="inline-flex items-center gap-1">
                          <Eye className="h-3 w-3" /> Viewer
                        </span>
                      </th>
                      <th className="text-center py-2.5 px-3 font-medium text-muted-foreground text-xs uppercase tracking-wider">
                        <span className="inline-flex items-center gap-1">
                          <Edit className="h-3 w-3" /> Editor
                        </span>
                      </th>
                      <th className="text-center py-2.5 px-3 font-medium text-muted-foreground text-xs uppercase tracking-wider">
                        <span className="inline-flex items-center gap-1">
                          <Crown className="h-3 w-3" /> Owner
                        </span>
                      </th>
                      <th className="text-center py-2.5 px-3 font-medium text-muted-foreground text-xs uppercase tracking-wider">
                        <span className="inline-flex items-center gap-1">
                          <Shield className="h-3 w-3" /> Admin
                        </span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {PERMISSION_BREAKDOWN.map((entry, idx) => (
                      <tr
                        key={idx}
                        className="border-b border-border/50 transition-colors hover:bg-accent/20"
                      >
                        <td className="py-2.5 px-3 font-medium">
                          {entry.action}
                        </td>
                        <td className="py-2.5 px-3 text-muted-foreground text-xs hidden md:table-cell">
                          {entry.description}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <PermissionCheck allowed={entry.viewer} />
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <PermissionCheck allowed={entry.editor} />
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <PermissionCheck allowed={entry.owner} />
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <PermissionCheck allowed={entry.admin} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 rounded-lg bg-muted/30 p-3 text-xs text-muted-foreground">
                <p className="flex items-center gap-1.5">
                  <ShieldAlert className="h-3.5 w-3.5 text-amber-500" />
                  <strong>Note:</strong> Admin is a system-wide role managed
                  separately via{' '}
                  <code className="px-1 py-0.5 rounded bg-muted font-mono">
                    promote_admin
                  </code>{' '}
                  /{' '}
                  <code className="px-1 py-0.5 rounded bg-muted font-mono">
                    demote_admin
                  </code>{' '}
                  reducers. Owners have full workspace control but are not
                  necessarily system admins.
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ═══════════════════════════════════════
            CUSTOM ROLES TAB
            ═══════════════════════════════════════ */}
        <TabsContent value="custom-roles" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <UserCog className="h-5 w-5 text-primary" />
                    Custom Roles
                  </CardTitle>
                  <CardDescription>
                    Create and manage custom roles with granular permissions.
                    Custom roles are stored locally.
                  </CardDescription>
                </div>
                {!showRoleForm && (
                  <Button
                    size="sm"
                    onClick={() => {
                      resetRoleForm();
                      setShowRoleForm(true);
                    }}
                  >
                    <Plus className="mr-1.5 h-3.5 w-3.5" /> Create Role
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {customRoles.length === 0 && !showRoleForm ? (
                <InfoBox
                  icon={UserCog}
                  title="No custom roles yet"
                  description="Create custom roles to define granular permission sets beyond the built-in viewer, editor, and owner roles."
                  action={
                    <Button
                      size="sm"
                      onClick={() => {
                        resetRoleForm();
                        setShowRoleForm(true);
                      }}
                    >
                      <Plus className="mr-1.5 h-3.5 w-3.5" /> Create Role
                    </Button>
                  }
                />
              ) : (
                <div className="space-y-2">
                  {customRoles.map((role) => (
                    <div
                      key={role.id}
                      className="flex items-start justify-between rounded-lg border border-border p-3 transition-colors hover:bg-accent/20"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <Badge
                            variant="outline"
                            className={role.color}
                          >
                            {role.name}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {role.permissions.length} permission
                            {role.permissions.length !== 1 ? 's' : ''}
                          </span>
                        </div>
                        {role.description && (
                          <p className="text-xs text-muted-foreground mt-1">
                            {role.description}
                          </p>
                        )}
                        <div className="flex flex-wrap gap-1 mt-2">
                          {CUSTOM_ROLE_PERMISSIONS.filter((p) =>
                            role.permissions.includes(p.id),
                          ).map((p) => (
                            <Badge
                              key={p.id}
                              variant="secondary"
                              className="text-[10px]"
                            >
                              {p.label}
                            </Badge>
                          ))}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0 ml-3">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-foreground"
                          onClick={() => openEditRole(role)}
                          title={`Edit ${role.name}`}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive"
                          onClick={() => handleDeleteRole(role.id, role.name)}
                          title={`Delete ${role.name}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Role create/edit form */}
              {showRoleForm && (
                <Card className="border-primary/50">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      {editingRoleId ? (
                        <>
                          <Pencil className="h-4 w-4" />
                          Edit Role
                        </>
                      ) : (
                        <>
                          <Plus className="h-4 w-4" />
                          Create Custom Role
                        </>
                      )}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <label className="text-sm font-medium">
                        Role Name *
                      </label>
                      <Input
                        placeholder="e.g. Auditor, Contributor, Moderator"
                        className="max-w-sm"
                        value={roleFormName}
                        onChange={(e) => setRoleFormName(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">
                        Description
                      </label>
                      <Input
                        placeholder="Brief description of this role's purpose"
                        className="max-w-md"
                        value={roleFormDescription}
                        onChange={(e) => setRoleFormDescription(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">
                        Permissions
                      </label>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {CUSTOM_ROLE_PERMISSIONS.map((perm) => (
                          <button
                            key={perm.id}
                            onClick={() => toggleRolePermission(perm.id)}
                            className={`flex items-start gap-3 rounded-lg border p-3 text-left transition-colors ${
                              roleFormPermissions.includes(perm.id)
                                ? 'border-primary/50 bg-primary/5'
                                : 'border-border hover:bg-accent/20'
                            }`}
                          >
                            <div className="mt-0.5">
                              {roleFormPermissions.includes(perm.id) ? (
                                <CheckSquare className="h-4 w-4 text-primary" />
                              ) : (
                                <Square className="h-4 w-4 text-muted-foreground" />
                              )}
                            </div>
                            <div>
                              <p className="text-sm font-medium">
                                {perm.label}
                              </p>
                              <p className="text-xs text-muted-foreground">
                                {perm.description}
                              </p>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Color</label>
                      <div className="flex flex-wrap gap-2">
                        {CUSTOM_ROLE_COLORS.map((color) => (
                          <button
                            key={color}
                            onClick={() => setRoleFormColor(color)}
                            className={`h-8 w-8 rounded-full border-2 transition-all ${
                              roleFormColor === color
                                ? 'border-primary scale-110'
                                : 'border-transparent hover:scale-105'
                            }`}
                            style={{
                              background: color.includes('indigo')
                                ? '#6366f1'
                                : color.includes('rose')
                                  ? '#f43f5e'
                                  : color.includes('cyan')
                                    ? '#06b6d4'
                                    : color.includes('orange')
                                      ? '#f97316'
                                      : '#14b8a6',
                            }}
                          />
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 pt-2">
                      <Button
                        onClick={handleSaveRole}
                        disabled={
                          !roleFormName.trim() ||
                          roleFormPermissions.length === 0
                        }
                      >
                        {editingRoleId ? 'Update Role' : 'Create Role'}
                      </Button>
                      <Button variant="outline" onClick={resetRoleForm}>
                        Cancel
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ═══════════════════════════════════════
            BULK OPERATIONS TAB
            ═══════════════════════════════════════ */}
        <TabsContent value="bulk" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Settings2 className="h-5 w-5 text-primary" />
                Bulk Operations
              </CardTitle>
              <CardDescription>
                Manage multiple members at once. Enter one peer ID per line,
                optionally with a role (peerId,role).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Workspace ID input */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Workspace ID</label>
                <Input
                  placeholder="Enter workspace ID for bulk operations..."
                  className="max-w-md font-mono text-sm"
                  value={workspaceId}
                  onChange={(e) => setWorkspaceId(e.target.value)}
                />
              </div>

              {!workspaceId.trim() ? (
                <InfoBox
                  icon={Settings2}
                  title="Enter a workspace ID"
                  description="Provide a workspace ID to perform bulk role assignments."
                />
              ) : (
                <>
                  {/* Default role selector */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">
                      Default Role
                    </label>
                    <div className="flex flex-wrap gap-2">
                      {AVAILABLE_PERMISSIONS.map((perm) => (
                        <Button
                          key={perm}
                          variant={
                            bulkPermission === perm ? 'default' : 'outline'
                          }
                          size="sm"
                          onClick={() => setBulkPermission(perm)}
                          className="flex items-center gap-1.5"
                        >
                          {PERMISSION_ICONS[perm]}
                          {PERMISSION_LABELS[perm]}
                        </Button>
                      ))}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Used when a line doesn't specify a role. Lines with
                      format <code className="text-[10px]">peerId,editor</code>{' '}
                      override this.
                    </p>
                  </div>

                  {/* Input area */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">
                      Peer IDs (one per line)
                    </label>
                    <textarea
                      placeholder={`0xabc123...\n0xdef456...,editor\n0x789ghi...,viewer`}
                      className="w-full min-h-[120px] rounded-lg border border-border bg-background p-3 font-mono text-sm resize-y focus:outline-none focus:ring-2 focus:ring-primary/50"
                      value={bulkInput}
                      onChange={(e) => setBulkInput(e.target.value)}
                    />
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      onClick={handleBulkParse}
                      disabled={!bulkInput.trim()}
                    >
                      <Search className="mr-1.5 h-3.5 w-3.5" /> Parse
                    </Button>
                    {!showBulkForm && bulkEntries.length === 0 && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setBulkInput(
                            members
                              .map((m) => `${m.peerId},${m.permission}`)
                              .join('\n'),
                          );
                        }}
                        disabled={members.length === 0}
                      >
                        <Copy className="mr-1.5 h-3.5 w-3.5" /> Copy Current
                        Members
                      </Button>
                    )}
                  </div>

                  {/* Parsed entries */}
                  {bulkEntries.length > 0 && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-medium">
                          {bulkEntries.length} peer
                          {bulkEntries.length !== 1 ? 's' : ''} parsed
                        </p>
                        <div className="flex items-center gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-xs"
                            onClick={toggleBulkSelectAll}
                          >
                            {bulkSelectAll ? (
                              <>
                                <CheckSquare className="mr-1 h-3.5 w-3.5" />{' '}
                                Deselect All
                              </>
                            ) : (
                              <>
                                <Square className="mr-1 h-3.5 w-3.5" /> Select
                                All
                              </>
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-xs text-muted-foreground"
                            onClick={() => {
                              setBulkEntries([]);
                              setBulkInput('');
                            }}
                          >
                            <Trash2 className="mr-1 h-3.5 w-3.5" /> Clear
                          </Button>
                        </div>
                      </div>
                      <div className="max-h-48 overflow-y-auto space-y-1 rounded-lg border border-border p-2">
                        {bulkEntries.map((entry, idx) => (
                          <div
                            key={idx}
                            className="flex items-center gap-2 rounded px-2 py-1.5 transition-colors hover:bg-accent/20"
                          >
                            <button
                              onClick={() => toggleBulkSelect(idx)}
                              className="shrink-0"
                            >
                              {entry.selected ? (
                                <CheckSquare className="h-4 w-4 text-primary" />
                              ) : (
                                <Square className="h-4 w-4 text-muted-foreground" />
                              )}
                            </button>
                            <span className="font-mono text-xs flex-1 min-w-0 truncate">
                              {entry.peerId}
                            </span>
                            <RoleBadge role={entry.permission} />
                          </div>
                        ))}
                      </div>

                      <div className="flex items-center gap-2 pt-2">
                        <Button
                          onClick={handleBulkApply}
                          disabled={
                            submitting ||
                            bulkEntries.filter((e) => e.selected).length === 0
                          }
                        >
                          {submitting
                            ? 'Applying...'
                            : `Apply to ${
                                bulkEntries.filter((e) => e.selected).length
                              } peer${
                                bulkEntries.filter((e) => e.selected).length !==
                                1
                                  ? 's'
                                  : ''
                              }`}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setBulkEntries([]);
                            setBulkInput('');
                            setShowBulkForm(false);
                          }}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* Quick actions */}
                  <div className="rounded-lg border border-border p-3">
                    <p className="text-sm font-medium mb-2">Quick Actions</p>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleBulkExport}
                        disabled={members.length === 0}
                      >
                        <Download className="mr-1.5 h-3.5 w-3.5" /> Export
                        Current Members
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          const input = document.createElement('input');
                          input.type = 'file';
                          input.accept = '.csv,.txt';
                          input.onchange = async (e) => {
                            const file = (e.target as HTMLInputElement)
                              ?.files?.[0];
                            if (!file) return;
                            const text = await file.text();
                            setBulkInput(text);
                          };
                          input.click();
                        }}
                      >
                        <Upload className="mr-1.5 h-3.5 w-3.5" /> Import from
                        File
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
