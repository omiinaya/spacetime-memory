/**
 * New features — MemoryMeta, Webhook, Observation, ContextTree, Review.
 *
 * Wraps the corresponding SpacetimeDB reducers for each domain.
 */
import type { ClientLike } from "./types";

// ---------------------------------------------------------------------------
// MemoryMeta — extensible metadata on memories
// ---------------------------------------------------------------------------

/** Set or update metadata on a memory (upsert). */
export async function setMemoryMeta(
  client: ClientLike,
  workspaceId: string,
  memoryId: string,
  category: string = "",
  immutable: boolean = false,
  extraJson: string = "{}",
): Promise<Record<string, unknown>> {
  return client._call("set_memory_meta", [workspaceId, memoryId, category, immutable, extraJson]);
}

/** Get metadata for a single memory by its ID. */
export async function getMemoryMeta(
  client: ClientLike,
  memoryId: string,
): Promise<Record<string, unknown> | null> {
  await client._call("get_memory_meta", [memoryId]);
  const rows = await client._query("memory_meta", "", { memory_id: memoryId });
  return rows.length > 0 ? rows[0] : null;
}

/** Batch-set metadata on multiple memories at once. */
export async function batchSetMemoryMeta(
  client: ClientLike,
  workspaceId: string,
  idsJson: string,
  category: string = "",
  immutable: boolean = false,
): Promise<Record<string, unknown>> {
  return client._call("batch_set_memory_meta", [workspaceId, idsJson, category, immutable]);
}

/** List all memory-metadata entries for a workspace. */
export async function listMemoryMeta(
  client: ClientLike,
  workspaceId: string,
): Promise<Record<string, unknown>[]> {
  return client._query("memory_meta", workspaceId);
}

// ---------------------------------------------------------------------------
// Webhook — registered callback URLs for workspace events
// ---------------------------------------------------------------------------

/** Register a new webhook for workspace events. */
export async function createWebhook(
  client: ClientLike,
  workspaceId: string,
  name: string,
  url: string,
  eventTypes: string = "[]",
  secret: string = "",
): Promise<Record<string, unknown>> {
  return client._call("create_webhook", [workspaceId, name, url, eventTypes, secret]);
}

/** Update an existing webhook's mutable fields. */
export async function updateWebhook(
  client: ClientLike,
  webhookId: string,
  name: string = "",
  url: string = "",
  eventTypes: string = "",
  isActive: boolean = true,
): Promise<Record<string, unknown>> {
  return client._call("update_webhook", [webhookId, name, url, eventTypes, isActive]);
}

/** Delete a webhook and its pending deliveries. */
export async function deleteWebhook(
  client: ClientLike,
  webhookId: string,
): Promise<Record<string, unknown>> {
  return client._call("delete_webhook", [webhookId]);
}

/** List all webhooks registered in a workspace. */
export async function listWebhooks(
  client: ClientLike,
  workspaceId: string,
): Promise<Record<string, unknown>[]> {
  await client._call("list_webhooks", [workspaceId]);
  return client._sqlExec(
    "SELECT * FROM webhook_list_result WHERE workspace_id = :ws ORDER BY created_at ASC",
    { ws: workspaceId },
  );
}

/** Manually fire a webhook event (creates pending deliveries). */
export async function fireWebhookEvent(
  client: ClientLike,
  workspaceId: string,
  eventType: string,
  payload: string = "{}",
): Promise<Record<string, unknown>> {
  return client._call("fire_webhook_event", [workspaceId, eventType, payload]);
}

// ---------------------------------------------------------------------------
// Observation — discrete knowledge-claim records
// ---------------------------------------------------------------------------

/** Create a discrete knowledge-claim observation. */
export async function createObservation(
  client: ClientLike,
  workspaceId: string,
  content: string,
  summary: string = "",
  evidenceJson: string = "[]",
  observationType: string = "fact",
  confidence: number = 0.8,
): Promise<Record<string, unknown>> {
  return client._call("create_observation", [
    workspaceId, content, summary, evidenceJson, observationType, confidence,
  ]);
}

/** Update an existing observation's mutable fields. */
export async function updateObservation(
  client: ClientLike,
  id: string,
  content: string = "",
  summary: string = "",
  confidence: number = 0.0,
): Promise<Record<string, unknown>> {
  return client._call("update_observation", [id, content, summary, confidence]);
}

/** Delete an observation by ID. */
export async function deleteObservation(
  client: ClientLike,
  id: string,
): Promise<Record<string, unknown>> {
  return client._call("delete_observation", [id]);
}

/** List all observations for a workspace (reads from json_data result). */
export async function listObservations(
  client: ClientLike,
  workspaceId: string,
): Promise<Record<string, unknown>[]> {
  await client._call("list_observations", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM observation_list_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
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

// ---------------------------------------------------------------------------
// ContextTree — hierarchical path-based context entries
// ---------------------------------------------------------------------------

/** Create or update a hierarchical context entry (upsert by path). */
export async function setContext(
  client: ClientLike,
  workspaceId: string,
  path: string,
  content: string,
  priority: number = 0.0,
  isGlobal: boolean = false,
): Promise<Record<string, unknown>> {
  return client._call("set_context", [workspaceId, path, content, priority, isGlobal]);
}

/** Delete a context entry by its primary key id. */
export async function deleteContext(
  client: ClientLike,
  contextId: string,
): Promise<Record<string, unknown>> {
  return client._call("delete_context", [contextId]);
}

/** List all context entries for a workspace (reads from results_json). */
export async function listContexts(
  client: ClientLike,
  workspaceId: string,
): Promise<Record<string, unknown>[]> {
  await client._call("list_contexts", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM context_tree_result WHERE workspace_id = :ws AND query_id = 'list' ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].results_json) {
    try {
      return JSON.parse(rows[0].results_json as string) as Record<string, unknown>[];
    } catch {
      // fall through
    }
  }
  return [];
}

/** Resolve the most specific context entries for a given path. */
export async function resolveContext(
  client: ClientLike,
  workspaceId: string,
  path: string,
): Promise<Record<string, unknown>[]> {
  await client._call("resolve_context", [workspaceId, path]);
  const rows = await client._sqlExec(
    "SELECT * FROM context_tree_result WHERE workspace_id = :ws AND query_id = :qid ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId, qid: path },
  );
  if (rows.length > 0 && rows[0].results_json) {
    try {
      return JSON.parse(rows[0].results_json as string) as Record<string, unknown>[];
    } catch {
      // fall through
    }
  }
  return [];
}

// ---------------------------------------------------------------------------
// Review — SM-2 spaced-repetition review scheduler
// ---------------------------------------------------------------------------

/** Schedule a memory for review using SM-2 spaced repetition. */
export async function scheduleReview(
  client: ClientLike,
  workspaceId: string,
  memoryId: string,
  userId: string,
): Promise<Record<string, unknown>> {
  return client._call("schedule_review", [workspaceId, memoryId, userId]);
}

/** Perform a review on an existing ReviewItem with a grade (0–6). */
export async function performReview(
  client: ClientLike,
  reviewId: string,
  grade: number,
): Promise<Record<string, unknown>> {
  return client._call("perform_review", [reviewId, grade]);
}

/** Get all review items due now for a workspace/user. */
export async function getDueReviews(
  client: ClientLike,
  workspaceId: string,
  userId: string,
): Promise<Record<string, unknown>[]> {
  await client._call("get_due_reviews", [workspaceId, userId]);
  const rows = await client._sqlExec(
    "SELECT * FROM review_result WHERE workspace_id = :ws AND user_id = :uid ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId, uid: userId },
  );
  if (rows.length > 0 && rows[0].items_json) {
    try {
      return JSON.parse(rows[0].items_json as string) as Record<string, unknown>[];
    } catch {
      // fall through
    }
  }
  return [];
}

/** Get review statistics for a workspace/user. */
export async function getReviewStats(
  client: ClientLike,
  workspaceId: string,
  userId: string,
): Promise<Record<string, unknown> | null> {
  await client._call("get_review_stats", [workspaceId, userId]);
  const rows = await client._sqlExec(
    "SELECT * FROM review_result WHERE workspace_id = :ws AND user_id = :uid ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId, uid: userId },
  );
  if (rows.length > 0 && rows[0].items_json) {
    try {
      return JSON.parse(rows[0].items_json as string) as Record<string, unknown>;
    } catch {
      // fall through
    }
  }
  return null;
}