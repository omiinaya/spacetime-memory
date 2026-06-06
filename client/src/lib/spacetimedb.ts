/**
 * SpacetimeDB HTTP SQL API client for the spacetime-memory frontend.
 *
 * The API accepts SQL queries via POST and returns JSON arrays of tables.
 * Each table has a schema with column names and rows as positional arrays.
 *
 * Usage:
 *   import { fetchMemories, fetchPeers, callReducer } from '@/lib/spacetimedb';
 *
 * For real-time updates, use usePollingQuery() hook.
 */

import { useEffect, useState, useCallback, useRef } from 'react';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_BASE = 'http://localhost:3001/v1/database/spacetime-memory';

// ---------------------------------------------------------------------------
// Row interfaces (snake_case columns from SpacetimeDB)
// ---------------------------------------------------------------------------

export interface WorkspaceRow {
  id: string;
  name: string;
  description: string;
  created_at: string | null;
}

export interface PeerRow {
  id: string;
  workspace_id: string;
  name: string;
  peer_type: string;
  metadata_json: string;
  created_at: string | null;
}

export interface SessionRow {
  id: string;
  workspace_id: string;
  name: string;
  summary: string;
  status: string;
  created_at: string | null;
}

export interface SessionParticipantRow {
  id: string;
  session_id: string;
  peer_id: string;
  role: string;
  joined_at: string | null;
}

export interface MessageRow {
  id: string;
  session_id: string;
  sender_id: string;
  content: string;
  message_type: string;
  created_at: string | null;
}

export interface MemoryRow {
  id: string;
  workspace_id: string;
  peer_id: string;
  observer_id: string;
  memory_type: string;
  content: string;
  summary: string;
  entities_json: string;
  confidence: number;
  is_active: boolean;
  tier: string;
  access_count: number;
  strength: number;
  trust_score: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface DocumentRow {
  id: string;
  workspace_id: string;
  peer_id: string;
  title: string;
  content: string;
  content_type: string;
  source_url: string;
  file_size: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProfileRow {
  id: string;
  peer_id: string;
  static_facts_json: string;
  dynamic_context_json: string;
  preferences_json: string;
  tags_json: string;
  updated_at: string | null;
}

export interface KgNodeRow {
  id: string;
  workspace_id: string;
  label: string;
  node_type: string;
  summary: string;
  metadata_json: string;
  community_id: number;
  created_at: string | null;
}

export interface KgEdgeRow {
  id: string;
  workspace_id: string;
  source_node_id: string;
  target_node_id: string;
  relation: string;
  weight: number;
  confidence: string;
  metadata_json: string;
  created_at: string | null;
}

export interface HybridResultRow {
  id: string;
  workspace_id: string;
  query_hash: string;
  entity_type: string;
  entity_id: string;
  content: string;
  score: number;
  strategy: string;
  created_at: string | null;
}

export interface InsightRow {
  id: string;
  workspace_id: string;
  peer_id: string;
  content: string;
  insight_type: string;
  source_memory_ids: string;
  created_at: string | null;
}

export interface TagRow {
  id: string;
  name: string;
  color: string;
  created_at: string | null;
}

// ---------------------------------------------------------------------------
// SQL API helpers
// ---------------------------------------------------------------------------

interface ColumnSchema {
  name: { some: string };
}

interface SqlTableResponse {
  schema: { elements: ColumnSchema[] };
  rows: unknown[][];
}

type SqlResponse = SqlTableResponse[];

export function parseSqlResponse<T>(response: SqlResponse): T[] {
  if (!response || response.length === 0) return [];
  const table = response[0];
  const columns = table.schema.elements.map((el) => el.name.some);
  return table.rows.map((row) => {
    const obj: Record<string, unknown> = {};
    columns.forEach((col, idx) => {
      obj[col] = row[idx];
    });
    return obj as unknown as T;
  });
}

export async function executeSql(sql: string): Promise<SqlResponse> {
  const res = await fetch(`${API_BASE}/sql`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: sql,
  });
  if (!res.ok) {
    throw new Error(`SpacetimeDB SQL error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Reducer call helper
// ---------------------------------------------------------------------------

export async function callReducer(name: string, args: unknown[]): Promise<Response> {
  const res = await fetch(`${API_BASE}/call/${name}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Reducer '${name}' error (${res.status}): ${body.slice(0, 200)}`);
  }
  return res;
}

// ---------------------------------------------------------------------------
// Table fetchers
// ---------------------------------------------------------------------------

export async function fetchWorkspaces(): Promise<WorkspaceRow[]> {
  const res = await executeSql('SELECT * FROM workspace ORDER BY created_at DESC');
  return parseSqlResponse<WorkspaceRow>(res);
}

export async function fetchPeers(workspaceId?: string): Promise<PeerRow[]> {
  let sql = 'SELECT * FROM peer';
  if (workspaceId) sql += ` WHERE workspace_id = '${esc(workspaceId)}'`;
  sql += ' ORDER BY created_at DESC';
  const res = await executeSql(sql);
  return parseSqlResponse<PeerRow>(res);
}

export async function fetchSessions(workspaceId?: string): Promise<SessionRow[]> {
  let sql = 'SELECT * FROM session';
  if (workspaceId) sql += ` WHERE workspace_id = '${esc(workspaceId)}'`;
  sql += ' ORDER BY created_at DESC';
  const res = await executeSql(sql);
  return parseSqlResponse<SessionRow>(res);
}

export async function fetchMessages(sessionId: string): Promise<MessageRow[]> {
  const sql = `SELECT * FROM message WHERE session_id = '${esc(sessionId)}' ORDER BY created_at ASC`;
  const res = await executeSql(sql);
  return parseSqlResponse<MessageRow>(res);
}

export async function fetchMemories(
  workspaceId?: string,
  memoryType?: string,
  tier?: string,
  limit = 100,
): Promise<MemoryRow[]> {
  const clauses: string[] = [];
  if (workspaceId) clauses.push(`workspace_id = '${esc(workspaceId)}'`);
  if (memoryType) clauses.push(`memory_type = '${esc(memoryType)}'`);
  if (tier) clauses.push(`tier = '${esc(tier)}'`);
  const where = clauses.length > 0 ? ` WHERE ${clauses.join(' AND ')}` : '';
  const sql = `SELECT * FROM memory${where} ORDER BY updated_at DESC LIMIT ${limit}`;
  const res = await executeSql(sql);
  return parseSqlResponse<MemoryRow>(res);
}

export async function fetchDocuments(workspaceId?: string): Promise<DocumentRow[]> {
  let sql = 'SELECT * FROM document';
  if (workspaceId) sql += ` WHERE workspace_id = '${esc(workspaceId)}'`;
  sql += ' ORDER BY updated_at DESC';
  const res = await executeSql(sql);
  return parseSqlResponse<DocumentRow>(res);
}

export async function fetchProfiles(): Promise<ProfileRow[]> {
  const res = await executeSql('SELECT * FROM profile ORDER BY updated_at DESC');
  return parseSqlResponse<ProfileRow>(res);
}

export async function fetchKgNodes(workspaceId?: string): Promise<KgNodeRow[]> {
  let sql = 'SELECT * FROM kg_node';
  if (workspaceId) sql += ` WHERE workspace_id = '${esc(workspaceId)}'`;
  sql += ' LIMIT 500';
  const res = await executeSql(sql);
  return parseSqlResponse<KgNodeRow>(res);
}

export async function fetchKgEdges(): Promise<KgEdgeRow[]> {
  const res = await executeSql('SELECT * FROM kg_edge LIMIT 2000');
  return parseSqlResponse<KgEdgeRow>(res);
}

export async function fetchKgNode(id: string): Promise<KgNodeRow | null> {
  const res = await executeSql(`SELECT * FROM kg_node WHERE id = '${esc(id)}'`);
  const rows = parseSqlResponse<KgNodeRow>(res);
  return rows[0] ?? null;
}

export async function fetchInsights(peerId?: string): Promise<InsightRow[]> {
  let sql = 'SELECT * FROM insight';
  if (peerId) sql += ` WHERE peer_id = '${esc(peerId)}'`;
  sql += ' ORDER BY created_at DESC';
  const res = await executeSql(sql);
  return parseSqlResponse<InsightRow>(res);
}

export async function fetchTags(): Promise<TagRow[]> {
  const res = await executeSql('SELECT * FROM tag ORDER BY name ASC');
  return parseSqlResponse<TagRow>(res);
}

// ---------------------------------------------------------------------------
// Aggregation / query helpers
// ---------------------------------------------------------------------------

export async function countRows(table: string, where?: string): Promise<number> {
  let sql = `SELECT COUNT(*) AS count FROM ${table}`;
  if (where) sql += ` WHERE ${where}`;
  const res = await executeSql(sql);
  const rows = parseSqlResponse<{ count: number }>(res);
  return rows[0]?.count ?? 0;
}

export async function sumColumn(table: string, column: string, where?: string): Promise<number> {
  let sql = `SELECT COALESCE(SUM(${column}), 0) AS total FROM ${table}`;
  if (where) sql += ` WHERE ${where}`;
  const res = await executeSql(sql);
  const rows = parseSqlResponse<{ total: number }>(res);
  return rows[0]?.total ?? 0;
}

// ---------------------------------------------------------------------------
// Dashboard-specific queries
// ---------------------------------------------------------------------------

export interface DashboardStats {
  totalMemories: number;
  activePeers: number;
  sessionsToday: number;
  totalWorkspaces: number;
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  const todayStart = Date.now() * 1000 - 86400_000_000; // 24h ago in micros
  const [totalMemories, activePeers, sessionsToday, totalWorkspaces] = await Promise.all([
    countRows('memory', "is_active = true"),
    countRows('peer'),
    countRows('session', `created_at > ${todayStart}`),
    countRows('workspace'),
  ]);
  return { totalMemories, activePeers, sessionsToday, totalWorkspaces };
}

export interface RecentActivity {
  action: string;
  peer: string;
  time: string;
  type: 'memory' | 'session' | 'insight';
}

export async function fetchRecentActivity(limit = 10): Promise<RecentActivity[]> {
  const results: RecentActivity[] = [];

  // Recent memories
  const memories = parseSqlResponse<MemoryRow>(
    await executeSql(`SELECT * FROM memory ORDER BY created_at DESC LIMIT ${limit}`),
  );
  for (const m of memories) {
    results.push({
      action: `Memory: ${m.summary || m.content.slice(0, 60)}`,
      peer: m.peer_id,
      time: formatTimestamp(m.created_at),
      type: 'memory',
    });
  }

  // Recent sessions
  const sessions = parseSqlResponse<SessionRow>(
    await executeSql(`SELECT * FROM session ORDER BY created_at DESC LIMIT ${limit}`),
  );
  for (const s of sessions) {
    results.push({
      action: `Session: ${s.name || s.id}`,
      peer: s.id,
      time: formatTimestamp(s.created_at),
      type: 'session',
    });
  }

  // Sort by time desc, take limit
  results.sort((a, b) => b.time.localeCompare(a.time));
  return results.slice(0, limit);
}

// ---------------------------------------------------------------------------
// Time helpers
// ---------------------------------------------------------------------------

function formatTimestamp(ts: string | null | number): string {
  if (!ts) return 'unknown';
  const num = typeof ts === 'number' ? ts : Number(ts);
  const ms = num / 1000; // microseconds → milliseconds
  const diff = Date.now() - ms;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.floor(hr / 24);
  return `${days}d ago`;
}

export function formatMemoryTimestamp(micros: string | null): string {
  return formatTimestamp(micros);
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// SQL escape
// ---------------------------------------------------------------------------

function esc(val: string): string {
  return val.replace(/'/g, "''");
}

// ---------------------------------------------------------------------------
// React hook — polling query
// ---------------------------------------------------------------------------

interface PollingState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function usePollingQuery<T>(
  fetcher: () => Promise<T>,
  intervalMs = 5000,
): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fetcherRef = useRef(fetcher);

  fetcherRef.current = fetcher;

  const fetchData = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    intervalRef.current = setInterval(fetchData, intervalMs);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchData, intervalMs]);

  return { data, loading, error, refetch: fetchData };
}
