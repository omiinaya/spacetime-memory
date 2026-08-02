import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Database, Users, Activity, Building2, AlertCircle } from 'lucide-react';
import { useReactiveDb } from '@/lib/useReactiveDb';
import { AlertsPanel } from './AlertsPanel';

function StatCard({ title, value, icon: Icon, loading, color }: {
  title: string;
  value: string;
  icon: React.ElementType;
  loading: boolean;
  color: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className={`h-4 w-4 ${color}`} />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-20" />
        ) : (
          <div className="text-2xl font-bold">{value}</div>
        )}
      </CardContent>
    </Card>
  );
}

function ActivityIcon({ type }: { type: string }) {
  switch (type) {
    case 'memory': return <Database className="h-4 w-4 text-blue-500" />;
    case 'session': return <Activity className="h-4 w-4 text-green-500" />;
    default: return <Database className="h-4 w-4 text-muted-foreground" />;
  }
}

function ActivitySkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between border-b border-border pb-3 last:border-0 last:pb-0">
          <div className="space-y-1 flex-1">
            <Skeleton className="h-4 w-3/5" />
            <Skeleton className="h-3 w-1/4" />
          </div>
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const { ready, error, stats, activity } = useReactiveDb();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          {ready
            ? `${stats?.totalWorkspaces ?? 0} workspace(s)`
            : 'Connecting...'}
        </p>
      </div>

      {/* Stat cards — reactive, no polling */}
      {error ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-6">
            <AlertCircle className="h-5 w-5 text-destructive" />
            <p className="text-sm text-destructive">Connection error: {error}</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Total Memories"
            value={stats ? (stats.totalMemories ?? 0).toLocaleString() : '—'}
            icon={Database}
            loading={!ready}
            color="text-blue-500"
          />
          <StatCard
            title="Active Peers"
            value={stats ? (stats.activePeers ?? 0).toLocaleString() : '—'}
            icon={Users}
            loading={!ready}
            color="text-green-500"
          />
          <StatCard
            title="Sessions Today"
            value={stats ? (stats.sessionsToday ?? 0).toLocaleString() : '—'}
            icon={Activity}
            loading={!ready}
            color="text-purple-500"
          />
          <StatCard
            title="Workspaces"
            value={stats ? (stats.totalWorkspaces ?? 0).toLocaleString() : '—'}
            icon={Building2}
            loading={!ready}
            color="text-orange-500"
          />
        </div>
      )}

      {/* Recent Activity — reactive */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recent Activity</CardTitle>
        </CardHeader>
        <CardContent>
          {!ready ? (
            <ActivitySkeleton />
          ) : !activity || activity.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
              <Activity className="h-8 w-8 mb-2 opacity-30" />
              <p className="text-sm">No recent activity</p>
              <p className="text-xs">Create a memory or session to get started.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {activity.map((item, i) => (
                <div key={i} className="flex items-center justify-between border-b border-border pb-3 last:border-0 last:pb-0">
                  <div className="flex items-start gap-3 min-w-0">
                    <ActivityIcon type={item.type} />
                    <div className="space-y-1 min-w-0">
                      <p className="text-sm font-medium truncate max-w-[400px]">{item.action}</p>
                      <p className="text-xs text-muted-foreground truncate max-w-[300px]">{item.peer}</p>
                    </div>
                  </div>
                  <span className="text-xs text-muted-foreground shrink-0 ml-3">{item.time}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>

      {/* Sidecar Alerts — reactive */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Sidecar Health</CardTitle>
        </CardHeader>
        <CardContent>
          <AlertsPanel />
        </CardContent>
      </Card>
      </Card>
    </div>
  );
}
