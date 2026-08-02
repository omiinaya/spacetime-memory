/**
 * Tag CRUD, memory tagging.
 */
import type { ClientLike, TagRecord } from "./types";
import { queryHash } from "./helpers";

export async function createTag(client: ClientLike, workspaceId: string, name: string, color?: string): Promise<void> {
  return client._call("create_tag", [workspaceId, name, color ?? ""]);
}

export async function tagMemory(client: ClientLike, tagId: string, memoryId: string): Promise<void> {
  return client._call("tag_memory", [tagId, memoryId]);
}

export async function untagMemory(client: ClientLike, tagId: string, memoryId: string): Promise<void> {
  return client._call("untag_memory", [tagId, memoryId]);
}

export async function batchTagMemories(client: ClientLike, tagId: string, memoryIds: string[]): Promise<void> {
  if (memoryIds.length === 0) return;
  return client._call("batch_tag_memories", [tagId, JSON.stringify(memoryIds)]);
}

export async function batchUntagMemories(client: ClientLike, tagId: string, memoryIds: string[]): Promise<void> {
  if (memoryIds.length === 0) return;
  return client._call("batch_untag_memories", [tagId, JSON.stringify(memoryIds)]);
}

export async function listTags(client: ClientLike, workspaceId: string): Promise<TagRecord[]> {
  await client._call("list_tags", [workspaceId]);
  const rows = await client._sqlExec("SELECT row_json FROM tag LIMIT 1000", {});
  return rows as TagRecord[];
}

export async function deleteTag(client: ClientLike, tagId: string): Promise<void> {
  return client._call("delete_tag", [tagId]);
}

export async function listTagsByMemory(client: ClientLike, memoryId: string): Promise<Record<string, unknown>[]> {
  await client._call("list_tags_by_memory", [memoryId]);
  return client._sqlExec(
    "SELECT id, memory_id, tag_id, tag_name, tag_color FROM memory_tag_result WHERE memory_id = :mid",
    { mid: memoryId },
  );
}

export async function updateTag(client: ClientLike, tagId: string, name: string = "", color: string = "#808080"): Promise<void> {
  return client._call("update_tag", [tagId, name, color]);
}

export async function searchByTags(client: ClientLike, workspaceId: string, tagIds: string[], query: string = "", limit: number = 10): Promise<Record<string, unknown>[]> {
  let embJson = "[]";
  if (query) {
    const queryText = `Represent this sentence for searching relevant passages: ${query}`;
    const emb = await client._embed(queryText);
    embJson = emb ? JSON.stringify(emb) : "[]";
  }
  const tagIdsJson = JSON.stringify(tagIds);
  await client._call("search_by_tags", [workspaceId, tagIdsJson, embJson, limit]);
  const qhash = queryHash(`tagged:${tagIdsJson}`);
  const rows = await client._sqlExec(
    "SELECT * FROM hybrid_result WHERE workspace_id = :ws AND query_hash = :qh",
    { ws: workspaceId, qh: qhash },
  );
  return (rows as Record<string, unknown>[]).sort((a, b) => Number(b.score ?? 0) - Number(a.score ?? 0));
}
