import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Users, AlertCircle } from 'lucide-react';
import { useTable } from '@/lib/useReactiveDb';

interface PeerRow {
  id: string;
  workspace_id: string;
  name: string;
  peer_type: string;
  metadata_json: string;
  created_at: string | null;
}

function Skeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between rounded-lg border border-border p-3">
          <div className="space-y-1">
            <div className="h-5 w-40 rounded bg-muted animate-pulse" />
            <div className="h-3 w-24 rounded bg-muted animate-pulse" />
          </div>
          <div className="h-5 w-16 rounded-full bg-muted animate-pulse" />
        </div>
      ))}
    </div>
  );
}

export default function Peers() {
  const { data: peers, loading, error } = useTable<PeerRow>('peer');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Peers</h1>
        <p className="text-muted-foreground">
          {loading ? 'Loading...' : `${peers.length} peer(s) registered`}
        </p>
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
            <Skeleton />
          ) : peers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Users className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">No peers yet</p>
              <p className="text-sm mt-1">Create a peer via the CLI or MCP tools.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {peers.map((peer) => (
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
