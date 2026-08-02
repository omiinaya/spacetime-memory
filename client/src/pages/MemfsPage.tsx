import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  FolderTree,
  FolderOpen,
  FileText,
  Folder,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Plus,
  Trash2,
  ArrowLeft,
  HardDrive,
  Link,
  FilePlus,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
  formatFileSize,
} from '@/lib/spacetimedb';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MemfsEntry {
  id: string;
  workspace_id: string;
  parent_id: string;
  name: string;
  path: string;
  entry_type: string;
  mime_type: string;
  data: string;
  size: number;
  is_mounted: boolean;
  mount_source: string;
  created_at: number;
  updated_at: number;
}

interface MemfsMount {
  id: string;
  workspace_id: string;
  mount_path: string;
  source_type: string;
  source_config: string;
  filter_query: string;
  created_at: number;
}

// ---------------------------------------------------------------------------
// Tree node helper
// ---------------------------------------------------------------------------

interface TreeNode {
  entry: MemfsEntry;
  children: TreeNode[];
  expanded: boolean;
}

function buildTree(entries: MemfsEntry[], parentId: string): TreeNode[] {
  return entries
    .filter((e) => e.parent_id === parentId)
    .sort((a, b) => {
      // Directories first, then alphabetical
      if (a.entry_type !== b.entry_type) {
        return a.entry_type === 'directory' ? -1 : 1;
      }
      return a.name.localeCompare(b.name);
    })
    .map((entry) => ({
      entry,
      children: buildTree(entries, entry.id),
      expanded: false,
    }));
}

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

export default function MemfsPage() {
  // Tree state
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Mounts
  const [mounts, setMounts] = useState<MemfsMount[]>([]);
  const [mountsLoading, setMountsLoading] = useState(false);

  // Detail view
  const [selectedEntry, setSelectedEntry] = useState<MemfsEntry | null>(null);

  // Create file/dir form
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createParentId, setCreateParentId] = useState('');
  const [createName, setCreateName] = useState('');
  const [createType, setCreateType] = useState<'file' | 'directory'>('file');
  const [createMimeType, setCreateMimeType] = useState('text/plain');
  const [createData, setCreateData] = useState('');
  const [creating, setCreating] = useState(false);

  // Create mount form
  const [showMountForm, setShowMountForm] = useState(false);
  const [mountPath, setMountPath] = useState('');
  const [mountSourceType, setMountSourceType] = useState('workspace');
  const [mountSourceConfig, setMountSourceConfig] = useState('{}');
  const [mountFilterQuery, setMountFilterQuery] = useState('');
  const [mountCreating, setMountCreating] = useState(false);

  // File content / write
  const [editData, setEditData] = useState('');
  const [writing, setWriting] = useState(false);

  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  // -----------------------------------------------------------------------
  // Load entries + mounts
  // -----------------------------------------------------------------------

  const loadEntries = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      await callReducer('get_memfs_entries', ['', '']);
      const res = await executeSql(
        "SELECT * FROM memfs_result ORDER BY created_at DESC"
      );
      const rows = parseSqlResponse<{ id: string; data: string }>(res);
      // Filter out count markers and parse entries
      const parsedEntries: MemfsEntry[] = [];
      for (const row of rows) {
        if (row.id.startsWith('_count_') || row.id.startsWith('not_found_')) continue;
        try {
          const entry = JSON.parse(row.data) as MemfsEntry;
          parsedEntries.push(entry);
        } catch {
          // skip
        }
      }
      if (parsedEntries.length > 0) {
        setTree(buildTree(parsedEntries, ''));
      } else {
        // Fallback: read from memfs_entry table
        const fallback = await executeSql(
          "SELECT * FROM memfs_entry ORDER BY path ASC LIMIT 500"
        );
        const flat = parseSqlResponse<MemfsEntry>(fallback);
        setTree(buildTree(flat, ''));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load entries');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMounts = useCallback(async () => {
    setMountsLoading(true);
    try {
      await callReducer('get_memfs_mounts', ['']);
      const res = await executeSql(
        "SELECT * FROM memfs_result ORDER BY created_at DESC"
      );
      const rows = parseSqlResponse<{ id: string; data: string }>(res);
      const parsedMounts: MemfsMount[] = [];
      for (const row of rows) {
        if (row.id.startsWith('_mount_count_') || row.id.startsWith('not_found_') || row.id.startsWith('_count_')) continue;
        try {
          const mount = JSON.parse(row.data) as MemfsMount;
          parsedMounts.push(mount);
        } catch {
          // skip
        }
      }
      if (parsedMounts.length > 0) {
        setMounts(parsedMounts);
      } else {
        const fallback = await executeSql(
          "SELECT * FROM memfs_mount ORDER BY created_at ASC LIMIT 100"
        );
        setMounts(parseSqlResponse<MemfsMount>(fallback));
      }
    } catch {
      // non-critical
    } finally {
      setMountsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadEntries();
    loadMounts();
  }, [loadEntries, loadMounts]);

  // -----------------------------------------------------------------------
  // Tree expansion
  // -----------------------------------------------------------------------

  const toggleExpand = useCallback((path: string[]) => {
    const expandNode = (nodes: TreeNode[], depth: number): TreeNode[] => {
      return nodes.map((node) => {
        if (depth < path.length && node.entry.id === path[depth]) {
          const isTarget = depth === path.length - 1;
          return {
            ...node,
            expanded: isTarget ? !node.expanded : node.expanded,
            children: expandNode(node.children, depth + 1),
          };
        }
        return {
          ...node,
          children: expandNode(node.children, depth + 1),
        };
      });
    };
    setTree((prev) => expandNode(prev, 0));
  }, []);

  // -----------------------------------------------------------------------
  // Select entry
  // -----------------------------------------------------------------------

  const selectEntry = useCallback((entry: MemfsEntry) => {
    setSelectedEntry(entry);
    setEditData(entry.data || '');
    setShowCreateForm(false);
    setShowMountForm(false);
  }, []);

  const backToList = useCallback(() => {
    setSelectedEntry(null);
  }, []);

  // -----------------------------------------------------------------------
  // Create file / directory
  // -----------------------------------------------------------------------

  const openCreateForm = useCallback((parentId: string) => {
    setCreateParentId(parentId);
    setCreateName('');
    setCreateType('file');
    setCreateMimeType('text/plain');
    setCreateData('');
    setShowCreateForm(true);
    setSelectedEntry(null);
  }, []);

  const handleCreateEntry = useCallback(async () => {
    clearMessages();
    if (!createName.trim()) {
      setError('Name is required');
      return;
    }
    setCreating(true);
    try {
      await callReducer('create_memfs_entry', [
        '',
        createParentId,
        createName.trim(),
        createType,
        createMimeType,
        createType === 'file' ? createData : '',
      ]);
      setSuccessMsg(`${createType === 'file' ? 'File' : 'Directory'} created`);
      setShowCreateForm(false);
      loadEntries();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create entry');
    } finally {
      setCreating(false);
    }
  }, [createParentId, createName, createType, createMimeType, createData, loadEntries]);

  // -----------------------------------------------------------------------
  // Write file content
  // -----------------------------------------------------------------------

  const handleWriteFile = useCallback(async () => {
    clearMessages();
    if (!selectedEntry || selectedEntry.entry_type !== 'file') return;
    setWriting(true);
    try {
      await callReducer('write_memfs_file', [
        selectedEntry.workspace_id,
        selectedEntry.id,
        editData,
      ]);
      setSuccessMsg('File written');
      // Reload entry data
      await callReducer('read_memfs_file', [selectedEntry.workspace_id, selectedEntry.id]);
      const res = await executeSql(
        "SELECT * FROM memfs_result WHERE id = 'read_" + selectedEntry.id + "' ORDER BY created_at DESC LIMIT 1"
      );
      const rows = parseSqlResponse<{ data: string }>(res);
      if (rows.length > 0) {
        setSelectedEntry((prev) =>
          prev ? { ...prev, data: rows[0].data, size: rows[0].data.length, updated_at: Date.now() * 1000 } : prev
        );
      }
      loadEntries();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to write file');
    } finally {
      setWriting(false);
    }
  }, [selectedEntry, editData, loadEntries]);

  // -----------------------------------------------------------------------
  // Delete entry
  // -----------------------------------------------------------------------

  const handleDeleteEntry = useCallback(
    async (entryId: string) => {
      clearMessages();
      if (!confirm('Delete this entry? This cannot be undone.')) return;
      setActionLoading(entryId);
      try {
        await callReducer('delete_memfs_entry', ['', entryId]);
        setSuccessMsg('Entry deleted');
        if (selectedEntry?.id === entryId) {
          setSelectedEntry(null);
        }
        loadEntries();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete entry');
      } finally {
        setActionLoading(null);
      }
    },
    [loadEntries, selectedEntry],
  );

  // -----------------------------------------------------------------------
  // Create mount
  // -----------------------------------------------------------------------

  const handleCreateMount = useCallback(async () => {
    clearMessages();
    if (!mountPath.trim()) {
      setError('Mount path is required');
      return;
    }
    setMountCreating(true);
    try {
      await callReducer('create_memfs_mount', [
        '',
        mountPath.trim(),
        mountSourceType,
        mountSourceConfig,
        mountFilterQuery,
      ]);
      setSuccessMsg('Mount created');
      setShowMountForm(false);
      setMountPath('');
      loadMounts();
      loadEntries();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create mount');
    } finally {
      setMountCreating(false);
    }
  }, [mountPath, mountSourceType, mountSourceConfig, mountFilterQuery, loadMounts, loadEntries]);

  // -----------------------------------------------------------------------
  // Delete mount
  // -----------------------------------------------------------------------

  const handleDeleteMount = useCallback(
    async (mountId: string) => {
      clearMessages();
      if (!confirm('Delete this mount point?')) return;
      setActionLoading(mountId);
      try {
        await callReducer('delete_memfs_mount', ['', mountId]);
        setSuccessMsg('Mount deleted');
        loadMounts();
        loadEntries();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete mount');
      } finally {
        setActionLoading(null);
      }
    },
    [loadMounts, loadEntries],
  );

  // -----------------------------------------------------------------------
  // Render tree node (recursive)
  // -----------------------------------------------------------------------

  const renderTree = (nodes: TreeNode[], depth: number): React.ReactNode => {
    return nodes.map((node) => (
      <div key={node.entry.id}>
        <div
          className={`flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-accent/50 cursor-pointer text-sm ${
            selectedEntry?.id === node.entry.id ? 'bg-accent' : ''
          }`}
          style={{ paddingLeft: `${12 + depth * 20}px` }}
          onClick={() => {
            if (node.entry.entry_type === 'directory') {
              toggleExpand([node.entry.id]);
            }
            selectEntry(node.entry);
          }}
        >
          {/* Expand/collapse icon for directories */}
          {node.entry.entry_type === 'directory' ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                toggleExpand([node.entry.id]);
              }}
              className="text-muted-foreground hover:text-foreground"
            >
              {node.expanded ? (
                <FolderOpen className="h-4 w-4" />
              ) : (
                <Folder className="h-4 w-4" />
              )}
            </button>
          ) : (
            <FileText className="h-4 w-4 text-blue-500" />
          )}

          <span className="flex-1 truncate">{node.entry.name}</span>

          {node.entry.is_mounted && (
            <Badge variant="outline" className="text-[10px] px-1 py-0">
              <Link className="h-3 w-3 mr-0.5" />
              mount
            </Badge>
          )}

          {node.entry.entry_type === 'file' && (
            <span className="text-xs text-muted-foreground shrink-0">
              {formatFileSize(node.entry.size)}
            </span>
          )}
        </div>

        {/* Children (shown when expanded) */}
        {node.expanded && node.children.length > 0 && (
          <div>{renderTree(node.children, depth + 1)}</div>
        )}

        {/* Empty directory hint */}
        {node.expanded && node.children.length === 0 && (
          <div
            className="text-xs text-muted-foreground italic py-1"
            style={{ paddingLeft: `${24 + depth * 20}px` }}
          >
            Empty directory
          </div>
        )}
      </div>
    ));
  };

  // -----------------------------------------------------------------------
  // Render: File detail view
  // -----------------------------------------------------------------------

  if (selectedEntry) {
    const e = selectedEntry;
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
                {e.entry_type === 'directory' ? (
                  <FolderOpen className="h-7 w-7 text-amber-500" />
                ) : (
                  <FileText className="h-7 w-7 text-blue-500" />
                )}
                {e.name}
              </h1>
              <p className="text-sm text-muted-foreground font-mono">{e.path}</p>
            </div>
          </div>
          <Badge variant="outline">
            {e.entry_type === 'file' ? formatFileSize(e.size) : 'directory'}
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

        {/* Info */}
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Type</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-medium capitalize">{e.entry_type}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">MIME Type</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm font-mono">{e.mime_type || '—'}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Size</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-bold">{formatFileSize(e.size)}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Mounted</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-medium">
                {e.is_mounted ? (
                  <Badge variant="default" className="bg-green-500/10 text-green-600">
                    Yes
                  </Badge>
                ) : (
                  <Badge variant="outline">No</Badge>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          {e.entry_type === 'directory' ? (
            <Button onClick={() => openCreateForm(e.id)}>
              <Plus className="h-4 w-4 mr-1.5" />
              New Entry
            </Button>
          ) : (
            <Button variant="outline" onClick={() => { /* trigger re-read */ }}>
              <RefreshCw className="h-4 w-4 mr-1.5" />
              Refresh Content
            </Button>
          )}
          <Button
            onClick={() => handleDeleteEntry(e.id)}
            disabled={actionLoading === e.id}
            variant="destructive"
          >
            <Trash2 className="h-4 w-4 mr-1.5" />
            Delete
          </Button>
          <Button variant="outline" onClick={loadEntries}>
            <RefreshCw className="h-4 w-4 mr-1.5" />
            Refresh Tree
          </Button>
        </div>

        {/* File content editor */}
        {e.entry_type === 'file' && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-lg flex items-center gap-2">
                <FileText className="h-5 w-5" />
                File Content
              </CardTitle>
              <CardDescription>
                Edit the file content below and save.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <textarea
                rows={12}
                value={editData}
                onChange={(e) => setEditData(e.target.value)}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
              <Button onClick={handleWriteFile} disabled={writing}>
                {writing ? 'Writing...' : 'Save'}
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Directory info */}
        {e.entry_type === 'directory' && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Directory Info</CardTitle>
            </CardHeader>
            <CardContent>
              {e.is_mounted && (
                <div className="mb-2">
                  <Badge variant="secondary">
                    <Link className="h-3 w-3 mr-1" />
                    Mount source: {e.mount_source}
                  </Badge>
                </div>
              )}
              <pre className="rounded-lg bg-muted p-3 text-xs overflow-x-auto">
                {JSON.stringify(e, null, 2)}
              </pre>
            </CardContent>
          </Card>
        )}
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Render: Main page
  // -----------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <FolderTree className="h-7 w-7 text-primary" />
            MemFS
          </h1>
          <p className="text-muted-foreground">
            Virtual file system for memory workspace data
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => openCreateForm('')}>
            <FilePlus className="h-4 w-4 mr-1.5" />
            New Entry
          </Button>
          <Button variant="secondary" onClick={() => setShowMountForm(true)}>
            <HardDrive className="h-4 w-4 mr-1.5" />
            Mount
          </Button>
          <Button variant="ghost" size="icon" onClick={() => { loadEntries(); loadMounts(); }}>
            <RefreshCw className="h-4 w-4" />
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

      {/* Create entry form */}
      {showCreateForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Create Entry</CardTitle>
            <CardDescription>
              Create a new file or directory in the virtual filesystem.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Name *
                </label>
                <input
                  placeholder="entry name"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Type
                </label>
                <select
                  value={createType}
                  onChange={(e) => setCreateType(e.target.value as 'file' | 'directory')}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <option value="file">File</option>
                  <option value="directory">Directory</option>
                </select>
              </div>
            </div>

            {createType === 'file' && (
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  MIME Type
                </label>
                <input
                  placeholder="text/plain"
                  value={createMimeType}
                  onChange={(e) => setCreateMimeType(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
            )}

            {createType === 'file' && (
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Initial Content
                </label>
                <textarea
                  rows={6}
                  value={createData}
                  onChange={(e) => setCreateData(e.target.value)}
                  className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
            )}

            {createParentId && (
              <p className="text-xs text-muted-foreground">
                Parent ID: {createParentId.slice(0, 16)}...
              </p>
            )}

            <div className="flex gap-2 pt-2">
              <Button onClick={handleCreateEntry} disabled={creating}>
                {creating ? 'Creating...' : createType === 'file' ? 'Create File' : 'Create Directory'}
              </Button>
              <Button variant="outline" onClick={() => setShowCreateForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Create mount form */}
      {showMountForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <HardDrive className="h-5 w-5" />
              Create Mount Point
            </CardTitle>
            <CardDescription>
              Mount a data source at a virtual path.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Mount Path *
                </label>
                <input
                  placeholder="/mnt/workspace"
                  value={mountPath}
                  onChange={(e) => setMountPath(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Source Type
                </label>
                <select
                  value={mountSourceType}
                  onChange={(e) => setMountSourceType(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <option value="workspace">Workspace</option>
                  <option value="memory">Memory</option>
                  <option value="note">Note</option>
                  <option value="session">Session</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
            </div>

            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Source Config (JSON)
              </label>
              <textarea
                rows={3}
                value={mountSourceConfig}
                onChange={(e) => setMountSourceConfig(e.target.value)}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>

            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Filter Query (optional)
              </label>
              <input
                placeholder="SQL/semantic filter"
                value={mountFilterQuery}
                onChange={(e) => setMountFilterQuery(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>

            <div className="flex gap-2 pt-2">
              <Button onClick={handleCreateMount} disabled={mountCreating}>
                {mountCreating ? 'Creating...' : 'Create Mount'}
              </Button>
              <Button variant="outline" onClick={() => setShowMountForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Main layout: Tree + Mounts */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* File tree */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-lg flex items-center gap-2">
                <FolderTree className="h-5 w-5" />
                File Browser
              </CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-1">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div
                      key={i}
                      className="h-7 rounded bg-muted animate-pulse"
                      style={{ marginLeft: `${(i % 3) * 16}px` }}
                    />
                  ))}
                </div>
              ) : tree.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <FolderTree className="h-10 w-10 mb-3 opacity-30" />
                  <p className="font-medium">No files yet</p>
                  <p className="text-sm mt-1">Create a file or directory to get started.</p>
                </div>
              ) : (
                <div className="space-y-0.5">{renderTree(tree, 0)}</div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Mounts sidebar */}
        <div>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-lg flex items-center gap-2">
                <HardDrive className="h-5 w-5" />
                Mount Points
              </CardTitle>
            </CardHeader>
            <CardContent>
              {mountsLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 2 }).map((_, i) => (
                    <div key={i} className="h-16 rounded-lg bg-muted animate-pulse" />
                  ))}
                </div>
              ) : mounts.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                  <HardDrive className="h-8 w-8 mb-2 opacity-30" />
                  <p className="text-sm font-medium">No mounts</p>
                  <p className="text-xs mt-1">Mount data sources to expose them in the FS.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {mounts.map((mount) => (
                    <div
                      key={mount.id}
                      className="rounded-lg border border-border p-3"
                    >
                      <div className="flex items-center justify-between">
                        <div className="min-w-0 flex-1 mr-2">
                          <p className="text-sm font-medium font-mono truncate">
                            {mount.mount_path}
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            <Badge variant="outline" className="text-[10px]">
                              {mount.source_type}
                            </Badge>
                            <span className="text-[10px] text-muted-foreground">
                              {formatMemoryTimestamp(mount.created_at)}
                            </span>
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDeleteMount(mount.id)}
                          disabled={actionLoading === mount.id}
                          className="text-destructive hover:text-destructive shrink-0"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <Button
                variant="outline"
                className="w-full mt-3"
                onClick={() => setShowMountForm(true)}
              >
                <Plus className="h-4 w-4 mr-1.5" />
                Add Mount
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
