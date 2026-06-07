/**
 * SpacetimeDB client using the official TypeScript SDK with WebSocket subscriptions.
 *
 * Best-practice pattern for SpacetimeDB v2.4:
 * - Connect via WebSocket (not HTTP polling)
 * - Subscribe to table queries
 * - Data arrives via push (onInsert/onDelete)
 * - Query local cache via iter()
 *
 // Reducer calls use the standard HTTP POST API.
  */
 /// <reference types="vite/client" />
 import { DbConnection } from './module-bindings';
 import { useState, useEffect } from 'react';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const WS_URI = (import.meta as any).env?.VITE_SPACETIMEDB_WS ?? 'ws://localhost:3001';
const DB_NAME = (import.meta as any).env?.VITE_SPACETIMEDB_DB ?? 'c200f381695ed98be9b3fa689dd298cddff6212d35c46ae2a01999f921b88c82';
const HTTP_HOST = (import.meta as any).env?.VITE_SPACETIMEDB_HOST ?? 'localhost:3001';

// ---------------------------------------------------------------------------
// Singleton connection
// ---------------------------------------------------------------------------

let _conn: DbConnection | null = null;
let _ready = false;
let _error: string | null = null;
const _readyCallbacks: Array<() => void> = [];
const _errorCallbacks: Array<(err: string) => void> = [];

export function getConnection(): DbConnection {
  if (_conn) return _conn;

  _conn = DbConnection.builder()
    .withUri(WS_URI)
    .withDatabaseName(DB_NAME)
    .withToken('')
    .onConnect((_c, _id, _token) => {
      console.debug('[stmem] connected');
    })
    .onDisconnect(() => {
      console.debug('[stmem] disconnected');
      _ready = false;
    })
    .build();

  return _conn;
}

// ---------------------------------------------------------------------------
// Subscription
// ---------------------------------------------------------------------------

export function subscribe(queries: string[]) {
  const conn = getConnection();
  conn.subscriptionBuilder()
    .onApplied(() => {
      _ready = true;
      for (const cb of _readyCallbacks) cb();
      _readyCallbacks.length = 0;
    })
    .subscribe(queries);
}

export function isReady(): boolean {
  return _ready;
}

export function getError(): string | null {
  return _error;
}

export function onReady(cb: () => void) {
  if (_ready) { cb(); return; }
  _readyCallbacks.push(cb);
}

export function onError(cb: (err: string) => void) {
  _errorCallbacks.push(cb);
}

// ---------------------------------------------------------------------------
// Reducer calls (HTTP)
// ---------------------------------------------------------------------------

export async function callReducer(name: string, args: unknown[]): Promise<void> {
  const res = await fetch(
    `http://${HTTP_HOST}/v1/database/${DB_NAME}/call/${name}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
    },
  );
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Reducer '${name}' error (${res.status}): ${body.slice(0, 200)}`);
  }
}

// ---------------------------------------------------------------------------
// Table cache accessors
// ---------------------------------------------------------------------------

function getFromCache<T>(tableName: string): T[] {
  const conn = getConnection();
  const table = (conn.db as any)[tableName];
  return table ? Array.from(table.iter()) : [];
}

// ---------------------------------------------------------------------------
// Dashboard types & helpers
// ---------------------------------------------------------------------------

export interface DashboardStats {
  totalMemories: number;
  activePeers: number;
  sessionsToday: number;
  totalWorkspaces: number;
}

export function getDashboardStats(): DashboardStats {
  const memories = getFromCache<any>('memory');
  const peers = getFromCache<any>('peer');
  const sessions = getFromCache<any>('session');
  const workspaces = getFromCache<any>('workspace');
  const now = Date.now() * 1000;
  const dayAgo = now - 86_400_000_000;
  return {
    totalMemories: memories.filter((m: any) => m.isActive).length,
    activePeers: peers.length,
    sessionsToday: sessions.filter((s: any) => s.createdAt > dayAgo).length,
    totalWorkspaces: workspaces.length,
  };
}

export interface RecentActivity {
  action: string;
  peer: string;
  time: string;
  type: 'memory' | 'session' | 'insight';
}

export function getRecentActivity(limit = 10): RecentActivity[] {
  const results: RecentActivity[] = [];
  for (const m of getFromCache<any>('memory')) {
    results.push({
      action: `Memory: ${m.summary || m.content?.slice(0, 60)}`,
      peer: m.peerId,
      time: m.createdAt ? fmt(m.createdAt) : 'unknown',
      type: 'memory',
    });
  }
  for (const s of getFromCache<any>('session')) {
    results.push({
      action: `Session: ${s.name || s.id}`,
      peer: s.id,
      time: s.createdAt ? fmt(s.createdAt) : 'unknown',
      type: 'session',
    });
  }
  results.sort((a, b) => b.time.localeCompare(a.time));
  return results.slice(0, limit);
}

// ---------------------------------------------------------------------------
// Legacy compatibility wrappers (old SQL API → SDK cache)
// ---------------------------------------------------------------------------

export async function fetchWorkspaces(): Promise<any[]> { return getFromCache('workspace'); }
export async function fetchPeers(ws?: string): Promise<any[]> {
  const a = getFromCache<any>('peer'); return ws ? a.filter((p: any) => p.workspaceId === ws) : a;
}
export async function fetchSessions(ws?: string): Promise<any[]> {
  const a = getFromCache<any>('session'); return ws ? a.filter((s: any) => s.workspaceId === ws) : a;
}
export async function fetchMessages(sid: string): Promise<any[]> {
  return getFromCache<any>('message').filter((m: any) => m.sessionId === sid);
}
export async function fetchMemories(ws?: string, type?: string, tier?: string, limit = 100): Promise<any[]> {
  let a = getFromCache<any>('memory');
  if (ws) a = a.filter((m: any) => m.workspaceId === ws);
  if (type) a = a.filter((m: any) => m.memoryType === type);
  if (tier) a = a.filter((m: any) => m.tier === tier);
  return a.slice(0, limit);
}
export async function fetchDocuments(ws?: string): Promise<any[]> {
  const a = getFromCache<any>('document'); return ws ? a.filter((d: any) => d.workspaceId === ws) : a;
}
export async function fetchProfiles(): Promise<any[]> { return getFromCache('profile'); }
export async function fetchKgNodes(ws?: string): Promise<any[]> {
  const a = getFromCache<any>('kg_node'); return ws ? a.filter((n: any) => n.workspaceId === ws) : a;
}
export async function fetchKgEdges(): Promise<any[]> { return getFromCache('kg_edge'); }
export async function fetchKgNode(id: string): Promise<any> {
  return getFromCache<any>('kg_node').find((n: any) => n.id === id) ?? null;
}
export async function fetchInsights(pid?: string): Promise<any[]> {
  const a = getFromCache<any>('insight'); return pid ? a.filter((i: any) => i.peerId === pid) : a;
}
export async function fetchTags(): Promise<any[]> { return getFromCache('tag'); }
export async function fetchDashboardStats(): Promise<DashboardStats> { return getDashboardStats(); }
export async function fetchRecentActivity(l = 10): Promise<RecentActivity[]> { return getRecentActivity(l); }

// ---------------------------------------------------------------------------
// Backward-compatible type aliases and hooks for unmigrated pages
// ---------------------------------------------------------------------------

// Type aliases (these were previously defined inline in the old spacetimedb.ts)
export type DocumentRow = any;
export type MemoryRow = any;
export type PeerRow = any;
export type SessionRow = any;

// Re-exported helpers
export const formatMemoryTimestamp = fmt;
export const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

// No-op SQL wrappers — subscriptions replace these for most pages.
// Still used for one-off reads like hybrid search results (temp tables written by reducers).
const _executeHttp = (sql: string): Promise<any> => {
  return fetch(`http://${HTTP_HOST}/v1/database/${DB_NAME}/sql`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: sql,
  }).then(r => r.json());
};

export async function executeSql(sql: string): Promise<any> {
  try {
    return await _executeHttp(sql);
  } catch {
    return [];
  }
}

export function parseSqlResponse<T>(response: any): T[] {
  if (!response || !Array.isArray(response) || response.length === 0) return [];
  const table = response[0];
  const columns = (table?.schema?.elements ?? []).map((el: any) =>
    el?.name?.some ?? '?'
  );
  return (table?.rows ?? []).map((row: any[]) => {
    const obj: Record<string, unknown> = {};
    columns.forEach((col: string, i: number) => { obj[col] = row[i]; });
    return obj as T;
  });
}

// Legacy polling hook — reads from SDK cache, re-renders on version change
export function usePollingQuery<T>(
  fetcher: () => Promise<T>,
  _intervalMs = 5000,
): { data: T | null; loading: boolean; error: string | null; refetch: () => void } {
  const [version, setVersion] = useState(0);
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Poll every _intervalMs
  useEffect(() => {
    const id = setInterval(() => setVersion((v) => v + 1), _intervalMs);
    return () => clearInterval(id);
  }, [_intervalMs]);

  // Re-fetch on version change
  useEffect(() => {
    fetcher()
      .then((result: T) => { setData(result); setError(null); })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [version]);

  return { data, loading, error, refetch: () => setVersion((v) => v + 1) };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(micros: string | number | null): string {
  if (micros == null) return 'unknown';
  const ms = (typeof micros === 'number' ? micros : Number(micros)) / 1000;
  const diff = Date.now() - ms;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
