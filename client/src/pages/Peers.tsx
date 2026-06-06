import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Users, AlertCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { usePollingQuery, fetchPeers } from '@/lib/spacetimedb';
import type { PeerRow } from '@/lib/spacetimedb';

function PeerSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between rounded-lg border border-border p-3">
          <div className="space-y-1">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-3 w-24" />
          </div>
          <div className="flex items-center gap-4">
            <Skeleton className="h-4 w-12" />
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Peers() {
  const { data: peers, loading, error, refetch } = usePollingQuery(() => fetchPeers(), 10000);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Peers</h1>
          <p className="text-muted-foreground">
            {loading ? 'Loading...' : `${peers?.length ?? 0} peer(s) registered`}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refetch}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">All Peers</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="flex items-center gap-3 py-6 text-destructive">
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm">{error}</p>
            </div>
          ) : loading ? (
            <PeerSkeleton />
          ) : !peers || peers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Users className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">No peers yet</p>
              <p className="text-sm mt-1">Create a peer via the CLI or MCP tools.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {(peers as PeerRow[]).map((peer) => (
                <div key={peer.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                  <div className="space-y-1 min-w-0">
                    <p className="font-medium truncate max-w-[300px]">{peer.name || peer.id}</p>
                    <p className="text-xs text-muted-foreground">
                      {peer.peer_type} · {peer.workspace_id ? peer.workspace_id.slice(0, 16) + '…' : '—'}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <Badge variant="outline">{peer.peer_type || 'unknown'}</Badge>
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
