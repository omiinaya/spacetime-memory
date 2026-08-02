import { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable } from '@/lib/useReactiveDb';
import { callReducer, formatMemoryTimestamp } from '@/lib/spacetimedb';
import {
  ShieldCheck,
  AlertTriangle,
  ThumbsUp,
  ThumbsDown,
  Search,
  Filter,
  RefreshCw,
  Trash2,
  TrendingUp,
  Clock,
  Database,
  BarChart3,
  Activity,
  AlertCircle,
  Flame,
  Layers,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types (snake_case from SpacetimeDB)
// ---------------------------------------------------------------------------
interface MemoryRow {
  id: string;
  workspace_id: string;
  content: string;
  summary: string;
  memory_type: string;
  tier: string;
  confidence: number;
  trust_score: number;
  feedback_count: number;
  access_count: number;
  strength: number;
  is_active: boolean;
  created_at: number;
  updated_at: number;
}

interface MemoryFeedbackRow {
  id: string;
  memory_id: string;
  rating: string;
  peer_id: string;
  created_at: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const TRUST_THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000 * 1000; // microseconds

function isDecayReady(updatedAt: number): boolean {
  const now = Date.now() * 1000; // convert to microseconds
  return now - updatedAt > TRUST_THIRTY_DAYS_MS;
}

const tierColors: Record<string, string> = {
  L0: 'bg-red-500/10 text-red-600 border-red-500/30',
  L1: 'bg-blue-500/10 text-blue-600 border-blue-500/30',
  L2: 'bg-gray-500/10 text-gray-500 border-gray-500/30',
};

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------
function StatCard({
  title,
  value,
  icon: Icon,
  loading,
  color,
  subtitle,
}: {
  title: string;
  value: string;
  icon: React.ElementType;
  loading: boolean;
  color: string;
  subtitle?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className={`h-4 w-4 ${color}`} />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-20" />
        ) : (
          <>
            <div className="text-2xl font-bold">{value}</div>
            {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function TrustDashboard() {
  const {
    data: memories,
    loading,
    error,
  } = useTable<MemoryRow>('memory');
  const { data: feedbacks } = useTable<MemoryFeedbackRow>('memory_feedback');

  // Filters
  const [search, setSearch] = useState('');
  const [tierFilter, setTierFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<string>('trust_score');

  // Compute aggregates
  const activeMemories = useMemo(
    () => memories.filter((m) => m.is_active),
    [memories],
  );

  const filtered = useMemo(() => {
    let list = activeMemories;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (m) =>
          m.content.toLowerCase().includes(q) ||
          m.summary.toLowerCase().includes(q) ||
          m.memory_type.toLowerCase().includes(q),
      );
    }
    if (tierFilter !== 'all') {
      list = list.filter((m) => m.tier === tierFilter);
    }
    list = [...list].sort((a, b) => {
      switch (sortBy) {
        case 'trust_score':
          return b.trust_score - a.trust_score;
        case 'confidence':
          return b.confidence - a.confidence;
        case 'updated_at':
          return (b.updated_at ?? 0) - (a.updated_at ?? 0);
        default:
          return 0;
      }
    });
    return list;
  }, [activeMemories, search, tierFilter, sortBy]);

  const lowTrustMemories = useMemo(
    () => activeMemories.filter((m) => m.trust_score < 0.5),
    [activeMemories],
  );

  const decayReadyMemories = useMemo(
    () => activeMemories.filter((m) => isDecayReady(m.updated_at)),
    [activeMemories],
  );

  const avgTrust = useMemo(() => {
    if (activeMemories.length === 0) return 0;
    return activeMemories.reduce((s, m) => s + m.trust_score, 0) / activeMemories.length;
  }, [activeMemories]);

  const avgConfidence = useMemo(() => {
    if (activeMemories.length === 0) return 0;
    return activeMemories.reduce((s, m) => s + m.confidence, 0) / activeMemories.length;
  }, [activeMemories]);

  const avgStrength = useMemo(() => {
    if (activeMemories.length === 0) return 0;
    return activeMemories.reduce((s, m) => s + m.strength, 0) / activeMemories.length;
  }, [activeMemories]);

  const totalFeedback = useMemo(
    () => activeMemories.reduce((s, m) => s + m.feedback_count, 0),
    [activeMemories],
  );

  // Trust distribution
  const trustDist = useMemo(() => {
    const low = activeMemories.filter((m) => m.trust_score < 0.4).length;
    const medium = activeMemories.filter((m) => m.trust_score >= 0.4 && m.trust_score < 0.7).length;
    const high = activeMemories.filter((m) => m.trust_score >= 0.7).length;
    return { low, medium, high };
  }, [activeMemories]);

  // Stats by tier
  const statsByTier = useMemo(() => {
    const tiers = ['L0', 'L1', 'L2'];
    return tiers.map((tier) => {
      const subset = activeMemories.filter((m) => m.tier === tier);
      const avg = subset.length > 0 ? subset.reduce((s, m) => s + m.trust_score, 0) / subset.length : 0;
      return { tier, count: subset.length, avgTrust: avg };
    });
  }, [activeMemories]);

  // Recent feedback: sort by created_at desc, take 20
  const recentFeedbacks = useMemo(
    () =>
      [...feedbacks]
        .sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))
        .slice(0, 20),
    [feedbacks],
  );

  // Build a lookup for feedback → memory content
  const memoryById = useMemo(() => {
    const map = new Map<string, MemoryRow>();
    for (const m of activeMemories) map.set(m.id, m);
    return map;
  }, [activeMemories]);

  // Actions
  const handleReinforce = async (memoryId: string) => {
    try {
      await callReducer('reinforce_memory', [memoryId]);
    } catch (e: any) {
      console.error('Reinforce failed', e);
    }
  };

  const handleDelete = async (memoryId: string) => {
    try {
      await callReducer('deactivate_memory', [memoryId]);
    } catch (e: any) {
      console.error('Deactivate failed', e);
    }
  };

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <ShieldCheck className="h-7 w-7 text-primary" />
            Trust Dashboard
          </h1>
          <p className="text-muted-foreground">
            {loading
              ? 'Loading...'
              : `Holographic reputation and trust score overview — ${activeMemories.length} active memories`}
          </p>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <Card className="border-red-500/30">
          <CardContent className="flex items-center gap-3 py-6">
            <AlertCircle className="h-5 w-5 text-destructive shrink-0" />
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Loading state */}
      {loading && !error && (
        <div className="space-y-6">
          {/* Skeleton stat cards */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Card key={i}>
                <CardHeader className="pb-2">
                  <Skeleton className="h-4 w-24" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-8 w-16" />
                </CardContent>
              </Card>
            ))}
          </div>
          {/* Skeleton sections */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <CardHeader><Skeleton className="h-5 w-40" /></CardHeader>
              <CardContent className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full rounded-lg" />
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><Skeleton className="h-5 w-40" /></CardHeader>
              <CardContent className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full rounded-lg" />
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && activeMemories.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <ShieldCheck className="h-12 w-12 mb-3 opacity-30" />
            <p className="font-medium text-lg">No memories yet</p>
            <p className="text-sm mt-1">
              Create memories via the CLI or MCP tools to see trust metrics here.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Main content — only when data exists */}
      {!loading && !error && activeMemories.length > 0 && (
        <>
          {/* 1. Overview stat cards */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
            <StatCard
              title="Total Active Memories"
              value={activeMemories.length.toLocaleString()}
              icon={Database}
              loading={false}
              color="text-blue-500"
            />
            <StatCard
              title="Avg Trust Score"
              value={avgTrust.toFixed(2)}
              icon={ShieldCheck}
              loading={false}
              color="text-green-500"
              subtitle={`${trustDist.high} high · ${trustDist.medium} medium · ${trustDist.low} low`}
            />
            <StatCard
              title="Avg Confidence"
              value={(avgConfidence * 100).toFixed(0) + '%'}
              icon={BarChart3}
              loading={false}
              color="text-purple-500"
            />
            <StatCard
              title="Total Feedback"
              value={totalFeedback.toLocaleString()}
              icon={Activity}
              loading={false}
              color="text-orange-500"
              subtitle={`${feedbacks.length} entries`}
            />
            <StatCard
              title="Avg Strength"
              value={avgStrength.toFixed(2)}
              icon={TrendingUp}
              loading={false}
              color="text-cyan-500"
            />
          </div>

          {/* 2. Trust distribution + Stats by tier */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Trust score distribution */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-muted-foreground" />
                  Trust Score Distribution
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-3 gap-3">
                  <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-center">
                    <div className="text-2xl font-bold text-red-500">{trustDist.low}</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      Low (0–0.4)
                    </div>
                    <div className="text-[10px] text-red-400/70 mt-0.5">Needs attention</div>
                  </div>
                  <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-4 text-center">
                    <div className="text-2xl font-bold text-yellow-500">{trustDist.medium}</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      Medium (0.4–0.7)
                    </div>
                    <div className="text-[10px] text-yellow-400/70 mt-0.5">Stable</div>
                  </div>
                  <div className="rounded-lg border border-green-500/30 bg-green-500/5 p-4 text-center">
                    <div className="text-2xl font-bold text-green-500">{trustDist.high}</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      High (0.7–1.0)
                    </div>
                    <div className="text-[10px] text-green-400/70 mt-0.5">Highly trusted</div>
                  </div>
                </div>
                {/* Distribution bar */}
                <div className="mt-4 flex h-3 w-full overflow-hidden rounded-full bg-muted">
                  {activeMemories.length > 0 && (
                    <>
                      <div
                        className="bg-red-500/70 transition-all"
                        style={{ width: `${(trustDist.low / activeMemories.length) * 100}%` }}
                      />
                      <div
                        className="bg-yellow-500/70 transition-all"
                        style={{ width: `${(trustDist.medium / activeMemories.length) * 100}%` }}
                      />
                      <div
                        className="bg-green-500/70 transition-all"
                        style={{ width: `${(trustDist.high / activeMemories.length) * 100}%` }}
                      />
                    </>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Stats by tier */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Layers className="h-4 w-4 text-muted-foreground" />
                  Trust by Tier
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {statsByTier.map(({ tier, count, avgTrust }) => (
                    <div
                      key={tier}
                      className="flex items-center justify-between rounded-lg border border-border p-3"
                    >
                      <div className="flex items-center gap-3">
                        <Badge variant="outline" className={tierColors[tier] ?? ''}>
                          {tier}
                        </Badge>
                        <span className="text-sm text-muted-foreground">
                          {count} memory{count !== 1 ? 'ies' : 'y'}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex h-2 w-24 overflow-hidden rounded-full bg-muted">
                          <div
                            className="rounded-full transition-all"
                            style={{
                              width: `${Math.min(avgTrust * 100, 100)}%`,
                              backgroundColor:
                                avgTrust < 0.4
                                  ? 'rgb(239 68 68)'
                                  : avgTrust < 0.7
                                    ? 'rgb(234 179 8)'
                                    : 'rgb(34 197 94)',
                            }}
                          />
                        </div>
                        <span className="text-sm font-mono text-muted-foreground w-10 text-right">
                          {avgTrust.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 3. Feedback activity + decay-ready */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Feedback activity */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-lg flex items-center gap-2">
                  <Activity className="h-4 w-4 text-muted-foreground" />
                  Feedback Activity
                </CardTitle>
                <Badge variant="secondary">{recentFeedbacks.length} recent</Badge>
              </CardHeader>
              <CardContent>
                {recentFeedbacks.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                    <ThumbsUp className="h-8 w-8 mb-2 opacity-30" />
                    <p className="text-sm">No feedback yet</p>
                    <p className="text-xs">Rate memories to build reputation data.</p>
                  </div>
                ) : (
                  <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                    {recentFeedbacks.map((fb) => {
                      const mem = memoryById.get(fb.memory_id);
                      const isHelpful = fb.rating === 'helpful';
                      return (
                        <div
                          key={fb.id}
                          className="flex items-start gap-3 rounded-lg border border-border p-2.5 text-sm"
                        >
                          <div className="shrink-0 mt-0.5">
                            {isHelpful ? (
                              <ThumbsUp className="h-4 w-4 text-green-500" />
                            ) : (
                              <ThumbsDown className="h-4 w-4 text-red-500" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-medium">
                              {mem
                                ? mem.summary || mem.content.slice(0, 80)
                                : '(deleted memory)'}
                            </p>
                            <div className="flex items-center gap-2 mt-0.5">
                              <Badge
                                variant="outline"
                                className={`text-[10px] ${
                                  isHelpful
                                    ? 'border-green-500/30 text-green-600'
                                    : 'border-red-500/30 text-red-600'
                                }`}
                              >
                                {fb.rating}
                              </Badge>
                              <span className="text-[10px] text-muted-foreground">
                                {formatMemoryTimestamp(fb.created_at)}
                              </span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Decay-ready display */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-lg flex items-center gap-2">
                  <Flame className="h-4 w-4 text-orange-500" />
                  Decay-Ready Memories
                </CardTitle>
                <Badge variant="outline" className="text-orange-500 border-orange-500/30">
                  {decayReadyMemories.length} affected
                </Badge>
              </CardHeader>
              <CardContent>
                {decayReadyMemories.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                    <Clock className="h-8 w-8 mb-2 opacity-30" />
                    <p className="text-sm">All memories are up-to-date</p>
                    <p className="text-xs">No memories have been idle for 30+ days.</p>
                  </div>
                ) : (
                  <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                    {decayReadyMemories.slice(0, 15).map((mem) => (
                      <div
                        key={mem.id}
                        className="flex items-start gap-3 rounded-lg border border-orange-500/20 bg-orange-500/5 p-2.5"
                      >
                        <Flame className="h-4 w-4 text-orange-500 shrink-0 mt-0.5" />
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-medium truncate">
                            {mem.summary || mem.content.slice(0, 80)}
                          </p>
                          <div className="flex items-center gap-2 mt-0.5 text-[10px] text-muted-foreground">
                            <span>Trust: {mem.trust_score.toFixed(2)}</span>
                            <span>·</span>
                            <span>Updated {formatMemoryTimestamp(mem.updated_at)}</span>
                            <Badge variant="outline" className={tierColors[mem.tier] ?? ''}>
                              {mem.tier}
                            </Badge>
                          </div>
                        </div>
                      </div>
                    ))}
                    {decayReadyMemories.length > 15 && (
                      <p className="text-xs text-center text-muted-foreground pt-1">
                        +{decayReadyMemories.length - 15} more
                      </p>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* 4. Low-trust memories table */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-lg flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-red-500" />
                  Low-Trust Memories (score &lt; 0.5)
                </CardTitle>
                <CardDescription>
                  These memories may need reinforcement or cleanup.
                </CardDescription>
              </div>
              <Badge variant="destructive">{lowTrustMemories.length} low-trust</Badge>
            </CardHeader>
            <CardContent>
              {lowTrustMemories.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                  <ShieldCheck className="h-8 w-8 mb-2 opacity-30" />
                  <p className="text-sm">No low-trust memories</p>
                  <p className="text-xs">All active memories have a trust score of 0.5 or above.</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border">
                        <th className="text-left font-medium text-muted-foreground pb-2 pr-3">Content</th>
                        <th className="text-left font-medium text-muted-foreground pb-2 pr-3">Score</th>
                        <th className="text-left font-medium text-muted-foreground pb-2 pr-3">Feedback</th>
                        <th className="text-left font-medium text-muted-foreground pb-2 pr-3">Tier</th>
                        <th className="text-right font-medium text-muted-foreground pb-2">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {lowTrustMemories.map((mem) => (
                        <tr key={mem.id} className="border-b border-border/50 hover:bg-muted/30">
                          <td className="py-2.5 pr-3">
                            <p className="truncate max-w-[300px] text-xs">
                              {mem.summary || mem.content.slice(0, 100)}
                            </p>
                            <span className="text-[10px] text-muted-foreground">
                              {formatMemoryTimestamp(mem.updated_at)}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3">
                            <span
                              className={`font-mono text-sm ${
                                mem.trust_score < 0.3 ? 'text-red-500' : 'text-yellow-500'
                              }`}
                            >
                              {mem.trust_score.toFixed(2)}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3">
                            <span className="text-xs text-muted-foreground">
                              {mem.feedback_count}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3">
                            <Badge variant="outline" className={`text-[10px] ${tierColors[mem.tier] ?? ''}`}>
                              {mem.tier}
                            </Badge>
                          </td>
                          <td className="py-2.5 text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => handleReinforce(mem.id)}
                                title="Reinforce (boost trust score)"
                                className="h-7 text-xs"
                              >
                                <RefreshCw className="h-3 w-3 mr-1" />
                                Reinforce
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleDelete(mem.id)}
                                title="Deactivate memory"
                                className="h-7 text-xs text-red-500 hover:text-red-600"
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* 5. Filter bar */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Filter className="h-4 w-4 text-muted-foreground" />
                Browse All Memories
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap items-center gap-3 mb-4">
                <div className="relative flex-1 min-w-[200px]">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    placeholder="Search by content, summary, or type..."
                    className="pl-9"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <select
                  className="h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={tierFilter}
                  onChange={(e) => setTierFilter(e.target.value)}
                >
                  <option value="all">All Tiers</option>
                  <option value="L0">L0 — Critical</option>
                  <option value="L1">L1 — Normal</option>
                  <option value="L2">L2 — Archival</option>
                </select>
                <select
                  className="h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                >
                  <option value="trust_score">Sort by Trust Score</option>
                  <option value="confidence">Sort by Confidence</option>
                  <option value="updated_at">Sort by Updated</option>
                </select>
                <Badge variant="secondary" className="shrink-0">
                  {filtered.length} / {activeMemories.length} memories
                </Badge>
              </div>

              {/* Memory list */}
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {filtered.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                    <Search className="h-8 w-8 mb-2 opacity-30" />
                    <p className="text-sm">No matching memories</p>
                    <p className="text-xs">Try adjusting your filters.</p>
                  </div>
                ) : (
                  filtered.slice(0, 50).map((mem) => {
                    const decay = isDecayReady(mem.updated_at);
                    return (
                      <div
                        key={mem.id}
                        className={`flex items-start justify-between rounded-lg border p-3 ${
                          decay ? 'border-orange-500/20 bg-orange-500/5' : 'border-border'
                        }`}
                      >
                        <div className="min-w-0 flex-1 mr-3">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium truncate max-w-[400px]">
                              {mem.summary || mem.content.slice(0, 120)}
                            </p>
                            {decay && (
                              <span title="Decay-ready"><Flame className="h-3 w-3 text-orange-500 shrink-0" /></span>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-[400px]">
                            {mem.content.slice(0, 160)}{mem.content.length > 160 ? '…' : ''}
                          </p>
                          <div className="flex items-center gap-3 mt-1 text-[10px] text-muted-foreground">
                            <span>{formatMemoryTimestamp(mem.created_at)}</span>
                            <span>Trust: {mem.trust_score.toFixed(2)}</span>
                            <span>Conf: {(mem.confidence * 100).toFixed(0)}%</span>
                            <span>Strength: {mem.strength.toFixed(2)}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <Badge variant="outline" className="text-[10px]">
                            {mem.memory_type}
                          </Badge>
                          <Badge variant="outline" className={`text-[10px] ${tierColors[mem.tier] ?? ''}`}>
                            {mem.tier}
                          </Badge>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
