import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { RefreshCw } from 'lucide-react';

const peers = [
  { id: 'node-berlin-01', address: '192.168.1.42:9187', status: 'online', latency: '12ms', memories: 3421 },
  { id: 'node-tokyo-03', address: '10.0.0.81:9187', status: 'online', latency: '89ms', memories: 5612 },
  { id: 'node-london-01', address: '172.16.0.22:9187', status: 'online', latency: '24ms', memories: 2814 },
  { id: 'node-sydney-02', address: '203.0.113.55:9187', status: 'offline', latency: '-', memories: 0 },
  { id: 'node-nyc-01', address: '198.51.100.10:9187', status: 'online', latency: '8ms', memories: 4521 },
];

export default function Peers() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Peers</h1>
          <p className="text-muted-foreground">Connected nodes in the spacetime memory network.</p>
        </div>
        <Button variant="outline" size="sm">
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Network Nodes</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {peers.map((peer) => (
              <div key={peer.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                <div className="space-y-1">
                  <p className="font-medium">{peer.id}</p>
                  <p className="text-xs text-muted-foreground">{peer.address}</p>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-sm text-muted-foreground">{peer.latency}</span>
                  <span className="text-sm text-muted-foreground">{peer.memories.toLocaleString()} memories</span>
                  <Badge variant={peer.status === 'online' ? 'default' : 'secondary'}>
                    {peer.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
