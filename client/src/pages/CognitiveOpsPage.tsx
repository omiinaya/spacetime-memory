import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Cpu,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Plus,
  Trash2,
  Play,
  ArrowLeft,
  Filter,
  ListChecks,
  Workflow,
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

interface CognitiveOp {
  id: string;
  workspace_id: string;
  name: string;
  op_type: string;
  description: string;
  config_json: string;
  pipeline_stage_type: string;
  created_at: number;
  updated_at: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const OP_TYPES = ['observe', 'filter', 'extract', 'transform', 'classify', 'rank', 'store'] as const;

const OP_TYPE_COLORS: Record<string, string> = {
  observe: 'bg-blue-500/10 text-blue-600 border-blue-500/30',
  filter: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/30',
  extract: 'bg-purple-500/10 text-purple-600 border-purple-500/30',
  transform: 'bg-amber-500/10 text-amber-600 border-amber-500/30',
  classify: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30',
  rank: 'bg-rose-500/10 text-rose-600 border-rose-500/30',
  store: 'bg-indigo-500/10 text-indigo-600 border-indigo-500/30',
};

const PIPELINE_ORDER = ['observe', 'extract', 'classify', 'filter', 'transform', 'rank', 'store'];

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

export default function CognitiveOpsPage() {
  const [ops, setOps] = useState<CognitiveOp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filter
  const [typeFilter, setTypeFilter] = useState('');

  // Detail view
  const [selectedOp, setSelectedOp] = useState<CognitiveOp | null>(null);
  const [execResult, setExecResult] = useState<string | null>(null);

  // Create form
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formOpType, setFormOpType] = useState('observe');
  const [formDescription, setFormDescription] = useState('');
  const [formConfigJson, setFormConfigJson] = useState('{}');
  const [formPipelineStageType, setFormPipelineStageType] = useState('');
  const [formSubmitting, setFormSubmitting] = useState(false);

  // Execute
  const [executeInput, setExecuteInput] = useState('{}');
  const [executing, setExecuting] = useState(false);

  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  // -----------------------------------------------------------------------
  // Load ops
  // -----------------------------------------------------------------------

  const loadOps = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      await callReducer('get_cognitive_ops', ['', typeFilter]);
      const res = await executeSql(
        "SELECT * FROM cognitive_op_result ORDER BY created_at DESC LIMIT 1"
      );
      const rows = parseSqlResponse<{ data: string }>(res);
      if (rows.length > 0 && rows[0].data) {
        try {
          const parsed = JSON.parse(rows[0].data) as CognitiveOp[];
          setOps(parsed);
          return;
        } catch {
          // fall through
        }
      }
      // Fallback: read from cognitive_op table directly
      const fallback = await executeSql(
        "SELECT * FROM cognitive_op ORDER BY created_at ASC LIMIT 200"
      );
      setOps(parseSqlResponse<CognitiveOp>(fallback));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load cognitive ops');
    } finally {
      setLoading(false);
    }
  }, [typeFilter]);

  useEffect(() => {
    loadOps();
  }, [loadOps]);

  // -----------------------------------------------------------------------
  // Select op detail
  // -----------------------------------------------------------------------

  const selectOp = useCallback((op: CognitiveOp) => {
    setSelectedOp(op);
    setExecResult(null);
    setShowForm(false);
  }, []);

  const backToList = useCallback(() => {
    setSelectedOp(null);
    setExecResult(null);
  }, []);

  // -----------------------------------------------------------------------
  // Create op
  // -----------------------------------------------------------------------

  const openCreateForm = useCallback(() => {
    setFormName('');
    setFormOpType('observe');
    setFormDescription('');
    setFormConfigJson('{}');
    setFormPipelineStageType('');
    setShowForm(true);
    setSelectedOp(null);
  }, []);

  const handleCreate = useCallback(async () => {
    clearMessages();
    if (!formName.trim()) {
      setError('Op name is required');
      return;
    }
    // Validate config JSON
    try {
      JSON.parse(formConfigJson);
    } catch {
      setError('config_json is not valid JSON');
      return;
    }
    setFormSubmitting(true);
    try {
      await callReducer('register_cognitive_op', [
        '',
        '',
        formName.trim(),
        formOpType,
        formDescription.trim(),
        formConfigJson,
        formPipelineStageType.trim(),
      ]);
      setSuccessMsg('Cognitive op registered');
      setShowForm(false);
      loadOps();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to register cognitive op');
    } finally {
      setFormSubmitting(false);
    }
  }, [formName, formOpType, formDescription, formConfigJson, formPipelineStageType, loadOps]);

  // -----------------------------------------------------------------------
  // Delete op
  // -----------------------------------------------------------------------

  const handleDelete = useCallback(
    async (opId: string) => {
      clearMessages();
      if (!confirm('Delete this cognitive operation?')) return;
      setActionLoading(opId);
      try {
        await callReducer('unregister_cognitive_op', ['', opId]);
        setSuccessMsg('Cognitive op deleted');
        if (selectedOp?.id === opId) {
          setSelectedOp(null);
        }
        loadOps();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete cognitive op');
      } finally {
        setActionLoading(null);
      }
    },
    [loadOps, selectedOp],
  );

  // -----------------------------------------------------------------------
  // Execute op
  // -----------------------------------------------------------------------

  const handleExecute = useCallback(async () => {
    clearMessages();
    if (!selectedOp) return;
    let inputParsed: Record<string, unknown>;
    try {
      inputParsed = JSON.parse(executeInput);
    } catch {
      setError('Input data is not valid JSON');
      return;
    }
    setExecuting(true);
    try {
      await callReducer('execute_cognitive_op', [
        selectedOp.workspace_id,
        selectedOp.id,
        JSON.stringify(inputParsed),
      ]);
      const res = await executeSql(
        "SELECT * FROM cognitive_op_result ORDER BY created_at DESC LIMIT 1"
      );
      const rows = parseSqlResponse<{ data: string }>(res);
      if (rows.length > 0 && rows[0].data) {
        try {
          const parsed = JSON.parse(rows[0].data);
          setExecResult(JSON.stringify(parsed, null, 2));
        } catch {
          setExecResult(rows[0].data);
        }
      } else {
        setExecResult('No result returned');
      }
      setSuccessMsg('Operation executed');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to execute op');
    } finally {
      setExecuting(false);
    }
  }, [selectedOp, executeInput]);

  const filteredOps = typeFilter
    ? ops.filter((o) => o.op_type === typeFilter)
    : ops;

  // -----------------------------------------------------------------------
  // Render: Detail view
  // -----------------------------------------------------------------------

  if (selectedOp) {
    const op = selectedOp;
    let configDisplay = op.config_json;
    try {
      configDisplay = JSON.stringify(JSON.parse(op.config_json), null, 2);
    } catch {
      // keep raw
    }

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
                <Cpu className="h-7 w-7 text-primary" />
                {op.name}
              </h1>
              <p className="text-sm text-muted-foreground">{op.description}</p>
            </div>
          </div>
          <Badge className={OP_TYPE_COLORS[op.op_type] ?? ''}>
            {op.op_type}
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
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Op Type</CardTitle>
            </CardHeader>
            <CardContent>
              <Badge className={OP_TYPE_COLORS[op.op_type] ?? ''}>
                {op.op_type}
              </Badge>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Pipeline Stage</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-mono text-sm">{op.pipeline_stage_type || '—'}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Created</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-muted-foreground">
                {formatMemoryTimestamp(op.created_at)}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Configuration */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="rounded-lg bg-muted p-3 text-xs overflow-x-auto whitespace-pre-wrap">
              {configDisplay}
            </pre>
          </CardContent>
        </Card>

        {/* Execute */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-lg flex items-center gap-2">
              <Play className="h-5 w-5" />
              Execute Operation
            </CardTitle>
            <CardDescription>
              Provide input data as JSON to execute this operation.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Input Data (JSON)
              </label>
              <textarea
                rows={6}
                value={executeInput}
                onChange={(e) => setExecuteInput(e.target.value)}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>
            <Button onClick={handleExecute} disabled={executing}>
              {executing ? 'Executing...' : 'Execute'}
            </Button>
            {execResult && (
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Result
                </label>
                <pre className="rounded-lg bg-muted p-3 text-xs overflow-x-auto whitespace-pre-wrap">
                  {execResult}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => handleDelete(op.id)}
            disabled={actionLoading === op.id}
            variant="destructive"
          >
            <Trash2 className="h-4 w-4 mr-1.5" />
            Unregister
          </Button>
          <Button variant="outline" onClick={loadOps}>
            <RefreshCw className="h-4 w-4 mr-1.5" />
            Refresh
          </Button>
        </div>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Render: List view
  // -----------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Cpu className="h-7 w-7 text-primary" />
            Cognitive Ops
          </h1>
          <p className="text-muted-foreground">
            {loading ? 'Loading...' : `${filteredOps.length} operation(s)`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={openCreateForm}>
            <Plus className="h-4 w-4 mr-1.5" />
            Register Op
          </Button>
          <Button variant="ghost" size="icon" onClick={loadOps}>
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

      {/* Filter */}
      <div className="flex items-center gap-3">
        <Filter className="h-4 w-4 text-muted-foreground" />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="flex h-10 w-44 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <option value="">All Types</option>
          {OP_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <Badge variant="secondary" className="gap-1">
          <ListChecks className="h-3 w-3" />
          {typeFilter || 'All'}
        </Badge>
      </div>

      {/* Create Form */}
      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Register Cognitive Operation</CardTitle>
            <CardDescription>
              Register a named cognitive operation that wraps a pipeline stage.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Name *
                </label>
                <input
                  placeholder="e.g. entity_extract, semantic_search"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Op Type *
                </label>
                <select
                  value={formOpType}
                  onChange={(e) => setFormOpType(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  {OP_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Description
              </label>
              <input
                placeholder="What this operation does"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Config JSON
                </label>
                <textarea
                  rows={4}
                  value={formConfigJson}
                  onChange={(e) => setFormConfigJson(e.target.value)}
                  className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Pipeline Stage Type
                </label>
                <input
                  placeholder="stage type identifier"
                  value={formPipelineStageType}
                  onChange={(e) => setFormPipelineStageType(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              <Button onClick={handleCreate} disabled={formSubmitting}>
                {formSubmitting ? 'Registering...' : 'Register'}
              </Button>
              <Button variant="outline" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Pipeline view */}
      {ops.length > 0 && !typeFilter && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Workflow className="h-5 w-5" />
              Pipeline Order
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-2">
              {PIPELINE_ORDER.map((stage, i) => {
                const stageOps = ops.filter((o) => o.op_type === stage);
                return (
                  <div key={stage} className="flex items-center gap-1">
                    <div
                      className={`rounded-lg border px-3 py-2 text-xs font-medium ${
                        OP_TYPE_COLORS[stage] ?? 'bg-muted text-muted-foreground'
                      } ${stageOps.length === 0 ? 'opacity-40' : ''}`}
                    >
                      <div className="font-semibold capitalize">{stage}</div>
                      <div className="text-[10px] opacity-70">
                        {stageOps.length} op(s)
                      </div>
                    </div>
                    {i < PIPELINE_ORDER.length - 1 && (
                      <Workflow className="h-4 w-4 text-muted-foreground rotate-90" />
                    )}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Ops list */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Registered Operations</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-lg border border-border p-4"
                >
                  <div className="space-y-2 flex-1">
                    <div className="h-5 w-32 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-48 rounded bg-muted animate-pulse" />
                  </div>
                  <div className="h-7 w-20 rounded-full bg-muted animate-pulse" />
                </div>
              ))}
            </div>
          ) : filteredOps.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Cpu className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">No cognitive operations registered</p>
              <p className="text-sm mt-1">
                {typeFilter
                  ? 'No ops match the selected type filter.'
                  : 'Register an operation to add pipeline capabilities.'}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredOps.map((op) => (
                <div
                  key={op.id}
                  className="flex items-center justify-between rounded-lg border border-border p-3 hover:bg-accent/30 cursor-pointer transition-colors"
                  onClick={() => selectOp(op)}
                >
                  <div className="min-w-0 flex-1 mr-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{op.name}</span>
                      <span className="text-xs text-muted-foreground">
                        ({op.id.slice(0, 8)}...)
                      </span>
                    </div>
                    {op.description && (
                      <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                        {op.description}
                      </p>
                    )}
                    <div className="flex items-center gap-2 mt-1 text-[11px] text-muted-foreground">
                      <span>Created {formatMemoryTimestamp(op.created_at)}</span>
                      {op.pipeline_stage_type && (
                        <>
                          <span>·</span>
                          <span>Stage: {op.pipeline_stage_type}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <Badge
                      variant="outline"
                      className={OP_TYPE_COLORS[op.op_type] ?? ''}
                    >
                      {op.op_type}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(op.id)}
                      disabled={actionLoading === op.id}
                      className="text-destructive hover:text-destructive"
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
