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
  subscribe([
    'SELECT * FROM workspace',
    'SELECT * FROM peer',
    'SELECT * FROM session',
    'SELECT * FROM session_participant',
    'SELECT * FROM message',
    'SELECT * FROM memory',
    'SELECT * FROM memory_feedback',
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
