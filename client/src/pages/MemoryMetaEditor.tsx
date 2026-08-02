import { useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Database,
  Search as SearchIcon,
  Filter,
  AlertCircle,
  Shield,
  Tag,
  RefreshCw,
  Lock,
  Unlock,
  Check,
  X,
} from 'lucide-react';
import { useTable } from '@/lib/useReactiveDb';
import { callReducer, formatMemoryTimestamp } from '@/lib/spacetimedb';

interface MemoryRow {
  id: string;
  workspace_id: string;
  content: string;
  summary: string;
  memory_type: string;
  tier: string;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

interface MemoryMetaRow {
  id: string;
  workspace_id: string;
  memory_id: string;
  category: string;
  immutable: boolean;
  extra_json: string;
  created_at: string;
  updated_at: string;
}

const memoryTypeColors: Record<string, string> = {
  world_fact: 'bg-blue-500/10 text-blue-600',
  experience: 'bg-green-500/10 text-green-600',
  mental_model: 'bg-purple-500/10 text-purple-600',
  consolidated: 'bg-orange-500/10 text-orange-600',
};

export default function MemoryMetaEditor() {
  const [searchTerm, setSearchTerm] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editCategory, setEditCategory] = useState('');
  const [editImmutable, setEditImmutable] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [batchCategory, setBatchCategory] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showBatch, setShowBatch] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const { data: memories, loading: memoriesLoading } = useTable<MemoryRow>('memory');
  const { data: metas, loading: metasLoading } = useTable<MemoryMetaRow>('memory_meta');

  const loading = memoriesLoading || metasLoading;

  const metaByMemoryId = new Map<string, MemoryMetaRow>();
  for (const m of metas) {
    metaByMemoryId.set(m.memory_id, m);
  }

  const filtered = memories
    .filter((m) => {
      if (!searchTerm) return true;
      const q = searchTerm.toLowerCase();
      const meta = metaByMemoryId.get(m.id);
      return (
        m.content.toLowerCase().includes(q) ||
        m.summary.toLowerCase().includes(q) ||
        m.memory_type.toLowerCase().includes(q) ||
        (meta && meta.category.toLowerCase().includes(q))
      );
    })
    .sort(
      (a, b) =>
        Number(b.updated_at ?? b.created_at ?? 0) -
        Number(a.updated_at ?? a.created_at ?? 0)
    );

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  const handleSaveMeta = useCallback(
    async (memoryId: string) => {
      clearMessages();
      setSaving(memoryId);
      try {
        await callReducer('set_memory_meta', [
          '',
          memoryId,
          editCategory,
          editImmutable,
          '{}',
        ]);
        setSuccessMsg('Metadata updated');
        setEditingId(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to save metadata');
      } finally {
        setSaving(null);
      }
    },
    [editCategory, editImmutable]
  );

  const handleBatchSave = useCallback(async () => {
    clearMessages();
    if (selectedIds.size === 0) return;
    setSaving('batch');
    try {
      const idsJson = JSON.stringify(Array.from(selectedIds));
      await callReducer('batch_set_memory_meta', [
        '',
        idsJson,
        batchCategory,
        false,
      ]);
      setSuccessMsg(`Updated ${selectedIds.size} memories`);
      setSelectedIds(new Set());
      setBatchCategory('');
      setShowBatch(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Batch update failed');
    } finally {
      setSaving(null);
    }
  }, [selectedIds, batchCategory]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Memory Meta Editor</h1>
          <p className="text-muted-foreground">
            {loading
              ? 'Loading...'
              : `${filtered.length} memory(ies) with metadata`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowBatch(!showBatch)}
          >
            <Tag className="h-4 w-4 mr-1" />
            Batch Edit
          </Button>
          <Button variant="ghost" size="icon" onClick={() => window.location.reload()}>
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

      {showBatch && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Tag className="h-5 w-5" />
              Batch Edit Metadata
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-3">
              {selectedIds.size} memory(ies) selected. Set a category for all selected memories.
            </p>
            <div className="flex items-end gap-3">
              <div className="flex-1">
                <label className="text-xs font-medium mb-1 block">Category</label>
                <Input
                  placeholder="e.g. preferences, history, facts"
                  value={batchCategory}
                  onChange={(e) => setBatchCategory(e.target.value)}
                />
              </div>
              <Button
                onClick={handleBatchSave}
                disabled={saving === 'batch' || selectedIds.size === 0}
              >
                {saving === 'batch' ? 'Saving...' : 'Apply to All'}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setSelectedIds(new Set());
                  setBatchCategory('');
                  setShowBatch(false);
                }}
              >
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex items-center gap-4">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search memories and categories..."
            className="pl-9"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <Badge variant="secondary" className="gap-1 shrink-0">
          <Filter className="h-3 w-3" />
          {searchTerm ? 'Filtering' : 'All'}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Memory Metadata</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-lg border border-border p-3"
                >
                  <div className="space-y-1 flex-1">
                    <div className="h-4 w-3/5 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-4/5 mt-1 rounded bg-muted animate-pulse" />
                  </div>
                  <div className="flex gap-3 shrink-0 ml-3">
                    <div className="h-5 w-16 rounded-full bg-muted animate-pulse" />
                    <div className="h-4 w-12 rounded bg-muted animate-pulse" />
                  </div>
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Database className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">
                {searchTerm ? 'No matching memories' : 'No memories yet'}
              </p>
              <p className="text-sm mt-1">
                {searchTerm
                  ? 'Try a different search term.'
                  : 'Store a memory to see and manage its metadata here.'}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {filtered.map((mem) => {
                const meta = metaByMemoryId.get(mem.id);
                const isEditing = editingId === mem.id;

                return (
                  <div
                    key={mem.id}
                    className={`flex items-start justify-between rounded-lg border p-3 transition-colors ${
                      selectedIds.has(mem.id)
                        ? 'border-primary/50 bg-primary/5'
                        : 'border-border'
                    }`}
                  >
                    <div className="min-w-0 flex-1 mr-3">
                      <div className="flex items-center gap-2">
                        {showBatch && (
                          <input
                            type="checkbox"
                            checked={selectedIds.has(mem.id)}
                            onChange={() => toggleSelect(mem.id)}
                            className="h-4 w-4 shrink-0 rounded border-gray-300"
                          />
                        )}
                        <p className="text-sm font-medium truncate max-w-[450px]">
                          {mem.summary || mem.content.slice(0, 120)}
                        </p>
                        {meta?.immutable && (
                          <Badge
                            variant="outline"
                            className="text-xs shrink-0 text-amber-500 border-amber-500/30"
                          >
                            <Lock className="h-3 w-3 mr-0.5" />
                            Immutable
                          </Badge>
                        )}
                        {meta?.category && (
                          <Badge
                            variant="secondary"
                            className="text-xs shrink-0"
                          >
                            <Tag className="h-3 w-3 mr-0.5" />
                            {meta.category}
                          </Badge>
                        )}
                      </div>

                      {isEditing ? (
                        <div className="mt-3 space-y-2 border-t border-border pt-3">
                          <div className="flex items-end gap-3">
                            <div className="flex-1">
                              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                                Category
                              </label>
                              <Input
                                placeholder="Category label"
                                value={editCategory}
                                onChange={(e) => setEditCategory(e.target.value)}
                                className="h-8 text-sm"
                              />
                            </div>
                            <div className="flex items-center gap-2 pb-1">
                              <label className="text-xs font-medium text-muted-foreground cursor-pointer flex items-center gap-1.5">
                                <input
                                  type="checkbox"
                                  checked={editImmutable}
                                  onChange={(e) => setEditImmutable(e.target.checked)}
                                  className="h-4 w-4 rounded"
                                />
                                Immutable
                              </label>
                            </div>
                            <div className="flex gap-1">
                              <Button
                                size="sm"
                                onClick={() => handleSaveMeta(mem.id)}
                                disabled={saving === mem.id}
                              >
                                {saving === mem.id ? 'Saving...' : 'Save'}
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
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground mt-1 truncate max-w-[450px]">
                          {mem.content.slice(0, 200)}
                          {mem.content.length > 200 ? '…' : ''}
                        </p>
                      )}

                      <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                        <span>{formatMemoryTimestamp(mem.created_at)}</span>
                        {mem.tier && <span>· Tier {mem.tier}</span>}
                        {meta && (
                          <>
                            <span>·</span>
                            {meta.immutable ? (
                              <Lock className="h-3 w-3 text-amber-500" />
                            ) : (
                              <Unlock className="h-3 w-3 text-green-500" />
                            )}
                          </>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <Badge
                        variant="outline"
                        className={memoryTypeColors[mem.memory_type] ?? ''}
                      >
                        {mem.memory_type}
                      </Badge>
                      {!mem.is_active && (
                        <Badge variant="secondary" className="text-xs">
                          inactive
                        </Badge>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => {
                          if (isEditing) {
                            setEditingId(null);
                          } else {
                            setEditingId(mem.id);
                            setEditCategory(meta?.category ?? '');
                            setEditImmutable(meta?.immutable ?? false);
                          }
                        }}
                      >
                        <Shield className="h-3.5 w-3.5" />
                      </Button>
                    </div>
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
