import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Brain,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Star,
  Clock,
  BarChart3,
  Layers,
  Sparkles,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
} from '@/lib/spacetimedb';

interface ReviewItem {
  id: string;
  workspace_id: string;
  memory_id: string;
  user_id: string;
  easiness_factor: number;
  interval_days: number;
  repetitions: number;
  next_review_at: string;
  last_reviewed_at: string;
  created_at: string;
  grade_sum: number;
  grade_count: number;
  is_active: boolean;
}

interface ReviewStats {
  total_due: number;
  total_items: number;
  average_ef: number;
  average_grade: number;
  total_reviews: number;
  mastered_count: number;
}

const GRADE_LABELS = [
  'Complete blackout',
  'Incorrect — but remembered upon seeing correct',
  'Incorrect — but the answer seemed easy to recall',
  'Correct — with serious difficulty',
  'Correct — after hesitation',
  'Correct — with perfect recall',
  'Perfect — faster than expected',
] as const;

const GRADE_COLORS = [
  'bg-red-600 hover:bg-red-700',
  'bg-red-400 hover:bg-red-500',
  'bg-orange-400 hover:bg-orange-500',
  'bg-yellow-400 hover:bg-yellow-500',
  'bg-lime-400 hover:bg-lime-500',
  'bg-green-400 hover:bg-green-500',
  'bg-emerald-600 hover:bg-emerald-700',
];

export default function ReviewPage() {
  const [dueItems, setDueItems] = useState<ReviewItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [showAnswer, setShowAnswer] = useState(false);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [done, setDone] = useState(false);
  const [scheduleMemoryId, setScheduleMemoryId] = useState('');

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  const loadReviews = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      await callReducer('get_due_reviews', ['', '']);
      const res = await executeSql(
        "SELECT * FROM review_result WHERE workspace_id = '' AND user_id = '' ORDER BY created_at DESC LIMIT 1"
      );
      const rows = parseSqlResponse<{ items_json: string; due_count: number }>(res);
      if (rows.length > 0 && rows[0].items_json) {
        try {
          const parsed = JSON.parse(rows[0].items_json) as ReviewItem[];
          setDueItems(parsed);
          setCurrentIndex(0);
          setShowAnswer(false);
          setDone(false);
        } catch {
          setDueItems([]);
        }
      } else {
        // Fallback: read from review_item table
        const fallback = await executeSql(
          "SELECT * FROM review_item WHERE is_active = true ORDER BY next_review_at ASC LIMIT 50"
        );
        setDueItems(parseSqlResponse<ReviewItem>(fallback));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load reviews');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadStats = useCallback(async () => {
    try {
      await callReducer('get_review_stats', ['', '']);
      const res = await executeSql(
        "SELECT * FROM review_result WHERE workspace_id = '' AND user_id = '' ORDER BY created_at DESC LIMIT 1"
      );
      const rows = parseSqlResponse<{ items_json: string }>(res);
      if (rows.length > 0 && rows[0].items_json) {
        try {
          setStats(JSON.parse(rows[0].items_json) as ReviewStats);
        } catch {
          // ignore
        }
      }
    } catch {
      // non-critical
    }
  }, []);

  useEffect(() => {
    loadReviews();
    loadStats();
  }, [loadReviews, loadStats]);

  const handleGrade = useCallback(
    async (grade: number) => {
      const item = dueItems[currentIndex];
      if (!item) return;
      clearMessages();
      setReviewing(true);
      try {
        await callReducer('perform_review', [item.id, grade]);
        setShowAnswer(false);
        if (currentIndex < dueItems.length - 1) {
          setCurrentIndex(currentIndex + 1);
        } else {
          setDone(true);
        }
        loadStats();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Review failed');
      } finally {
        setReviewing(false);
      }
    },
    [dueItems, currentIndex, loadStats]
  );

  const handleScheduleReview = useCallback(async () => {
    clearMessages();
    if (!scheduleMemoryId.trim()) {
      setError('Memory ID is required');
      return;
    }
    try {
      await callReducer('schedule_review', ['', scheduleMemoryId.trim(), '']);
      setSuccessMsg('Memory scheduled for review');
      setScheduleMemoryId('');
      loadReviews();
      loadStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to schedule review');
    }
  }, [scheduleMemoryId, loadReviews, loadStats]);

  const currentItem = dueItems[currentIndex];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Review</h1>
        <p className="text-muted-foreground">
          SM-2 spaced repetition review interface
        </p>
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

      {/* Stats Section */}
      <div className="grid gap-4 md:grid-cols-5">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Clock className="h-4 w-4 text-blue-500" />
              Due Now
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {stats?.total_due ?? dueItems.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Layers className="h-4 w-4 text-purple-500" />
              Total Items
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.total_items ?? '—'}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Star className="h-4 w-4 text-amber-500" />
              Avg EF
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {stats?.average_ef ? stats.average_ef.toFixed(2) : '—'}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-green-500" />
              Avg Grade
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {stats?.average_grade ? stats.average_grade.toFixed(1) : '—'}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-emerald-500" />
              Mastered
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {stats?.mastered_count ?? '—'}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Schedule Review Section */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Clock className="h-5 w-5" />
            Schedule Memory for Review
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Memory ID
              </label>
              <input
                placeholder="Enter memory ID to schedule"
                value={scheduleMemoryId}
                onChange={(e) => setScheduleMemoryId(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>
            <Button
              onClick={handleScheduleReview}
              disabled={!scheduleMemoryId.trim()}
            >
              Schedule
            </Button>
            <Button variant="outline" onClick={loadReviews}>
              <RefreshCw className="h-4 w-4 mr-1" />
              Refresh
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Review Card */}
      <Card className="min-h-[300px]">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Brain className="h-5 w-5 text-primary" />
            {loading ? 'Loading...' : done ? 'Review Complete' : 'Review'}
          </CardTitle>
          {!loading && !done && dueItems.length > 0 && (
            <CardDescription>
              Item {currentIndex + 1} of {dueItems.length}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-4">
              <div className="h-20 rounded-lg bg-muted animate-pulse" />
              <div className="flex justify-center gap-2">
                {Array.from({ length: 7 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-24 w-20 rounded-lg bg-muted animate-pulse"
                  />
                ))}
              </div>
            </div>
          ) : done ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <Check className="h-12 w-12 text-green-500 mb-4" />
              <h3 className="text-xl font-semibold mb-2">Review Complete!</h3>
              <p className="text-muted-foreground mb-6">
                You have reviewed all {dueItems.length} due items.
              </p>
              <Button onClick={loadReviews}>
                <RefreshCw className="h-4 w-4 mr-1.5" />
                Load More
              </Button>
            </div>
          ) : dueItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <Star className="h-12 w-12 text-muted-foreground/30 mb-4" />
              <h3 className="text-xl font-semibold mb-2">No Reviews Due</h3>
              <p className="text-muted-foreground mb-6">
                All caught up! Schedule a memory above to start reviewing.
              </p>
              <Button onClick={loadReviews}>
                <RefreshCw className="h-4 w-4 mr-1.5" />
                Check Again
              </Button>
            </div>
          ) : currentItem ? (
            <div className="space-y-6">
              {/* Memory content */}
              <div className="rounded-lg border border-border bg-card p-6">
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="secondary" className="text-xs">
                    EF: {currentItem.easiness_factor.toFixed(2)}
                  </Badge>
                  <Badge variant="outline" className="text-xs">
                    Interval: {currentItem.interval_days}d
                  </Badge>
                  <Badge variant="outline" className="text-xs">
                    Reps: {currentItem.repetitions}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground mb-1">
                  Memory ID: {currentItem.memory_id}
                </p>
                <p className="text-xs text-muted-foreground">
                  Last reviewed: {formatMemoryTimestamp(currentItem.last_reviewed_at)}
                </p>
              </div>

              {/* Grade buttons */}
              {!showAnswer ? (
                <div className="text-center">
                  <Button
                    size="lg"
                    onClick={() => setShowAnswer(true)}
                    className="px-8"
                  >
                    <Brain className="h-5 w-5 mr-2" />
                    Show Answer / Grade
                  </Button>
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm font-medium text-center">
                    How well did you recall this item?
                  </p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {GRADE_LABELS.map((label, grade) => (
                      <button
                        key={grade}
                        onClick={() => handleGrade(grade)}
                        disabled={reviewing}
                        className={`flex flex-col items-center justify-center rounded-lg px-3 py-2 text-white text-xs font-medium transition-all hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed ${GRADE_COLORS[grade]}`}
                      >
                        <span className="text-lg font-bold">{grade}</span>
                        <span className="mt-1 text-[10px] leading-tight text-center max-w-[80px]">
                          {label.split(' — ').pop()}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
