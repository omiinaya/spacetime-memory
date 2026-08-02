/**
 * FactTriple — subject-predicate-object knowledge triple operations.
 *
 * Wraps the corresponding SpacetimeDB reducers for each domain.
 */
import type { ClientLike } from "./types";

// ---------------------------------------------------------------------------
// FactTriple — subject-predicate-object knowledge triples
// ---------------------------------------------------------------------------

/** Store a fact triple (subject-predicate-object). */
export async function storeFactTriple(
  client: ClientLike,
  workspaceId: string,
  subjectId: string,
  predicate: string,
  objectId: string,
  confidence: number = 1.0,
  validFrom: number = 0,
  validTo: number = 0,
): Promise<Record<string, unknown>> {
  return client._call("store_fact_triple", [
    workspaceId, subjectId, predicate, objectId, confidence, validFrom, validTo,
  ]);
}

/** Update the confidence score of an existing fact triple. */
export async function updateFactTripleConfidence(
  client: ClientLike,
  tripleId: string,
  confidence: number,
): Promise<Record<string, unknown>> {
  return client._call("update_fact_triple_confidence", [tripleId, confidence]);
}

/** Delete a fact triple by its ID. */
export async function deleteFactTriple(
  client: ClientLike,
  tripleId: string,
): Promise<Record<string, unknown>> {
  return client._call("delete_fact_triple", [tripleId]);
}

/** Set temporal validity bounds on a fact triple. */
export async function setFactTripleTemporalBounds(
  client: ClientLike,
  tripleId: string,
  validFrom: number,
  validTo: number,
): Promise<Record<string, unknown>> {
  return client._call("set_fact_triple_temporal_bounds", [tripleId, validFrom, validTo]);
}

/** List all fact triples for a workspace (reads from fact_triple_list_result). */
export async function listFactTriples(
  client: ClientLike,
  workspaceId: string,
): Promise<Record<string, unknown>[]> {
  await client._call("list_fact_triples", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM fact_triple_list_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].json_data) {
    try {
      return JSON.parse(rows[0].json_data as string) as Record<string, unknown>[];
    } catch {
      // fall through
    }
  }
  return [];
}
