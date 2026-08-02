/**
 * React hooks for reactive access to the SpacetimeDB local cache.
 */
import { useState, useEffect } from 'react';
import {
  getConnection,
  isReady,
  getError,
  onReady,
  subscribe,
  getDashboardStats,
  getRecentActivity,
} from './spacetimedb';
export type { DashboardStats, RecentActivity } from './spacetimedb';

let _version = 0;
const _listeners = new Set<() => void>();

function bump() {
  _version++;
  for (const cb of _listeners) cb();
}

/**
 * Set up the connection and subscriptions. Call once from App root.
 */
export function initReactiveDb() {
  getConnection();

  // Subscribe to all tables the frontend needs
  // Note: Large tables are limited to prevent performance issues.
  // Full data access is available via the SDK/API for batch operations.
  subscribe([
    // Small tables — no limit needed
    'SELECT * FROM workspace',
    'SELECT * FROM peer',
    'SELECT * FROM session',
    'SELECT * FROM session_participant',
    'SELECT * FROM memory_feedback',
    'SELECT * FROM context_directory',
    'SELECT * FROM directory_memory_link',
    'SELECT * FROM profile',
    'SELECT * FROM kg_node',
    'SELECT * FROM kg_edge',
    'SELECT * FROM kg_community',
    'SELECT * FROM insight',
    'SELECT * FROM tag',
    'SELECT * FROM document',
    'SELECT * FROM doc_chunk',
    'SELECT * FROM note',
    'SELECT * FROM note_backlink',
    'SELECT * FROM note_block',
    'SELECT * FROM block_reference',
    'SELECT * FROM account',
    'SELECT * FROM tour',
    'SELECT * FROM tour_stop',
    'SELECT * FROM merge_suggestion',
    'SELECT * FROM space_permission',
    'SELECT * FROM memory_meta',
    'SELECT * FROM webhook',
    'SELECT * FROM webhook_delivery',
    'SELECT * FROM observation',
    'SELECT * FROM context_tree',
    'SELECT * FROM review_item',
    'SELECT * FROM fact_triple',
    'SELECT * FROM directive',

    // Large tables — intentionally NOT subscribed via WS.
    // STDB v2's subscription engine rejects WHERE/LIMIT/ORDER BY forms and a
    // full-table subscription of `memory` (tens of thousands of rows) never
    // settles, which blocks `ready` for the ENTIRE dashboard (every page hangs
    // in its loading skeleton forever). These tables are fetched on demand via
    // the SQL proxy / HTTP endpoint. See fetchTable in spacetimedb.ts.
  ]);

  // Bump version when initial data lands
  onReady(() => bump());
}

/**
 * Hook that re-renders when any subscribed table changes.
 */
export function useReactiveDb() {
  const [ready, setReady] = useState(isReady());
  const [error, setError] = useState<string | null>(getError());
  const [, setVersion] = useState(_version);

  useEffect(() => {
    const fn = () => {
      setVersion(_version);
      setReady(isReady());
      setError(getError());
    };
    _listeners.add(fn);
    return () => { _listeners.delete(fn); };
  }, []);

  return {
    ready,
    error,
    stats: getDashboardStats(),
    activity: getRecentActivity(8),
  };
}

/**
 * Hook that returns rows from a table in the local cache.
 */
export function useTable<T>(tableName: string): {
  data: T[];
  loading: boolean;
  error: string | null;
} {
  const { ready, error } = useReactiveDb();
  const conn = getConnection();
  const table = (conn.db as any)[tableName];
  const data: T[] = table ? Array.from(table.iter()) : [];
  return { data, loading: !ready, error };
}
