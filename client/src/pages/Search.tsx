import { useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Search as SearchIcon,
  Sparkles,
  Database,
  AlertCircle,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
} from '@/lib/spacetimedb';

interface SearchResult {
  id: string;
  entity_type: string;
  entity_id: string;
  content: string;
  score: number;
  strategy: string;
  created_at: string | null;
}

function ResultSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="rounded-lg border border-border p-3">
          <Skeleton className="h-4 w-16 mb-2" />
          <Skeleton className="h-5 w-3/5 mb-1" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      ))}
    </div>
  );
}

export default function Search() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const handleSearch = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed) return;

    setSearching(true);
    setSearchError(null);
    setSearched(true);

    try {
      await callReducer('hybrid_search', [
        '', // workspace_id (empty = all)
        trimmed,
        '[]', // query_embedding_json (no embedder from browser)
        '', // memory_type
        '', // tier
        20, // limit
        '["keyword","temporal"]',
      ]);

      const qhash = _queryHash(trimmed);
      const res = await executeSql(
        `SELECT * FROM hybrid_result WHERE query_hash = '${_esc(qhash)}' ORDER BY score DESC LIMIT 50`,
      );
      setResults(parseSqlResponse<SearchResult>(res));
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : 'Search failed');
      setResults([]);
    } finally {
      setSearching(false);
    }
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Search</h1>
        <p className="text-muted-foreground">Full-text search across all memories.</p>
      </div>

      <div className="flex gap-4">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search across memories, documents, and graph nodes..."
            className="pl-9 h-12 text-base"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
        </div>
        <Button
          variant="default"
          className="h-12 shrink-0"
          onClick={handleSearch}
          disabled={searching || !query.trim()}
        >
          {searching ? (
            <span className="flex items-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
              Searching
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              Search
            </span>
          )}
        </Button>
      </div>

      {searchError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-6 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <p className="text-sm">{searchError}</p>
          </CardContent>
        </Card>
      ) : searching ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Results</CardTitle>
          </CardHeader>
          <CardContent>
            <ResultSkeleton />
          </CardContent>
        </Card>
      ) : !searched ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <SearchIcon className="h-12 w-12 text-muted-foreground/30 mb-4" />
            <p className="text-lg font-medium text-muted-foreground">Search all memories</p>
            <p className="text-sm text-muted-foreground/60 mt-1">
              Enter a query above to search via keyword and temporal strategies.
            </p>
          </CardContent>
        </Card>
      ) : results.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Database className="h-12 w-12 text-muted-foreground/30 mb-4" />
            <p className="text-lg font-medium text-muted-foreground">No results</p>
            <p className="text-sm text-muted-foreground/60 mt-1">
              No memories match your query.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Results ({results.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {results.map((r) => (
                <div key={r.id} className="rounded-lg border border-border p-3">
                  <div className="flex items-start justify-between gap-2">
                    <Badge variant="outline" className="text-xs shrink-0">
                      {r.strategy}
                    </Badge>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {(r.score * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="text-sm mt-2 line-clamp-3">{r.content}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {r.entity_type} · {r.entity_id.slice(0, 16)}… · {formatMemoryTimestamp(r.created_at)}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function _queryHash(query: string): string {
  let h = 0n;
  for (const b of new TextEncoder().encode(query)) {
    h = ((h * 6364136223846793005n) + BigInt(b)) & 0xFFFFFFFFFFFFFFFFn;
  }
  return h.toString(16).padStart(16, '0');
}

function _esc(val: string): string {
  return val.replace(/'/g, "''");
}
