/**
 * Reflection Loop — structured self-reflection sessions for AI agents.
 *
 * Each session is a multi-cycle process where an agent reflects on memories,
 * stores insights by type (patterns, contradictions, gaps, observations,
 * connections, syntheses), and completes with a summary status.
 *
 * Wraps the corresponding SpacetimeDB reducers.
 */
import type { ClientLike } from "./types";

// ---------------------------------------------------------------------------
// Result types
// ---------------------------------------------------------------------------

export interface ReflectionSessionRecord {
  id: string;
  workspace_id: string;
  peer_id: string;
  config_json: string;
  cycles_completed: number;
  status: string;
  insight_count: number;
  started_at: number;
  completed_at: number | null;
  created_at: number;
}

export interface ReflectionInsightRecord {
  id: string;
  workspace_id: string;
  session_id: string;
  content: string;
  confidence: number;
  insight_type: string;
  source_memory_ids: string;
  source_note_ids: string;
  cycle: number;
  created_at: number;
}

export type InsightType =
  | "pattern"
  | "contradiction"
  | "gap"
  | "observation"
  | "connection"
  | "synthesis";

// ---------------------------------------------------------------------------
// Reflection Session CRUD
// ---------------------------------------------------------------------------

/**
 * Create a new reflection session.
 * Returns the created session record.
 */
export async function createReflectionSession(
  client: ClientLike,
  workspaceId: string,
  peerId: string,
  config: Record<string, unknown> = {},
): Promise<Record<string, any>> {
  const configJson = JSON.stringify(config);
  await client._call("create_reflection_session", [
    workspaceId,
    peerId,
    configJson,
  ]);
  const rows = await client._sqlExec(
    "SELECT * FROM reflection_session_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].json_data) {
    try {
      return JSON.parse(rows[0].json_data as string) as Record<string, any>;
    } catch {
      return rows[0] as Record<string, any>;
    }
  }
  return rows[0] as Record<string, any>;
}

/**
 * Start (or advance) a reflection cycle within a session.
 * Returns the updated session state.
 */
export async function startReflectionCycle(
  client: ClientLike,
  workspaceId: string,
  sessionId: string,
): Promise<Record<string, any>> {
  await client._call("start_reflection_cycle", [workspaceId, sessionId]);
  const rows = await client._sqlExec(
    "SELECT * FROM reflection_session_result WHERE workspace_id = :ws AND id = :sid ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId, sid: sessionId },
  );
  if (rows.length > 0 && rows[0].json_data) {
    try {
      return JSON.parse(rows[0].json_data as string) as Record<string, any>;
    } catch {
      return rows[0] as Record<string, any>;
    }
  }
  return rows[0] as Record<string, any>;
}

/**
 * Store a reflection insight for a session.
 * sourceMemoryIds and sourceNoteIds are arrays of IDs serialised as JSON.
 */
export async function storeReflectionInsight(
  client: ClientLike,
  workspaceId: string,
  sessionId: string,
  content: string,
  confidence: number = 0.5,
  insightType: InsightType = "observation",
  sourceMemoryIds: string[] = [],
  sourceNoteIds: string[] = [],
): Promise<Record<string, any>> {
  const memIdsJson = JSON.stringify(sourceMemoryIds);
  const noteIdsJson = JSON.stringify(sourceNoteIds);
  await client._call("store_reflection_insight", [
    workspaceId,
    sessionId,
    content,
    confidence,
    insightType,
    memIdsJson,
    noteIdsJson,
  ]);
  const rows = await client._sqlExec(
    "SELECT * FROM reflection_insight_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].json_data) {
    try {
      return JSON.parse(rows[0].json_data as string) as Record<string, any>;
    } catch {
      return rows[0] as Record<string, any>;
    }
  }
  return rows[0] as Record<string, any>;
}

/**
 * Complete a reflection session with a final status
 * (e.g. "completed", "aborted", "archived").
 */
export async function completeReflectionSession(
  client: ClientLike,
  workspaceId: string,
  sessionId: string,
  status: string = "completed",
): Promise<Record<string, any>> {
  await client._call("complete_reflection_session", [
    workspaceId,
    sessionId,
    status,
  ]);
  const rows = await client._sqlExec(
    "SELECT * FROM reflection_session_result WHERE workspace_id = :ws AND id = :sid ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId, sid: sessionId },
  );
  if (rows.length > 0 && rows[0].json_data) {
    try {
      return JSON.parse(rows[0].json_data as string) as Record<string, any>;
    } catch {
      return rows[0] as Record<string, any>;
    }
  }
  return rows[0] as Record<string, any>;
}

// ---------------------------------------------------------------------------
// Query helpers
// ---------------------------------------------------------------------------

/**
 * Get all reflection sessions for a workspace.
 */
export async function getReflectionSessions(
  client: ClientLike,
  workspaceId: string,
): Promise<Record<string, any>[]> {
  await client._call("get_reflection_sessions", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM reflection_session_result WHERE workspace_id = :ws ORDER BY created_at DESC",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].json_data) {
    try {
      return JSON.parse(rows[0].json_data as string) as Record<string, any>[];
    } catch {
      // fall through to individual rows
    }
  }
  return rows as Record<string, any>[];
}

/**
 * Get all insights belonging to a specific reflection session.
 */
export async function getReflectionInsights(
  client: ClientLike,
  workspaceId: string,
  sessionId: string,
): Promise<Record<string, any>[]> {
  await client._call("get_reflection_insights", [workspaceId, sessionId]);
  const rows = await client._sqlExec(
    "SELECT * FROM reflection_insight_result WHERE workspace_id = :ws AND session_id = :sid ORDER BY created_at ASC",
    { ws: workspaceId, sid: sessionId },
  );
  if (rows.length > 0 && rows[0].json_data) {
    try {
      return JSON.parse(rows[0].json_data as string) as Record<string, any>[];
    } catch {
      // fall through
    }
  }
  return rows as Record<string, any>[];
}

// ---------------------------------------------------------------------------
// Deletion
// ---------------------------------------------------------------------------

/**
 * Delete a reflection session and all its associated insights.
 */
export async function deleteReflectionSession(
  client: ClientLike,
  workspaceId: string,
  sessionId: string,
): Promise<Record<string, any>> {
  return client._call("delete_reflection_session", [
    workspaceId,
    sessionId,
  ]) as Promise<Record<string, any>>;
}
