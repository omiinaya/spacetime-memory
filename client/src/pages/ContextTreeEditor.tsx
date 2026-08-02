import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  FolderTree,
  Plus,
  Trash2,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Globe,
  Globe2,
  Search,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
} from '@/lib/spacetimedb';

interface ContextEntry {
  id: string;
  workspace_id: string;
  path: string;
  content: string;
  priority: number;
  is_global: boolean;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export default function ContextTreeEditor() {
  const [entries, setEntries] = useState<ContextEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [pathFilter, setPathFilter] = useState('');

  // Create form
  const [showForm, setShowForm] = useState(false);
  const [newPath, setNewPath] = useState('/');
  const [newContent, setNewContent] = useState('');
  const [newPriority, setNewPriority] = useState('0');
  const [newIsGlobal, setNewIsGlobal] = useState(false);

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editPriority, setEditPriority] = useState('0');
  const [editIsGlobal, setEditIsGlobal] = useState(false);

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  const loadEntries = useCallback(async () => {

    setLoading(true);
    try {
      await callReducer('list_contexts', ['']);
      const res = await executeSql(
        "SELECT * FROM context_tree_result WHERE workspace_id = '' AND query_id = 'list' ORDER BY created_at DESC LIMIT 1"
      );
      const rows = parseSqlResponse<{ results_json: string }>(res);
      if (rows.length > 0 && rows[0].results_json) {
        try {
          const parsed = JSON.parse(rows[0].results_json) as ContextEntry[];
          setEntries(parsed);
        } catch {
          setEntries([]);
        }
      } else {
        // Fallback: read from context_tree directly
        const fallback = await executeSql(
          "SELECT * FROM context_tree WHERE workspace_id = '' ORDER BY path ASC LIMIT 200"
        );
        setEntries(parseSqlResponse<ContextEntry>(fallback));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load context entries');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadEntries();
  }, [loadEntries]);

  const handleCreate = useCallback(async () => {
    clearMessages();
    if (!newPath.trim() || !newContent.trim()) {
      setError('Path and content are required');
      return;
    }
    try {
      await callReducer('set_context', [
        '',
        newPath.trim(),
        newContent.trim(),
        parseFloat(newPriority) || 0,
        newIsGlobal,
      ]);
      setSuccessMsg('Context entry created');
      setShowForm(false);
      setNewPath('/');
      setNewContent('');
      setNewPriority('0');
      setNewIsGlobal(false);
      loadEntries();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create context entry');
    }
  }, [newPath, newContent, newPriority, newIsGlobal, loadEntries]);

  const handleUpdate = useCallback(
    async (entryId: string) => {
      clearMessages();
      // update_context doesn't exist as a separate reducer — use set_context
      // Find the entry to get its path
      const entry = entries.find((e) => e.id === entryId);
      if (!entry) return;
      try {
        await callReducer('set_context', [
          entry.workspace_id || '',
          entry.path,
          editContent,
          parseFloat(editPriority) || 0,
          editIsGlobal,
        ]);
        setSuccessMsg('Context entry updated');
        setEditingId(null);
        loadEntries();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update context entry');
      }
    },
    [editContent, editPriority, editIsGlobal, entries, loadEntries]
  );

  const handleDelete = useCallback(
    async (entryId: string) => {
      clearMessages();
      try {
        await callReducer('delete_context', [entryId]);
        setSuccessMsg('Context entry deleted');
        loadEntries();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete context entry');
      }
    },
    [loadEntries]
  );

  // Build tree structure
  const filtered = entries.filter((e) => {
    if (!pathFilter) return true;
    return e.path.toLowerCase().includes(pathFilter.toLowerCase());
  });

  // Group by top-level path
  const treePaths = [...new Set(filtered.map((e) => e.path))].sort();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Context Tree</h1>
          <p className="text-muted-foreground">
            {loading
              ? 'Loading...'
              : `${filtered.length} context entr(ies)`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => setShowForm(true)}>
            <Plus className="h-4 w-4 mr-1.5" />
            Add Context
          </Button>
          <Button variant="ghost" size="icon" onClick={loadEntries}>
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

      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">New Context Entry</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Path *
              </label>
              <Input
                placeholder="/api/v2"
                value={newPath}
                onChange={(e) => setNewPath(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                Hierarchical path like /api/v2/users or /.
              </p>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Content *
              </label>
              <Input
                placeholder="Context text for this path"
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Priority
                </label>
                <Input
                  type="number"
                  step="0.1"
                  value={newPriority}
                  onChange={(e) => setNewPriority(e.target.value)}
                />
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    checked={newIsGlobal}
                    onChange={(e) => setNewIsGlobal(e.target.checked)}
                    className="h-4 w-4 rounded"
                  />
                  <span className="text-muted-foreground">Global context</span>
                </label>
              </div>
            </div>
            <div className="flex gap-2 pt-2">
              <Button onClick={handleCreate}>Create</Button>
              <Button variant="outline" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter by path..."
            className="pl-9"
            value={pathFilter}
            onChange={(e) => setPathFilter(e.target.value)}
          />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Context Entries</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 rounded-lg border border-border p-3"
                >
                  <div className="h-4 w-4 rounded bg-muted animate-pulse mt-1" />
                  <div className="space-y-1 flex-1">
                    <div className="h-4 w-32 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-64 rounded bg-muted animate-pulse" />
                  </div>
                  <div className="h-6 w-16 rounded-full bg-muted animate-pulse" />
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <FolderTree className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">
                {pathFilter ? 'No matching paths' : 'No context entries yet'}
              </p>
              <p className="text-sm mt-1">
                {pathFilter
                  ? 'Try a different filter.'
                  : 'Add context entries for hierarchical path-based retrieval.'}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {treePaths.map((path) => {
                const entry = entries.find((e) => e.path === path)!;
                const isEditing = editingId === entry.id;
                const depth = path === '/' ? 0 : path.split('/').filter(Boolean).length;

                return (
                  <div
                    key={entry.id}
                    className="rounded-lg border border-border p-3"
                    style={{ marginLeft: depth * 16 }}
                  >
                    {isEditing ? (
                      <div className="space-y-3">
                        <Input
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          placeholder="Content"
                          className="h-8 text-sm"
                        />
                        <div className="flex items-center gap-3">
                          <div className="flex-1">
                            <Input
                              type="number"
                              step="0.1"
                              value={editPriority}
                              onChange={(e) => setEditPriority(e.target.value)}
                              placeholder="Priority"
                              className="h-8 text-sm"
                            />
                          </div>
                          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                            <input
                              type="checkbox"
                              checked={editIsGlobal}
                              onChange={(e) => setEditIsGlobal(e.target.checked)}
                              className="h-4 w-4 rounded"
                            />
                            Global
                          </label>
                        </div>
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            onClick={() => handleUpdate(entry.id)}
                          >
                            Save
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setEditingId(null)}
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start justify-between">
                        <div className="min-w-0 flex-1 mr-3">
                          <div className="flex items-center gap-2">
                            <Badge
                              variant="outline"
                              className="text-xs font-mono"
                            >
                              {entry.path}
                            </Badge>
                            {entry.is_global && (
                              <Badge
                                variant="secondary"
                                className="text-xs"
                              >
                                <Globe className="h-3 w-3 mr-0.5" />
                                Global
                              </Badge>
                            )}
                            {entry.priority > 0 && (
                              <span className="text-xs text-muted-foreground">
                                p={entry.priority}
                              </span>
                            )}
                          </div>
                          <p className="text-sm mt-1">
                            {entry.content}
                          </p>
                          <p className="text-xs text-muted-foreground mt-1">
                            Updated {formatMemoryTimestamp(entry.updated_at)}
                            {entry.created_by && (
                              <> · by {entry.created_by.slice(0, 12)}…</>
                            )}
                          </p>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={() => {
                              setEditingId(entry.id);
                              setEditContent(entry.content);
                              setEditPriority(String(entry.priority));
                              setEditIsGlobal(entry.is_global);
                            }}
                          >
                            <Globe2 className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-destructive hover:text-destructive"
                            onClick={() => handleDelete(entry.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
