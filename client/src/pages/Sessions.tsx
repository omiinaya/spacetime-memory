import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Clock, Play, Square } from 'lucide-react';

const sessions = [
  { id: 'ses-001', type: 'Memory Sync', peer: 'node-berlin-01', start: '10:32:15', duration: '4m 12s', records: 847, status: 'active' },
  { id: 'ses-002', type: 'Query Session', peer: 'node-london-01', start: '10:28:00', duration: '8m 30s', records: 124, status: 'active' },
  { id: 'ses-003', type: 'Bulk Load', peer: 'node-tokyo-03', start: '09:15:00', duration: '1h 12m', records: 5210, status: 'completed' },
  { id: 'ses-004', type: 'GC Cycle', peer: 'core', start: '08:00:00', duration: '15m', records: 0, status: 'completed' },
  { id: 'ses-005', type: 'Replication', peer: 'node-nyc-01', start: '10:30:00', duration: '2m 05s', records: 342, status: 'active' },
];

export default function Sessions() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Sessions</h1>
        <p className="text-muted-foreground">Active and recent session activity across the network.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Session Log</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {sessions.map((session) => (
              <div key={session.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                <div className="flex items-start gap-3">
                  {session.status === 'active' ? (
                    <Play className="mt-1 h-4 w-4 text-green-500" />
                  ) : (
                    <Square className="mt-1 h-4 w-4 text-muted-foreground" />
                  )}
                  <div>
                    <p className="font-medium">{session.type}</p>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span>{session.peer}</span>
                      <span>·</span>
                      <Clock className="h-3 w-3" />
                      <span>{session.start}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-sm text-muted-foreground">{session.duration}</span>
                  <span className="text-sm text-muted-foreground">{session.records.toLocaleString()} records</span>
                  <Badge variant={session.status === 'active' ? 'default' : 'secondary'}>
                    {session.status}
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
