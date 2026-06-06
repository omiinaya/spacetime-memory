import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Database, Search as SearchIcon, Filter, AlertCircle } from 'lucide-react';
import { useTable } from '@/lib/useReactiveDb';
import { formatMemoryTimestamp } from '@/lib/spacetimedb';

interface MemoryRow {
  id: string;
  workspace_id: string;
  content: string;
  summary: string;
  memory_type: string;
  tier: string;
  confidence: number;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

const memoryTypeColors: Record<string, string> = {
  world_fact: 'bg-blue-500/10 text-blue-600',
  experience: 'bg-green-500/10 text-green-600',
  mental_model: 'bg-purple-500/10 text-purple-600',
  consolidated: 'bg-orange-500/10 text-orange-600',
};

export default function MemoryBrowser() {
  const [searchTerm, setSearchTerm] = useState('');
  const { data: memories, loading, error } = useTable<MemoryRow>('memory');

  const filtered = memories
    .filter((m) => {
      if (!searchTerm) return true;
      const q = searchTerm.toLowerCase();
      return (
        m.content.toLowerCase().includes(q) ||
        m.summary.toLowerCase().includes(q) ||
        m.memory_type.toLowerCase().includes(q)
      );
    })
    .sort((a, b) => Number(b.updated_at ?? b.created_at ?? 0) - Number(a.updated_at ?? a.created_at ?? 0));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Memory Browser</h1>
        <p className="text-muted-foreground">
          {loading ? 'Loading...' : `${filtered.length} memory(ies)`}
        </p>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search memories by content, summary, or type..."
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
          <CardTitle className="text-lg">Stored Memories</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="flex items-center gap-3 py-6 text-destructive">
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm">{error}</p>
            </div>
          ) : loading ? (
            <div className="space-y-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg border border-border p-3">
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
                  : 'Store a memory via the CLI or MCP tools to see it here.'}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {filtered.map((mem) => (
                <div key={mem.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                  <div className="min-w-0 flex-1 mr-3">
                    <p className="text-sm font-medium truncate max-w-[500px]">
                      {mem.summary || mem.content.slice(0, 120)}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1 truncate max-w-[500px]">
                      {mem.content.slice(0, 200)}{mem.content.length > 200 ? '…' : ''}
                    </p>
                    <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                      <span>{formatMemoryTimestamp(mem.created_at)}</span>
                      {mem.tier && <span>· Tier {mem.tier}</span>}
                      {mem.confidence > 0 && <span>· {(mem.confidence * 100).toFixed(0)}%</span>}
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
                      <Badge variant="secondary" className="text-xs">inactive</Badge>
                    )}
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
