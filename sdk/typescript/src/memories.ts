/**
 * Memory operations — store, update, delete, get, search.
 */
import type { ClientLike, MemoryRecord, SearchResult, SearchOptions, StoreOptions, ListMemoriesOptions, MemoryRevisionRecord, CrossEncoderRerankOptions } from "./types";
import { IMAGES_CONTEXT_PREFIX } from "./types";
import { sortByCreatedDesc, sortByCreatedAsc, fnmatch, queryHash, esc, escLike } from "./helpers";

/** Tantivy BM25 full-text search. */
export async function tantivySearch(client: ClientLike, workspaceId: string, query: string, limit: number = 20): Promise<SearchResult[]> {
  try {
    await client._call("tantivy_search", [workspaceId, query, limit]);
    const qhash = queryHash(query);
    const rows = await client._query("hybrid_result", workspaceId, { query_hash: qhash, entity_type: "memory" });
    rows.sort((a: Record<string, unknown>, b: Record<string, unknown>) => ((b.score ?? 0) as number) - ((a.score ?? 0) as number));
    return rows.slice(0, limit).map((r: Record<string, unknown>) => ({
      id: r.id || "",
      entity_id: r.entity_id || "",
      entity_type: r.entity_type || "memory",
      content: r.content || "",
      score: (r.score ?? 0) as number,
      strategy: r.strategy || "tantivy",
      memory_content: r.memory_content || r.content || "",
    })) as SearchResult[];
  } catch {
    const rows = await client._sqlExec(
      "SELECT * FROM memory WHERE workspace_id = :ws",
      { ws: workspaceId },
    );
    const q = query.toLowerCase();
    const filtered = rows.filter((r: Record<string, unknown>) =>
      String(r.content ?? "").toLowerCase().includes(q),
    );
    return filtered.slice(0, limit).map((r: Record<string, unknown>) => ({
      id: r.id || "",
      entity_id: r.id || "",
      entity_type: "memory",
      content: r.content || "",
      score: 0.5,
      strategy: "keyword",
      memory_content: r.content || "",
    })) as SearchResult[];
  }
}

export async function store(client: ClientLike, workspaceId: string, content: string, opts?: StoreOptions): Promise<void> {
  const memType = opts?.memoryType ?? "experience";
  let imagesJson = "";
  if (opts?.images) {
    const images: string[] = Array.isArray(opts.images) ? opts.images : [opts.images];
    imagesJson = JSON.stringify(images);
  }
  await client._call("store_memory", [
    workspaceId, opts?.peerId ?? "", "", memType, content,
    opts?.summary ?? "", "[]", 0.8, "", "", imagesJson,
  ]);

  const emb = await client._embed(content);
  if (emb.length > 0) {
    const mems = await client._sqlExec(
      "SELECT id FROM memory WHERE workspace_id = :ws",
      { ws: workspaceId },
    );
    if (mems.length > 0) {
      await client._call("index_entity", [
        workspaceId, "memory", mems[mems.length - 1].id as string, content, JSON.stringify(emb),
      ]);
    }
  }

  if (opts?.tier && ["L0", "L1", "L2"].includes(opts.tier)) {
    const mems = await client._sqlExec(
      "SELECT id FROM memory WHERE workspace_id = :ws",
      { ws: workspaceId },
    );
    if (mems.length > 0) {
      await client._call("update_memory_tier", [(mems[mems.length - 1].id as string), opts.tier]);
    }
  }
}

export async function search(client: ClientLike, workspaceId: string, query: string, opts?: SearchOptions): Promise<SearchResult[]> {
  const limit = opts?.limit ?? 20;
  const semantic = opts?.semantic ?? true;

  const emb = semantic ? await client._embed(query) : [];
  const embJson = emb.length > 0 ? JSON.stringify(emb) : "[]";
  // Use appropriate strategies based on mode
  const strategies = semantic
    ? JSON.stringify(["semantic", "keyword", "graph", "temporal"])
    : JSON.stringify(["keyword"]);
  await client._call("hybrid_search", [workspaceId, query, embJson, opts?.memoryType ?? "", opts?.tier ?? "", limit, strategies, 0]);
  const qhash = queryHash(query);
  let rows = await client._query("hybrid_result", workspaceId, { query_hash: qhash });
  rows.sort((a, b) => ((b.score ?? 0) as number) - ((a.score ?? 0) as number));

  const memIds: string[] = rows.filter((r) => r.entity_type === "memory").map((r) => r.entity_id as string);
  const nodeIds: string[] = rows.filter((r) => r.entity_type === "node").map((r) => r.entity_id as string);
  const memMap: Record<string, string> = {};
  const nodeMap: Record<string, string> = {};
  for (const mid of memIds) {
    const mems = await client._query("memory", workspaceId, { id: mid });
    if (mems.length > 0) memMap[mid] = (mems[0].content ?? "") as string;
  }
  for (const nid of nodeIds) {
    const nodes = await client._query("kg_node", workspaceId, { id: nid });
    if (nodes.length > 0) nodeMap[nid] = (nodes[0].label ?? "") as string;
  }
  for (const r of rows) {
    const eid = (r.entity_id ?? "") as string;
    if (r.entity_type === "memory") r.memory_content = memMap[eid] ?? "";
    else if (r.entity_type === "node") r.memory_content = nodeMap[eid] ?? "";
    else r.memory_content = "";
  }
  const crossEncoder = opts?.crossEncoder ?? true;
  if (crossEncoder) {
    try { rows = await crossEncoderRerank(client, query, rows, { topK: rows.length }); } catch { /* fallback */ }
  }
  return rows.slice(0, limit) as unknown as SearchResult[];
}

export async function getMemory(client: ClientLike, memoryId: string): Promise<MemoryRecord[]> {
  const results = (await client._sqlExec(
    "SELECT * FROM memory WHERE id = :mid",
    { mid: memoryId },
  )) as unknown as MemoryRecord[];
  if (results.length > 0) {
    try { await client._call("reinforce_memory", [memoryId]); } catch { /* ignore */ }
  }
  return results;
}

export async function getMemoryImages(client: ClientLike, memoryId: string): Promise<Record<string, string>[]> {
  const mems = await client._sqlExec("SELECT context FROM memory WHERE id = :mid", { mid: memoryId });
  if (mems.length === 0) return [];
  const context = (mems[0].context ?? "") as string;
  if (!context.startsWith(IMAGES_CONTEXT_PREFIX)) return [];
  try {
    const jsonPart = context.slice(IMAGES_CONTEXT_PREFIX.length);
    return JSON.parse(jsonPart) as Record<string, string>[];
  } catch { return []; }
}

export async function deleteMemory(client: ClientLike, memoryId: string): Promise<void> {
  return client._call("deactivate_memory", [memoryId]);
}

export async function batchDeleteMemories(client: ClientLike, workspaceId: string, memoryIds: string[]): Promise<void> {
  if (memoryIds.length === 0) return;
  return client._call("batch_delete_memories", [workspaceId, JSON.stringify(memoryIds)]);
}

export async function reinforce(client: ClientLike, memoryId: string): Promise<void> {
  return client._call("reinforce_memory", [memoryId]);
}

export async function updateMemory(client: ClientLike, memoryId: string, content: string, summary?: string, confidence?: number, expiresAt?: number): Promise<void> {
  const args: unknown[] = [memoryId, content, summary ?? "", confidence ?? 0.8];
  if (expiresAt !== undefined) args.push(expiresAt);
  return client._call("update_memory", args);
}

export async function rateMemory(client: ClientLike, memoryId: string, rating: string, peerId: string): Promise<void> {
  return client._call("rate_memory", [memoryId, rating, peerId]);
}

export async function getUserMemories(client: ClientLike, userScope: string, workspaceId: string): Promise<Record<string, unknown>[]> {
  await client._call("get_user_memories", [userScope, workspaceId]);
  return client._query("user_memory_result", workspaceId, { user_scope: userScope });
}

export async function consolidateMemories(client: ClientLike, workspaceId: string, sourceIds: string[], targetContent: string, targetSummary: string): Promise<void> {
  return client._call("consolidate_memories", [workspaceId, JSON.stringify(sourceIds), targetContent, targetSummary]);
}

export async function expireMemories(client: ClientLike): Promise<void> {
  return client._call("expire_memories", []);
}

export async function getMemoryStats(client: ClientLike, workspaceId: string): Promise<Record<string, string> | null> {
  await client._call("get_memory_stats", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM workspace_memory_stats_result WHERE workspace_id = :ws",
    { ws: workspaceId },
  );
  if (rows && rows.length > 0) {
    const result: Record<string, string> = {};
    for (const row of rows) result[row.stat_key] = row.stat_value;
    return result;
  }
  return null;
}

export async function getMemoryHistory(client: ClientLike, memoryId: string): Promise<MemoryRevisionRecord[]> {
  const rows = await client._sqlExec(
    "SELECT * FROM memory_revision WHERE memory_id = :mid",
    { mid: memoryId },
  );
  return (rows as MemoryRevisionRecord[]).sort((a, b) => Number(a.version ?? 0) - Number(b.version ?? 0));
}

export async function searchDirectoryContents(client: ClientLike, workspaceId: string, directoryPath: string): Promise<Record<string, unknown>[]> {
  await client._call("search_directory_contents", [workspaceId, directoryPath]);
  const rows = await client._sqlExec(
    "SELECT * FROM directory_content_result WHERE workspace_id = :ws AND directory_path = :dp",
    { ws: workspaceId, dp: directoryPath },
  );
  return sortByCreatedDesc(rows).slice(0, 1);
}

export async function listMemories(client: ClientLike, workspaceId: string, opts?: ListMemoriesOptions): Promise<MemoryRecord[]> {
  const limit = opts?.limit ?? 50;
  let q = "SELECT * FROM memory WHERE workspace_id = :ws AND is_active = true";
  const params: Record<string, string> = { ws: workspaceId };
  if (opts?.memoryType) { q += " AND memory_type = :mt"; params.mt = opts.memoryType; }
  let rows = await client._sqlExec(q, params);
  rows.sort((a: any, b: any) => Number(b.created_at ?? 0) - Number(a.created_at ?? 0));
  return rows.slice(0, limit) as MemoryRecord[];
}

export async function fuzzyGet(client: ClientLike, workspaceId: string, name: string, field?: string, threshold?: number, limit?: number): Promise<Record<string, unknown> | null> {
  const rows = await client._sqlExec(
    `SELECT * FROM memory WHERE workspace_id = :ws AND is_active = true LIMIT ${limit ?? 50}`,
    { ws: workspaceId },
  );
  if (rows.length === 0) return null;
  const t = threshold ?? 0.5;
  const f = field ?? "content";
  let best: Record<string, unknown> | null = null;
  let bestRatio = 0;
  for (const r of rows) {
    const text = ((r[f] as string) ?? "").toLowerCase();
    const target = name.toLowerCase();
    if (!text) continue;
    const bigrams = new Map<string, number>();
    for (let i = 0; i < text.length - 1; i++) {
      const bg = text.substring(i, i + 2); bigrams.set(bg, (bigrams.get(bg) ?? 0) + 1);
    }
    let intersect = 0;
    for (let i = 0; i < target.length - 1; i++) {
      const bg = target.substring(i, i + 2);
      if ((bigrams.get(bg) ?? 0) > 0) { intersect++; bigrams.set(bg, (bigrams.get(bg) ?? 0) - 1); }
    }
    const ratio = (2 * intersect) / (Math.max(text.length - 1, 1) + Math.max(target.length - 1, 1));
    if (ratio > bestRatio) { bestRatio = ratio; best = r as Record<string, unknown>; }
  }
  if (best && bestRatio >= t) return best;
  return null;
}

export async function globGet(client: ClientLike, workspaceId: string, pattern: string, field?: string, limit?: number): Promise<Record<string, unknown>[]> {
  const rows = await client._sqlExec(
    `SELECT * FROM memory WHERE workspace_id = :ws AND is_active = true LIMIT ${limit ?? 200}`,
    { ws: workspaceId },
  );
  if (rows.length === 0) return [];
  const f = field ?? "id";
  const patLower = pattern.toLowerCase();
  const matches: Record<string, unknown>[] = [];
  for (const r of rows) {
    const val = ((r[f] as string) ?? "").toLowerCase();
    if (fnmatch(val, patLower)) matches.push(r);
  }
  return matches;
}

export async function setMemoryContext(client: ClientLike, memoryId: string, context: string): Promise<void> {
  return client._call("set_memory_context", [memoryId, context]);
}

export async function getContextChain(client: ClientLike, memoryId: string): Promise<Record<string, unknown>[]> {
  await client._call("get_context_chain", [memoryId]);
  return client._sqlExec("SELECT * FROM context_chain_result WHERE memory_id = :mid", { mid: memoryId });
}

export async function updateMemoryTier(client: ClientLike, memoryId: string, tier: string): Promise<void> {
  return client._call("update_memory_tier", [memoryId, tier]);
}

export async function setMemoryScope(client: ClientLike, memoryId: string, userScope: string): Promise<void> {
  return client._call("set_memory_scope", [memoryId, userScope]);
}

export async function escalateMemories(client: ClientLike, workspaceId: string, l2ToL1?: number, l1ToL0?: number): Promise<void> {
  return client._call("escalate_memories", [workspaceId, l2ToL1 ?? 5, l1ToL0 ?? 20]);
}

export async function searchWithFilters(client: ClientLike, workspaceId: string, query: string, memoryType?: string, tier?: string, metadataFilter?: string, locationFilter?: string, limit?: number): Promise<Record<string, unknown>[]> {
  let q = "SELECT * FROM memory WHERE workspace_id = :ws AND is_active = true";
  const params: Record<string, string> = { ws: workspaceId };
  if (memoryType) { q += " AND memory_type = :mt"; params.mt = memoryType; }
  if (tier) { q += " AND tier = :t"; params.t = tier; }
  const ll = limit ?? 20;
  let rows = await client._sqlExec(q, params);
  if (query) {
    const ql = query.toLowerCase();
    rows = rows.filter((r: Record<string, unknown>) => String(r.content ?? "").toLowerCase().includes(ql));
  }
  rows.sort((a: Record<string, unknown>, b: Record<string, unknown>) => ((b.created_at ?? 0) as number) - ((a.created_at ?? 0) as number));
  // Post-filter: metadata JSON matching
  if (metadataFilter) {
    let mf: Record<string, unknown>;
    try { mf = JSON.parse(metadataFilter); } catch { mf = {}; }
    rows = rows.filter((r: Record<string, unknown>) => {
      let meta: Record<string, unknown> = {};
      const raw = r.metadata_json;
      if (typeof raw === "string" && raw) { try { meta = JSON.parse(raw); } catch { meta = {}; } }
      else if (typeof raw === "object" && raw !== null) { meta = raw as Record<string, unknown>; }
      return Object.entries(mf).every(([k, v]) => meta[k] === v);
    });
  }
  if (locationFilter) {
    const loc = locationFilter.toLowerCase();
    rows = rows.filter((r: Record<string, unknown>) => {
      const content = String(r.content ?? "").toLowerCase();
      const summary = String(r.summary ?? "").toLowerCase();
      return content.includes(loc) || summary.includes(loc);
    });
  }
  return rows.slice(0, ll);
}

export async function recommendMemories(client: ClientLike, workspaceId: string, limit?: number, minUrgency?: number): Promise<Record<string, unknown>[]> {
  await client._call("recommend_memories", [workspaceId, limit ?? 20, minUrgency ?? 0.3]);
  return client._sqlExec("SELECT * FROM memory_recommendation WHERE workspace_id = :ws", { ws: workspaceId });
}

export async function autoInvalidate(client: ClientLike, oldMemoryId: string, newMemoryId: string): Promise<Record<string, unknown>> {
  return await client._call("auto_invalidate", [oldMemoryId, newMemoryId]);
}

export async function temporalSearchWithWeight(client: ClientLike, workspaceId: string, query: string, memoryType = "", tier = "", limit = 10, recencyWeight = 0.5, timeContext = 0): Promise<Record<string, unknown>[]> {
  await client._call("temporal_search_with_weight", [workspaceId, query, "[]", memoryType, tier, limit, recencyWeight, timeContext]);
  const rows = await client._sqlExec("SELECT * FROM hybrid_result WHERE workspace_id = :ws", { ws: workspaceId });
  const sorted = rows.sort((a: any, b: any) => Number(b.created_at ?? 0) - Number(a.created_at ?? 0));
  return sorted.slice(0, Math.max(1, limit));
}

// ---------------------------------------------------------------------------
// Batch memory operations
// ---------------------------------------------------------------------------

export async function storeBatch(client: ClientLike, workspaceId: string, items: {
  content: string; summary?: string; memoryType?: string; peerId?: string; confidence?: number; images?: string | Record<string, string> | (string | Record<string, string>)[];
}[]): Promise<void> {
  const cleanItems = items.filter((item) => item.content.trim().length > 0);
  if (cleanItems.length === 0) return;
  const contents = cleanItems.map((item) => item.content);
  let embeddings: number[][] = [];
  try {
    const resp = await fetch(`${client.embedderUrl}/embed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texts: contents }),
      signal: AbortSignal.timeout(10_000 * contents.length),
    });
    if (resp.ok) {
      const data: { embeddings?: number[][]; embedding?: number[] } = await resp.json();
      embeddings = data?.embeddings ?? [];
      if (embeddings.length === 0 && data?.embedding) embeddings = [data.embedding];
    }
  } catch { embeddings = []; }

  const payload = cleanItems.map((item) => {
    let context = "";
    if (item.images) {
      const images: (string | Record<string, string>)[] = Array.isArray(item.images) ? item.images : [item.images];
      context = JSON.stringify(images);
    }
    return {
      workspace_id: workspaceId, peer_id: item.peerId ?? "", observer_id: "",
      memory_type: item.memoryType ?? "experience", content: item.content,
      summary: item.summary ?? item.content.slice(0, 200), entities_json: "[]",
      confidence: item.confidence ?? 0.8, source_session_id: "", source_message_id: "", context,
    };
  });

  await client._call("store_memory_batch", [JSON.stringify(payload)]);

  for (let i = 0; i < cleanItems.length; i++) {
    const emb = embeddings[i];
    if (emb && emb.length > 0) {
      const mems = await client._sqlExec("SELECT id FROM memory WHERE workspace_id = :ws", { ws: workspaceId });
      if (mems.length > 0) {
        await client._call("index_entity", [workspaceId, "memory", mems[mems.length - 1].id, cleanItems[i].content, JSON.stringify(emb)]);
      }
    }
  }
}

export async function batchUpdateMemories(client: ClientLike, workspaceId: string, memoryIds: string[], updates: Record<string, unknown>): Promise<{ status: string; updated: number; errors?: string[] }> {
  let updated = 0;
  const errors: string[] = [];
  for (const memId of memoryIds) {
    try {
      const rows = await client._sqlExec("SELECT * FROM memory WHERE id = :id AND workspace_id = :ws", { id: memId, ws: workspaceId });
      if (rows.length === 0) { errors.push(`Memory '${memId}' not found`); continue; }
      const current = rows[0] as Record<string, unknown>;
      const content = (updates.content as string) ?? (current.content as string) ?? "";
      const summary = (updates.summary as string) ?? (current.summary as string) ?? "";
      const confidence = (updates.confidence as number) ?? (current.confidence as number) ?? 0.8;
      const expiresAt = (updates.expires_at as number) ?? 0;
      await updateMemory(client, memId, content, summary, confidence, expiresAt);
      updated++;
    } catch (e: unknown) { errors.push(`Memory '${memId}': ${e instanceof Error ? e.message : String(e)}`); }
  }
  if (errors.length > 0) return { status: "partial", updated, errors };
  return { status: "ok", updated };
}

// ---------------------------------------------------------------------------
// Cross-encoder rerank
// ---------------------------------------------------------------------------

export async function crossEncoderRerank(client: ClientLike, query: string, candidates: Record<string, unknown>[], opts: CrossEncoderRerankOptions = {}): Promise<Record<string, unknown>[]> {
  const contentKey = opts.contentKey ?? "memory_content";
  const topK = opts.topK ?? 20;
  try {
    const resp = await fetch(`${client.mcpUrl}/tools/call`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "cross_encoder_rerank", arguments: { query, candidates_json: JSON.stringify(candidates), content_key: contentKey, top_k: topK } }),
      signal: AbortSignal.timeout(30_000),
    });
    if (!resp.ok) throw new Error(`MCP tool call failed (${resp.status}): ${await resp.text()}`);
    const data = (await resp.json()) as Record<string, unknown>;
    const resultField = data?.result;
    if (typeof resultField === "string" && resultField.startsWith("[")) return JSON.parse(resultField) as Record<string, unknown>[];
    if (Array.isArray(data?.content)) {
      const contentArr = data.content as Array<{ text?: string }>;
      for (const item of contentArr) { if (typeof item.text === "string" && item.text.startsWith("[")) return JSON.parse(item.text) as Record<string, unknown>[]; }
    }
    throw new Error("Unexpected MCP response format");
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(`crossEncoderRerank failed: ${msg}`);
  }
}
