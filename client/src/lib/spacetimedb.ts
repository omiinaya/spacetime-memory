/**
 * SpacetimeDB client using the official TypeScript SDK with WebSocket subscriptions.
 *
 * Best-practice pattern for SpacetimeDB v2.4:
 * - Connect via WebSocket (not HTTP polling)
 * - Subscribe to table queries
 * - Data arrives via push (onInsert/onDelete)
 * - Query local cache via iter()
 *
 * Reducer calls use the standard HTTP POST API.
 */
/// <reference types="vite/client" />
import { DbConnection } from './module-bindings';
import { useState, useEffect } from 'react';
import type {
  Memory,
  Peer,
  Session,
  Workspace,
  Message,
  Document,
  Profile,
  KgNode,
  KgEdge,
  Insight,
  Tag,
  Note,
  NoteBacklink,
} from './module-bindings/types';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const WS_URI: string = import.meta.env.VITE_SPACETIMEDB_WS ?? 'ws://localhost:3001';
const DB_NAME: string = import.meta.env.VITE_SPACETIMEDB_DB ?? 'c2007f52296c94e0c7fb057d3cca532ce42a97a15b4820e0c60476a956be95ff';
const HTTP_HOST: string = import.meta.env.VITE_SPACETIMEDB_HOST ?? 'localhost:3001';
// Optional server-issued token for private-table access (used by E2E/dev setups).
const AUTH_TOKEN: string = import.meta.env.VITE_SPACETIMEDB_TOKEN ?? '';

// E2E test seam: when window.__MOCK_STDB__ is set, all table reads return empty
// and subscriptions apply immediately. This lets Playwright test every page's
// structure/empty-state deterministically WITHOUT any live SpacetimeDB — the
// dashboard previously hung in its loading skeleton when the WS to a loaded
// STDB was slow, making E2E flaky under concurrent benchmark load.
declare global {
  interface Window {
    __MOCK_STDB__?: boolean;
    /** E2E seed data: table name → array of row objects. When set, the mock
     *  connection returns these rows from table.iter() instead of empty. */
    __MOCK_DATA__?: Record<string, unknown[]>;
  }
}

function isMockDb(): boolean {
  return typeof window !== 'undefined' && window.__MOCK_STDB__ === true;
}

function mockRows(tableName: string): unknown[] {
  if (typeof window !== 'undefined' && window.__MOCK_DATA__) {
    return window.__MOCK_DATA__[tableName] ?? [];
  }
  return [];
}

// ---------------------------------------------------------------------------
// Singleton connection
// ---------------------------------------------------------------------------

let _conn: DbConnection | null = null;
let _ready = false;
let _error: string | null = null;
const _readyCallbacks: Array<() => void> = [];
const _errorCallbacks: Array<(err: string) => void> = [];

/** Fake connection for E2E. Every table yields an empty iterable; identity is
 *  null; subscriptions apply immediately. Satisfies the DbConnection surface
 *  the pages actually use (db.<table>.iter(), identity, subscriptionBuilder). */
function createMockConnection(): DbConnection {
  const emptyIterable = (tableName: string) => {
    const rows = mockRows(tableName);
    return { iter: () => rows as Iterable<unknown> };
  };
  const db = new Proxy(
    {},
    {
      get: (_t, prop: string) => emptyIterable(prop),
      has: () => true,
    },
  ) as unknown as DbConnection['db'];
  // The real SubscriptionBuilder is fluent: every hook returns the builder so
  // the app can chain .onApplied(cb).onError(cb).subscribe(queries). Our mock
  // fires onApplied immediately (ready) and no-ops the rest.
  const builder = {
    onApplied: (cb: () => void) => {
      cb();
      return builder;
    },
    onError: () => builder,
    subscribe: () => {},
  };
  return {
    db,
    identity: undefined,
    reducers: {} as never,
    realmName: '',
    databaseName: '',
    subscriptionBuilder: () => builder,
    callReducer: async () => {},
  } as unknown as DbConnection;
}

export function getConnection(): DbConnection {
  if (_conn) return _conn;
  if (isMockDb()) {
    _conn = createMockConnection();
    _ready = true;
    return _conn;
  }

  _conn = DbConnection.builder()
    .withUri(WS_URI)
    .withDatabaseName(DB_NAME)
    .withToken(AUTH_TOKEN)
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
      console.debug('[stmem] subscription applied');
      _ready = true;
      for (const cb of _readyCallbacks) cb();
      _readyCallbacks.length = 0;
    })
    .onError((ctx: any) => {
      const err = ctx?.event ?? ctx?.error ?? ctx;
      console.error('[stmem] subscription error:', err);
      _error = typeof err === 'string' ? err : (err as Error)?.message ?? JSON.stringify(err);
      for (const cb of _errorCallbacks) cb(_error);
      _errorCallbacks.length = 0;
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
  // Dynamic table-name access requires casting through unknown.
  const table = (conn.db as unknown as Record<string, { iter(): Iterable<T> }>)[tableName];
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
  const memories = getFromCache<Memory>('memory');
  const peers = getFromCache<Peer>('peer');
  const sessions = getFromCache<Session>('session');
  const workspaces = getFromCache<Workspace>('workspace');
  const now = Date.now() * 1000;
  const dayAgo = now - 86_400_000_000;
  return {
    totalMemories: memories.filter(m => m.isActive).length,
    activePeers: peers.length,
    sessionsToday: sessions.filter(s => s.createdAt > dayAgo).length,
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
  for (const m of getFromCache<Memory>('memory')) {
    results.push({
      action: `Memory: ${m.summary || m.content.slice(0, 60)}`,
      peer: m.peerId,
      time: m.createdAt ? fmt(m.createdAt) : 'unknown',
      type: 'memory',
    });
  }
  for (const s of getFromCache<Session>('session')) {
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
// Typed fetch functions
// ---------------------------------------------------------------------------

export async function fetchWorkspaces(): Promise<Workspace[]> { return getFromCache('workspace'); }

export async function fetchPeers(ws?: string): Promise<Peer[]> {
  const a = getFromCache<Peer>('peer');
  return ws ? a.filter(p => p.workspaceId === ws) : a;
}

export async function fetchSessions(ws?: string): Promise<Session[]> {
  const a = getFromCache<Session>('session');
  return ws ? a.filter(s => s.workspaceId === ws) : a;
}

export async function fetchMessages(sid: string): Promise<Message[]> {
  return getFromCache<Message>('message').filter(m => m.sessionId === sid);
}

export async function fetchMemories(
  ws?: string,
  type?: string,
  tier?: string,
  limit = 100,
): Promise<Memory[]> {
  let a = getFromCache<Memory>('memory');
  if (ws) a = a.filter(m => m.workspaceId === ws);
  if (type) a = a.filter(m => m.memoryType === type);
  if (tier) a = a.filter(m => m.tier === tier);
  return a.slice(0, limit);
}

export async function fetchDocuments(ws?: string): Promise<Document[]> {
  const a = getFromCache<Document>('document');
  return ws ? a.filter(d => d.workspaceId === ws) : a;
}

export async function fetchProfiles(): Promise<Profile[]> {
  return getFromCache('profile');
}

export async function fetchKgNodes(ws?: string): Promise<KgNode[]> {
  const a = getFromCache<KgNode>('kg_node');
  return ws ? a.filter(n => n.workspaceId === ws) : a;
}

export async function fetchKgEdges(): Promise<KgEdge[]> {
  return getFromCache('kg_edge');
}

export async function fetchKgNode(id: string): Promise<KgNode | null> {
  return getFromCache<KgNode>('kg_node').find(n => n.id === id) ?? null;
}

export async function fetchInsights(pid?: string): Promise<Insight[]> {
  const a = getFromCache<Insight>('insight');
  return pid ? a.filter(i => i.peerId === pid) : a;
}

export async function fetchTags(): Promise<Tag[]> {
  return getFromCache('tag');
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  return getDashboardStats();
}

export async function fetchRecentActivity(l = 10): Promise<RecentActivity[]> {
  return getRecentActivity(l);
}

// Local interface for Tour (not auto-generated by STDB bindings)
export interface Tour {
  id: string;
  workspaceId: string;
  name: string;
  description: string;
  stopsJson: string;
  isActive: boolean;
  createdAt: number;
  updatedAt: number;
}

export async function fetchTours(): Promise<Tour[]> {
  return getFromCache('tour');
}

export async function fetchTourStops(tourId: string): Promise<TourStop[]> {
  try {
    const rows = await executeSql(
      `SELECT * FROM tour_stop WHERE tour_id = '${tourId}'`,
    );
    return parseSqlResponse<TourStop>(rows);
  } catch { return []; }
}

export interface TourStop {
  id: string;
  tourId: string;
  title: string;
  description: string;
  stopOrder: number;
  content: string;
  createdAt: number;
}

export interface NoteWithBacklinks extends Note {
  backlinkCount: number;
  outgoingLinks: string;
}

export async function fetchNotesWithBacklinks(): Promise<NoteWithBacklinks[]> {
  const notes = getFromCache<Note>('note');
  const backlinks = getFromCache<NoteBacklink>('note_backlink');
  const blCount = new Map<string, number>();
  for (const bl of backlinks) {
    blCount.set(bl.targetNoteId, (blCount.get(bl.targetNoteId) || 0) + 1);
  }
  return notes.map(n => {
    const parsedLinks = extractWikilinks(n.content || '');
    return {
      ...n,
      backlinkCount: blCount.get(n.id) || 0,
      outgoingLinks: JSON.stringify(parsedLinks),
    };
  });
}

function extractWikilinks(content: string): string[] {
  const links: string[] = [];
  const re = /\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g;
  let m;
  while ((m = re.exec(content)) !== null) {
    links.push(m[1].trim());
  }
  return [...new Set(links)];
}

// ---------------------------------------------------------------------------
// Backward-compatible type aliases (for unmigrated pages, now properly typed)
// ---------------------------------------------------------------------------

export type DocumentRow = Document;
export type MemoryRow = Memory;
export type PeerRow = Peer;
export type SessionRow = Session;

// Re-exported helpers
export const formatMemoryTimestamp = fmt;
export const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

// ---------------------------------------------------------------------------
// SQL helpers — still used for one-off reads like hybrid search results
// (temp tables written by reducers)
// ---------------------------------------------------------------------------

const _executeHttp = (sql: string): Promise<unknown> => {
  return fetch(`http://${HTTP_HOST}/v1/database/${DB_NAME}/sql`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: sql,
  }).then(r => r.json());
};

export async function executeSql(sql: string): Promise<unknown> {
  try {
    return await _executeHttp(sql);
  } catch {
    return [];
  }
}

export function parseSqlResponse<T>(response: unknown): T[] {
  if (!response || !Array.isArray(response) || response.length === 0) return [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const table = (response as any[])[0];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const columns: string[] = (table?.schema?.elements ?? []).map((el: any) =>
    el?.name?.some ?? '?',
  );
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (table?.rows ?? []).map((row: any[]) => {
    const obj: Record<string, unknown> = {};
    columns.forEach((col, i) => { obj[col] = row[i]; });
    return obj as T;
  });
}

// ---------------------------------------------------------------------------
// Legacy polling hook — reads from SDK cache, re-renders on version change
// ---------------------------------------------------------------------------

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

function fmt(micros: string | number | bigint | null): string {
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
