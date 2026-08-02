/**
 * TypeScript SDK for spacetime-memory.
 *
 * Barrel export file. The actual domain logic lives in src/ modules.
 *
 * Connects to a running SpacetimeDB instance via HTTP SQL API + reducer
 * endpoint, and to the Rust ONNX embedder sidecar for semantic search.
 *
 * Usage:
 *   import { Client } from "spacetime-memory";
 *   const client = new Client();
 *   await client.createWorkspace("my-workspace");
 *   await client.store("ws-id", "I like pizza");
 *   const results = await client.search("ws-id", "pizza", { semantic: true });
 */

// ---------------------------------------------------------------------------
// Re‑export all types, constants, and result interfaces from src/types
// ---------------------------------------------------------------------------
export * from "./src/types";

// ---------------------------------------------------------------------------
// Re‑export helper functions (used by tests and downstream code)
// ---------------------------------------------------------------------------
export { esc, escLike, sortByCreatedDesc, sortByCreatedAsc, jsLike, safeIdent, safeNum, fnmatch, queryHash, parseSqlResponse } from "./src/helpers";

// ---------------------------------------------------------------------------
// Re‑export Compounder and WsSubscription for convenience
// ---------------------------------------------------------------------------
export { Compounder, CompounderCrossLinkResult, SuggestConnectionResult, EntityPageResult, IngestSourceResult, StoreAnswerResultEx } from "./compounder";
export { WsSubscription, WsSubscriptionStats } from "./ws_subscription";

// ---------------------------------------------------------------------------
// Import domain function modules
// ---------------------------------------------------------------------------
import * as auth from "./src/auth";
import * as admin from "./src/admin";
import * as ws from "./src/workspaces";
import * as sessions from "./src/sessions";
import * as users from "./src/users";
import * as notes from "./src/notes";
import * as kg from "./src/kg";
import * as tags from "./src/tags";
import * as peers from "./src/peers";
import * as profile from "./src/profile";
import * as docs from "./src/documents";
import * as insights from "./src/insights";
import * as memories from "./src/memories";
import * as newFeatures from "./src/newFeatures";
import * as factTriple from "./src/factTriple";
import * as directive from "./src/directive";
import * as batchOps from "./src/batchOps";
import * as patternDetection from "./src/patternDetection";

// ---------------------------------------------------------------------------
// DeltaSync is needed inside the class
// ---------------------------------------------------------------------------
import { DeltaSync } from "./delta_sync";

// Internal helpers used by _sql and _sqlExec
import { esc, escLike, parseSqlResponse } from "./src/helpers";

import type {
  ClientOptions, ClientLike, StoreOptions, SearchOptions, ListMemoriesOptions,
  MemoryRecord, SearchResult, Workspace, SpaceMemberRecord, PeerRecord,
  SessionStepRecord, NoteRecord, TagRecord, FactRecord, MentalModelRecord,
  MemoryRevisionRecord, CrossLinkResult, LintResult, StoreAnswerResult,
  OverviewResult, CrossEncoderRerankOptions, AddFactOptions, KGNodeRecord,
  KGEdgeRecord, StoreAnswerOptions, BatchMemoryItem,
} from "./src/types";

// ---------------------------------------------------------------------------
// Client class
// ---------------------------------------------------------------------------

export class Client {
  /** @internal */ host: string;
  /** @internal */ port: string;
  /** @internal */ database: string;
  /** @internal */ embedderUrl: string;
  /** @internal */ tantivyUrl: string;
  /** @internal */ mcpUrl: string;
  /** @internal */ baseUrl: string;
  /** @internal */ token: string;
  /** @internal */ _metricsCollector: { record?: unknown; record_latency?: unknown; to_dict?: () => Record<string, unknown>; toDict?: () => Record<string, unknown> } | null = null;
  private _deltaSync: DeltaSync | null = null;

  constructor(opts: ClientOptions = {}) {
    this.host = opts.host ?? process.env.SPACETIMEDB_HOST ?? "127.0.0.1";
    this.port = String(opts.port ?? process.env.SPACETIMEDB_PORT ?? "3001");
    this.database = opts.database ?? process.env.SPACETIMEDB_DB ?? "spacetime-memory";
    this.embedderUrl = opts.embedderUrl ?? process.env.EMBEDDER_URL ?? "http://127.0.0.1:9090/v1";
    this.tantivyUrl = opts.tantivyUrl ?? process.env.TANTIVY_URL ?? "http://127.0.0.1:9091";
    this.mcpUrl = opts.mcpUrl ?? process.env.MCP_URL ?? "http://127.0.0.1:8099";
    this.token = opts.token ?? process.env.SPACETIMEDB_TOKEN ?? "";
    this.baseUrl = `http://${this.host}:${this.port}`;
  }

  // -----------------------------------------------------------------------
  // Internal helpers (public so domain modules can use them)
  // -----------------------------------------------------------------------

  /** Auth headers attached to every request when a token is configured. */
  _authHeaders(): Record<string, string> {
    return this.token ? { Authorization: `Bearer ${this.token}` } : {};
  }

  private sqlUrl(): string {
    return `${this.baseUrl}/v1/database/${this.database}/sql`;
  }

  private reducerUrl(): string {
    return `${this.baseUrl}/v1/database/${this.database}/call`;
  }

  /**
   * Execute a raw SQL SELECT query against the SpacetimeDB SQL API.
   * Prefer _query() for content tables; reserved for public result tables.
   */
  async _sql(query: string): Promise<Record<string, unknown>[]> {
    const resp = await fetch(this.sqlUrl(), {
      method: "POST",
      headers: { "Content-Type": "text/plain", ...this._authHeaders() },
      body: query,
    });
    if (!resp.ok) {
      throw new Error(`SQL error (${resp.status}): ${await resp.text()}`);
    }
    const { parseSqlResponse } = await import("./src/helpers");
    return parseSqlResponse(await resp.text());
  }

  /**
   * SAFE parameterized SQL execution.
   */
  async _sqlExec(
    template: string,
    params: Record<string, string>,
    opts?: { like?: boolean },
  ): Promise<Record<string, unknown>[]> {
    const { esc, escLike } = await import("./src/helpers");
    let query = template;
    for (const [key, val] of Object.entries(params)) {
      const escaped = opts?.like
        ? `'${escLike(val)}'`
        : `'${esc(val)}'`;
      query = query.replace(
        new RegExp(`:${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'g'),
        escaped,
      );
    }
    return this._sql(query);
  }

  /**
   * Deterministic 64-bit hash matching the Rust hybrid_query reducer.
   */
  private _queryHash(query: string): string {
    let h = BigInt(0);
    const encoder = new TextEncoder();
    const bytes = encoder.encode(query);
    for (const b of bytes) {
      h = ((h * 6364136223846793005n) + BigInt(b)) & 0xFFFFFFFFFFFFFFFFn;
    }
    return h.toString(16).padStart(16, "0");
  }

  /**
   * Call a named reducer (stored procedure) with positional arguments.
   */
  async _call(reducer: string, args: unknown[]): Promise<any> {
    const resp = await fetch(`${this.reducerUrl()}/${reducer}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...this._authHeaders() },
      body: JSON.stringify(args),
    });
    if (!resp.ok) {
      throw new Error(`Reducer error (${resp.status}): ${await resp.text()}`);
    }
    const text = await resp.text();
    if (!text || !text.trim()) return null;
    try { return JSON.parse(text); } catch { return text; }
  }

  /**
   * Call a reducer and return the raw response body.
   */
  async _callWithResult(reducer: string, args: unknown[]): Promise<string> {
    const resp = await fetch(`${this.reducerUrl()}/${reducer}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...this._authHeaders() },
      body: JSON.stringify(args),
    });
    if (!resp.ok) {
      throw new Error(`Reducer error (${resp.status}): ${await resp.text()}`);
    }
    const text = await resp.text();
    if (text.length === 0) {
      throw new Error(`Reducer '${reducer}' returned empty response`);
    }
    return text;
  }

  /**
   * Get a text embedding vector from the embedder sidecar.
   */
  async _embed(text: string): Promise<number[]> {
    try {
      const resp = await fetch(`${this.embedderUrl}/embeddings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: text, model: process.env.EMBEDDER_LOCAL_MODEL ?? "BAAI/bge-m3" }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!resp.ok) return [];
      const data = await resp.json() as Record<string, unknown>;
      const first = (data?.data as Record<string, unknown>[])?.[0];
      return (first?.embedding as number[]) ?? [];
    } catch { return []; }
  }

  /**
   * Query a content table through the query_table reducer (SQL injection safe).
   */
  async _query(
    table: string,
    workspaceId: string = "",
    filter?: Record<string, string>
  ): Promise<Record<string, unknown>[]> {
    const queryId = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36);
    const filterJson = JSON.stringify(filter ?? {});
    await this._call("query_table", [queryId, table, workspaceId, filterJson, "[]"]);
    const rows = await this._sqlExec(
      "SELECT table_name, row_json FROM query_result WHERE query_id = :qid",
      { qid: queryId },
    );
    const results: Record<string, unknown>[] = [];
    for (const r of rows) {
      if (r?.row_json) { results.push(JSON.parse(r.row_json as string)); }
      else { results.push(r); }
    }
    return results;
  }

  // -----------------------------------------------------------------------
  // Auth / Account
  // -----------------------------------------------------------------------

  register(username: string, displayName: string = "", password: string = ""): Promise<void> {
    return auth.register(this, username, displayName, password);
  }
  login(username: string, password: string): Promise<void> { return auth.login(this, username, password); }
  logout(): Promise<void> { return auth.logout(this); }
  updateAccount(displayName: string = "", currentPassword: string = "", newPassword: string = ""): Promise<void> {
    return auth.updateAccount(this, displayName, currentPassword, newPassword);
  }
  deactivateAccount(password: string): Promise<void> { return auth.deactivateAccount(this, password); }

  /** Promote a user to admin. */
  promoteAdmin(targetIdentity: string): Promise<void> { return admin.promoteAdmin(this, targetIdentity); }
  /** Demote an admin to regular user. */
  demoteAdmin(targetIdentity: string): Promise<void> { return admin.demoteAdmin(this, targetIdentity); }
  /** List all admin accounts. */
  listAdmins(): Promise<Record<string, unknown>[]> { return admin.listAdmins(this); }

  // -----------------------------------------------------------------------
  // API Keys
  // -----------------------------------------------------------------------

  createApiKey(workspaceId: string, name: string, permissions?: string): Promise<Record<string, unknown>> {
    return auth.createApiKey(this, workspaceId, name, permissions);
  }
  deactivateApiKey(keyId: string): Promise<void> { return auth.deactivateApiKey(this, keyId); }
  listApiKeys(workspaceId: string): Promise<Record<string, unknown>[]> { return auth.listApiKeys(this, workspaceId); }
  verifyApiKey(rawKey: string): Promise<Record<string, unknown>> { return auth.verifyApiKey(this, rawKey); }
  updateApiKey(keyId: string, name = "", permissions = "", scope = "", isActive = true): Promise<Record<string, unknown>> {
    return auth.updateApiKey(this, keyId, name, permissions, scope, isActive);
  }

  // -----------------------------------------------------------------------
  // Workspace
  // -----------------------------------------------------------------------

  createWorkspace(name: string, description?: string): Promise<void> { return ws.createWorkspace(this, name, description); }
  listWorkspaces(): Promise<Workspace[]> { return ws.listWorkspaces(this); }
  updateWorkspace(id: string, name: string, description: string): Promise<void> { return ws.updateWorkspace(this, id, name, description); }
  deleteWorkspace(workspaceId: string): Promise<void> { return ws.deleteWorkspace(this, workspaceId); }
  setWorkspaceVisibility(workspaceId: string, isPublic: boolean): Promise<void> { return ws.setWorkspaceVisibility(this, workspaceId, isPublic); }
  getWorkspaceContext(workspaceId: string): Promise<Record<string, unknown> | null> { return ws.getWorkspaceContext(this, workspaceId); }
  listSpaceMembers(workspaceId: string): Promise<SpaceMemberRecord[]> { return ws.listSpaceMembers(this, workspaceId); }
  grantSpaceAccess(workspaceId: string, peerId: string, permission: string): Promise<void> { return ws.grantSpaceAccess(this, workspaceId, peerId, permission); }
  revokeSpaceAccess(workspaceId: string, peerId: string): Promise<void> { return ws.revokeSpaceAccess(this, workspaceId, peerId); }
  setWorkspaceContext(workspaceId: string, context: string): Promise<void> { return ws.setWorkspaceContext(this, workspaceId, context); }
  getDecayConfig(workspaceId: string): Promise<Record<string, unknown> | null> { return ws.getDecayConfig(this, workspaceId); }
  setDecayModel(workspaceId: string, modelType: string, halfLife: number, maxStrength: number): Promise<void> {
    return ws.setDecayModel(this, workspaceId, modelType, halfLife, maxStrength);
  }
  initWorkspaceEncryption(workspaceId: string): Promise<Record<string, unknown>> { return ws.initWorkspaceEncryption(this, workspaceId); }
  setWorkspaceEncryptionEnabled(workspaceId: string, enabled: boolean): Promise<Record<string, unknown>> { return ws.setWorkspaceEncryptionEnabled(this, workspaceId, enabled); }
  rotateWorkspaceEncryptionKey(workspaceId: string): Promise<Record<string, unknown>> { return ws.rotateWorkspaceEncryptionKey(this, workspaceId); }
  encryptExistingMemories(workspaceId: string): Promise<Record<string, unknown>> { return ws.encryptExistingMemories(this, workspaceId); }
  getDecryptedMemory(memoryId: string): Promise<Record<string, unknown> | null> { return ws.getDecryptedMemory(this, memoryId); }

  // -----------------------------------------------------------------------
  // Peers
  // -----------------------------------------------------------------------

  listPeers(workspaceId?: string): Promise<PeerRecord[]> { return peers.listPeers(this, workspaceId); }
  getPeerReputation(peerId: string): Promise<Record<string, unknown> | null> { return peers.getPeerReputation(this, peerId); }
  addFact(workspaceId: string, peerId: string, content: string, opts?: AddFactOptions): Promise<void> {
    return peers.addFact(this, workspaceId, peerId, content, opts);
  }
  listFacts(workspaceId: string, peerId: string): Promise<FactRecord[]> { return peers.listFacts(this, workspaceId, peerId); }
  deleteFact(factId: string): Promise<void> { return peers.deleteFact(this, factId); }
  updateFact(factId: string, content: string, confidence?: number): Promise<void> { return peers.updateFact(this, factId, content, confidence); }
  searchFacts(workspaceId: string, query: string): Promise<FactRecord[]> { return peers.searchFacts(this, workspaceId, query); }

  // -----------------------------------------------------------------------
  // Mental Models
  // -----------------------------------------------------------------------

  synthesizeMentalModels(workspaceId: string, memoryIds: string[]): Promise<MentalModelRecord[]> {
    return insights.synthesizeMentalModels(this, workspaceId, memoryIds);
  }
  getMentalModel(modelId: string): Promise<MentalModelRecord[]> { return insights.getMentalModel(this, modelId); }
  listMentalModels(workspaceId: string, status?: string): Promise<MentalModelRecord[]> {
    return insights.listMentalModels(this, workspaceId, status);
  }
  deleteMentalModel(modelId: string): Promise<void> { return insights.deleteMentalModel(this, modelId); }
  updateMentalModel(modelId: string, content: string, confidence?: number, status?: string): Promise<void> {
    return insights.updateMentalModel(this, modelId, content, confidence, status);
  }

  // -----------------------------------------------------------------------
  // Memory
  // -----------------------------------------------------------------------

  store(workspaceId: string, content: string, opts?: StoreOptions): Promise<void> {
    return memories.store(this, workspaceId, content, opts);
  }
  search(workspaceId: string, query: string, opts?: SearchOptions): Promise<SearchResult[]> {
    return memories.search(this, workspaceId, query, opts);
  }
  getMemory(memoryId: string): Promise<MemoryRecord[]> { return memories.getMemory(this, memoryId); }
  getMemoryImages(memoryId: string): Promise<Record<string, string>[]> { return memories.getMemoryImages(this, memoryId); }
  deleteMemory(memoryId: string): Promise<void> { return memories.deleteMemory(this, memoryId); }
  reinforce(memoryId: string): Promise<void> { return memories.reinforce(this, memoryId); }
  updateMemory(memoryId: string, content: string, summary?: string, confidence?: number, expiresAt?: number): Promise<void> {
    return memories.updateMemory(this, memoryId, content, summary, confidence, expiresAt);
  }
  rateMemory(memoryId: string, rating: string, peerId: string): Promise<void> { return memories.rateMemory(this, memoryId, rating, peerId); }
  getUserMemories(userScope: string, workspaceId: string): Promise<Record<string, unknown>[]> {
    return memories.getUserMemories(this, userScope, workspaceId);
  }
  consolidateMemories(workspaceId: string, sourceIds: string[], targetContent: string, targetSummary: string): Promise<void> {
    return memories.consolidateMemories(this, workspaceId, sourceIds, targetContent, targetSummary);
  }
  expireMemories(): Promise<void> { return memories.expireMemories(this); }
  getMemoryStats(workspaceId: string): Promise<Record<string, string> | null> { return memories.getMemoryStats(this, workspaceId); }
  getMemoryHistory(memoryId: string): Promise<MemoryRevisionRecord[]> { return memories.getMemoryHistory(this, memoryId); }
  searchDirectoryContents(workspaceId: string, directoryPath: string): Promise<Record<string, unknown>[]> {
    return memories.searchDirectoryContents(this, workspaceId, directoryPath);
  }
  listMemories(workspaceId: string, opts?: ListMemoriesOptions): Promise<MemoryRecord[]> {
    return memories.listMemories(this, workspaceId, opts);
  }
  fuzzyGet(workspaceId: string, name: string, field?: string, threshold?: number, limit?: number): Promise<Record<string, unknown> | null> {
    return memories.fuzzyGet(this, workspaceId, name, field, threshold, limit);
  }
  globGet(workspaceId: string, pattern: string, field?: string, limit?: number): Promise<Record<string, unknown>[]> {
    return memories.globGet(this, workspaceId, pattern, field, limit);
  }
  setMemoryContext(memoryId: string, context: string): Promise<void> { return memories.setMemoryContext(this, memoryId, context); }
  getContextChain(memoryId: string): Promise<Record<string, unknown>[]> { return memories.getContextChain(this, memoryId); }
  updateMemoryTier(memoryId: string, tier: string): Promise<void> { return memories.updateMemoryTier(this, memoryId, tier); }
  setMemoryScope(memoryId: string, userScope: string): Promise<void> { return memories.setMemoryScope(this, memoryId, userScope); }
  escalateMemories(workspaceId: string, l2ToL1?: number, l1ToL0?: number): Promise<void> {
    return memories.escalateMemories(this, workspaceId, l2ToL1, l1ToL0);
  }
  searchWithFilters(workspaceId: string, query: string, memoryType?: string, tier?: string, metadataFilter?: string, locationFilter?: string, limit?: number): Promise<Record<string, unknown>[]> {
    return memories.searchWithFilters(this, workspaceId, query, memoryType, tier, metadataFilter, locationFilter, limit);
  }
  recommendMemories(workspaceId: string, limit?: number, minUrgency?: number): Promise<Record<string, unknown>[]> {
    return memories.recommendMemories(this, workspaceId, limit, minUrgency);
  }
  autoInvalidate(oldMemoryId: string, newMemoryId: string): Promise<Record<string, unknown>> { return memories.autoInvalidate(this, oldMemoryId, newMemoryId); }
  temporalSearchWithWeight(workspaceId: string, query: string, memoryType = "", tier = "", limit = 10, recencyWeight = 0.5, timeContext = 0): Promise<Record<string, unknown>[]> {
    return memories.temporalSearchWithWeight(this, workspaceId, query, memoryType, tier, limit, recencyWeight, timeContext);
  }

  // -----------------------------------------------------------------------
  // Batch memory operations
  // -----------------------------------------------------------------------

  storeBatch(workspaceId: string, items: BatchMemoryItem[]): Promise<void> {
    return memories.storeBatch(this, workspaceId, items as any);
  }

  // -----------------------------------------------------------------------
  // Knowledge Graph
  // -----------------------------------------------------------------------

  createNode(workspaceId: string, label: string, nodeType?: string, summary?: string, sourceMemoryId?: string, sourceDocumentId?: string): Promise<void> {
    return kg.createNode(this, workspaceId, label, nodeType, summary, sourceMemoryId, sourceDocumentId);
  }
  createEdge(workspaceId: string, sourceNodeId: string, targetNodeId: string, relation: string, weight?: number): Promise<void> {
    return kg.createEdge(this, workspaceId, sourceNodeId, targetNodeId, relation, weight);
  }
  queryGraph(workspaceId: string, query?: string): Promise<KGNodeRecord[]> { return kg.queryGraph(this, workspaceId, query); }
  getNeighbors(nodeId: string): Promise<KGEdgeRecord[]> { return kg.getNeighbors(this, nodeId); }
  updateNode(nodeId: string, summary?: string, nodeType?: string): Promise<void> { return kg.updateNode(this, nodeId, summary, nodeType); }
  deleteNode(nodeId: string): Promise<void> { return kg.deleteNode(this, nodeId); }
  updateEdge(edgeId: string, weight?: number): Promise<void> { return kg.updateEdge(this, edgeId, weight); }
  deleteEdge(edgeId: string): Promise<void> { return kg.deleteEdge(this, edgeId); }
  getNode(nodeId: string): Promise<Record<string, unknown>[]> { return kg.getNode(this, nodeId); }
  getNeighborsViaReducer(workspaceId: string, nodeId: string): Promise<void> { return kg.getNeighborsViaReducer(this, workspaceId, nodeId); }
  graphBfs(workspaceId: string, startNodeId: string, maxDepth: number = 3): Promise<Record<string, unknown>[]> {
    return kg.graphBfs(this, workspaceId, startNodeId, maxDepth);
  }
  bfs(workspaceId: string, startNodeId: string, maxDepth?: number): Promise<Record<string, unknown>[]> {
    return kg.bfs(this, workspaceId, startNodeId, maxDepth);
  }
  shortestPath(workspaceId: string, sourceId: string, targetId: string, maxHops: number = 6): Promise<Record<string, unknown>[]> {
    return kg.shortestPath(this, workspaceId, sourceId, targetId, maxHops);
  }
  getEdgeHistory(edgeGroupId: string): Promise<Record<string, unknown>[]> { return kg.getEdgeHistory(this, edgeGroupId); }
  addNodeCitation(workspaceId: string, nodeId: string, memoryId: string, description?: string): Promise<void> {
    return kg.addNodeCitation(this, workspaceId, nodeId, memoryId, description);
  }
  addEdgeCitation(workspaceId: string, edgeId: string, memoryId: string, description?: string): Promise<void> {
    return kg.addEdgeCitation(this, workspaceId, edgeId, memoryId, description);
  }
  getCitations(workspaceId: string, entityId: string, entityType?: string): Promise<Record<string, unknown>[]> {
    return kg.getCitations(this, workspaceId, entityId, entityType);
  }
  detectBridgeNodes(workspaceId: string, limit?: number, minCommunities?: number): Promise<Record<string, unknown>[]> {
    return kg.detectBridgeNodes(this, workspaceId, limit, minCommunities);
  }
  computePageRank(workspaceId: string, damping?: number, maxIterations?: number): Promise<void> {
    return kg.computePageRank(this, workspaceId, damping, maxIterations);
  }
  computeKgStats(workspaceId: string): Promise<Record<string, unknown> | null> { return kg.computeKgStats(this, workspaceId); }
  computeCommunityHierarchy(workspaceId: string): Promise<void> { return kg.computeCommunityHierarchy(this, workspaceId); }
  detectCommunities(workspaceId: string): Promise<void> { return kg.detectCommunities(this, workspaceId); }
  seedCommunities(workspaceId: string): Promise<void> { return kg.seedCommunities(this, workspaceId); }
  getCommunity(communityId: number): Promise<Record<string, unknown>[]> { return kg.getCommunity(this, communityId); }
  resolveEntity(workspaceId: string, name: string): Promise<void> { return kg.resolveEntity(this, workspaceId, name); }
  extractEntities(workspaceId: string, content: string): Promise<void> { return kg.extractEntities(this, workspaceId, content); }
  extractEntitiesLlm(workspaceId: string, content: string): Promise<any[]> { return kg.extractEntitiesLlm(this, workspaceId, content); }
  addAlias(entityLinkId: string, alias: string): Promise<void> { return kg.addAlias(this, entityLinkId, alias); }
  createEntityLink(workspaceId: string, name: string, entityType: string, description: string = ""): Promise<void> {
    return kg.createEntityLink(this, workspaceId, name, entityType, description);
  }

  // -----------------------------------------------------------------------
  // Notes / Wiki
  // -----------------------------------------------------------------------

  createNote(workspaceId: string, title: string, content: string, opts?: { note_date?: string; embed?: boolean }): Promise<void> {
    return notes.createNote(this, workspaceId, title, content, opts);
  }
  updateNote(noteId: string, title: string = "", content: string = "", embeddingJson: string = "[]", expectedVersion: number = 0): Promise<void> {
    return notes.updateNote(this, noteId, title, content, embeddingJson, expectedVersion);
  }
  deleteNote(noteId: string): Promise<void> { return notes.deleteNote(this, noteId); }
  listNotes(workspaceId: string): Promise<NoteRecord[]> { return notes.listNotes(this, workspaceId); }
  getNote(noteId: string): Promise<NoteRecord[]> { return notes.getNote(this, noteId); }
  getNoteByDate(noteDate: string): Promise<NoteRecord[]> { return notes.getNoteByDate(this, noteDate); }
  getNoteByTitle(title: string): Promise<NoteRecord[]> { return notes.getNoteByTitle(this, title); }
  getNoteHistory(noteId: string): Promise<Record<string, unknown>[]> { return notes.getNoteHistory(this, noteId); }
  getBacklinks(noteId: string): Promise<Record<string, unknown>[]> { return notes.getBacklinks(this, noteId); }
  getOutgoingLinks(noteId: string): Promise<Record<string, unknown>[]> { return notes.getOutgoingLinks(this, noteId); }

  // -----------------------------------------------------------------------
  // Tags
  // -----------------------------------------------------------------------

  createTag(workspaceId: string, name: string, color?: string): Promise<void> { return tags.createTag(this, workspaceId, name, color); }
  tagMemory(tagId: string, memoryId: string): Promise<void> { return tags.tagMemory(this, tagId, memoryId); }
  untagMemory(tagId: string, memoryId: string): Promise<void> { return tags.untagMemory(this, tagId, memoryId); }
  batchTagMemories(tagId: string, memoryIds: string[]): Promise<void> { return tags.batchTagMemories(this, tagId, memoryIds); }
  batchUntagMemories(tagId: string, memoryIds: string[]): Promise<void> { return tags.batchUntagMemories(this, tagId, memoryIds); }
  listTags(workspaceId: string): Promise<TagRecord[]> { return tags.listTags(this, workspaceId); }
  deleteTag(tagId: string): Promise<void> { return tags.deleteTag(this, tagId); }
  listTagsByMemory(memoryId: string): Promise<Record<string, unknown>[]> { return tags.listTagsByMemory(this, memoryId); }
  updateTag(tagId: string, name: string = "", color: string = "#808080"): Promise<void> { return tags.updateTag(this, tagId, name, color); }
  searchByTags(workspaceId: string, tagIds: string[], query: string = "", limit: number = 10): Promise<Record<string, unknown>[]> {
    return tags.searchByTags(this, workspaceId, tagIds, query, limit);
  }

  // -----------------------------------------------------------------------
  // Sessions
  // -----------------------------------------------------------------------

  createSession(workspaceId: string, name?: string): Promise<void> { return sessions.createSession(this, workspaceId, name); }
  joinSession(sessionId: string): Promise<void> { return sessions.joinSession(this, sessionId); }
  leaveSession(sessionId: string): Promise<void> { return sessions.leaveSession(this, sessionId); }
  addAgentStep(sessionId: string, step: string, stepType?: string): Promise<void> {
    return sessions.addAgentStep(this, sessionId, step, stepType);
  }
  getSessionSteps(sessionId: string): Promise<SessionStepRecord[]> { return sessions.getSessionSteps(this, sessionId); }
  getPeerSessions(peerId: string): Promise<Record<string, unknown>[]> { return sessions.getPeerSessions(this, peerId); }
  getSessionMessages(sessionId: string): Promise<Record<string, unknown>[]> { return sessions.getSessionMessages(this, sessionId); }
  searchSessionsSemantic(query: string, limit?: number): Promise<Record<string, unknown>[]> {
    return sessions.searchSessionsSemantic(this, query, limit);
  }

  // -----------------------------------------------------------------------
  // Tours
  // -----------------------------------------------------------------------

  createTour(workspaceId: string, name: string, description?: string): Promise<void> { return sessions.createTour(this, workspaceId, name, description); }
  addTourStop(tourId: string, nodeId: string, sequence: number): Promise<void> { return sessions.addTourStop(this, tourId, nodeId, sequence); }
  removeTourStop(tourStopId: string): Promise<void> { return sessions.removeTourStop(this, tourStopId); }
  deleteTourStop(stopId: string): Promise<void> { return sessions.deleteTourStop(this, stopId); }
  deleteTour(tourId: string): Promise<void> { return sessions.deleteTour(this, tourId); }

  // -----------------------------------------------------------------------
  // Profile
  // -----------------------------------------------------------------------

  getProfileContext(peerId: string): Promise<Record<string, unknown> | null> { return profile.getProfileContext(this, peerId); }
  addProfileFact(peerId: string, fact: string): Promise<void> { return profile.addProfileFact(this, peerId, fact); }
  addDynamicContext(peerId: string, context: string): Promise<void> { return profile.addDynamicContext(this, peerId, context); }
  getProfile(peerId: string): Promise<Record<string, unknown> | null> { return profile.getProfile(this, peerId); }
  listProfiles(workspaceId: string): Promise<Record<string, unknown>[]> { return profile.listProfiles(this, workspaceId); }
  searchProfiles(workspaceId: string, query: string, limit?: number): Promise<Record<string, unknown>[]> {
    return profile.searchProfiles(this, workspaceId, query, limit);
  }
  upsertProfile(peerId: string, staticFacts?: string, dynamicContext?: string, preferences?: string, tags?: string): Promise<void> {
    return profile.upsertProfile(this, peerId, staticFacts, dynamicContext, preferences, tags);
  }

  // -----------------------------------------------------------------------
  // Documents
  // -----------------------------------------------------------------------

  createDocument(workspaceId: string, title: string, content?: string, contentType?: string, filePath?: string, sourceUrl?: string, metadata?: Record<string, unknown>): Promise<void> {
    return docs.createDocument(this, workspaceId, title, content, contentType, filePath, sourceUrl, metadata);
  }
  getDocument(docId: string): Promise<Record<string, unknown> | null> { return docs.getDocument(this, docId); }
  listDocuments(workspaceId: string): Promise<Record<string, unknown>[]> { return docs.listDocuments(this, workspaceId); }
  getDocumentChunks(docId: string): Promise<Record<string, unknown>[]> { return docs.getDocumentChunks(this, docId); }
  deleteDocument(docId: string): Promise<void> { return docs.deleteDocument(this, docId); }
  searchDocuments(workspaceId: string, query: string, limit = 10): Promise<Record<string, unknown>[]> { return docs.searchDocuments(this, workspaceId, query, limit); }
  updateDocument(documentId: string, title = "", content = "", metadata: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return docs.updateDocument(this, documentId, title, content, metadata);
  }

  // -----------------------------------------------------------------------
  // Insights & Mental Models
  // -----------------------------------------------------------------------

  createInsight(workspaceId: string, sourceMemoryId: string, content: string, summary = ""): Promise<Record<string, unknown>> {
    return insights.createInsight(this, workspaceId, sourceMemoryId, content, summary);
  }
  deleteInsight(insightId: string): Promise<Record<string, unknown>> { return insights.deleteInsight(this, insightId); }

  // -----------------------------------------------------------------------
  // Directory
  // -----------------------------------------------------------------------

  listDirectory(directoryId: string): Promise<Record<string, unknown>[]> { return ws.listDirectory(this, directoryId); }
  traverseDirectory(workspaceId: string, rootDirectoryId: string): Promise<Record<string, unknown>[]> {
    return ws.traverseDirectory(this, workspaceId, rootDirectoryId);
  }
  getDirectory(workspaceId: string, pathOrId: string): Promise<Record<string, unknown>[]> {
    return ws.getDirectory(this, workspaceId, pathOrId);
  }
  createDirectory(workspaceId: string, name: string, path: string, parentId?: string, description?: string): Promise<void> {
    return ws.createDirectory(this, workspaceId, name, path, parentId, description);
  }
  linkMemoryToDirectory(directoryId: string, memoryId: string, workspaceId: string): Promise<void> {
    return ws.linkMemoryToDirectory(this, directoryId, memoryId, workspaceId);
  }
  unlinkMemoryFromDirectory(directoryId: string, memoryId: string): Promise<void> {
    return ws.unlinkMemoryFromDirectory(this, directoryId, memoryId);
  }

  // -----------------------------------------------------------------------
  // Context Packs
  // -----------------------------------------------------------------------

  listContextPacks(workspaceId: string): Promise<Record<string, unknown>[]> { return ws.listContextPacks(this, workspaceId); }
  listContextEntries(packId: string): Promise<Record<string, unknown>[]> { return ws.listContextEntries(this, packId); }
  listContextDeltas(previousPackId: string): Promise<Record<string, unknown>[]> { return ws.listContextDeltas(this, previousPackId); }
  storeContextPack(workspaceId: string, name: string, memoryIds: string[], contextText?: string): Promise<void> {
    return ws.storeContextPack(this, workspaceId, name, memoryIds, contextText);
  }

  // -----------------------------------------------------------------------
  // Connector Configuration
  // -----------------------------------------------------------------------

  registerConnector(name: string, connectorType: string, configJson: string, workspaceId: string, scheduleSecs: number): Promise<void> {
    return ws.registerConnector(this, name, connectorType, configJson, workspaceId, scheduleSecs);
  }
  updateConnector(id: string, name: string, connectorType: string, configJson: string, workspaceId: string, scheduleSecs: number, isActive: boolean): Promise<void> {
    return ws.updateConnector(this, id, name, connectorType, configJson, workspaceId, scheduleSecs, isActive);
  }
  deleteConnector(id: string): Promise<void> { return ws.deleteConnector(this, id); }

  // -----------------------------------------------------------------------
  // Harmonic Beliefs
  // -----------------------------------------------------------------------

  storeHarmonicBeliefs(workspaceId: string, peerId: string, beliefsJson: string, clusterId: string): Promise<void> {
    return insights.storeHarmonicBeliefs(this, workspaceId, peerId, beliefsJson, clusterId);
  }
  clearHarmonicBeliefs(workspaceId: string, minConfidence: number): Promise<void> {
    return insights.clearHarmonicBeliefs(this, workspaceId, minConfidence);
  }
  logResonanceSession(workspaceId: string, peerId: string, clusterCount: number, beliefsGenerated: number, contradictionsResolved: number, harmonyScoreAvg: number, durationMs: number): Promise<void> {
    return insights.logResonanceSession(this, workspaceId, peerId, clusterCount, beliefsGenerated, contradictionsResolved, harmonyScoreAvg, durationMs);
  }

  // -----------------------------------------------------------------------
  // Pattern Detection
  // -----------------------------------------------------------------------

  detectPatterns(workspaceId: string, opts?: { limit?: number; includeClusters?: boolean; includeTerms?: boolean; includeCoOccur?: boolean }): Promise<{
    temporal_clusters: Array<{ start_time: number; end_time: number; count: number; ids: string[]; summary_terms: string[] }>;
    frequent_terms: Array<{ term: string; frequency: number; doc_count: number }>;
    co_occurrences: Array<{ term_a: string; term_b: string; count: number }>;
    total_memories: number;
    summary: string;
  }> {
    return insights.detectPatterns(this, workspaceId, opts);
  }

  // -----------------------------------------------------------------------
  // Pattern Detection — server-side reducers
  // -----------------------------------------------------------------------

  detectTemporalClusters(workspaceId: string): Promise<import("./src/patternDetection").TemporalClusterRecord[]> {
    return patternDetection.detectTemporalClusters(this, workspaceId);
  }

  detectEntityCooccurrences(workspaceId: string): Promise<import("./src/patternDetection").EntityCooccurrenceRecord[]> {
    return patternDetection.detectEntityCooccurrences(this, workspaceId);
  }

  detectTopicClusters(workspaceId: string): Promise<import("./src/patternDetection").TopicClusterRecord[]> {
    return patternDetection.detectTopicClusters(this, workspaceId);
  }

  // -----------------------------------------------------------------------
  // Admin / Health
  // -----------------------------------------------------------------------

  ping(): Promise<Record<string, unknown>> { return admin.ping(this); }
  checkEmbedderHealth(): Promise<Record<string, unknown>> { return admin.checkEmbedderHealth(this); }
  health(): Promise<Record<string, unknown>> { return admin.health(this); }
  checkTantivyHealth(): Promise<Record<string, unknown>> { return admin.checkTantivyHealth(this); }
  runMaintenance(): Promise<void> { return admin.runMaintenance(this); }
  dedup(workspaceId: string): Promise<void> { return admin.dedup(this, workspaceId); }
  suggestMerges(workspaceId: string, threshold?: number): Promise<void> { return admin.suggestMerges(this, workspaceId, threshold); }
  approveMerge(suggestionId: string): Promise<void> { return admin.approveMerge(this, suggestionId); }
  rejectMerge(suggestionId: string): Promise<void> { return admin.rejectMerge(this, suggestionId); }

  // -----------------------------------------------------------------------
  // Backup / Restore
  // -----------------------------------------------------------------------

  backup(outputPath?: string): Promise<Record<string, unknown>> { return admin.backup(this, outputPath); }
  restore(inputJson: string | Record<string, unknown>): Promise<Record<string, unknown>> { return admin.restore(this, inputJson); }

  // -----------------------------------------------------------------------
  // Metrics
  // -----------------------------------------------------------------------

  setMetricsCollector(collector: any): void { admin.setMetricsCollector(this, collector); }
  getMetrics(): any | null { return admin.getMetrics(this); }

  // -----------------------------------------------------------------------
  // User management
  // -----------------------------------------------------------------------

  addUser(userId: string, email = "", firstName = "", lastName = "", metadataJson = ""): Promise<Record<string, unknown>> {
    return users.addUser(this, userId, email, firstName, lastName, metadataJson);
  }
  getUser(userId: string): Promise<Record<string, unknown>> { return users.getUser(this, userId); }
  updateUser(userId: string, email = "", firstName = "", lastName = "", metadataJson = ""): Promise<Record<string, unknown>> {
    return users.updateUser(this, userId, email, firstName, lastName, metadataJson);
  }
  deleteUser(userId: string): Promise<Record<string, unknown>> { return users.deleteUser(this, userId); }
  listUsers(): Promise<Record<string, unknown>[]> { return users.listUsers(this); }
  getUserSessions(userId: string): Promise<Record<string, unknown>[]> { return users.getUserSessions(this, userId); }

  // -----------------------------------------------------------------------
  // Tantivy
  // -----------------------------------------------------------------------

  _tantivySearch(workspaceId: string, query: string, limit: number = 20): Promise<SearchResult[]> {
    return memories.tantivySearch(this, workspaceId, query, limit);
  }

  // -----------------------------------------------------------------------
  // Cross-encoder rerank
  // -----------------------------------------------------------------------

  crossEncoderRerank(query: string, candidates: Record<string, unknown>[], opts: CrossEncoderRerankOptions = {}): Promise<Record<string, unknown>[]> {
    return memories.crossEncoderRerank(this, query, candidates, opts);
  }

  // -----------------------------------------------------------------------
  // DeltaSync
  // -----------------------------------------------------------------------

  get deltaSync(): DeltaSync {
    if (this._deltaSync === null) {
      this._deltaSync = new DeltaSync(this as any);
    }
    return this._deltaSync;
  }

  // -----------------------------------------------------------------------
  // Compounder / Wiki operations (on Client)
  // -----------------------------------------------------------------------

  crossLink(workspaceId: string, limit?: number): Promise<CrossLinkResult> { return ws.crossLink(this, workspaceId, limit); }
  suggestConnections(workspaceId: string): Promise<KGNodeRecord[]> { return ws.suggestConnections(this, workspaceId); }
  lintWorkspace(workspaceId: string): Promise<LintResult> { return ws.lintWorkspace(this, workspaceId); }
  generateOverview(workspaceId: string): Promise<OverviewResult> { return ws.generateOverview(this, workspaceId); }
  exportWorkspace(workspaceId: string): Promise<string> { return ws.exportWorkspace(this, workspaceId); }
  exportWorkspaceJson(workspaceId: string, opts?: { includeSystemNotes?: boolean; outputPath?: string }): Promise<Record<string, unknown>> {
    return ws.exportWorkspaceJson(this, workspaceId, opts);
  }
  storeAnswer(query: string, answer: string, opts?: StoreAnswerOptions): Promise<StoreAnswerResult> {
    return ws.storeAnswer(this, query, answer, opts);
  }

  // -----------------------------------------------------------------------
  // New Features — MemoryMeta, Webhook, Observation, ContextTree, Review
  // -----------------------------------------------------------------------

  setMemoryMeta(workspaceId: string, memoryId: string, category: string = "", immutable: boolean = false, extraJson: string = "{}"): Promise<Record<string, unknown>> {
    return newFeatures.setMemoryMeta(this, workspaceId, memoryId, category, immutable, extraJson);
  }
  getMemoryMeta(memoryId: string): Promise<Record<string, unknown> | null> {
    return newFeatures.getMemoryMeta(this, memoryId);
  }
  batchSetMemoryMeta(workspaceId: string, idsJson: string, category: string = "", immutable: boolean = false): Promise<Record<string, unknown>> {
    return newFeatures.batchSetMemoryMeta(this, workspaceId, idsJson, category, immutable);
  }
  listMemoryMeta(workspaceId: string): Promise<Record<string, unknown>[]> {
    return newFeatures.listMemoryMeta(this, workspaceId);
  }
  createWebhook(workspaceId: string, name: string, url: string, eventTypes: string = "[]", secret: string = ""): Promise<Record<string, unknown>> {
    return newFeatures.createWebhook(this, workspaceId, name, url, eventTypes, secret);
  }
  updateWebhook(webhookId: string, name: string = "", url: string = "", eventTypes: string = "", isActive: boolean = true): Promise<Record<string, unknown>> {
    return newFeatures.updateWebhook(this, webhookId, name, url, eventTypes, isActive);
  }
  deleteWebhook(webhookId: string): Promise<Record<string, unknown>> {
    return newFeatures.deleteWebhook(this, webhookId);
  }
  listWebhooks(workspaceId: string): Promise<Record<string, unknown>[]> {
    return newFeatures.listWebhooks(this, workspaceId);
  }
  fireWebhookEvent(workspaceId: string, eventType: string, payload: string = "{}"): Promise<Record<string, unknown>> {
    return newFeatures.fireWebhookEvent(this, workspaceId, eventType, payload);
  }
  createObservation(workspaceId: string, content: string, summary: string = "", evidenceJson: string = "[]", observationType: string = "fact", confidence: number = 0.8): Promise<Record<string, unknown>> {
    return newFeatures.createObservation(this, workspaceId, content, summary, evidenceJson, observationType, confidence);
  }
  updateObservation(id: string, content: string = "", summary: string = "", confidence: number = 0.0): Promise<Record<string, unknown>> {
    return newFeatures.updateObservation(this, id, content, summary, confidence);
  }
  deleteObservation(id: string): Promise<Record<string, unknown>> {
    return newFeatures.deleteObservation(this, id);
  }
  listObservations(workspaceId: string): Promise<Record<string, unknown>[]> {
    return newFeatures.listObservations(this, workspaceId);
  }
  setContext(workspaceId: string, path: string, content: string, priority: number = 0.0, isGlobal: boolean = false): Promise<Record<string, unknown>> {
    return newFeatures.setContext(this, workspaceId, path, content, priority, isGlobal);
  }
  deleteContext(contextId: string): Promise<Record<string, unknown>> {
    return newFeatures.deleteContext(this, contextId);
  }
  listContexts(workspaceId: string): Promise<Record<string, unknown>[]> {
    return newFeatures.listContexts(this, workspaceId);
  }
  resolveContext(workspaceId: string, path: string): Promise<Record<string, unknown>[]> {
    return newFeatures.resolveContext(this, workspaceId, path);
  }
  scheduleReview(workspaceId: string, memoryId: string, userId: string): Promise<Record<string, unknown>> {
    return newFeatures.scheduleReview(this, workspaceId, memoryId, userId);
  }
  performReview(reviewId: string, grade: number): Promise<Record<string, unknown>> {
    return newFeatures.performReview(this, reviewId, grade);
  }
  getDueReviews(workspaceId: string, userId: string): Promise<Record<string, unknown>[]> {
    return newFeatures.getDueReviews(this, workspaceId, userId);
  }
  getReviewStats(workspaceId: string, userId: string): Promise<Record<string, unknown> | null> {
    return newFeatures.getReviewStats(this, workspaceId, userId);
  }

  // -----------------------------------------------------------------------
  // FactTriple — subject-predicate-object knowledge triples
  // -----------------------------------------------------------------------

  storeFactTriple(workspaceId: string, subjectId: string, predicate: string, objectId: string, confidence: number = 1.0, validFrom: number = 0, validTo: number = 0): Promise<Record<string, unknown>> {
    return factTriple.storeFactTriple(this, workspaceId, subjectId, predicate, objectId, confidence, validFrom, validTo);
  }
  updateFactTripleConfidence(tripleId: string, confidence: number): Promise<Record<string, unknown>> {
    return factTriple.updateFactTripleConfidence(this, tripleId, confidence);
  }
  deleteFactTriple(tripleId: string): Promise<Record<string, unknown>> {
    return factTriple.deleteFactTriple(this, tripleId);
  }
  setFactTripleTemporalBounds(tripleId: string, validFrom: number, validTo: number): Promise<Record<string, unknown>> {
    return factTriple.setFactTripleTemporalBounds(this, tripleId, validFrom, validTo);
  }
  listFactTriples(workspaceId: string): Promise<Record<string, unknown>[]> {
    return factTriple.listFactTriples(this, workspaceId);
  }

  // -----------------------------------------------------------------------
  // Directive — goal/task directive management
  // -----------------------------------------------------------------------

  createDirective(workspaceId: string, name: string, description: string = "", priority: number = 0.0, assignedTo: string = "", metadataJson: string = "{}"): Promise<Record<string, unknown>> {
    return directive.createDirective(this, workspaceId, name, description, priority, assignedTo, metadataJson);
  }
  updateDirectiveStatus(directiveId: string, status: string): Promise<Record<string, unknown>> {
    return directive.updateDirectiveStatus(this, directiveId, status);
  }
  updateDirectiveProgress(directiveId: string, progress: number): Promise<Record<string, unknown>> {
    return directive.updateDirectiveProgress(this, directiveId, progress);
  }
  deleteDirective(directiveId: string): Promise<Record<string, unknown>> {
    return directive.deleteDirective(this, directiveId);
  }
  listDirectives(workspaceId: string): Promise<Record<string, unknown>[]> {
    return directive.listDirectives(this, workspaceId);
  }

  // -----------------------------------------------------------------------
  // BatchOps — batch memory operations
  // -----------------------------------------------------------------------

  batchUpdateMemories(workspaceId: string, memoryIds: string[], updates: Record<string, unknown>): Promise<{ status: string; updated: number; errors?: string[] }> {
    return batchOps.batchUpdateMemories(this, workspaceId, memoryIds, updates);
  }
  batchDeleteMemories(workspaceId: string, memoryIds: string[]): Promise<Record<string, unknown>> {
    return batchOps.batchDeleteMemories(this, workspaceId, memoryIds);
  }
  batchSetCategory(workspaceId: string, memoryIds: string[], category: string): Promise<Record<string, unknown>> {
    return batchOps.batchSetCategory(this, workspaceId, memoryIds, category);
  }

  // -----------------------------------------------------------------------
  // Static factory
  // -----------------------------------------------------------------------

  /** Create a Client using a JWT token stored in a file (Node.js only). */
  static async fromTokenFile(
    tokenPath: string,
    opts: { host?: string; port?: number | string; database?: string } = {}
  ): Promise<Client> {
    const fs = await import("fs/promises");
    const token = (await fs.readFile(tokenPath, "utf-8")).trim();
    return new Client({ ...opts, token } as any);
  }
}
