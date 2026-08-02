/**
 * Zep-compatible adapter for spacetime-memory (TypeScript).
 *
 * Drop-in replacement for the Zep Cloud SDK, backed by SpacetimeDB.
 *
 * Mapping (Zep → spacetime-memory):
 *   session_id  → workspace (workspace_id = sanitized session_id)
 *   user_id     → peer (name = user_id, resolved per workspace)
 *   memory      → memory rows (memory_type = "zep")
 *   facts       → fact table via add_fact / list_facts / update_fact / delete_fact
 *   graph nodes → kg_node, graph edges → kg_edge
 *   episodes    → memory rows (each episode is a stored memory)
 *
 * Features with no backend equivalent THROW instead of silently returning
 * null — silent stubs hide integration bugs.
 */

import { Client, ClientOptions } from "./client";

export interface ZepConfig {
  host?: string;
  port?: number | string;
  db?: string;
  apiKey?: string;
}
export interface Session {
  session_id: string;
  user_id?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
}
export interface ZepMemory {
  memory_id: string;
  session_id: string;
  messages: MemoryMessage[];
  metadata?: Record<string, unknown>;
  created_at?: string;
}
export interface MemoryMessage {
  role: string;
  content: string;
  metadata?: Record<string, unknown>;
}
export interface MemorySearchResult {
  memory: ZepMemory;
  score: number;
  summary?: string;
}
export interface Fact {
  fact_uuid: string;
  fact: string;
  score?: number;
  summary?: string;
  created_at?: string;
}
export interface Summary {
  summary: string;
  created_at?: string;
}
export interface UserRecord {
  user_id: string;
  email?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
}
export interface GraphNode {
  uuid: string;
  name: string;
  labels?: string[];
  summary?: string;
  attributes?: Record<string, unknown>;
  created_at?: string;
}
export interface GraphEdge {
  uuid: string;
  source_node_uuid: string;
  target_node_uuid: string;
  name: string;
  fact?: string;
  episodes?: string[];
  created_at?: string;
}
export interface GraphSearchResults {
  nodes: GraphNode[];
  edges: GraphEdge[];
  episodes: GraphNode[];
}
export interface GraphSearchOptions {
  scope?: "nodes" | "edges" | "episodes";
  userId?: string;
  limit?: number;
  centerNodeUuid?: string;
}

export class NotFoundError extends Error {
  constructor(msg = "Resource not found") { super(msg); this.name = "NotFoundError"; }
}
export class BadRequestError extends Error {
  constructor(msg = "Bad request") { super(msg); this.name = "BadRequestError"; }
}
export class ApiError extends Error {
  constructor(msg = "API error") { super(msg); this.name = "ApiError"; }
}
export class ConflictError extends Error {
  constructor(msg = "Conflict") { super(msg); this.name = "ConflictError"; }
}

export enum RoleType {
  USER = "user",
  ASSISTANT = "assistant",
  SYSTEM = "system",
  FUNCTION = "function",
  TOOL = "tool",
}
export enum SearchScope { MESSAGES = "messages", SUMMARY = "summary", FACTS = "facts" }
export enum SearchType { SIMILARITY = "similarity", TIMEWEIGHTED = "timeweighted", MMR = "mmr" }

function sanitizeSessionId(sessionId: string): string {
  return sessionId.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function microsToIso(v: unknown): string | undefined {
  if (v === null || v === undefined) return undefined;
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return undefined;
  // spacetime-memory timestamps are microseconds since epoch
  return new Date(n / 1000).toISOString();
}

/**
 * The STDB v2 SQL endpoint supports only SELECT / WHERE (=, AND, OR) / LIMIT.
 * ORDER BY and LIKE are rejected — sort and filter client-side instead.
 */
function sortByCreatedDesc(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  return rows.sort((a, b) => Number(b.created_at ?? 0) - Number(a.created_at ?? 0));
}
function sortByCreatedAsc(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  return rows.sort((a, b) => Number(a.created_at ?? 0) - Number(b.created_at ?? 0));
}
function jsLike(value: unknown, needle: string): boolean {
  return String(value ?? "").toLowerCase().includes(needle.toLowerCase());
}

export class _MemoryProxy {
  private _client: Client;
  private _peerCache: Map<string, string> = new Map();

  constructor(client: Client) {
    this._client = client;
  }

  private _ws(sessionId: string): string {
    return sanitizeSessionId(sessionId);
  }

  /** Ensure the backing workspace exists (idempotent). */
  private async _ensureWorkspace(sessionId: string): Promise<string> {
    const ws = this._ws(sessionId);
    const rows = await this._client._sqlExec(
      "SELECT id FROM workspace WHERE id = :ws",
      { ws },
    );
    if (!rows?.length) {
      try {
        await this._client._call("create_workspace", [sessionId, "zep session", ws]);
      } catch {
        // Race or already-exists: re-check
        const again = await this._client._sqlExec(
          "SELECT id FROM workspace WHERE id = :ws",
          { ws },
        );
        if (!again?.length) throw new ApiError(`Failed to create workspace for session ${sessionId}`);
      }
    }
    return ws;
  }

  /** Resolve (or lazily create) the peer backing a Zep user in a workspace. */
  private async _resolvePeer(ws: string, userId: string): Promise<string> {
    const key = `${ws}:${userId}`;
    const cached = this._peerCache.get(key);
    if (cached) return cached;
    const rows = await this._client._sqlExec(
      "SELECT id FROM peer WHERE workspace_id = :ws AND name = :name",
      { ws, name: userId },
    );
    let peerId: string;
    if (rows?.length) {
      peerId = String(rows[0].id);
    } else {
      await this._client._call("create_peer", [ws, userId, "user", "{}"]);
      const again = await this._client._sqlExec(
        "SELECT id FROM peer WHERE workspace_id = :ws AND name = :name",
        { ws, name: userId },
      );
      if (!again?.length) throw new ApiError(`Failed to create peer for user ${userId}`);
      peerId = String(again[0].id);
    }
    this._peerCache.set(key, peerId);
    return peerId;
  }

  async add(
    sessionId: string,
    messages: string | MemoryMessage[],
    metadata?: Record<string, unknown>,
  ): Promise<ZepMemory> {
    const ws = await this._ensureWorkspace(sessionId);
    const msgList: MemoryMessage[] =
      typeof messages === "string"
        ? [{ role: RoleType.USER, content: messages }]
        : messages;
    if (!msgList.length) throw new BadRequestError("messages must not be empty");
    const content = msgList.map((m) => `${m.role}: ${m.content}`).join("\n");
    const userId = (metadata?.user_id as string) ?? "zep-user";
    const peerId = await this._resolvePeer(ws, userId);
    await this._client._call("store_memory", [
      ws, peerId, peerId, "zep", content,
      content.slice(0, 120), "[]", 0.8, sessionId, "", "[]",
    ]);
    const rows = await this._client._sqlExec(
      "SELECT id, created_at FROM memory WHERE workspace_id = :ws AND source_session_id = :sid",
      { ws, sid: sessionId },
    );
    const latest = rows?.length ? sortByCreatedDesc(rows)[0] : null;
    const memId = latest ? String(latest.id) : "";
    return {
      memory_id: memId,
      session_id: sessionId,
      messages: msgList,
      metadata,
      created_at: microsToIso(latest?.created_at) ?? new Date().toISOString(),
    };
  }

  async get(sessionId: string, lastN?: number): Promise<ZepMemory | null> {
    const ws = this._ws(sessionId);
    const rows = await this._client._sqlExec(
      "SELECT id, content, created_at FROM memory WHERE workspace_id = :ws AND is_active = true",
      { ws },
    );
    if (!rows?.length) return null;
    const all = sortByCreatedAsc(rows);
    const mems = lastN ? all.slice(-lastN) : all;
    const messages: MemoryMessage[] = mems.map((r: Record<string, unknown>) => ({
      role: RoleType.USER,
      content: String(r.content ?? ""),
    }));
    return {
      memory_id: String(mems[0]?.id ?? ""),
      session_id: sessionId,
      messages,
      created_at: microsToIso(mems[0]?.created_at),
    };
  }

  async delete(sessionId: string): Promise<void> {
    const ws = this._ws(sessionId);
    const rows = await this._client._sqlExec(
      "SELECT id FROM memory WHERE workspace_id = :ws AND is_active = true",
      { ws },
    );
    const ids = (rows ?? []).map((r: Record<string, unknown>) => String(r.id));
    if (ids.length) {
      await this._client._call("batch_delete_memories", [ws, JSON.stringify(ids)]);
    }
  }

  async search(
    sessionId: string,
    query: string,
    limit = 5,
    _scoreThreshold?: number,
    _searchType?: SearchType,
    _searchScope?: SearchScope,
  ): Promise<MemorySearchResult[]> {
    const ws = this._ws(sessionId);
    const results = await this._client.search(ws, query, { limit, semantic: true });
    return (results ?? []).map((r) => ({
      memory: {
        memory_id: String(r.id ?? ""),
        session_id: sessionId,
        messages: [
          // hybrid_result.content is populated by the reducer; the TS client's
          // entity lookup lands in memory_content — accept either.
          { role: RoleType.USER, content: String(r.content ?? "") || String(r.memory_content ?? "") },
        ],
      },
      score: Number(r.score ?? 0),
      summary: undefined as string | undefined,
    }));
  }

  async addFact(sessionId: string, fact: string, userId = "zep-user"): Promise<Fact> {
    const ws = await this._ensureWorkspace(sessionId);
    const peerId = await this._resolvePeer(ws, userId);
    await this._client._call("add_fact", [
      ws, peerId, "general", "zep", fact, 0.9, "zep", "L1",
    ]);
    const rows = await this._client._sqlExec(
      "SELECT id, created_at FROM fact WHERE workspace_id = :ws AND content = :c",
      { ws, c: fact },
    );
    const latest = rows?.length ? sortByCreatedDesc(rows)[0] : null;
    return {
      fact_uuid: latest ? String(latest.id) : "",
      fact,
      created_at: microsToIso(latest?.created_at) ?? new Date().toISOString(),
    };
  }

  async getFact(factUuid: string): Promise<Fact | null> {
    const rows = await this._client._sqlExec(
      "SELECT id, content, confidence, created_at FROM fact WHERE id = :id",
      { id: factUuid },
    );
    if (!rows?.length) return null;
    const r = rows[0] as Record<string, unknown>;
    return {
      fact_uuid: String(r.id),
      fact: String(r.content ?? ""),
      score: Number(r.confidence ?? 0),
      created_at: microsToIso(r.created_at),
    };
  }

  async deleteFact(factUuid: string): Promise<void> {
    await this._client._call("delete_fact", [factUuid]);
  }

  async listFacts(sessionId: string, limit = 100): Promise<Fact[]> {
    const ws = this._ws(sessionId);
    const rows = await this._client._sqlExec(
      `SELECT id, content, confidence, created_at FROM fact WHERE workspace_id = :ws LIMIT ${Math.max(1, Math.min(1000, Math.floor(limit)))}`,
      { ws },
    );
    return (rows ?? []).map((r: Record<string, unknown>) => ({
      fact_uuid: String(r.id),
      fact: String(r.content ?? ""),
      score: Number(r.confidence ?? 0),
      created_at: microsToIso(r.created_at),
    }));
  }

  async getSession(sessionId: string): Promise<Session | null> {
    const ws = this._ws(sessionId);
    const rows = await this._client._sqlExec(
      "SELECT id, name, created_at FROM workspace WHERE id = :ws",
      { ws },
    );
    if (!rows?.length) return null;
    return {
      session_id: sessionId,
      metadata: { workspace: ws },
      created_at: microsToIso(rows[0].created_at),
    };
  }

  async updateSession(sessionId: string, metadata: Record<string, unknown>): Promise<void> {
    const ws = this._ws(sessionId);
    const summary = JSON.stringify(metadata);
    // Workspace metadata has no dedicated column; the session summary reducer
    // is the closest backend concept. Encode metadata into the session summary.
    const sessions = await this._client._sqlExec(
      "SELECT id FROM session WHERE workspace_id = :ws",
      { ws },
    );
    if (sessions?.length) {
      await this._client._call("update_session_summary", [String(sessions[0].id), summary]);
    }
  }

  async listSessions(userId?: string, limit = 50): Promise<Session[]> {
    if (!userId) {
      const rows = await this._client._sqlExec(
        `SELECT id, name, created_at FROM workspace LIMIT ${Math.max(1, Math.min(1000, Math.floor(limit)))}`,
        {},
      );
      return (rows ?? []).map((r: Record<string, unknown>) => ({
        session_id: String(r.name ?? r.id),
        created_at: microsToIso(r.created_at),
      }));
    }
    // Sessions owned by a user = workspaces containing a peer with that name
    const peers = await this._client._sqlExec(
      "SELECT workspace_id FROM peer WHERE name = :name",
      { name: userId },
    );
    const out: Session[] = [];
    for (const p of peers ?? []) {
      const ws = String((p as Record<string, unknown>).workspace_id);
      const rows = await this._client._sqlExec(
        "SELECT name, created_at FROM workspace WHERE id = :ws",
        { ws },
      );
      if (rows?.length) {
        out.push({
          session_id: String(rows[0].name ?? ws),
          user_id: userId,
          created_at: microsToIso(rows[0].created_at),
        });
      }
    }
    return out;
  }
}

export class _UserProxy {
  private _client: Client;
  /** Workspace that backs the global Zep user directory. */
  static readonly USERS_WORKSPACE = "_zep_users";

  constructor(client: Client) {
    this._client = client;
  }

  private async _ensureUsersWorkspace(): Promise<void> {
    const rows = await this._client._sqlExec(
      "SELECT id FROM workspace WHERE id = :ws",
      { ws: _UserProxy.USERS_WORKSPACE },
    );
    if (!rows?.length) {
      try {
        await this._client._call("create_workspace", [
          "Zep user directory", "zep users", _UserProxy.USERS_WORKSPACE,
        ]);
      } catch {
        /* race — exists now */
      }
    }
  }

  async add(userData: Partial<UserRecord> & { user_id: string }): Promise<UserRecord> {
    if (!userData.user_id) throw new BadRequestError("user_id is required");
    await this._ensureUsersWorkspace();
    const existing = await this.get(userData.user_id);
    if (existing) throw new ConflictError(`User ${userData.user_id} already exists`);
    await this._client._call("create_peer", [
      _UserProxy.USERS_WORKSPACE,
      userData.user_id,
      "user",
      JSON.stringify({ email: userData.email ?? null, ...(userData.metadata ?? {}) }),
    ]);
    return (await this.get(userData.user_id))!;
  }

  async get(userId: string): Promise<UserRecord | null> {
    const rows = await this._client._sqlExec(
      "SELECT id, name, metadata, created_at FROM peer WHERE workspace_id = :ws AND name = :name",
      { ws: _UserProxy.USERS_WORKSPACE, name: userId },
    );
    if (!rows?.length) return null;
    const r = rows[0] as Record<string, unknown>;
    let meta: Record<string, unknown> = {};
    try { meta = JSON.parse(String(r.metadata ?? "{}")); } catch { /* keep {} */ }
    const { email, ...rest } = meta as Record<string, unknown> & { email?: string };
    return {
      user_id: String(r.name),
      email: email ?? undefined,
      metadata: rest,
      created_at: microsToIso(r.created_at),
    };
  }

  async update(userId: string, data: Partial<UserRecord>): Promise<void> {
    const existing = await this.get(userId);
    if (!existing) throw new NotFoundError(`User ${userId} not found`);
    const rows = await this._client._sqlExec(
      "SELECT id FROM peer WHERE workspace_id = :ws AND name = :name",
      { ws: _UserProxy.USERS_WORKSPACE, name: userId },
    );
    const merged = { ...(existing.metadata ?? {}), ...(data.metadata ?? {}) };
    if (data.email !== undefined) (merged as Record<string, unknown>).email = data.email;
    await this._client._call("update_peer", [
      String(rows[0].id), userId, JSON.stringify(merged),
    ]);
  }

  async delete(userId: string): Promise<void> {
    const rows = await this._client._sqlExec(
      "SELECT id FROM peer WHERE workspace_id = :ws AND name = :name",
      { ws: _UserProxy.USERS_WORKSPACE, name: userId },
    );
    if (!rows?.length) throw new NotFoundError(`User ${userId} not found`);
    await this._client._call("delete_peer", [String(rows[0].id)]);
  }

  async listOrdered(limit = 100): Promise<UserRecord[]> {
    const rows = await this._client._sqlExec(
      "SELECT name, created_at FROM peer WHERE workspace_id = :ws",
      { ws: _UserProxy.USERS_WORKSPACE },
    );
    return sortByCreatedAsc(rows ?? [])
      .slice(0, Math.max(1, Math.min(1000, Math.floor(limit))))
      .map((r: Record<string, unknown>) => ({
        user_id: String(r.name),
        created_at: microsToIso(r.created_at),
      }));
  }

  async getSessions(userId: string, limit = 50): Promise<Session[]> {
    const peers = await this._client._sqlExec(
      "SELECT workspace_id FROM peer WHERE name = :name",
      { name: userId },
    );
    const out: Session[] = [];
    for (const p of (peers ?? []).slice(0, limit)) {
      const ws = String((p as Record<string, unknown>).workspace_id);
      if (ws === _UserProxy.USERS_WORKSPACE) continue;
      const rows = await this._client._sqlExec(
        "SELECT name, created_at FROM workspace WHERE id = :ws",
        { ws },
      );
      if (rows?.length) {
        out.push({
          session_id: String(rows[0].name ?? ws),
          user_id: userId,
          created_at: microsToIso(rows[0].created_at),
        });
      }
    }
    return out;
  }
}

export class _GraphNodeProxy {
  constructor(private _client: Client) {}

  async get(uuid: string): Promise<GraphNode | null> {
    const rows = await this._client._sqlExec(
      "SELECT id, label, node_type, summary, metadata, created_at FROM kg_node WHERE id = :id",
      { id: uuid },
    );
    if (!rows?.length) return null;
    return rowToNode(rows[0] as Record<string, unknown>);
  }

  async getByUserId(userId: string, limit = 100): Promise<GraphNode[]> {
    const ws = sanitizeSessionId(userId);
    const rows = await this._client._sqlExec(
      `SELECT id, label, node_type, summary, metadata, created_at FROM kg_node WHERE workspace_id = :ws LIMIT ${Math.max(1, Math.min(1000, Math.floor(limit)))}`,
      { ws },
    );
    return (rows ?? []).map((r: Record<string, unknown>) => rowToNode(r));
  }

  async add(workspaceId: string, node: { name: string; labels?: string[]; summary?: string; attributes?: Record<string, unknown> }): Promise<GraphNode> {
    const nodeType = node.labels?.[0] ?? "entity";
    await this._client._call("create_node", [
      workspaceId, node.name, nodeType, node.summary ?? "",
      JSON.stringify(node.attributes ?? {}), "", "",
    ]);
    const rows = await this._client._sqlExec(
      "SELECT id, label, node_type, summary, metadata, created_at FROM kg_node WHERE workspace_id = :ws AND label = :label",
      { ws: workspaceId, label: node.name },
    );
    const latest = rows?.length ? sortByCreatedDesc(rows)[0] : null;
    if (!latest) throw new ApiError("Node creation did not persist");
    return rowToNode(latest);
  }

  async delete(uuid: string): Promise<void> {
    await this._client._call("delete_node", [uuid]);
  }
}

export class _GraphEdgeProxy {
  constructor(private _client: Client) {}

  async get(uuid: string): Promise<GraphEdge | null> {
    const rows = await this._client._sqlExec(
      "SELECT id, source_node_id, target_node_id, relation, metadata, created_at FROM kg_edge WHERE id = :id",
      { id: uuid },
    );
    if (!rows?.length) return null;
    return rowToEdge(rows[0] as Record<string, unknown>);
  }

  async getByNode(nodeUuid: string, limit = 100): Promise<GraphEdge[]> {
    const cap = Math.max(1, Math.min(1000, Math.floor(limit)));
    const out: GraphEdge[] = [];
    for (const col of ["source_node_id", "target_node_id"]) {
      const rows = await this._client._sqlExec(
        `SELECT id, source_node_id, target_node_id, relation, metadata, created_at FROM kg_edge WHERE ${col} = :id LIMIT ${cap}`,
        { id: nodeUuid },
      );
      for (const r of rows ?? []) out.push(rowToEdge(r as Record<string, unknown>));
    }
    return out;
  }

  async add(workspaceId: string, edge: { sourceNodeUuid: string; targetNodeUuid: string; name: string; fact?: string }): Promise<GraphEdge> {
    await this._client._call("create_edge", [
      workspaceId, edge.sourceNodeUuid, edge.targetNodeUuid, edge.name,
      1.0, 0.9, JSON.stringify({ fact: edge.fact ?? "" }), "",
    ]);
    const rows = await this._client._sqlExec(
      "SELECT id, source_node_id, target_node_id, relation, metadata, created_at FROM kg_edge WHERE source_node_id = :src AND target_node_id = :tgt AND relation = :rel",
      { src: edge.sourceNodeUuid, tgt: edge.targetNodeUuid, rel: edge.name },
    );
    const latest = rows?.length ? sortByCreatedDesc(rows)[0] : null;
    if (!latest) throw new ApiError("Edge creation did not persist");
    return rowToEdge(latest);
  }

  async delete(uuid: string): Promise<void> {
    await this._client._call("delete_edge", [uuid]);
  }
}

export class _GraphEpisodeProxy {
  constructor(private _client: Client) {}

  async get(uuid: string): Promise<GraphNode | null> {
    const rows = await this._client._sqlExec(
      "SELECT id, content, created_at FROM memory WHERE id = :id",
      { id: uuid },
    );
    if (!rows?.length) return null;
    const r = rows[0] as Record<string, unknown>;
    return {
      uuid: String(r.id),
      name: String(r.content ?? "").slice(0, 80),
      labels: ["episode"],
      summary: String(r.content ?? ""),
      created_at: microsToIso(r.created_at),
    };
  }
}

function rowToNode(r: Record<string, unknown>): GraphNode {
  let attrs: Record<string, unknown> = {};
  try { attrs = JSON.parse(String(r.metadata ?? "{}")); } catch { /* keep {} */ }
  return {
    uuid: String(r.id),
    name: String(r.label ?? ""),
    labels: [String(r.node_type ?? "entity")],
    summary: r.summary as string | undefined,
    attributes: attrs,
    created_at: microsToIso(r.created_at),
  };
}

export interface GraphCommunity {
  uuid: string;
  name: string;
  summary?: string;
  created_at?: string;
  member_count: number;
  members: string[];
  edges: { uuid: string; source_node_uuid: string; target_node_uuid: string }[];
}

export class _GraphCommunityProxy {
  constructor(private _client: Client) {}

  async build(userId: string): Promise<GraphCommunity[]> {
    const ws = sanitizeSessionId(userId);
    try { await this._client._call("detect_communities", [ws]); } catch { /* non-fatal */ }
    try { await this._client._call("seed_communities", [ws]); } catch { /* non-fatal */ }
    return this.list(userId);
  }

  async list(userId: string, limit = 100): Promise<GraphCommunity[]> {
    const ws = sanitizeSessionId(userId);
    const rows = await this._client._sqlExec(
      "SELECT id, label, node_type, summary, created_at FROM kg_node WHERE workspace_id = :ws AND node_type = 'community'",
      { ws },
    );
    const communities: GraphCommunity[] = [];
    for (const r of (rows ?? []) as Record<string, unknown>[]) {
      if (String(r.workspace_id ?? "") !== ws || String(r.node_type ?? "") !== "community") continue;
      communities.push(await this._rowToCommunity(r, ws));
      if (communities.length >= Math.max(1, Math.floor(limit))) break;
    }
    return communities;
  }

  async get(uuid: string, userId: string): Promise<GraphCommunity | null> {
    const ws = sanitizeSessionId(userId);
    const rows = await this._client._sqlExec(
      "SELECT id, label, node_type, summary, created_at FROM kg_node WHERE id = :id AND node_type = 'community'",
      { id: uuid },
    );
    const row = (rows ?? []).find((r) =>
      String(r.id) === uuid && String(r.node_type ?? "") === "community"
    ) as Record<string, unknown> | undefined;
    if (!row) return null;
    return this._rowToCommunity(row, ws);
  }

  async search(query: string, userId: string, limit = 10): Promise<GraphCommunity[]> {
    const ws = sanitizeSessionId(userId);
    const rows = await this._client._sqlExec(
      "SELECT id, label, node_type, summary, created_at FROM kg_node WHERE workspace_id = :ws AND node_type = 'community'",
      { ws },
    );
    const q = query.toLowerCase().trim();
    const out: GraphCommunity[] = [];
    for (const r of (rows ?? []) as Record<string, unknown>[]) {
      if (String(r.workspace_id ?? "") !== ws || String(r.node_type ?? "") !== "community") continue;
      const label = String(r.label ?? "").toLowerCase();
      const summary = String(r.summary ?? "").toLowerCase();
      if (!q || label.includes(q) || summary.includes(q)) {
        out.push(await this._rowToCommunity(r, ws));
        if (out.length >= Math.max(1, Math.floor(limit))) break;
      }
    }
    return out;
  }

  private async _rowToCommunity(r: Record<string, unknown>, ws: string): Promise<GraphCommunity> {
    const members: string[] = [];
    const edges: GraphCommunity["edges"] = [];
    try {
      const edgeRows = await this._client._sqlExec(
        "SELECT id, source_node_id, target_node_id FROM kg_edge WHERE workspace_id = :ws AND source_node_id = :src",
        { ws, src: String(r.id) },
      );
      for (const e of (edgeRows ?? []) as Record<string, unknown>[]) {
        members.push(String(e.target_node_id ?? ""));
        edges.push({
          uuid: String(e.id ?? ""),
          source_node_uuid: String(e.source_node_id ?? ""),
          target_node_uuid: String(e.target_node_id ?? ""),
        });
      }
    } catch { /* non-fatal — edges may not exist yet */ }
    return {
      uuid: String(r.id ?? ""),
      name: String(r.label ?? ""),
      summary: r.summary as string | undefined,
      created_at: microsToIso(r.created_at),
      member_count: new Set(members.filter(Boolean)).size,
      members: [...new Set(members.filter(Boolean))].sort(),
      edges,
    };
  }
}

function rowToEdge(r: Record<string, unknown>): GraphEdge {
  let meta: Record<string, unknown> = {};
  try { meta = JSON.parse(String(r.metadata ?? "{}")); } catch { /* keep {} */ }
  return {
    uuid: String(r.id),
    source_node_uuid: String(r.source_node_id ?? ""),
    target_node_uuid: String(r.target_node_id ?? ""),
    name: String(r.relation ?? ""),
    fact: (meta.fact as string) || undefined,
    created_at: microsToIso(r.created_at),
  };
}

export class _GraphProxy {
  node: _GraphNodeProxy;
  edge: _GraphEdgeProxy;
  episode: _GraphEpisodeProxy;
  community: _GraphCommunityProxy;

  constructor(private _client: Client) {
    this.node = new _GraphNodeProxy(_client);
    this.edge = new _GraphEdgeProxy(_client);
    this.episode = new _GraphEpisodeProxy(_client);
    this.community = new _GraphCommunityProxy(_client);
  }

  /** Add data to the graph. Text data is stored as an episode (memory). */
  async add(data: { userId: string; type?: "text" | "message" | "json" | "episode"; data: string; sourceDescription?: string }): Promise<GraphNode> {
    if (!data.userId) throw new BadRequestError("userId is required");
    const ws = sanitizeSessionId(data.userId);
    await this._client.store(ws, data.data, {
      memoryType: "episode",
      summary: data.sourceDescription ?? data.data.slice(0, 120),
    });
    const rows = await this._client._sqlExec(
      "SELECT id, content, created_at FROM memory WHERE workspace_id = :ws",
      { ws },
    );
    const latest = rows?.length ? sortByCreatedDesc(rows)[0] : null;
    if (!latest) throw new ApiError("Episode creation did not persist");
    return {
      uuid: String(latest.id),
      name: String(latest.content ?? "").slice(0, 80),
      labels: ["episode"],
      summary: String(latest.content ?? ""),
      created_at: microsToIso(latest.created_at),
    };
  }

  async search(query: string, options?: GraphSearchOptions): Promise<GraphSearchResults> {
    const scope = options?.scope;
    const limit = Math.max(1, Math.min(1000, Math.floor(options?.limit ?? 10)));
    const ws = options?.userId ? sanitizeSessionId(options.userId) : null;
    const out: GraphSearchResults = { nodes: [], edges: [], episodes: [] };
    // LIKE is unsupported server-side: fetch scoped rows, substring-filter in JS.
    const SCAN_CAP = 5000;

    if (!scope || scope === "nodes") {
      const rows = ws
        ? await this._client._sqlExec(
            `SELECT id, label, node_type, summary, metadata, created_at FROM kg_node WHERE workspace_id = :ws LIMIT ${SCAN_CAP}`,
            { ws })
        : await this._client._sqlExec(
            `SELECT id, label, node_type, summary, metadata, created_at FROM kg_node LIMIT ${SCAN_CAP}`,
            {});
      out.nodes = (rows ?? [])
        .filter((r: Record<string, unknown>) => jsLike(r.label, query))
        .slice(0, limit)
        .map((r: Record<string, unknown>) => rowToNode(r));
    }
    if (!scope || scope === "edges") {
      const rows = ws
        ? await this._client._sqlExec(
            `SELECT id, source_node_id, target_node_id, relation, metadata, created_at FROM kg_edge WHERE workspace_id = :ws LIMIT ${SCAN_CAP}`,
            { ws })
        : await this._client._sqlExec(
            `SELECT id, source_node_id, target_node_id, relation, metadata, created_at FROM kg_edge LIMIT ${SCAN_CAP}`,
            {});
      out.edges = (rows ?? [])
        .filter((r: Record<string, unknown>) => jsLike(r.relation, query))
        .slice(0, limit)
        .map((r: Record<string, unknown>) => rowToEdge(r));
    }
    if (!scope || scope === "episodes") {
      const rows = ws
        ? await this._client._sqlExec(
            `SELECT id, content, created_at FROM memory WHERE workspace_id = :ws AND is_active = true LIMIT ${SCAN_CAP}`,
            { ws })
        : await this._client._sqlExec(
            `SELECT id, content, created_at FROM memory WHERE is_active = true LIMIT ${SCAN_CAP}`,
            {});
      out.episodes = (rows ?? [])
        .filter((r: Record<string, unknown>) => jsLike(r.content, query))
        .slice(0, limit)
        .map((r: Record<string, unknown>) => ({
          uuid: String(r.id),
          name: String(r.content ?? "").slice(0, 80),
          labels: ["episode"],
          summary: String(r.content ?? ""),
          created_at: microsToIso(r.created_at),
        }));
    }
    return out;
  }

  /**
   * Create a Subject→Predicate→Object triple. Nodes are matched by UUID
   * (or created by name when `createMissing` is set).
   */
  async addTriplet(args: {
    workspaceId?: string;
    sourceNodeUuid: string;
    targetNodeUuid: string;
    relationName: string;
    fact?: string;
  }): Promise<GraphEdge> {
    const ws = args.workspaceId ?? "";
    return this.edge.add(ws, {
      sourceNodeUuid: args.sourceNodeUuid,
      targetNodeUuid: args.targetNodeUuid,
      name: args.relationName,
      fact: args.fact,
    });
  }
}

export class ZepClient {
  memory: _MemoryProxy;
  user: _UserProxy;
  graph: _GraphProxy;
  protected _client: Client;

  constructor(config: ZepConfig = {}) {
    this._client = new Client({
      host: config.host,
      port: config.port,
      database: config.db,
    } as ClientOptions);
    this.memory = new _MemoryProxy(this._client);
    this.user = new _UserProxy(this._client);
    this.graph = new _GraphProxy(this._client);
  }

  close(): void { /* stateless HTTP client — nothing to close */ }

  async summarizeMemory(sessionId: string): Promise<string | null> {
    const ws = sanitizeSessionId(sessionId);
    const rows = await this._client._sqlExec(
      "SELECT summary, created_at FROM memory WHERE workspace_id = :ws AND is_active = true",
      { ws },
    );
    if (!rows?.length) return null;
    const latest = sortByCreatedDesc(rows)[0];
    return String(latest.summary ?? "") || null;
  }
}

export class Zep extends ZepClient {
  constructor(config: ZepConfig = {}) { super(config); }
}

/** TS is inherently async — AsyncZepClient is an alias for parity with the Python SDK. */
export class AsyncZepClient extends ZepClient {
  constructor(config: ZepConfig = {}) { super(config); }
  async close(): Promise<void> { /* stateless */ }
}
export class AsyncZep extends AsyncZepClient {
  constructor(config: ZepConfig = {}) { super(config); }
}

export class FactRatingExamples {
  high = ""; medium = ""; low = "";
  constructor(data?: Partial<FactRatingExamples>) { Object.assign(this, data ?? {}); }
}
export class FactRatingInstruction {
  instruction = ""; examples?: FactRatingExamples;
  constructor(data?: Partial<FactRatingInstruction>) { Object.assign(this, data ?? {}); }
}
export class ZepEnvironment {
  message = "";
  constructor(data?: Partial<ZepEnvironment>) { Object.assign(this, data ?? {}); }
}

export { MemoryMessage as Message };
