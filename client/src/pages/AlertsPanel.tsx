import { useTable } from '../lib/useReactiveDb';
import { AlertTriangle, CheckCircle, XCircle } from 'lucide-react';

interface EmbedderAlert {
  id: string;
  severity: number;
  message: string;
  consecutive_failures: number;
  total_calls: number;
  total_errors: number;
  error_rate_pct: number;
  degraded: boolean;
  recovery: boolean;
  reachable: boolean;
  embedder_url: string;
  created_at: number;
}

interface TantivyAlert {
  id: string;
  severity: number;
  message: string;
  consecutive_failures: number;
  total_checks: number;
  total_failures: number;
  error_rate_pct: number;
  degraded: boolean;
  recovery: boolean;
  reachable: boolean;
  tantivy_url: string;
  created_at: number;
}

function SeverityIcon({ severity }: { severity: number }) {
  if (severity === 0) return <CheckCircle className="h-4 w-4 text-green-500" />;
  if (severity === 1) return <AlertTriangle className="h-4 w-4 text-yellow-500" />;
  return <XCircle className="h-4 w-4 text-red-500" />;
}

function fmtTime(ts: number): string {
  return new Date(ts / 1000).toLocaleString();
}

export function EmbAlertRow({ a }: { a: EmbedderAlert }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-neutral-800/50 text-sm">
      <SeverityIcon severity={a.severity} />
      <div className="flex-1 min-w-0">
        <p className="truncate font-medium">{a.message || (a.recovery ? 'Embedder recovered' : a.degraded ? 'Degraded' : 'OK')}</p>
        <p className="text-xs text-neutral-500">{fmtTime(a.created_at)}</p>
      </div>
      <div className="text-xs text-neutral-400 shrink-0">
        {a.error_rate_pct.toFixed(1)}% err
      </div>
    </div>
  );
}

export function TanAlertRow({ a }: { a: TantivyAlert }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-neutral-800/50 text-sm">
      <SeverityIcon severity={a.severity} />
      <div className="flex-1 min-w-0">
        <p className="truncate font-medium">{a.message || (a.recovery ? 'Tantivy recovered' : a.degraded ? 'Degraded' : 'OK')}</p>
        <p className="text-xs text-neutral-500">{fmtTime(a.created_at)}</p>
      </div>
      <div className="text-xs text-neutral-400 shrink-0">
        {a.error_rate_pct.toFixed(1)}% err
      </div>
    </div>
  );
}

export function AlertsPanel() {
  const { data: embAlerts, loading: embLoading } = useTable<EmbedderAlert>('embedder_alert');
  const { data: tanAlerts, loading: tanLoading } = useTable<TantivyAlert>('tantivy_alert');

  const recentEmb = (embAlerts || []).slice(0, 10);
  const recentTan = (tanAlerts || []).slice(0, 10);

  if (embLoading || tanLoading) return <div className="text-sm text-neutral-500">Loading alerts...</div>;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-neutral-400 mb-2">Embedder Alerts</h3>
        {recentEmb.length === 0 ? (
          <p className="text-xs text-neutral-600">No recent alerts</p>
        ) : (
          <div className="space-y-0">{recentEmb.map(a => <EmbAlertRow key={a.id} a={a} />)}</div>
        )}
      </div>
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-neutral-400 mb-2">Tantivy Alerts</h3>
        {recentTan.length === 0 ? (
          <p className="text-xs text-neutral-600">No recent alerts</p>
        ) : (
          <div className="space-y-0">{recentTan.map(a => <TanAlertRow key={a.id} a={a} />)}</div>
        )}
      </div>
    </div>
  );
}
