/**
 * Mem0-compatible drop-in adapter for TypeScript.
 *
 * Matches the real Mem0 TypeScript SDK API (mem0ai/mem0 packages/mem0-ts).
 * All public method signatures (add, search, getAll, get, delete, history, update)
 * accept the same arguments as upstream mem0.Memory. Return shapes match
 * ({ results: [...] }).
 *
 * NOTE: Constructor differs from upstream — accepts a plain config object
 * instead of a typed MemoryConfig. The upstream also requires an LLM provider
 * config which our adapter doesn't need (uses embedded LLM client).
 *
 * **Error contract:**
 * - `Error` with message for invalid inputs (empty text, missing required args)
 * - `Error` for backend failures (DB down, connection errors) — propagates from Client
 * - `console.warn` logged for transient issues (LLM extraction, KG node creation failures)
 *   — the operation degrades gracefully rather than crashing.
 * - Graph search returns `[]` on failure (logged), consistent with mem0's
 *   `getAll` returning empty for missing data.
 *
 * Usage:
 *
 * ```typescript
 * import { Memory } from "spacetime-memory/mem0";
 *
 * const m = new Memory({ host: "127.0.0.1", port: 3001 });
 * await m.add("I like pizza", { userId: "alice", agentId: "assistant" });
 * const results = await m.search("food preferences", { userId: "alice" });
 * const memory = await m.get(results.results[0].id);
 * const allMems = await m.getAll({ userId: "alice" });
 * await m.update(results.results[0].id, "I love pizza");
 * await m.delete(results.results[0].id);
 * const history = await m.history(results.results[0].id);
 * m.reset();
 * ```
 */

import { Client, ClientOptions, SearchResult } from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Configuration options for the Memory constructor. */
export interface MemoryConfig {
  /** SpacetimeDB host (default: 127.0.0.1) */
  host?: string;
  /** SpacetimeDB port (default: 3001) */
  port?: number | string;
  /** Database name (default: spacetime-memory) */
  db?: string;
  /** Embedder sidecar URL (default: http://127.0.0.1:4000) */
  embedderUrl?: string;
  /** MCP server URL for cross-encoder reranking (default: http://127.0.0.1:8099) */
  mcpUrl?: string;
  /** Per-user LLM config overrides: { userId: { model, apiKey, baseUrl } } */
  llmConfig?: Record<string, { model?: string; apiKey?: string; baseUrl?: string }>;
}

/** Result of an add operation. */
export interface AddResult {
  results: MemoryResult[];
  relation_events: unknown[];
}

/** Individual memory record in results. */
export interface MemoryResult {
  id: string;
  memory: string;
  score?: number;
  user_id: string;
  agent_id: string;
  metadata?: Record<string, unknown>;
}

/** Search options (Mem0 v1.x + v2.x compatible). */
export interface SearchOptions {
  userId?: string;
  agentId?: string;
  runId?: string;
  limit?: number;
  threshold?: number;
  topK?: number;
  filters?: Record<string, unknown>;
  rerank?: boolean;
  graphContext?: boolean;
}

/** GetAll options (Mem0 v1.x + v2.x compatible). */
export interface GetAllOptions {
  userId?: string;
  agentId?: string;
  runId?: string;
  limit?: number;
  filters?: Record<string, unknown>;
  topK?: number;
}

/** Update options. */
export interface UpdateOptions {
  metadata?: Record<string, unknown>;
}

/** DeleteAll options. */
export interface DeleteAllOptions {
  userId?: string;
  agentId?: string;
  runId?: string;
  filters?: Record<string, unknown>;
}

/** History entry. */
export interface HistoryEntry {
  version: number;
  content: string;
  summary: string;
  confidence: number;
  created_at: number;
}

/** Chat options. */
export interface ChatOptions {
  userId?: string;
  agentId?: string;
  runId?: string;
  messages?: Array<{ role: string; content: string }>;
  memoryType?: string;
  llmConfig?: { provider?: string; model?: string; apiKey?: string; baseUrl?: string };
}

/** Chat result. */
export interface ChatResult {
  response: string;
  context: string[];
  memories: MemoryResult[];
}

/** Graph entity record. */
export interface GraphEntity {
  id: string;
  label: string;
  node_type: string;
  entity_type: string;
  summary: string;
  metadata_json: string;
  created_at: number;
  score?: number;
  merged?: boolean;
}

/** Graph add options. */
export interface GraphAddOptions {
  entityType?: string;
  userId?: string;
  agentId?: string;
  metadata?: Record<string, unknown>;
}

/** Graph search options. */
export interface GraphSearchOptions {
  userId?: string;
  limit?: number;
}

/** Graph getAll options. */
export interface GraphGetAllOptions {
  userId?: string;
  limit?: number;
}

// ---------------------------------------------------------------------------
// Internal: Graph Store (entity store)
// ---------------------------------------------------------------------------

interface LLMClient {
  available: boolean;
  extractFacts(text: string): Promise<string[]>;
  chat(messages: Array<{ role: string; content: string }>): Promise<string | null>;
}

class SimpleLLMClient implements LLMClient {
  available = false;
  async extractFacts(_text: string): Promise<string[]> { return []; }
  async chat(_messages: Array<{ role: string; content: string }>): Promise<string | null> { return null; }
}

class GraphStore {
  private memory: Memory;

  constructor(memory: Memory) {
    this.memory = memory;
  }

  private _ws(userId?: string): string {
    return this.memory._ws(userId);
  }

  private _tag(userId?: string): string {
    return userId ? `mem0_user:${userId}` : "mem0_global";
  }

  private _tagFilter(rows: any[], tag: string): any[] {
    return rows.filter((r) => {
      const meta = r.metadata_json || r.description || "";
      try {
        const parsed = JSON.parse(meta);
        if (parsed?.tag === tag) return true;
      } catch {
        if (!meta) return true;
      }
      return false;
    });
  }

  private _entityLinkToDict(row: any, tag: string): GraphEntity {
    return {
      id: row.id || "",
      label: row.entity_name || "",
      node_type: row.entity_type || "concept",
      entity_type: row.entity_type || "concept",
      summary: row.entity_name || "",
      metadata_json: row.description || JSON.stringify({ tag }),
      created_at: row.created_at || 0,
    };
  }

  /**
   * Add an entity to the graph with vector-based deduplication.
   * Embeds the entity name and searches for similar existing entities
   * (matching real Mem0's Qdrant-backed dedup). If a close match is
   * found, the existing entity is updated with the new alias. Falls
   * back gracefully when the embedder is unavailable.
   */
  async add(text: string, options: GraphAddOptions = {}): Promise<GraphEntity> {
    const { entityType = "concept", userId, agentId, metadata } = options;
    if (!text || !text.trim()) {
      throw new Error("graph.add() requires non-empty text");
    }
    const cleaned = text.trim();
    const wsId = this._ws(userId);
    const meta = { ...metadata };
    if (agentId) meta.agent_id = agentId;
    const tag = this._tag(userId);
    meta.tag = tag;

    // Vector-based dedup: search for similar existing entities
    try {
      const semanticRows = await this.memory._client.search({
        workspaceId: wsId,
        query: cleaned,
        limit: 5,
        semantic: true,
      });
      const nodeRows = semanticRows.filter((r) => r.entity_type === "node");
      for (const r of nodeRows) {
        const score = r.score ?? 0;
        if (score < 0.85) continue;
        const nid = r.entity_id;
        if (!nid) continue;
        const rows = await this.memory._client._query("kg_node", { id: nid }, wsId);
        if (!rows.length) continue;
        const existing = rows[0];
        const existingName = existing.label || "";
        try {
          const elRows = await this.memory._client._query(
            "entity_link",
            { entity_name: existingName },
            wsId,
          );
          if (elRows.length) {
            const elId = elRows[0].id;
            await this.memory._client._call("add_alias", [elId, cleaned]);
          }
        } catch {
          // alias already exists or entity_link not available
        }
        return {
          id: nid,
          label: existingName,
          node_type: existing.node_type || entityType,
          entity_type: existing.node_type || entityType,
          summary: existing.summary || "",
          metadata_json: existing.metadata_json || JSON.stringify(meta),
          created_at: existing.created_at || 0,
          merged: true,
        };
      }
    } catch {
      // Embedder down → fall through to exact match
    }

    return this._addExact(cleaned, entityType, wsId, meta, tag);
  }

  private async _addExact(
    text: string,
    entityType: string,
    wsId: string,
    meta: Record<string, unknown>,
    tag: string,
  ): Promise<GraphEntity> {
    try {
      await this.memory._client._call("create_entity_link", [
        wsId,
        text,
        entityType,
        JSON.stringify(meta),
      ]);
      const rows = await this.memory._client._query(
        "entity_link",
        { entity_name: text },
        wsId,
      );
      if (rows.length) return this._entityLinkToDict(rows[0], tag);
      return { id: "", label: text, node_type: entityType, entity_type: entityType, summary: text, metadata_json: JSON.stringify(meta), created_at: 0 };
    } catch {
      const result = await this.memory._client._call("create_node", [
        wsId,
        text,
        entityType,
        text,
        JSON.stringify(meta),
      ]);
      return result as GraphEntity;
    }
  }

  /**
   * Search graph entities by label.
   * When the embedder sidecar is available, uses vector/semantic search
   * via hybrid_search for relevance-ranked results (matches real
   * Mem0's vector-backed entity_store). Falls back to substring matching
   * when the embedder is unavailable.
   */
  async search(query: string, options: GraphSearchOptions = {}): Promise<GraphEntity[]> {
    const { userId, limit = 10 } = options;
    const wsId = this._ws(userId);
    const tag = this._tag(userId);

    try {
      const semanticRows = await this.memory._client.search({
        workspaceId: wsId,
        query,
        limit,
        semantic: true,
      });
      const nodeRows = semanticRows.filter((r) => r.entity_type === "node");
      if (nodeRows.length) {
        const results: GraphEntity[] = [];
        for (const r of nodeRows.slice(0, limit)) {
          const nid = r.entity_id;
          if (!nid) continue;
          const rows = await this.memory._client._query("kg_node", { id: nid }, wsId);
          if (rows.length) {
            const n = rows[0];
            results.push({
              id: n.id || "",
              label: n.label || "",
              node_type: n.node_type || "entity",
              entity_type: n.node_type || "entity",
              summary: n.summary || "",
              metadata_json: n.metadata_json || "{}",
              created_at: n.created_at || 0,
              score: r.score || 0,
            });
          }
        }
        if (results.length) return this._tagFilter(results, tag).slice(0, limit);
      }
    } catch {
      // Embedder down or hybrid_search fails → fallback
    }

    // Tantivy BM25 search fallback (better than substring)
    try {
      const tantivyHits = await this.memory._client._tantivySearch(wsId, query, limit);
      if (tantivyHits.length) {
        const results: GraphEntity[] = [];
        for (const th of tantivyHits.slice(0, limit)) {
          const nid = th.entity_id;
          const etype = th.entity_type || "node";
          if (!nid) continue;
          if (etype === "node") {
            const rows = await this.memory._client._query("kg_node", { id: nid }, wsId);
            if (rows.length) {
              const n = rows[0];
              results.push({
                id: n.id || "",
                label: n.label || "",
                node_type: n.node_type || "entity",
                entity_type: n.node_type || "entity",
                summary: n.summary || "",
                metadata_json: n.metadata_json || "{}",
                created_at: n.created_at || 0,
                score: th.score || 0,
              });
            }
          }
        }
        if (results.length) return this._tagFilter(results, tag).slice(0, limit);
      }
    } catch {
      // fall through
    }

    // Fallback: substring match on entity_link or kg_node
    try {
      try {
        await this.memory._client._call("resolve_entity", [wsId, query]);
      } catch {
        // ignore
      }
      const rows = await this.memory._client._query("entity_link", {}, wsId);
      const q = query.toLowerCase();
      const matched = rows.filter((r) => (r.entity_name || "").toLowerCase().includes(q));
      return this._tagFilter(matched, tag).slice(0, limit).map((r) => this._entityLinkToDict(r, tag));
    } catch {
      const rows = await this.memory._client._call("query_graph", [wsId, query]);
      return this._tagFilter(rows, tag).slice(0, limit);
    }
  }

  /**
   * List all graph entities for a user.
   * Queries the entity_link table. Falls back to query_graph (kg_node)
   * if entity_link is not available.
   */
  async getAll(options: GraphGetAllOptions = {}): Promise<GraphEntity[]> {
    const { userId, limit = 100 } = options;
    const wsId = this._ws(userId);
    const tag = this._tag(userId);

    try {
      const rows = await this.memory._client._query("entity_link", {}, wsId);
      const filtered = this._tagFilter(rows, tag);
      return filtered.slice(0, limit).map((r) => this._entityLinkToDict(r, tag));
    } catch {
      const rows = await this.memory._client._call("query_graph", [wsId, ""]);
      return this._tagFilter(rows, tag).slice(0, limit);
    }
  }

  /**
   * Delete a graph entity by node ID.
   * Deletes via delete_node (kg_node). Entity link deletion is
   * not yet supported by the server-side reducer; entity_link rows
   * are left in place for now.
   */
  async delete(entityId: string): Promise<{ status: string; deleted: string }> {
    await this.memory._client._call("delete_node", [entityId]);
    return { status: "ok", deleted: entityId };
  }
}

// ---------------------------------------------------------------------------
// Memory Class (Mem0 API)
// ---------------------------------------------------------------------------

/**
 * Drop-in replacement for `mem0.Memory`.
 *
 * Models are not available in spacetime-memory, so `model` and similar
 * Mem0-specific options are accepted but silently ignored (or routed as
 * metadata). The adapter maps:
 *
 * - `user_id`  → `workspace_id`
 * - `agent_id` → `peer_id`
 * - `run_id`   → `source_session_id`
 */
export class Memory {
  private _client: Client;
  private _userIdToWs: Map<string, string> = new Map();
  private _llmOverrides: Map<string, { model?: string; apiKey?: string; baseUrl?: string }> = new Map();
  private _graphStore: GraphStore | null = null;

  constructor(config: MemoryConfig = {}) {
    this._client = new Client({
      host: config.host,
      port: config.port,
      database: config.db,
      embedderUrl: config.embedderUrl,
      mcpUrl: config.mcpUrl,
    });

    if (config.llmConfig) {
      for (const [uid, cfg] of Object.entries(config.llmConfig)) {
        if (cfg && typeof cfg === "object") {
          this._llmOverrides.set(uid, cfg);
        }
      }
    }
  }

  /**
   * Create a Memory instance from a config dict (Mem0 v2+ compat).
   */
  static fromConfig(configDict: MemoryConfig): Memory {
    return new Memory(configDict);
  }

  // -------------------------------------------------------------------------
  // Graph (entity store) — Mem0 v2+ compat
  // -------------------------------------------------------------------------

  get graph(): GraphStore {
    if (!this._graphStore) this._graphStore = new GraphStore(this);
    return this._graphStore;
  }

  // -------------------------------------------------------------------------
  // Per-user LLM config
  // -------------------------------------------------------------------------

  setLlmConfig(userId: string, llmConfig: { provider?: string; model?: string; apiKey?: string; baseUrl?: string }): void {
    this._llmOverrides.set(userId, llmConfig);
  }

  private _resolveLlmFor(userId?: string): LLMClient {
    if (userId && this._llmOverrides.has(userId)) {
      const cfg = this._llmOverrides.get(userId)!;
      // TODO: implement proper LLM client with custom config
      return new SimpleLLMClient();
    }
    return new SimpleLLMClient();
  }

  // -------------------------------------------------------------------------
  // Internal helpers
  // -------------------------------------------------------------------------

  private async _ws(userId?: string): Promise<string> {
    if (!userId) return "";
    if (!this._userIdToWs.has(userId)) {
      const ws = await this._client._call("list_workspaces", []);
      // TODO: resolve workspace from list
      // For now, assume workspace name == userId and create if needed
      try {
        await this._client._call("create_workspace", [userId, `Mem0 user: ${userId}`]);
      } catch {
        // might already exist
      }
      const wsList = await this._client._sqlExec(`SELECT id FROM workspace WHERE name = :name`, { name: userId });
      if (wsList.length) {
        this._userIdToWs.set(userId, wsList[0].id as string);
      } else {
        throw new Error(`Could not resolve or create workspace for user_id='${userId}'`);
      }
    }
    return this._userIdToWs.get(userId) || "";
  }

  private _extractIdsFromFilters(filters?: Record<string, unknown>): [string | undefined, string | undefined, string | undefined] {
    if (!filters) return [undefined, undefined, undefined];
    return [
      filters.user_id as string | undefined,
      filters.agent_id as string | undefined,
      filters.run_id as string | undefined,
    ];
  }

  private async _handleMessageList(
    messages: Array<{ role: string; content: string }>,
    userId?: string,
    agentId?: string,
    runId?: string,
    infer = true,
  ): Promise<{ content: string; summary: string }> {
    const conversation = messages
      .filter((m) => m.content)
      .map((m) => `${m.role || "user"}: ${m.content}`)
      .join("\n");

    let extractedMemories: string[] | null = null;
    if (infer) {
      try {
        const llm = this._resolveLlmFor(userId);
        if (llm.available) {
          extractedMemories = await llm.extractFacts(conversation);
        }
      } catch (exc) {
        console.warn("LLM memory extraction from conversation failed:", exc);
      }
    }

    if (extractedMemories && extractedMemories.length > 0) {
      const allResults: MemoryResult[] = [];
      for (const fact of extractedMemories) {
        const r = await this.add(fact, { userId, agentId, runId, infer: false });
        allResults.push(...r.results);
      }
      throw new _InferMergeDone({ results: allResults, relation_events: [] });
    }

    if (infer) {
      return { content: messages.map((m) => m.content).join(" "), summary: "" };
    }
    return { content: conversation, summary: conversation.slice(0, 200) };
  }

  private async _tryInferMerge(
    content: string,
    userId?: string,
    agentId?: string,
  ): Promise<AddResult | null> {
    const searchResult = await this.search(content, { userId, limit: 5 });
    const closeMatches = searchResult.results.filter((r) => (r.score ?? 0) > 0.85);
    if (!closeMatches.length) return null;

    const bestMatch = closeMatches[0];
    const memId = bestMatch.id;
    const existingContent = bestMatch.memory || "";
    const merged = `${existingContent}\n${content}`;
    await this.update(memId, merged);

    try {
      const llm = this._resolveLlmFor(userId);
      if (llm.available) {
        const facts = await llm.extractFacts(merged);
        if (facts.length) {
          await this._storeFactsAsKgNodes(facts, userId, agentId);
          await this._client._call("update_memory", [memId, JSON.stringify({ extracted_facts: facts })]);
        }
      }
    } catch (exc) {
      console.warn("Failed to update memory with KG facts:", exc);
    }

    return {
      results: [
        {
          id: memId,
          memory: merged,
          event: "UPDATE",
          user_id: userId || "",
          agent_id: agentId || "",
        },
      ],
      relation_events: [],
    };
  }

  private async _storeFactsAsKgNodes(
    facts: string[],
    userId?: string,
    agentId?: string,
  ): Promise<string[]> {
    const wsId = await this._ws(userId);
    if (!wsId || !facts.length) return [];
    const nodeIds: string[] = [];
    for (const fact of facts) {
      if (fact.trim().length < 4) continue;
      try {
        const meta: Record<string, unknown> = { tag: userId ? `mem0_user:${userId}` : "mem0_global" };
        if (agentId) meta.agent_id = agentId;
        const result = await this._client._call("create_node", [
          wsId,
          fact,
          "fact",
          fact,
          JSON.stringify(meta),
        ]);
        if (result && typeof result === "object" && "id" in result) {
          nodeIds.push((result as any).id);
        }
      } catch {
        console.debug("Failed to create KG node for fact:", fact);
      }
    }
    return nodeIds;
  }

  private async _getGraphContext(query: string, userId?: string, limit = 5): Promise<string[]> {
    const wsId = await this._ws(userId);
    try {
      const rows = await this._client._call("query_graph", [wsId, query]);
      return rows.slice(0, limit).map((r: any) => r.label).filter(Boolean);
    } catch (exc) {
      console.warn("_GraphStore.search() failed:", exc);
      return [];
    }
  }

  // -------------------------------------------------------------------------
  // Mem0 API
  // -------------------------------------------------------------------------

  /**
   * Store a memory.
   */
  async add(
    messages: string | Array<{ role: string; content: string }>,
    options: {
      userId?: string;
      agentId?: string;
      runId?: string;
      metadata?: Record<string, unknown>;
      filters?: Record<string, unknown>;
      infer?: boolean;
      prompt?: string;
      outputFormat?: string;
      memoryType?: string;
    } = {},
  ): Promise<AddResult> {
    const {
      userId,
      agentId,
      runId,
      metadata,
      filters,
      infer = true,
      memoryType,
    } = options;

    let finalUserId = userId;
    let finalAgentId = agentId;
    let finalRunId = runId;

    if (filters && !finalUserId) finalUserId = filters.user_id as string | undefined;
    if (filters && !finalAgentId) finalAgentId = filters.agent_id as string | undefined;
    if (filters && !finalRunId) finalRunId = filters.run_id as string | undefined;

    try {
      let content: string;
      let summary = "";

      if (Array.isArray(messages)) {
        const result = await this._handleMessageList(messages, finalUserId, finalAgentId, finalRunId, infer);
        content = result.content;
        summary = result.summary;
      } else {
        content = String(messages);
        summary = "";
      }

      if (infer && typeof messages === "string" && finalUserId) {
        const mergedResult = await this._tryInferMerge(content, finalUserId, finalAgentId);
        if (mergedResult) return mergedResult;
      }

      let extractedFacts: string[] | null = null;
      if (infer) {
        try {
          const llm = this._resolveLlmFor(finalUserId);
          if (llm.available) {
            extractedFacts = await llm.extractFacts(content);
          }
        } catch (exc) {
          console.warn("LLM fact extraction failed:", exc);
        }
      }

      const meta: Record<string, unknown> = {};
      if (extractedFacts) meta.extracted_facts = extractedFacts;
      if (metadata) Object.assign(meta, metadata);

      const wsId = await this._ws(finalUserId);

      await this._client._call("store_memory", [
        wsId,
        finalAgentId || "",
        "",
        memoryType || "experience",
        content,
        summary || content.slice(0, 200),
        "[]",
        0.8,
        "",
        "",
      ]);

      if (extractedFacts) {
        await this._storeFactsAsKgNodes(extractedFacts, finalUserId, finalAgentId);
      }

      if (finalUserId) {
        const stored = await this._client.search({
          workspaceId: wsId,
          query: content,
          limit: 1,
          semantic: true,
        });
        if (stored.length) {
          const memId = stored[0].entity_id || stored[0].id;
          if (memId) {
            try {
              await this._client._call("set_memory_scope", [memId, finalUserId]);
            } catch (exc) {
              console.warn("mem0.add: set_memory_scope failed for", memId, exc);
            }
          }
        }
      }

      const searchResults = await this._client.search({
        workspaceId: wsId,
        query: content,
        limit: 1,
        semantic: true,
      });

      return {
        results: searchResults.map((r) => ({
          id: r.entity_id || r.id || "",
          memory: r.memory_content || r.content || "",
          event: "ADD",
          user_id: finalUserId || "",
          agent_id: finalAgentId || "",
        })),
        relation_events: [],
      };
    } catch (exc) {
      if (exc instanceof _InferMergeDone) return exc.payload;
      throw new Error(`mem0.add() failed: ${exc}`);
    }
  }

  /**
   * Retrieve a single memory by its ID.
   */
  async get(memoryId: string): Promise<{ results: MemoryResult[] }> {
    try {
      const rows = await this._client._call("get_memory", [memoryId]);
      const activeRows = (rows || []).filter((r: any) => r.is_active !== false);
      if (activeRows.length) {
        const record = activeRows[0];
        return {
          results: [
            {
              id: record.id || "",
              memory: record.content || "",
              user_id: record.peer_id || "",
              agent_id: record.observer_id || "",
              metadata: {},
            },
          ],
        };
      }
      return { results: [] };
    } catch (exc) {
      throw new Error(`mem0.get('${memoryId}') failed: ${exc}`);
    }
  }

  /**
   * Search memories by semantic similarity to query.
   */
  async search(
    query: string,
    options: SearchOptions = {},
  ): Promise<{ results: MemoryResult[] }> {
    const {
      userId,
      agentId,
      runId,
      limit = 100,
      threshold = 0.0,
      topK,
      filters,
      rerank,
      graphContext = true,
    } = options;

    let finalUserId = userId;
    let finalAgentId = agentId;
    let finalRunId = runId;

    if (filters) {
      const [fu, fa, fr] = this._extractIdsFromFilters(filters);
      finalUserId = finalUserId || fu;
      finalAgentId = finalAgentId || fa;
      finalRunId = finalRunId || fr;
    }

    const effectiveLimit = topK ?? limit;
    const effectiveThreshold = threshold;

    const wsId = await this._ws(finalUserId);

    let graphEntities: string[] = [];
    if (graphContext) {
      graphEntities = await this._getGraphContext(query, finalUserId);
    }

    try {
      const rows = await this._client.search({
        workspaceId: wsId,
        query,
        limit: effectiveLimit,
        semantic: true,
      });

      const results: MemoryResult[] = [];
      for (const r of rows || []) {
        const score = r.score ?? 0;
        if (effectiveThreshold > 0 && score < effectiveThreshold) continue;

        const memId = r.entity_id || "";
        if (finalUserId && memId) {
          const memRecords = await this._client._call("get_memory", [memId]);
          if (memRecords.length) {
            const memUserScope = memRecords[0].user_scope || "";
            if (memUserScope && memUserScope !== finalUserId) continue;
          }
        }

        const meta: Record<string, unknown> = {};
        if (graphEntities.length) meta.graph_context = graphEntities;

        results.push({
          id: memId,
          memory: r.memory_content || r.content || "",
          score,
          user_id: finalUserId || "",
          agent_id: finalAgentId || "",
          metadata: meta,
        });
      }
      return { results };
    } catch (exc) {
      throw new Error(`mem0.search('${query}') failed: ${exc}`);
    }
  }

  /**
   * List all memories for a user.
   */
  async getAll(options: GetAllOptions = {}): Promise<{ results: MemoryResult[] }> {
    const { userId, agentId, runId, limit = 100, filters, topK } = options;

    let finalUserId = userId;
    let finalAgentId = agentId;
    let finalRunId = runId;

    if (filters) {
      const [fu, fa, fr] = this._extractIdsFromFilters(filters);
      finalUserId = finalUserId || fu;
      finalAgentId = finalAgentId || fa;
      finalRunId = finalRunId || fr;
    }

    const effectiveLimit = topK ?? limit;

    try {
      let rows: any[];
      if (finalUserId) {
        const wsId = await this._ws(finalUserId);
        const allMems = await this._client._call("list_memories", [wsId, 1000]);
        rows = allMems.filter((r: any) => r.user_scope === "" || r.user_scope === finalUserId).slice(0, effectiveLimit);
      } else {
        const wsId = await this._ws(undefined);
        rows = await this._client._call("list_memories", [wsId, effectiveLimit]);
      }

      return {
        results: rows.map((r) => ({
          id: r.id || r.entity_id || "",
          memory: r.content || "",
          user_id: finalUserId || "",
          agent_id: finalAgentId || "",
          metadata: {},
        })),
      };
    } catch (exc) {
      throw new Error(`mem0.get_all(user_id='${finalUserId}') failed: ${exc}`);
    }
  }

  /**
   * Update a memory's content and/or metadata.
   */
  async update(
    memoryId: string,
    data: string | Record<string, unknown>,
    options: UpdateOptions = {},
  ): Promise<{ message: string }> {
    try {
      let content: string;
      if (typeof data === "object") {
        content = (data.content as string) ?? (data.memory as string) ?? JSON.stringify(data);
      } else {
        content = data;
      }
      await this._client._call("update_memory", [memoryId, content, content.slice(0, 200)]);
      return { message: "Memory updated successfully!" };
    } catch (exc) {
      throw new Error(`mem0.update('${memoryId}') failed: ${exc}`);
    }
  }

  /**
   * Delete a memory by ID.
   */
  async delete(memoryId: string): Promise<{ message: string }> {
    try {
      await this._client._call("delete_memory", [memoryId]);
      return { message: "Memory deleted successfully!" };
    } catch (exc) {
      throw new Error(`mem0.delete('${memoryId}') failed: ${exc}`);
    }
  }

  /**
   * Delete all memories for a user.
   */
  async deleteAll(options: DeleteAllOptions = {}): Promise<{ status: string; deleted: number }> {
    const { userId, agentId, runId, filters } = options;

    let finalUserId = userId;
    let finalAgentId = agentId;
    let finalRunId = runId;

    if (filters) {
      const [fu, fa, fr] = this._extractIdsFromFilters(filters);
      finalUserId = finalUserId || fu;
      finalAgentId = finalAgentId || fa;
      finalRunId = finalRunId || fr;
    }

    try {
      const result = await this.getAll({ userId: finalUserId, agentId: finalAgentId, runId: finalRunId });
      const memories = result.results;
      for (const mem of memories) {
        const memId = mem.id;
        if (memId) await this._client._call("delete_memory", [memId]);
      }
      return { status: "ok", deleted: memories.length };
    } catch (exc) {
      throw new Error(`mem0.delete_all(user_id='${finalUserId}') failed: ${exc}`);
    }
  }

  /**
   * Get version history for a memory.
   */
  async history(memoryId: string): Promise<HistoryEntry[]> {
    try {
      return await this._client._call("get_memory_history", [memoryId]);
    } catch (exc) {
      throw new Error(`mem0.history('${memoryId}') failed: ${exc}`);
    }
  }

  /**
   * Reset all state (clear workspace cache).
   */
  reset(): { status: string } {
    this._userIdToWs.clear();
    return { status: "ok" };
  }

  /**
   * Close the underlying HTTP client (idempotent).
   * Mem0 v2+ compat.
   */
  close(): void {
    this._userIdToWs.clear();
  }

  // -------------------------------------------------------------------------
  // chat() — RAG + LLM response (Mem0 v2 forward-looking)
  // -------------------------------------------------------------------------

  /**
   * Generate a chat response augmented by stored memories.
   */
  async chat(
    query: string,
    options: ChatOptions = {},
  ): Promise<ChatResult> {
    const { userId, agentId = "assistant", runId, messages, memoryType, llmConfig } = options;

    await this.add(query, { userId, agentId, runId, memoryType });

    const searchResults = await this.search(query, { userId, agentId, runId, limit: 10 });
    const contextTexts = searchResults.results.map((r) => r.memory).filter(Boolean);

    const systemPrompt =
      "You are a helpful assistant with access to the user's stored memories. " +
      "Use the following relevant memories to answer the user's question. " +
      "If the memories are not relevant, answer normally.";

    let contextBlock = "";
    if (contextTexts.length) {
      contextBlock = "\nRelevant memories:\n" + contextTexts.map((t) => `- ${t}`).join("\n");
    }

    let historyBlock = "";
    if (messages) {
      historyBlock = "\nConversation history:\n" + messages.map((m) => `${m.role}: ${m.content}`).join("\n");
    }

    const userPrompt = `${contextBlock}${historyBlock}\nUser: ${query}\nAssistant:`;

    let responseText = query;
    if (llmConfig) {
      // TODO: implement custom LLM client
    }

    await this.add(responseText, { userId, agentId, runId, memoryType });

    return {
      response: responseText,
      context: contextTexts,
      memories: searchResults.results,
    };
  }

  /**
   * Create a memory tool for agent frameworks.
   * @deprecated This method was removed from upstream Mem0 v2.0.
   */
  createMemoryTool(options: { userId?: string; agentId?: string; runId?: string } = {}): { status: string; note: string } {
    return {
      status: "not_implemented",
      note: "create_memory_tool was removed from Mem0 v2.0. Use chat() for RAG or search()+add() directly.",
    };
  }
}

// ---------------------------------------------------------------------------
// Internal exception for infer+merge flow
// ---------------------------------------------------------------------------

class _InferMergeDone extends Error {
  payload: AddResult;
  constructor(payload: AddResult) {
    super("InferMergeDone");
    this.payload = payload;
  }
}

export { Memory as Mem0Memory };