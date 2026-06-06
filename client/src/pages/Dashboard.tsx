import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Database, Users, Activity, Clock } from 'lucide-react';

const stats = [
  { title: 'Total Memories', value: '12,847', icon: Database, change: '+12%', color: 'text-blue-500' },
  { title: 'Active Peers', value: '24', icon: Users, change: '+3', color: 'text-green-500' },
  { title: 'Sessions Today', value: '156', icon: Activity, change: '+8%', color: 'text-purple-500' },
  { title: 'Avg Response', value: '42ms', icon: Clock, change: '-5ms', color: 'text-orange-500' },
];

const recentActivity = [
  { id: 1, action: 'Memory synced', peer: 'node-berlin-01', time: '2m ago', status: 'success' },
  { id: 2, action: 'Session created', peer: 'node-tokyo-03', time: '5m ago', status: 'success' },
  { id: 3, action: 'Knowledge graph updated', peer: 'core', time: '12m ago', status: 'processing' },
  { id: 4, action: 'Peer disconnected', peer: 'node-sydney-02', time: '18m ago', status: 'warning' },
  { id: 5, action: 'Memory query executed', peer: 'node-london-01', time: '25m ago', status: 'success' },
];

export default function Dashboard() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Overview of your spacetime memory network.</p>
      </div>

      {/* Stat cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
              <stat.icon className={`h-4 w-4 ${stat.color}`} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-xs text-muted-foreground">{stat.change} from last week</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Recent Activity */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recent Activity</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {recentActivity.map((item) => (
              <div key={item.id} className="flex items-center justify-between border-b border-border pb-3 last:border-0 last:pb-0">
                <div className="space-y-1">
                  <p className="text-sm font-medium">{item.action}</p>
                  <p className="text-xs text-muted-foreground">{item.peer}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">{item.time}</span>
                  <Badge
                    variant={
                      item.status === 'success'
                        ? 'default'
                        : item.status === 'processing'
                        ? 'secondary'
                        : 'destructive'
                    }
                  >
                    {item.status}
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
