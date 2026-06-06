import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Clock, MessageSquare, AlertCircle } from 'lucide-react';
import { useTable } from '@/lib/useReactiveDb';
import { formatMemoryTimestamp } from '@/lib/spacetimedb';

interface SessionRow {
  id: string;
  workspace_id: string;
  name: string;
  summary: string;
  status: string;
  created_at: string | null;
}

function Skeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between rounded-lg border border-border p-3">
          <div className="space-y-1">
            <div className="h-5 w-48 rounded bg-muted animate-pulse" />
            <div className="h-3 w-32 rounded bg-muted animate-pulse" />
          </div>
          <div className="h-5 w-20 rounded-full bg-muted animate-pulse" />
        </div>
      ))}
    </div>
  );
}

export default function Sessions() {
  const { data: sessions, loading, error } = useTable<SessionRow>('session');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Sessions</h1>
        <p className="text-muted-foreground">
          {loading ? 'Loading...' : `${sessions.length} session(s)`}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Session Log</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="flex items-center gap-3 py-6 text-destructive">
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm">{error}</p>
            </div>
          ) : loading ? (
            <Skeleton />
          ) : sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <MessageSquare className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">No sessions yet</p>
              <p className="text-sm mt-1">Create a session to start tracking conversations.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {sessions.map((session) => (
                <div key={session.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <MessageSquare className="mt-1 h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="min-w-0">
                      <p className="font-medium truncate max-w-[350px]">{session.name || session.id.slice(0, 24) + '…'}</p>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Clock className="h-3 w-3" />
                        <span>{formatMemoryTimestamp(session.created_at)}</span>
                        {session.summary && <><span>·</span><span className="truncate max-w-[200px]">{session.summary}</span></>}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <Badge variant={session.status === 'active' ? 'default' : 'secondary'}>
                      {session.status || 'unknown'}
                    </Badge>
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
