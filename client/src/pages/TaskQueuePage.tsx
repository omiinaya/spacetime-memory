import { useState, useCallback, useEffect, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  List,
  RefreshCw,
  AlertCircle,
  Check,
  X,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  User,
  AlertTriangle,
  Layers,
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

interface TaskContent {
  type: string;
  status: 'pending' | 'claimed' | 'completed' | 'failed';
  priority: number;
  worker_id: string;
  attempts: number;
  max_retries: number;
  error_message: string;
  task_type: string;
  payload: string;
  result: string;
}

interface TaskRow {
  id: string;
  workspace_id: string;
  memory_type: string;
  content: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  peer_id: string;
  // Parsed content helpers
  _parsed?: TaskContent;
}

interface QueueStats {
  total: number;
  pending: number;
  claimed: number;
  completed: number;
  failed: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseTaskContent(row: TaskRow): TaskRow {
  if (row._parsed) return row;
  try {
    const parsed = JSON.parse(row.content) as TaskContent;
    return { ...row, _parsed: parsed };
  } catch {
    return { ...row, _parsed: { type: '', status: 'pending', priority: 0, worker_id: '', attempts: 0, max_retries: 3, error_message: '', task_type: '', payload: '', result: '' } };
  }
}

const statusBadgeVariant = (status: string): 'default' | 'secondary' | 'destructive' | 'outline' => {
  switch (status) {
    case 'pending':
      return 'secondary';
    case 'claimed':
      return 'default';
    case 'completed':
      return 'outline';
    case 'failed':
      return 'destructive';
    default:
      return 'secondary';
  }
};

const priorityBadgeVariant = (priority: number): 'default' | 'secondary' | 'destructive' | 'outline' => {
  if (priority >= 5) return 'destructive';
  if (priority >= 3) return 'default';
  return 'secondary';
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TaskQueuePage() {
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters
  const [activeTab, setActiveTab] = useState('all');
  const [searchType, setSearchType] = useState('');

  // -----------------------------------------------------------------------
  // Data loading
  // -----------------------------------------------------------------------

  const clearMessages = useCallback(() => {
    setError(null);
    setSuccessMsg(null);
  }, []);

  const loadTasks = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      const res = await executeSql(
        "SELECT * FROM memory WHERE memory_type = 'task_queue' AND is_active = true ORDER BY created_at ASC LIMIT 200"
      );
      const rows = parseSqlResponse<TaskRow>(res);
      setTasks(rows.map(parseTaskContent));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load task queue');
    } finally {
      setLoading(false);
    }
  }, [clearMessages]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  // -----------------------------------------------------------------------
  // Computed stats
  // -----------------------------------------------------------------------

  const stats: QueueStats = useMemo(() => {
    const s: QueueStats = { total: 0, pending: 0, claimed: 0, completed: 0, failed: 0 };
    s.total = tasks.length;
    for (const t of tasks) {
      switch (t._parsed?.status) {
        case 'pending':
          s.pending++;
          break;
        case 'claimed':
          s.claimed++;
          break;
        case 'completed':
          s.completed++;
          break;
        case 'failed':
          s.failed++;
          break;
      }
    }
    return s;
  }, [tasks]);

  // -----------------------------------------------------------------------
  // Filtered tasks
  // -----------------------------------------------------------------------

  const filteredTasks = useMemo(() => {
    return tasks.filter((t) => {
      const status = t._parsed?.status ?? 'pending';
      if (activeTab !== 'all' && status !== activeTab) return false;
      if (searchType.trim()) {
        const typeMatch =
          (t._parsed?.type ?? '').toLowerCase().includes(searchType.toLowerCase()) ||
          (t._parsed?.task_type ?? '').toLowerCase().includes(searchType.toLowerCase());
        if (!typeMatch) return false;
      }
      return true;
    });
  }, [tasks, activeTab, searchType]);

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  const handleClaim = useCallback(
    async (taskId: string) => {
      clearMessages();
      try {
        await callReducer('claim_task', [taskId]);
        setSuccessMsg('Task claimed');
        loadTasks();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to claim task');
      }
    },
    [clearMessages, loadTasks]
  );

  const handleComplete = useCallback(
    async (taskId: string) => {
      clearMessages();
      try {
        await callReducer('complete_task', [taskId, '']);
        setSuccessMsg('Task completed');
        loadTasks();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to complete task');
      }
    },
    [clearMessages, loadTasks]
  );

  const handleFail = useCallback(
    async (taskId: string) => {
      clearMessages();
      try {
        await callReducer('fail_task', [taskId, 'Manually failed from UI']);
        setSuccessMsg('Task failed');
        loadTasks();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fail task');
      }
    },
    [clearMessages, loadTasks]
  );

  const handleRetry = useCallback(
    async (taskId: string) => {
      clearMessages();
      try {
        await callReducer('retry_task', [taskId]);
        setSuccessMsg('Task queued for retry');
        loadTasks();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to retry task');
      }
    },
    [clearMessages, loadTasks]
  );

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Task Queue</h1>
          <p className="text-muted-foreground">
            Monitor and manage background task processing.
          </p>
        </div>
        <Button onClick={loadTasks} variant="ghost" size="icon">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-destructive text-sm">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Success */}
      {successMsg && (
        <div className="flex items-center gap-3 rounded-lg border border-green-500/50 bg-green-500/10 p-3 text-green-600 text-sm">
          <Check className="h-5 w-5 shrink-0" />
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg(null)} className="ml-auto">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Queue Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Total
            </CardTitle>
            <Layers className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.total}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Pending
            </CardTitle>
            <Clock className="h-4 w-4 text-yellow-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-yellow-500">{stats.pending}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Claimed
            </CardTitle>
            <Play className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-500">{stats.claimed}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Completed
            </CardTitle>
            <CheckCircle2 className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-500">{stats.completed}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Failed
            </CardTitle>
            <XCircle className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-500">{stats.failed}</div>
          </CardContent>
        </Card>
      </div>

      {/* Filter + Search */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="all">
              <List className="h-4 w-4 mr-1.5" />
              All
            </TabsTrigger>
            <TabsTrigger value="pending">
              <Clock className="h-4 w-4 mr-1.5" />
              Pending
            </TabsTrigger>
            <TabsTrigger value="claimed">
              <Play className="h-4 w-4 mr-1.5" />
              Claimed
            </TabsTrigger>
            <TabsTrigger value="completed">
              <CheckCircle2 className="h-4 w-4 mr-1.5" />
              Completed
            </TabsTrigger>
            <TabsTrigger value="failed">
              <XCircle className="h-4 w-4 mr-1.5" />
              Failed
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <Input
            placeholder="Filter by task type..."
            value={searchType}
            onChange={(e) => setSearchType(e.target.value)}
            className="h-9 w-full sm:w-56"
          />
          <Button variant="outline" size="sm" onClick={() => setSearchType('')}>
            Clear
          </Button>
        </div>
      </div>

      {/* Task List */}
      <div className="space-y-3">
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
                <div className="flex gap-2">
                  <div className="h-6 w-16 rounded-full bg-muted animate-pulse" />
                  <div className="h-6 w-16 rounded-full bg-muted animate-pulse" />
                </div>
              </div>
            ))}
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <List className="h-10 w-10 mb-3 opacity-30" />
            <p className="font-medium">No tasks found</p>
            <p className="text-sm mt-1">
              {searchType || activeTab !== 'all'
                ? 'Try changing your filter or search criteria.'
                : 'The task queue is empty. No pending tasks to process.'}
            </p>
          </div>
        ) : (
          filteredTasks.map((task) => {
            const c = task._parsed!;
            return (
              <div
                key={task.id}
                className="rounded-lg border border-border p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1 mr-3">
                    {/* Title row */}
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-medium text-sm">
                        {c.task_type || c.type || 'Task'}
                      </h3>
                      <Badge
                        variant={statusBadgeVariant(c.status)}
                        className="text-xs capitalize"
                      >
                        {c.status}
                      </Badge>
                      <Badge
                        variant={priorityBadgeVariant(c.priority)}
                        className="text-xs"
                      >
                        <AlertTriangle className="h-3 w-3 mr-1" />
                        P{c.priority}
                      </Badge>
                    </div>

                    {/* Details row */}
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-xs text-muted-foreground">
                      <span className="font-mono">
                        ID: {task.id.slice(0, 12)}…
                      </span>
                      {c.worker_id && (
                        <span className="flex items-center gap-1">
                          <User className="h-3 w-3" />
                          {c.worker_id.slice(0, 12)}…
                        </span>
                      )}
                      <span>
                        Attempts: {c.attempts}/{c.max_retries}
                      </span>
                      {c.error_message && (
                        <span className="flex items-center gap-1 text-destructive">
                          <AlertCircle className="h-3 w-3" />
                          {c.error_message.slice(0, 60)}
                          {c.error_message.length > 60 && '…'}
                        </span>
                      )}
                    </div>

                    {/* Timestamp row */}
                    <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                      <span>
                        Created {formatMemoryTimestamp(task.created_at)}
                      </span>
                      {task.updated_at && (
                        <>
                          <span>·</span>
                          <span>
                            Updated {formatMemoryTimestamp(task.updated_at)}
                          </span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Action buttons */}
                  <div className="flex items-center gap-1 shrink-0">
                    {c.status === 'pending' && (
                      <Button
                        variant="default"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => handleClaim(task.id)}
                      >
                        <Play className="h-3.5 w-3.5 mr-1" />
                        Claim
                      </Button>
                    )}
                    {c.status === 'claimed' && (
                      <>
                        <Button
                          variant="default"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => handleComplete(task.id)}
                        >
                          <Check className="h-3.5 w-3.5 mr-1" />
                          Complete
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => handleFail(task.id)}
                        >
                          <X className="h-3.5 w-3.5 mr-1" />
                          Fail
                        </Button>
                      </>
                    )}
                    {c.status === 'failed' && c.attempts < c.max_retries && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => handleRetry(task.id)}
                      >
                        <RefreshCw className="h-3.5 w-3.5 mr-1" />
                        Retry
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
