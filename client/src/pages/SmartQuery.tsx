import { useState, useCallback } from 'react';
import { Search, Sparkles, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { parseSqlResponse } from '@/lib/spacetimedb';

interface QueryFilter {
  memoryType: string;
  tier: string;
  minTrust: number;
  maxAge: number; // hours, 0 = all
  tag: string;
  directory: string;
}

interface ResultItem {
  id: string;
  entityType: string;
  entityId: string;
  content: string;
  score: number;
  strategy: string;
}

function ResultCard({ item }: { item: ResultItem }) {
  return (
    <Card className="mb-2">
      <CardContent className="p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <p className="text-sm text-foreground line-clamp-2">{item.content || item.entityId}</p>
            <div className="flex gap-2 mt-1">
              <Badge variant="secondary" className="text-[10px]">{item.entityType}</Badge>
              <span className="text-[10px] text-muted-foreground">{item.strategy}</span>
            </div>
          </div>
          <div className="text-right shrink-0">
            <span className="text-sm font-mono text-muted-foreground">
              {(item.score * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function SmartQuery() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ResultItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<QueryFilter>({
    memoryType: '',
    tier: '',
    minTrust: 0,
    maxAge: 0,
    tag: '',
    directory: '',
  });
  const [presetName, setPresetName] = useState('');
  const [savedPresets, setSavedPresets] = useState<Array<{ name: string; query: string; filters: QueryFilter }>>(() => {
    try {
      return JSON.parse(localStorage.getItem('smartQueryPresets') || '[]');
    } catch { return []; }
  });

  const runQuery = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);

    try {
      // Embed query
      const embedResp = await fetch('http://localhost:9090/embed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: query }),
      });
      const emb = embedResp.ok ? (await embedResp.json()).embedding : [];

      // Build workspace ID - use first available
      const wsResp = await fetch('http://localhost:3001/v1/database/spacetime-memory/sql', {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain' },
        body: 'SELECT id FROM workspace',
      });
      const wsData: any[] = parseSqlResponse(await wsResp.text());
      const wsId = wsData[0]?.id || '';

      // Call hybrid search
      const strategies = JSON.stringify(['semantic', 'keyword', 'graph', 'temporal']);
      const memType = filters.memoryType || '';
      const tier = filters.tier || '';
      const limit = 20;

      const reducerResp = await fetch(`http://localhost:3001/v1/database/spacetime-memory/call/hybrid_search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([wsId, query, JSON.stringify(emb), memType, tier, limit, strategies]),
      });
      if (!reducerResp.ok) {
        throw new Error(`Search failed: ${await reducerResp.text()}`);
      }

      // Read results — same hash algo as the Rust reducer
      let hash = 0;
      for (let i = 0; i < query.length; i++) {
        hash = ((hash << 5) - hash) + query.charCodeAt(i);
        hash |= 0;
      }
      const qhashStr = (hash >>> 0).toString(16).padStart(16, '0');

      const resultResp = await fetch('http://localhost:3001/v1/database/spacetime-memory/sql', {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain' },
        body: `SELECT * FROM hybrid_result WHERE workspace_id = '${wsId}' AND query_hash = '${qhashStr}'`,
      });
      const raw: any[] = parseSqlResponse(await resultResp.text());

      // Look up content for memory results
      const items: ResultItem[] = [];
      for (const row of raw) {
        let content = row.entityId || '';
        if (row.entityType === 'memory') {
          const memResp = await fetch('http://localhost:3001/v1/database/spacetime-memory/sql', {
            method: 'POST',
            headers: { 'Content-Type': 'text/plain' },
            body: `SELECT content FROM memory WHERE id = '${row.entityId}'`,
          });
          const memData: any[] = parseSqlResponse(await memResp.text());
          if (memData[0]) content = memData[0].content || '';
        }
        items.push({
          id: row.id || '',
          entityType: row.entityType || '',
          entityId: row.entityId || '',
          content,
          score: row.score || 0,
          strategy: row.strategy || '',
        });
      }

      items.sort((a, b) => b.score - a.score);
      setResults(items);
    } catch (e: any) {
      setError(e.message || 'Query failed');
    } finally {
      setLoading(false);
    }
  }, [query, filters]);

  const savePreset = () => {
    if (!presetName.trim()) return;
    const newPreset = { name: presetName, query, filters: { ...filters } };
    const updated = [...savedPresets, newPreset];
    setSavedPresets(updated);
    localStorage.setItem('smartQueryPresets', JSON.stringify(updated));
    setPresetName('');
  };

  const loadPreset = (preset: typeof savedPresets[0]) => {
    setQuery(preset.query);
    setFilters(preset.filters);
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Smart Query</h1>
          <p className="text-sm text-muted-foreground">Compose hybrid search with filters</p>
        </div>
      </div>

      {/* Query input */}
      <div className="flex gap-2">
        <Input
          placeholder="Search memories, entities, and documents..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && runQuery()}
          className="flex-1"
        />
        <Button onClick={runQuery} disabled={loading || !query.trim()}>
          {loading ? (
            <span className="flex items-center gap-1"><span className="animate-spin">⟳</span> Searching...</span>
          ) : (
            <span className="flex items-center gap-1"><Search className="h-4 w-4" /> Search</span>
          )}
        </Button>
      </div>

      {/* Filters */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Memory Type</label>
          <select
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={filters.memoryType}
            onChange={(e) => setFilters({...filters, memoryType: e.target.value})}
          >
            <option value="">Any</option>
            <option value="world_fact">World Fact</option>
            <option value="experience">Experience</option>
            <option value="mental_model">Mental Model</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Tier</label>
          <select
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={filters.tier}
            onChange={(e) => setFilters({...filters, tier: e.target.value})}
          >
            <option value="">Any</option>
            <option value="L0">L0 — Critical</option>
            <option value="L1">L1 — Normal</option>
            <option value="L2">L2 — Archival</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Min Trust</label>
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={0} max={100} step={5}
              value={filters.minTrust}
              onChange={(e) => setFilters({...filters, minTrust: Number(e.target.value)})}
              className="flex-1"
            />
            <span className="text-xs w-8">{filters.minTrust}%</span>
          </div>
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Max Age</label>
          <select
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={String(filters.maxAge)}
            onChange={(e) => setFilters({...filters, maxAge: Number(e.target.value)})}
          >
            <option value="0">Any</option>
            <option value="1">1 hour</option>
            <option value="24">24 hours</option>
            <option value="168">7 days</option>
            <option value="720">30 days</option>
          </select>
        </div>
      </div>

      {/* Presets */}
      <div className="flex gap-2 items-center">
        <Input
          placeholder="Save as preset..."
          value={presetName}
          onChange={(e) => setPresetName(e.target.value)}
          className="max-w-xs"
        />
        <Button variant="outline" size="sm" onClick={savePreset} disabled={!presetName.trim()}>
          <Save className="h-3 w-3 mr-1" /> Save
        </Button>
        {savedPresets.length > 0 && (
          <div className="flex gap-1 ml-2">
            {savedPresets.map((p, i) => (
              <Badge
                key={i}
                variant="outline"
                className="cursor-pointer hover:bg-accent"
                onClick={() => loadPreset(p)}
              >
                {p.name}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      <div className="space-y-1">
        {loading && (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-lg" />
            ))}
          </div>
        )}
        {error && (
          <Card className="border-red-500/30">
            <CardContent className="p-3 text-sm text-red-400">{error}</CardContent>
          </Card>
        )}
        {!loading && !error && results.length === 0 && query && (
          <Card>
            <CardContent className="p-6 text-center text-muted-foreground">
              <Sparkles className="h-8 w-8 mx-auto mb-2 opacity-30" />
              <p>No results found. Try broadening your filters.</p>
            </CardContent>
          </Card>
        )}
        {results.map((item) => (
          <ResultCard key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}
