import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Play,
  Plus,
  Trash2,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  List,
  GitBranch,
  Activity,
  Layers,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
} from '@/lib/spacetimedb';

const PIPELINE_STAGES = [
  'Search',
  'Filter',
  'Extract',
  'Transform',
  'Store',
  'Classify',
  'Rank',
] as const;

type PipelineStage = (typeof PIPELINE_STAGES)[number];

interface PipelineContent {
  name: string;
  stages: PipelineStage[];
  status: 'idle' | 'running' | 'completed' | 'failed';
}

interface PipelineRow {
  id: string;
  workspace_id: string;
  content: string;
  summary: string;
  memory_type: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface ExecutionRow {
  id: string;
  pipeline_id: string;
  workspace_id: string;
  status: string;
  stages_completed: string;
  stages_total: number;
  started_at: string;
  completed_at: string;
  error_message: string;
  content: string;
  created_at: string;
}

function parsePipelineContent(content: string): PipelineContent {
  try {
    const parsed = JSON.parse(content);
    return {
      name: parsed.name || 'Unnamed Pipeline',
      stages: Array.isArray(parsed.stages) ? parsed.stages : [],
      status: parsed.status || 'idle',
    };
  } catch {
    return { name: 'Unnamed Pipeline', stages: [], status: 'idle' };
  }
}

function buildPipelineContent(
  name: string,
  stages: PipelineStage[],
  status: string = 'idle',
): string {
  return JSON.stringify({ name, stages, status });
}

const stageColors: Record<string, string> = {
  Search: 'bg-blue-500/10 text-blue-600 border-blue-200',
  Filter: 'bg-cyan-500/10 text-cyan-600 border-cyan-200',
  Extract: 'bg-violet-500/10 text-violet-600 border-violet-200',
  Transform: 'bg-amber-500/10 text-amber-600 border-amber-200',
  Store: 'bg-green-500/10 text-green-600 border-green-200',
  Classify: 'bg-purple-500/10 text-purple-600 border-purple-200',
  Rank: 'bg-rose-500/10 text-rose-600 border-rose-200',
};

const statusBadgeVariant: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  idle: 'secondary',
  running: 'default',
  completed: 'default',
  failed: 'destructive',
};

export default function PipelinePage() {
  const [pipelines, setPipelines] = useState<PipelineRow[]>([]);
  const [executions, setExecutions] = useState<ExecutionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('pipelines');

  // Create form state
  const [showForm, setShowForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newStages, setNewStages] = useState<PipelineStage[]>([]);

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  const loadPipelines = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      const res = await executeSql(
        "SELECT * FROM memory WHERE memory_type = 'pipeline' AND is_active = true ORDER BY created_at ASC",
      );
      const rows = parseSqlResponse<PipelineRow>(res);
      setPipelines(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load pipelines');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadExecutions = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      const res = await executeSql(
        "SELECT * FROM memory WHERE memory_type = 'pipeline_execution' ORDER BY created_at DESC LIMIT 100",
      );
      const rows = parseSqlResponse<ExecutionRow>(res);
      setExecutions(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load execution history');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'pipelines') {
      loadPipelines();
    } else {
      loadExecutions();
    }
  }, [activeTab, loadPipelines, loadExecutions]);

  const toggleStage = (stage: PipelineStage) => {
    setNewStages((prev) =>
      prev.includes(stage)
        ? prev.filter((s) => s !== stage)
        : [...prev, stage],
    );
  };

  const handleCreate = useCallback(async () => {
    clearMessages();
    if (!newName.trim()) {
      setError('Pipeline name is required');
      return;
    }
    if (newStages.length === 0) {
      setError('At least one stage is required');
      return;
    }
    try {
      const content = buildPipelineContent(newName.trim(), newStages);
      await callReducer('store_memory', [
        '',
        content,
        'pipeline',
        'standard',
        0.5,
      ]);
      setSuccessMsg('Pipeline created');
      setShowForm(false);
      setNewName('');
      setNewStages([]);
      loadPipelines();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create pipeline');
    }
  }, [newName, newStages, loadPipelines]);

  const handleExecute = useCallback(
    async (pipelineId: string) => {
      clearMessages();
      try {
        await callReducer('store_memory', [
          '',
          JSON.stringify({
            pipeline_id: pipelineId,
            status: 'running',
            started_at: new Date().toISOString(),
          }),
          'pipeline_execution',
          'standard',
          0.5,
        ]);
        setSuccessMsg('Pipeline execution started');
        loadPipelines();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to execute pipeline');
      }
    },
    [loadPipelines],
  );

  const handleDelete = useCallback(
    async (pipelineId: string) => {
      clearMessages();
      try {
        await callReducer('deactivate_memory', [pipelineId]);
        setSuccessMsg('Pipeline deleted');
        loadPipelines();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete pipeline');
      }
    },
    [loadPipelines],
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Pipelines</h1>
          <p className="text-muted-foreground">
            Define and manage data processing pipelines with ordered stages.
          </p>
        </div>
        <Button
          onClick={activeTab === 'pipelines' ? loadPipelines : loadExecutions}
          variant="ghost"
          size="icon"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
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

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="pipelines">
            <GitBranch className="h-4 w-4 mr-1.5" />
            Pipelines
          </TabsTrigger>
          <TabsTrigger value="executions">
            <Activity className="h-4 w-4 mr-1.5" />
            Execution History
          </TabsTrigger>
        </TabsList>

        <TabsContent value="pipelines">
          {!showForm && (
            <Button onClick={() => setShowForm(true)}>
              <Plus className="h-4 w-4 mr-1.5" />
              Create Pipeline
            </Button>
          )}

          {showForm && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">New Pipeline</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="text-xs font-medium mb-1 block text-muted-foreground">
                    Pipeline Name *
                  </label>
                  <Input
                    placeholder="My Pipeline"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </div>

                <div>
                  <label className="text-xs font-medium mb-2 block text-muted-foreground">
                    Stages (select in order) *
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {PIPELINE_STAGES.map((stage) => {
                      const selected = newStages.includes(stage);
                      return (
                        <button
                          key={stage}
                          type="button"
                          onClick={() => toggleStage(stage)}
                          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                            selected
                              ? stageColors[stage] || 'bg-primary/10 text-primary border-primary'
                              : 'bg-muted text-muted-foreground border-border hover:border-foreground/30'
                          }`}
                        >
                          {selected && <Check className="h-3 w-3" />}
                          {stage}
                        </button>
                      );
                    })}
                  </div>
                  {newStages.length > 0 && (
                    <p className="text-xs text-muted-foreground mt-2">
                      Stage order: {newStages.join(' → ')}
                    </p>
                  )}
                </div>

                <div className="flex gap-2 pt-2">
                  <Button onClick={handleCreate}>Create</Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowForm(false);
                      setNewName('');
                      setNewStages([]);
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="mt-4 space-y-3">
            {loading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-lg border border-border p-3"
                  >
                    <div className="space-y-1 flex-1">
                      <div className="h-4 w-48 rounded bg-muted animate-pulse" />
                      <div className="h-3 w-64 rounded bg-muted animate-pulse" />
                    </div>
                    <div className="h-6 w-16 rounded-full bg-muted animate-pulse" />
                  </div>
                ))}
              </div>
            ) : pipelines.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <GitBranch className="h-10 w-10 mb-3 opacity-30" />
                <p className="font-medium">No pipelines defined</p>
                <p className="text-sm mt-1">
                  Create a pipeline to process data through a sequence of stages.
                </p>
              </div>
            ) : (
              pipelines.map((pl) => {
                const pContent = parsePipelineContent(pl.content);
                return (
                  <div
                    key={pl.id}
                    className="rounded-lg border border-border p-4"
                  >
                    <div className="flex items-start justify-between">
                      <div className="min-w-0 flex-1 mr-3">
                        <div className="flex items-center gap-2">
                          <h3 className="font-medium text-sm">
                            {pContent.name}
                          </h3>
                          <Badge
                            variant={
                              statusBadgeVariant[pContent.status] || 'secondary'
                            }
                            className="text-xs"
                          >
                            {pContent.status}
                          </Badge>
                          <Badge
                            variant="outline"
                            className="text-xs gap-1"
                          >
                            <Layers className="h-3 w-3" />
                            {pContent.stages.length} stage
                            {pContent.stages.length !== 1 ? 's' : ''}
                          </Badge>
                        </div>

                        {pContent.stages.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5 mt-2">
                            {pContent.stages.map((stage, idx) => (
                              <Badge
                                key={stage}
                                variant="outline"
                                className={`text-xs border ${
                                  stageColors[stage] || ''
                                }`}
                              >
                                {idx > 0 && (
                                  <span className="mr-1 text-muted-foreground">
                                    →
                                  </span>
                                )}
                                {stage}
                              </Badge>
                            ))}
                          </div>
                        )}

                        <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
                          <span>
                            Created {formatMemoryTimestamp(pl.created_at)}
                          </span>
                          {pl.updated_at && pl.updated_at !== pl.created_at && (
                            <>
                              <span>·</span>
                              <span>
                                Updated {formatMemoryTimestamp(pl.updated_at)}
                              </span>
                            </>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-green-600 hover:text-green-700"
                          onClick={() => handleExecute(pl.id)}
                          title="Execute pipeline"
                        >
                          <Play className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-destructive hover:text-destructive"
                          onClick={() => handleDelete(pl.id)}
                          title="Delete pipeline"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </TabsContent>

        <TabsContent value="executions">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Pipeline Execution History</CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div
                      key={i}
                      className="h-12 rounded-lg bg-muted animate-pulse"
                    />
                  ))}
                </div>
              ) : executions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <List className="h-10 w-10 mb-3 opacity-30" />
                  <p className="font-medium">No executions yet</p>
                  <p className="text-sm mt-1">
                    Pipeline execution records will appear here when pipelines
                    are run.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {executions.map((ex) => {
                    let exStatus = 'unknown';
                    let exPipelineId = '';
                    try {
                      const parsed = JSON.parse(ex.content || '{}');
                      exStatus = parsed.status || 'unknown';
                      exPipelineId = parsed.pipeline_id || '';
                    } catch {
                      // fallback
                    }
                    return (
                      <div
                        key={ex.id}
                        className="flex items-start justify-between rounded-lg border border-border p-3"
                      >
                        <div className="min-w-0 flex-1 mr-3">
                          <div className="flex items-center gap-2">
                            <Badge
                              variant={
                                exStatus === 'completed'
                                  ? 'default'
                                  : exStatus === 'running'
                                    ? 'default'
                                    : exStatus === 'failed'
                                      ? 'destructive'
                                      : 'secondary'
                              }
                              className="text-xs"
                            >
                              {exStatus}
                            </Badge>
                            <span className="text-xs font-medium">
                              Pipeline: {exPipelineId.slice(0, 12)}…
                            </span>
                          </div>
                          <p className="text-xs text-muted-foreground mt-1">
                            Execution record
                          </p>
                        </div>
                        <span className="text-xs text-muted-foreground shrink-0">
                          {formatMemoryTimestamp(ex.created_at)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
