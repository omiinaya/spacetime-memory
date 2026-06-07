import { useState, useMemo, useRef, useEffect } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useTable } from '@/lib/useReactiveDb';
import {
  Database,
  AlertCircle,
  Search,
  Filter,
  X,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Type definitions                                                   */
/* ------------------------------------------------------------------ */

interface MemoryRow {
  id: string;
  workspace_id: string;
  peer_id: string;
  memory_type: string;
  content: string;
  summary: string;
  confidence: number;
  is_active: boolean;
  tier: string;
  access_count: number;
  strength: number;
  trust_score: number;
  created_at: number;
  updated_at: number;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const TIERS = ['L0', 'L1', 'L2'] as const;
type Tier = (typeof TIERS)[number];

const TIER_LABELS: Record<Tier, string> = {
  L0: 'Long-Term (L0)',
  L1: 'Working (L1)',
  L2: 'Ephemeral (L2)',
};

const TIER_COLORS: Record<Tier, string> = {
  L0: 'border-blue-500/30 bg-blue-500/5',
  L1: 'border-purple-500/30 bg-purple-500/5',
  L2: 'border-amber-500/30 bg-amber-500/5',
};

const TIER_BADGE: Record<Tier, string> = {
  L0: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
  L1: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
  L2: 'bg-amber-500/10 text-amber-600 border-amber-500/20',
};

const MEMORY_TYPE_COLORS: Record<string, string> = {
  world_fact: 'bg-green-500/10 text-green-600 border-green-500/20',
  experience: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
  mental_model: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
  consolidated: 'bg-orange-500/10 text-orange-600 border-orange-500/20',
};

/* Connection colors */
const TRAJECTORY_COLORS = {
  'L2→L1': { stroke: '#22c55e', label: 'escalated' },
  'L1→L2': { stroke: '#eab308', label: 'decayed' },
  'L1→L0': { stroke: '#3b82f6', label: 'promoted' },
  'L0→L1': { stroke: '#f97316', label: 'demoted' },
} as const;

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function tierOrder(t: string): number {
  if (t === 'L0') return 0;
  if (t === 'L1') return 1;
  if (t === 'L2') return 2;
  return 3;
}

function formatConfidence(val: number): string {
  return `${(val * 100).toFixed(0)}%`;
}

function formatStrength(val: number): string {
  return (val * 100).toFixed(0);
}

function contentExcerpt(content: string, maxLen = 120): string {
  if (content.length <= maxLen) return content;
  return content.slice(0, maxLen) + '…';
}

/* ------------------------------------------------------------------ */
/*  Skeleton                                                           */
/* ------------------------------------------------------------------ */

function TrajectorySkeleton() {
  return (
    <div className="space-y-8">
      {TIERS.map((tier) => (
        <div key={tier} className="space-y-3">
          <div className="h-5 w-40 rounded bg-muted animate-pulse" />
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-32 rounded-lg border border-border bg-card animate-pulse"
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function TrajectoryViz() {
  const { data: memories, loading, error } = useTable<MemoryRow>('memory');
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  const [filterTier, setFilterTier] = useState<string>('all');
  const [filterType, setFilterType] = useState<string>('all');
  const [searchText, setSearchText] = useState('');

  /* ---------- Resize observer ---------- */
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  /* ---------- Filtered memories ---------- */
  const processed = useMemo(() => {
    const memoryTypes = new Set<string>();

    const filtered = memories
      .filter((m) => m.tier && TIERS.includes(m.tier as Tier))
      .filter((m) => {
        if (filterTier !== 'all' && m.tier !== filterTier) return false;
        if (filterType !== 'all' && m.memory_type !== filterType) return false;
        if (searchText.trim()) {
          const q = searchText.toLowerCase();
          return (
            (m.summary || m.content).toLowerCase().includes(q) ||
            m.memory_type.toLowerCase().includes(q) ||
            m.tier.toLowerCase().includes(q)
          );
        }
        return true;
      })
      .sort((a, b) => tierOrder(a.tier) - tierOrder(b.tier) || b.strength - a.strength);

    // Collect available types for filter
    memories.forEach((m) => {
      if (m.memory_type) memoryTypes.add(m.memory_type);
    });

    return { filtered, memoryTypes: Array.from(memoryTypes).sort() };
  }, [memories, filterTier, filterType, searchText]);

  const { filtered: filteredMemories, memoryTypes } = processed;

  /* ---------- Stats ---------- */
  const stats = useMemo(() => {
    const byTier: Record<string, number> = { L0: 0, L1: 0, L2: 0 };
    let totalConf = 0;
    let totalStr = 0;
    for (const m of filteredMemories) {
      if (byTier[m.tier] !== undefined) byTier[m.tier]++;
      totalConf += m.confidence;
      totalStr += m.strength;
    }
    return {
      total: filteredMemories.length,
      byTier,
      avgConfidence: filteredMemories.length > 0 ? totalConf / filteredMemories.length : 0,
      avgStrength: filteredMemories.length > 0 ? totalStr / filteredMemories.length : 0,
    };
  }, [filteredMemories]);

  /* ---------- Tier groups ---------- */
  const tierGroups = useMemo(() => {
    const groups: Record<Tier, MemoryRow[]> = {
      L0: [],
      L1: [],
      L2: [],
    };
    for (const m of filteredMemories) {
      if (TIERS.includes(m.tier as Tier)) {
        groups[m.tier as Tier].push(m);
      }
    }
    return groups;
  }, [filteredMemories]);

  /* ---------- Build trajectory connections ---------- */
  const trajectories = useMemo(() => {
    const connections: Array<{
      from: MemoryRow;
      to: MemoryRow;
      type: keyof typeof TRAJECTORY_COLORS;
    }> = [];

    // Heuristic: link memories by creation order within tiers
    const l0 = [...tierGroups.L0];
    const l1 = [...tierGroups.L1];
    const l2 = [...tierGroups.L2];

    // L2 → L1: escalated (link recent L2 to recent L1 by creation time proximity)
    for (let i = 0; i < Math.min(l2.length, l1.length); i++) {
      connections.push({ from: l2[i], to: l1[i], type: 'L2→L1' });
    }

    // L1 → L2: decayed
    for (let i = l1.length - 1, j = l2.length - 1; i >= 0 && j >= 0 && l1.length > l2.length; i--, j--) {
      if (!connections.some((c) => c.from.id === l1[i].id && c.to.id === l2[j].id)) {
        connections.push({ from: l1[i], to: l2[j], type: 'L1→L2' });
      }
    }

    // L1 → L0: promoted
    for (let i = 0; i < Math.min(l1.length, l0.length); i++) {
      connections.push({ from: l1[i], to: l0[i], type: 'L1→L0' });
    }

    // L0 → L1: demoted
    for (let i = l0.length - 1, j = l1.length - 1; i >= 0 && j >= 0 && l0.length > l1.length; i--, j--) {
      if (!connections.some((c) => c.from.id === l0[i].id && c.to.id === l1[j].id)) {
        connections.push({ from: l0[i], to: l1[j], type: 'L0→L1' });
      }
    }

    return connections;
  }, [tierGroups]);

  /* ---------- Render a single memory card ---------- */
  function MemoryCard({ mem, tier }: { mem: MemoryRow; tier: Tier }) {
    return (
      <Card
        id={`memory-card-${mem.id}`}
        className={`border-2 ${TIER_COLORS[tier]} transition-all hover:shadow-md`}
      >
        <CardContent className="p-3 space-y-2">
          {/* Header: type badge + tier badge */}
          <div className="flex items-center justify-between gap-2">
            <Badge
              variant="outline"
              className={`text-[10px] ${
                MEMORY_TYPE_COLORS[mem.memory_type] ?? ''
              }`}
            >
              {mem.memory_type || 'unknown'}
            </Badge>
            <Badge
              variant="outline"
              className={`text-[10px] ${TIER_BADGE[tier]}`}
            >
              {tier}
            </Badge>
          </div>

          {/* Content excerpt */}
          <p className="text-xs leading-relaxed line-clamp-3">
            {mem.summary || contentExcerpt(mem.content)}
          </p>

          {/* Metrics row */}
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground pt-1 border-t border-border/50">
            <span title="Confidence">
              {formatConfidence(mem.confidence)}
            </span>
            <span>·</span>
            <span title="Strength">{formatStrength(mem.strength)}%</span>
            <span>·</span>
            <span title="Access count">{mem.access_count} hits</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  /* ---------- Loading skeleton ---------- */

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Trajectory Visualization</h1>
          <p className="text-muted-foreground">
            Retrieval trajectories and memory reinforcement paths.
          </p>
        </div>
        <TrajectorySkeleton />
      </div>
    );
  }

  /* ---------- Error state ---------- */

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Trajectory Visualization</h1>
          <p className="text-muted-foreground">
            Retrieval trajectories and memory reinforcement paths.
          </p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <AlertCircle className="h-12 w-12 text-destructive" />
            <h2 className="mt-4 text-lg font-semibold">Failed to load</h2>
            <p className="mt-1 text-sm text-muted-foreground">{error}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  /* ---------- Empty state ---------- */

  if (memories.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Trajectory Visualization</h1>
          <p className="text-muted-foreground">
            Retrieval trajectories and memory reinforcement paths.
          </p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Database className="h-12 w-12 text-muted-foreground/30 mb-4" />
            <p className="text-lg font-medium text-muted-foreground">
              No memories available
            </p>
            <p className="text-sm text-muted-foreground/60 mt-1">
              Store memories to see trajectory visualizations.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  /* ---------- Main render ---------- */

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Trajectory Visualization</h1>
        <p className="text-muted-foreground">
          {stats.total} memory{stats.total !== 1 ? 'ies' : 'y'} across{' '}
          {Object.values(stats.byTier).filter((v) => v > 0).length} tier(s)
        </p>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card>
          <CardContent className="p-3 text-center">
            <p className="text-2xl font-bold">{stats.total}</p>
            <p className="text-xs text-muted-foreground">Total</p>
          </CardContent>
        </Card>
        {TIERS.map((tier) => (
          <Card key={tier} className={`border-l-4 ${
            tier === 'L0' ? 'border-l-blue-500' : tier === 'L1' ? 'border-l-purple-500' : 'border-l-amber-500'
          }`}>
            <CardContent className="p-3 text-center">
              <p className="text-2xl font-bold">{stats.byTier[tier]}</p>
              <p className="text-xs text-muted-foreground">{TIER_LABELS[tier]}</p>
            </CardContent>
          </Card>
        ))}
        <Card>
          <CardContent className="p-3 text-center">
            <p className="text-lg font-bold">{(stats.avgConfidence * 100).toFixed(0)}%</p>
            <p className="text-xs text-muted-foreground">Avg Confidence</p>
            <p className="text-xs text-muted-foreground/60">{(stats.avgStrength * 100).toFixed(0)}% strength</p>
          </CardContent>
        </Card>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3">
        <Filter className="h-4 w-4 text-muted-foreground shrink-0" />
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search memories…"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="pl-9 pr-8 h-9 text-sm"
          />
          {searchText && (
            <button
              onClick={() => setSearchText('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        <select
          value={filterTier}
          onChange={(e) => setFilterTier(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="all">All Tiers</option>
          {TIERS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="all">All Types</option>
          {memoryTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <Button
          variant="ghost"
          size="sm"
          className="text-xs h-9"
          onClick={() => {
            setFilterTier('all');
            setFilterType('all');
            setSearchText('');
          }}
        >
          Reset
        </Button>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span className="font-medium">Trajectory Legend:</span>
        {Object.entries(TRAJECTORY_COLORS).map(([key, val]) => (
          <span key={key} className="flex items-center gap-1.5">
            <svg width="24" height="4" className="overflow-visible">
              <path
                d="M0 2 Q12 -4 24 2"
                stroke={val.stroke}
                strokeWidth="2"
                fill="none"
              />
            </svg>
            <span className="capitalize">{val.label}</span>
            <span className="text-muted-foreground/40">({key})</span>
          </span>
        ))}
      </div>

      {/* Tiered layout with SVG connections */}
      <div className="relative" ref={containerRef}>
        {/* SVG overlay for connection lines */}
        <svg
          ref={svgRef}
          className="absolute inset-0 pointer-events-none z-10"
          width={dimensions.width}
          height={dimensions.height}
          style={{ overflow: 'visible' }}
        >
          {trajectories.map((t, i) => {
            const fromEl = document.getElementById(
              `memory-card-${t.from.id}`,
            );
            const toEl = document.getElementById(
              `memory-card-${t.to.id}`,
            );
            if (!fromEl || !toEl) return null;

            const fromRect = fromEl.getBoundingClientRect();
            const toRect = toEl.getBoundingClientRect();
            const containerRect =
              containerRef.current?.getBoundingClientRect();

            if (!containerRect) return null;

            const x1 = fromRect.left - containerRect.left + fromRect.width / 2;
            const y1 = fromRect.top - containerRect.top + fromRect.height;
            const x2 = toRect.left - containerRect.left + toRect.width / 2;
            const y2 = toRect.top - containerRect.top;

            const color = TRAJECTORY_COLORS[t.type].stroke;
            return (
              <g key={`traj-${i}`}>
                <path
                  d={`M${x1},${y1} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2} ${x2},${y2}`}
                  stroke={color}
                  strokeWidth="2"
                  fill="none"
                  strokeDasharray={t.type === 'L1→L2' || t.type === 'L0→L1' ? '5,3' : 'none'}
                  opacity="0.6"
                />
                <circle cx={x2} cy={y2} r="3" fill={color} />
              </g>
            );
          })}
        </svg>

        {/* Tier columns */}
        <div className="space-y-8 relative z-20">
          {TIERS.map((tier) => {
            const mems = tierGroups[tier];
            if (mems.length === 0) return null;

            return (
              <div key={tier}>
                <div className="flex items-center gap-2 mb-3">
                  <h2 className="text-lg font-semibold">{TIER_LABELS[tier]}</h2>
                  <Badge variant="secondary" className="text-xs">
                    {mems.length} memory{mems.length !== 1 ? 'ies' : 'y'}
                  </Badge>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                  {mems.map((mem) => (
                    <MemoryCard key={mem.id} mem={mem} tier={tier} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        {/* Empty filtered state */}
        {filteredMemories.length === 0 && (
          <Card className="mt-4">
            <CardContent className="flex flex-col items-center justify-center py-12">
              <Database className="h-10 w-10 mb-3 opacity-30 text-muted-foreground" />
              <p className="font-medium text-muted-foreground">
                No matching memories
              </p>
              <p className="text-sm text-muted-foreground/60 mt-1">
                Try adjusting your filters.
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
