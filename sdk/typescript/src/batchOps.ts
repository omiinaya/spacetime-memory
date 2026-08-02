/**
 * BatchOps — batch memory operations (Phase 2 reducer implementations).
 *
 * Wraps the corresponding SpacetimeDB reducers for each domain.
 */
import type { ClientLike } from "./types";

// ---------------------------------------------------------------------------
// BatchOps — batch memory operations using dedicated reducers
// ---------------------------------------------------------------------------

/**
 * Batch-update multiple memories with the same set of field changes.
 * Uses the Phase 2 dedicated reducer instead of client-side iteration.
 */
export async function batchUpdateMemories(
  client: ClientLike,
  workspaceId: string,
  memoryIds: string[],
  updates: Record<string, unknown>,
): Promise<{ status: string; updated: number; errors?: string[] }> {
  const result = await client._call("batch_update_memories", [
    workspaceId, JSON.stringify(memoryIds), JSON.stringify(updates),
  ]);
  if (result && typeof result === "object") {
    return result as { status: string; updated: number; errors?: string[] };
  }
  return { status: "ok", updated: memoryIds.length };
}

/**
 * Batch-delete (deactivate) multiple memories by ID.
 * Uses the Phase 2 reducer with workspace scoping.
 */
export async function batchDeleteMemories(
  client: ClientLike,
  workspaceId: string,
  memoryIds: string[],
): Promise<Record<string, unknown>> {
  if (memoryIds.length === 0) return { status: "ok" };
  return client._call("batch_delete_memories", [workspaceId, JSON.stringify(memoryIds)]);
}

/**
 * Batch-set the category/metadata field on multiple memories at once.
 */
export async function batchSetCategory(
  client: ClientLike,
  workspaceId: string,
  memoryIds: string[],
  category: string,
): Promise<Record<string, unknown>> {
  return client._call("batch_set_category", [workspaceId, JSON.stringify(memoryIds), category]);
}
