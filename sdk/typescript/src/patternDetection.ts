/**
 * Server-side pattern detection — temporal clusters, entity co‑occurrences,
 * topic clusters. Wraps the corresponding SpacetimeDB reducers.
 *
 * Each reducer reads from the memory table server-side and writes results to
 * a result table (compute‑and‑store pattern). The SDK wrapper calls the
 * reducer, then reads from the result table.
 */
import type { ClientLike } from "./types";

// ---------------------------------------------------------------------------
// Result types
// ---------------------------------------------------------------------------

export interface TemporalClusterRecord {
  id: string;
  workspace_id: string;
  start_time: number;
  end_time: number;
  count: number;
  /** JSON array of memory IDs */
  memory_ids: string;
  /** JSON array of top summary terms */
  summary_terms: string;
  created_at: number;
}

export interface EntityCooccurrenceRecord {
  id: string;
  workspace_id: string;
  entity_a: string;
  entity_b: string;
  count: number;
  strength: number;
  created_at: number;
}

export interface TopicClusterRecord {
  id: string;
  workspace_id: string;
  topic: string;
  count: number;
  /** JSON array of memory IDs */
  memory_ids: string;
  /** JSON array of top terms */
  top_terms: string;
  avg_confidence: number;
  created_at: number;
}

// ---------------------------------------------------------------------------
// Temporal Clusters
// ---------------------------------------------------------------------------

/**
 * Detect temporal clusters — groups of memories stored close together in time.
 * Uses 30‑minute buckets. Requires admin auth.
 * Returns list of cluster records sorted by start_time descending.
 */
export async function detectTemporalClusters(
  client: ClientLike,
  workspaceId: string,
): Promise<TemporalClusterRecord[]> {
  await client._call("detect_temporal_clusters", [workspaceId]);
  return client._sqlExec(
    "SELECT * FROM temporal_cluster_result WHERE workspace_id = :ws ORDER BY start_time DESC",
    { ws: workspaceId },
  ) as Promise<TemporalClusterRecord[]>;
}

// ---------------------------------------------------------------------------
// Entity Co‑occurrences
// ---------------------------------------------------------------------------

/**
 * Detect entity co‑occurrence patterns — pairs of entities that frequently
 * appear together in the same memory (from entities_json).
 * Requires admin auth. Returns list sorted by count descending.
 */
export async function detectEntityCooccurrences(
  client: ClientLike,
  workspaceId: string,
): Promise<EntityCooccurrenceRecord[]> {
  await client._call("detect_entity_cooccurrences", [workspaceId]);
  return client._sqlExec(
    "SELECT * FROM entity_cooccurrence_result WHERE workspace_id = :ws ORDER BY count DESC",
    { ws: workspaceId },
  ) as Promise<EntityCooccurrenceRecord[]>;
}

// ---------------------------------------------------------------------------
// Topic Clusters
// ---------------------------------------------------------------------------

/**
 * Detect topic clusters — groups of memories organised by shared term frequency.
 * Requires admin auth. Returns list sorted by cluster size (count) descending.
 */
export async function detectTopicClusters(
  client: ClientLike,
  workspaceId: string,
): Promise<TopicClusterRecord[]> {
  await client._call("detect_topic_clusters", [workspaceId]);
  return client._sqlExec(
    "SELECT * FROM topic_cluster_result WHERE workspace_id = :ws ORDER BY count DESC",
    { ws: workspaceId },
  ) as Promise<TopicClusterRecord[]>;
}
