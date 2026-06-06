import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Database, Search as SearchIcon, Filter } from 'lucide-react';

const memories = [
  { id: 'mem-001', key: 'user:alice:preferences', value: '{...}', type: 'json', size: '2.4 KB', ttl: '7d 12h' },
  { id: 'mem-002', key: 'session:abc123:context', value: '{...}', type: 'json', size: '1.1 KB', ttl: '2h' },
  { id: 'mem-003', key: 'graph:node:entity_42:embedding', value: '[0.12, 0.89, ...]', type: 'vector', size: '16 KB', ttl: '30d' },
  { id: 'mem-004', key: 'peer:node-nyc-01:status', value: '"online"', type: 'string', size: '28 B', ttl: '5m' },
];

export default function MemoryBrowser() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Memory Browser</h1>
        <p className="text-muted-foreground">Browse and inspect stored memory entries.</p>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Search memories by key or value..." className="pl-9" />
        </div>
        <Badge variant="secondary" className="gap-1">
          <Filter className="h-3 w-3" />
          Filters
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Stored Memories</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {memories.map((mem) => (
              <div key={mem.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                <div className="flex items-start gap-3">
                  <Database className="mt-0.5 h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="font-mono text-sm font-medium">{mem.key}</p>
                    <p className="font-mono text-xs text-muted-foreground">{mem.value}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Badge variant="outline">{mem.type}</Badge>
                  <span className="text-xs text-muted-foreground">{mem.size}</span>
                  <span className="text-xs text-muted-foreground">TTL: {mem.ttl}</span>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
