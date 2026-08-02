import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Eye,
  Plus,
  Trash2,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Lightbulb,
  Search,
  Filter,
  Database,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
} from '@/lib/spacetimedb';

interface ObservationRow {
  id: string;
  workspace_id: string;
  content: string;
  summary: string;
  evidence_json: string;
  observation_type: string;
  confidence: number;
  status: string;
  superseded_by: string;
  created_at: string;
  updated_at: string;
  memory_count: number;
  last_verified_at: string;
}

const obsTypeColors: Record<string, string> = {
  fact: 'bg-blue-500/10 text-blue-600',
  inference: 'bg-purple-500/10 text-purple-600',
  belief: 'bg-amber-500/10 text-amber-600',
};

const statusColors: Record<string, string> = {
  active: 'bg-green-500/10 text-green-600',
  stale: 'bg-yellow-500/10 text-yellow-600',
  superseded: 'bg-gray-500/10 text-gray-600',
};

export default function ObservationsPage() {
  const [observations, setObservations] = useState<ObservationRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  // Create form
  const [showForm, setShowForm] = useState(false);
  const [newContent, setNewContent] = useState('');
  const [newSummary, setNewSummary] = useState('');
  const [newType, setNewType] = useState('fact');
  const [newConfidence, setNewConfidence] = useState('0.8');
  const [newEvidence, setNewEvidence] = useState('[]');

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editSummary, setEditSummary] = useState('');
  const [editConfidence, setEditConfidence] = useState('0.8');

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  const loadObservations = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      await callReducer('list_observations', ['']);
      const res = await executeSql(
        "SELECT * FROM observation_list_result WHERE workspace_id = '' ORDER BY created_at DESC LIMIT 1"
      );
      const rows = parseSqlResponse<{ json_data: string }>(res);
      if (rows.length > 0 && rows[0].json_data) {
        try {
          const parsed = JSON.parse(rows[0].json_data) as ObservationRow[];
          setObservations(parsed);
        } catch {
          setObservations([]);
        }
      } else {
        // Fallback: read from observation table directly
        const fallback = await executeSql(
          "SELECT * FROM observation WHERE workspace_id = '' ORDER BY created_at DESC LIMIT 200"
        );
        setObservations(parseSqlResponse<ObservationRow>(fallback));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load observations');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadObservations();
  }, [loadObservations]);

  const handleCreate = useCallback(async () => {
    clearMessages();
    if (!newContent.trim()) {
      setError('Content is required');
      return;
    }
    try {
      await callReducer('create_observation', [
        '',
        newContent.trim(),
        newSummary.trim(),
        newEvidence,
        newType,
        parseFloat(newConfidence) || 0.8,
      ]);
      setSuccessMsg('Observation created');
      setShowForm(false);
      setNewContent('');
      setNewSummary('');
      setNewType('fact');
      setNewConfidence('0.8');
      setNewEvidence('[]');
      loadObservations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create observation');
    }
  }, [newContent, newSummary, newType, newConfidence, newEvidence, loadObservations]);

  const handleUpdate = useCallback(
    async (id: string) => {
      clearMessages();
      try {
        await callReducer('update_observation', [
          id,
          editContent,
          editSummary,
          parseFloat(editConfidence) || 0.0,
        ]);
        setSuccessMsg('Observation updated');
        setEditingId(null);
        loadObservations();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update observation');
      }
    },
    [editContent, editSummary, editConfidence, loadObservations]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      clearMessages();
      try {
        await callReducer('delete_observation', [id]);
        setSuccessMsg('Observation deleted');
        loadObservations();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete observation');
      }
    },
    [loadObservations]
  );

  const filtered = observations.filter((o) => {
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      if (
        !o.content.toLowerCase().includes(q) &&
        !o.summary.toLowerCase().includes(q)
      )
        return false;
    }
    if (typeFilter && o.observation_type !== typeFilter) return false;
    if (statusFilter && o.status !== statusFilter) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Observations</h1>
          <p className="text-muted-foreground">
            {loading
              ? 'Loading...'
              : `${filtered.length} knowledge claim(s)`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => setShowForm(true)}>
            <Plus className="h-4 w-4 mr-1.5" />
            Create
          </Button>
          <Button variant="ghost" size="icon" onClick={loadObservations}>
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
            <CardTitle className="text-lg">New Observation</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Content *
              </label>
              <Input
                placeholder="Observation content"
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Summary
              </label>
              <Input
                placeholder="Short summary"
                value={newSummary}
                onChange={(e) => setNewSummary(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Type
                </label>
                <select
                  value={newType}
                  onChange={(e) => setNewType(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="fact">Fact</option>
                  <option value="inference">Inference</option>
                  <option value="belief">Belief</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Confidence
                </label>
                <Input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={newConfidence}
                  onChange={(e) => setNewConfidence(e.target.value)}
                />
              </div>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Evidence (JSON array of memory IDs)
              </label>
              <Input
                placeholder='["mem-1", "mem-2"]'
                value={newEvidence}
                onChange={(e) => setNewEvidence(e.target.value)}
              />
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
            placeholder="Search observations..."
            className="pl-9"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="flex h-10 w-32 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <option value="">All Types</option>
          <option value="fact">Fact</option>
          <option value="inference">Inference</option>
          <option value="belief">Belief</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="flex h-10 w-36 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <option value="">All Status</option>
          <option value="active">Active</option>
          <option value="stale">Stale</option>
          <option value="superseded">Superseded</option>
        </select>
        <Badge variant="secondary" className="gap-1 shrink-0">
          <Filter className="h-3 w-3" />
          {typeFilter || statusFilter ? 'Filtering' : 'All'}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Knowledge Claims</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={i}
                  className="flex items-start justify-between rounded-lg border border-border p-3"
                >
                  <div className="space-y-1 flex-1">
                    <div className="h-4 w-3/5 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-4/5 rounded bg-muted animate-pulse" />
                  </div>
                  <div className="flex gap-2">
                    <div className="h-5 w-16 rounded-full bg-muted animate-pulse" />
                    <div className="h-5 w-12 rounded-full bg-muted animate-pulse" />
                  </div>
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Lightbulb className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">
                {searchTerm || typeFilter || statusFilter
                  ? 'No matching observations'
                  : 'No observations yet'}
              </p>
              <p className="text-sm mt-1">
                {searchTerm || typeFilter || statusFilter
                  ? 'Try adjusting your filters.'
                  : 'Create an observation to record a knowledge claim.'}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {filtered.map((obs) => {
                const isEditing = editingId === obs.id;
                let evidence: string[] = [];
                try {
                  evidence = JSON.parse(obs.evidence_json);
                } catch {
                  // ignore
                }

                return (
                  <div
                    key={obs.id}
                    className="rounded-lg border border-border p-3"
                  >
                    {isEditing ? (
                      <div className="space-y-3">
                        <Input
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          placeholder="Content"
                          className="h-8 text-sm"
                        />
                        <Input
                          value={editSummary}
                          onChange={(e) => setEditSummary(e.target.value)}
                          placeholder="Summary"
                          className="h-8 text-sm"
                        />
                        <Input
                          type="number"
                          min="0"
                          max="1"
                          step="0.05"
                          value={editConfidence}
                          onChange={(e) => setEditConfidence(e.target.value)}
                          placeholder="Confidence"
                          className="h-8 text-sm"
                        />
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            onClick={() => handleUpdate(obs.id)}
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
                      <>
                        <div className="flex items-start justify-between">
                          <div className="min-w-0 flex-1 mr-3">
                            <div className="flex items-center gap-2 mb-1">
                              <Badge
                                variant="outline"
                                className={
                                  obsTypeColors[obs.observation_type] ?? ''
                                }
                              >
                                {obs.observation_type}
                              </Badge>
                              <Badge
                                variant="outline"
                                className={
                                  statusColors[obs.status] ??
                                  'bg-gray-500/10 text-gray-600'
                                }
                              >
                                {obs.status}
                              </Badge>
                              {obs.confidence > 0 && (
                                <span className="text-xs text-muted-foreground">
                                  {(obs.confidence * 100).toFixed(0)}%
                                </span>
                              )}
                            </div>
                            <p className="text-sm font-medium">
                              {obs.summary || obs.content.slice(0, 150)}
                            </p>
                            {obs.summary && (
                              <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                {obs.content}
                              </p>
                            )}
                            <div className="flex items-center gap-3 mt-1.5 text-xs text-muted-foreground">
                              <span>
                                Created {formatMemoryTimestamp(obs.created_at)}
                              </span>
                              {evidence.length > 0 && (
                                <span>
                                  · {evidence.length} evidence
                                  memory(ies)
                                </span>
                              )}
                              {obs.memory_count > 0 && (
                                <span>· {obs.memory_count} linked</span>
                              )}
                            </div>
                            {evidence.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-2">
                                {evidence.map((eid) => (
                                  <Badge
                                    key={eid}
                                    variant="outline"
                                    className="text-[10px]"
                                  >
                                    <Database className="h-2.5 w-2.5 mr-0.5" />
                                    {eid.slice(0, 10)}…
                                  </Badge>
                                ))}
                              </div>
                            )}
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() => {
                                setEditingId(obs.id);
                                setEditContent(obs.content);
                                setEditSummary(obs.summary);
                                setEditConfidence(
                                  String(obs.confidence)
                                );
                              }}
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-destructive hover:text-destructive"
                              onClick={() => handleDelete(obs.id)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                      </>
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
