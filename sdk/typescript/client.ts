/**
 * TypeScript SDK for spacetime-memory.
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
// Types
// ---------------------------------------------------------------------------

export interface MemoryRecord {
  id: string;
  workspace_id: string;
  peer_id: string;
  content: string;
  summary: string;
  memory_type: string;
  confidence: number;
  is_active: boolean;
  tier: string;
  strength: number;
  access_count: number;
  trust_score: number;
  created_at: number;
  updated_at: number;
}

export interface SearchResult {
  id: string;
  entity_id: string;
  entity_type: string;
  content: string;
  score: number;
  strategy: string;
  memory_content?: string;
  node_label?: string;
  context_json?: string;
}

export interface ClientOptions {
  host?: string;
  port?: number | string;
  database?: string;
  embedderUrl?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function esc(val: string): string {
  return val.replace(/'/g, "''");
}

function queryHash(query: string): string {
  let h = 0;
  for (let i = 0; i < query.length; i++) {
    h = (Math.imul(h, 6364136223846793005) + query.charCodeAt(i)) >>> 0;
  }
  return h.toString(16).padStart(16, "0");
}

function parseSqlResponse(raw: string): any[] {
  if (!raw.trim()) return [];
  const tables = JSON.parse(raw);
  const results: any[] = [];
  for (const table of tables) {
    const elements = table?.schema?.elements ?? [];
    const colNames: string[] = elements.map(
      (el: any) => el?.name?.some ?? "?col?"
    );
    for (const row of table?.rows ?? []) {
      const r: any = {};
      for (let i = 0; i < colNames.length; i++) {
        r[colNames[i]] = row[i];
      }
      results.push(r);
    }
  }
  return results;
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export class Client {
  private readonly host: string;
  private readonly port: string;
  private readonly database: string;
  private readonly embedderUrl: string;
  private readonly baseUrl: string;

  constructor(opts: ClientOptions = {}) {
    this.host = opts.host ?? process.env.SPACETIMEDB_HOST ?? "127.0.0.1";
    this.port = String(opts.port ?? process.env.SPACETIMEDB_PORT ?? "3001");
    this.database =
      opts.database ??
      process.env.SPACETIMEDB_DB ??
      "spacetime-memory";
    this.embedderUrl =
      opts.embedderUrl ?? process.env.EMBEDDER_URL ?? "http://127.0.0.1:4000";
    this.baseUrl = `http://${this.host}:${this.port}`;
  }

  private sqlUrl(): string {
    return `${this.baseUrl}/v1/database/${this.database}/sql`;
  }

  private reducerUrl(): string {
    return `${this.baseUrl}/v1/database/${this.database}/call`;
  }

  // -----------------------------------------------------------------------
  // HTTP
  // -----------------------------------------------------------------------

  private async _sql(query: string): Promise<any[]> {
    const resp = await fetch(this.sqlUrl(), {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: query,
    });
    if (!resp.ok) {
      throw new Error(`SQL error (${resp.status}): ${await resp.text()}`);
    }
    return parseSqlResponse(await resp.text());
  }

  private async _call(reducer: string, args: any[]): Promise<void> {
    const resp = await fetch(`${this.reducerUrl()}/${reducer}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    });
    if (!resp.ok) {
      throw new Error(
        `Reducer error (${resp.status}): ${await resp.text()}`
      );
    }
  }

  private async _embed(text: string): Promise<number[]> {
    try {
      const resp = await fetch(`${this.embedderUrl}/embed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!resp.ok) return [];
      const data: any = await resp.json();
      return data?.embedding ?? [];
    } catch {
      return [];
    }
  }

  // -----------------------------------------------------------------------
  // Workspace
  // -----------------------------------------------------------------------

  async createWorkspace(
    name: string,
    description?: string
  ): Promise<void> {
    return this._call("create_workspace", [name, description ?? ""]);
  }

  async listWorkspaces(): Promise<any[]> {
    return this._sql("SELECT * FROM workspace");
  }

  async updateWorkspace(
    id: string,
    name: string,
    description: string
  ): Promise<void> {
    return this._call("update_workspace", [id, name, description]);
  }

  async deleteWorkspace(workspaceId: string): Promise<void> {
    return this._call("delete_workspace", [workspaceId]);
  }

  async setWorkspaceVisibility(
    workspaceId: string,
    isPublic: boolean
  ): Promise<void> {
    return this._call("set_workspace_visibility", [workspaceId, isPublic]);
  }

  async getWorkspaceContext(workspaceId: string): Promise<any> {
    await this._call("get_workspace_context", [workspaceId]);
    const rows = await this._sql(
      `SELECT * FROM workspace_context_result WHERE workspace_id = '${esc(workspaceId)}'`
    );
    return rows.length > 0 ? rows[0] : null;
  }

  async listSpaceMembers(workspaceId: string): Promise<any[]> {
    return this._sql(
      `SELECT * FROM space_member WHERE workspace_id = '${esc(workspaceId)}'`
    );
  }

  async grantSpaceAccess(
    workspaceId: string,
    peerId: string,
    permission: string
  ): Promise<void> {
    return this._call("grant_space_access", [workspaceId, peerId, permission]);
  }

  async revokeSpaceAccess(
    workspaceId: string,
    peerId: string
  ): Promise<void> {
    return this._call("revoke_space_access", [workspaceId, peerId]);
  }

  // -----------------------------------------------------------------------
  // Mental Models
  // -----------------------------------------------------------------------

  async synthesizeMentalModels(
    workspaceId: string,
    memoryIds: string[]
  ): Promise<any[]> {
    await this._call("synthesize_mental_models", [
      workspaceId,
      JSON.stringify(memoryIds),
    ]);
    return this._sql(
      `SELECT * FROM mental_model_result WHERE workspace_id = '${esc(workspaceId)}'`
    );
  }

  async getMentalModel(modelId: string): Promise<any[]> {
    return this._sql(
      `SELECT * FROM mental_model WHERE id = '${esc(modelId)}'`
    );
  }

  async listMentalModels(
    workspaceId: string,
    status?: string
  ): Promise<any[]> {
    let where = `workspace_id = '${esc(workspaceId)}'`;
    if (status) {
      where += ` AND status = '${esc(status)}'`;
    }
    return this._sql(
      `SELECT * FROM mental_model WHERE ${where} ORDER BY created_at DESC`
    );
  }

  async deleteMentalModel(modelId: string): Promise<void> {
    return this._call("delete_mental_model", [modelId]);
  }

  async updateMentalModel(
    modelId: string,
    content: string,
    confidence?: number,
    status?: string
  ): Promise<void> {
    return this._call("update_mental_model", [
      modelId,
      content,
      confidence ?? 0.5,
      status ?? "completed",
    ]);
  }

  // -----------------------------------------------------------------------
  // Memory
  // -----------------------------------------------------------------------

  async store(
    workspaceId: string,
    content: string,
    opts?: {
      summary?: string;
      memoryType?: string;
      peerId?: string;
      tier?: string;
    }
  ): Promise<void> {
    const memType = opts?.memoryType ?? "experience";
    await this._call("store_memory", [
      workspaceId,
      opts?.peerId ?? "",
      "",
      memType,
      content,
      opts?.summary ?? "",
      "[]",
      0.8,
      "",
      "",
    ]);

    const emb = await this._embed(content);
    if (emb.length > 0) {
      const mems = await this._sql(
        `SELECT id FROM memory WHERE workspace_id = '${esc(workspaceId)}'`
      );
      if (mems.length > 0) {
        await this._call("index_entity", [
          workspaceId,
          "memory",
          mems[mems.length - 1].id,
          content,
          JSON.stringify(emb),
        ]);
      }
    }

    if (opts?.tier && ["L0", "L1", "L2"].includes(opts.tier)) {
      const mems = await this._sql(
        `SELECT id FROM memory WHERE workspace_id = '${esc(workspaceId)}'`
      );
      if (mems.length > 0) {
        await this._call("update_memory_tier", [mems[mems.length - 1].id, opts.tier]);
      }
    }
  }

  async search(
    workspaceId: string,
    query: string,
    opts?: {
      memoryType?: string;
      tier?: string;
      limit?: number;
      semantic?: boolean;
    }
  ): Promise<SearchResult[]> {
    const limit = opts?.limit ?? 20;
    const semantic = opts?.semantic ?? true;

    if (semantic) {
      const emb = await this._embed(query);
      const embJson = emb.length > 0 ? JSON.stringify(emb) : "[]";
      const strategies = JSON.stringify([
        "semantic",
        "keyword",
        "graph",
        "temporal",
      ]);
      await this._call("hybrid_search", [
        workspaceId,
        query,
        embJson,
        opts?.memoryType ?? "",
        opts?.tier ?? "",
        limit,
        strategies,
      ]);
      const qhash = queryHash(query);
      let rows = await this._sql(
        `SELECT * FROM hybrid_result WHERE workspace_id = '${esc(workspaceId)}' AND query_hash = '${esc(qhash)}'`
      );
      rows.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

      // Look up entity content in Python-style
      const memIds: string[] = rows.filter((r: any) => r.entity_type === "memory").map((r: any) => r.entity_id);
      const nodeIds: string[] = rows.filter((r: any) => r.entity_type === "node").map((r: any) => r.entity_id);
      const memMap: Record<string, string> = {};
      const nodeMap: Record<string, string> = {};
      for (const mid of memIds) {
        const mems = await this._sql(`SELECT id, content FROM memory WHERE id = '${esc(mid)}'`);
        if (mems.length > 0) memMap[mid] = mems[0].content ?? "";
      }
      for (const nid of nodeIds) {
        const nodes = await this._sql(`SELECT id, label FROM kg_node WHERE id = '${esc(nid)}'`);
        if (nodes.length > 0) nodeMap[nid] = nodes[0].label ?? "";
      }
      for (const r of rows) {
        const eid = r.entity_id ?? "";
        if (r.entity_type === "memory") r.memory_content = memMap[eid] ?? "";
        else if (r.entity_type === "node") r.memory_content = nodeMap[eid] ?? "";
        else r.memory_content = "";
      }
      return rows.slice(0, limit);
    }

    let clauses = [`workspace_id = '${esc(workspaceId)}'`];
    if (query) {
      clauses.push(
        `(content LIKE '%${esc(query)}%' OR summary LIKE '%${esc(query)}%')`
      );
    }
    if (opts?.memoryType) {
      clauses.push(`memory_type = '${esc(opts.memoryType)}'`);
    }
    if (opts?.tier) {
      clauses.push(`tier = '${esc(opts.tier)}'`);
    }
    const where = clauses.join(" AND ");
    let rows = await this._sql(
      `SELECT * FROM memory WHERE ${where}`
    );
    rows.sort((a: any, b: any) => (b.created_at ?? 0) - (a.created_at ?? 0));
    return rows.slice(0, limit);
  }

  async getMemory(memoryId: string): Promise<MemoryRecord[]> {
    const results = await this._sql(
      `SELECT * FROM memory WHERE id = '${esc(memoryId)}'`
    );
    if (results.length > 0) {
      try {
        await this._call("reinforce_memory", [memoryId]);
      } catch {}
    }
    return results as MemoryRecord[];
  }

  async deleteMemory(memoryId: string): Promise<void> {
    return this._call("deactivate_memory", [memoryId]);
  }

  async reinforce(memoryId: string): Promise<void> {
    return this._call("reinforce_memory", [memoryId]);
  }

  async updateMemory(
    memoryId: string,
    content: string,
    summary?: string,
    confidence?: number,
    expiresAt?: number
  ): Promise<void> {
    const args: any[] = [memoryId, content, summary ?? "", confidence ?? 0.8];
    if (expiresAt !== undefined) {
      args.push(expiresAt);
    }
    return this._call("update_memory", args);
  }

  async rateMemory(
    memoryId: string,
    rating: string,
    peerId: string
  ): Promise<void> {
    return this._call("rate_memory", [memoryId, rating, peerId]);
  }

  async consolidateMemories(
    workspaceId: string,
    sourceIds: string[],
    targetContent: string,
    targetSummary: string
  ): Promise<void> {
    return this._call("consolidate_memories", [
      workspaceId,
      JSON.stringify(sourceIds),
      targetContent,
      targetSummary,
    ]);
  }

  async expireMemories(): Promise<void> {
    return this._call("expire_memories", []);
  }

  async getMemoryHistory(memoryId: string): Promise<any[]> {
    return this._sql(
      `SELECT * FROM memory_revision WHERE memory_id = '${esc(memoryId)}' ORDER BY version ASC`
    );
  }

  async searchDirectoryContents(
    workspaceId: string,
    directoryPath: string
  ): Promise<any[]> {
    await this._call("search_directory_contents", [workspaceId, directoryPath]);
    return this._sql(
      `SELECT * FROM directory_content_result WHERE workspace_id = '${esc(workspaceId)}' AND directory_path = '${esc(directoryPath)}' ORDER BY created_at DESC LIMIT 1`
    );
  }

  async listMemories(
    workspaceId: string,
    opts?: { memoryType?: string; limit?: number }
  ): Promise<MemoryRecord[]> {
    const limit = opts?.limit ?? 50;
    let clauses = [
      `workspace_id = '${esc(workspaceId)}'`,
      "is_active = true",
    ];
    if (opts?.memoryType) {
      clauses.push(`memory_type = '${esc(opts.memoryType)}'`);
    }
    const where = clauses.join(" AND ");
    let rows = await this._sql(
      `SELECT * FROM memory WHERE ${where}`
    );
    rows.sort((a: any, b: any) => (b.created_at ?? 0) - (a.created_at ?? 0));
    return rows.slice(0, limit) as MemoryRecord[];
  }

  // -----------------------------------------------------------------------
  // Knowledge Graph
  // -----------------------------------------------------------------------

  async createNode(
    workspaceId: string,
    label: string,
    nodeType?: string,
    summary?: string
  ): Promise<void> {
    await this._call("create_node", [
      workspaceId,
      label,
      nodeType ?? "concept",
      summary ?? "",
      "{}",
    ]);

    const content = summary ? `${label}: ${summary}` : label;
    const emb = await this._embed(content);
    if (emb.length > 0) {
      const nodes = await this._sql(
        `SELECT id FROM kg_node WHERE workspace_id = '${esc(workspaceId)}' AND label = '${esc(label)}'`
      );
      if (nodes.length > 0) {
        await this._call("index_entity", [
          workspaceId,
          "node",
          nodes[nodes.length - 1].id,
          content,
          JSON.stringify(emb),
        ]);
      }
    }
  }

  async createEdge(
    workspaceId: string,
    sourceNodeId: string,
    targetNodeId: string,
    relation: string,
    weight?: number
  ): Promise<void> {
    return this._call("create_edge", [
      workspaceId,
      sourceNodeId,
      targetNodeId,
      relation,
      weight ?? 1.0,
      "EXTRACTED",
      "{}",
    ]);
  }

  async queryGraph(
    workspaceId: string,
    query?: string
  ): Promise<any[]> {
    if (query) {
      return this._sql(
        `SELECT * FROM kg_node WHERE workspace_id = '${esc(workspaceId)}' AND label LIKE '%${esc(query)}%'`
      );
    }
    return this._sql(
      `SELECT * FROM kg_node WHERE workspace_id = '${esc(workspaceId)}'`
    );
  }

  async getNeighbors(nodeId: string): Promise<any[]> {
    return this._sql(
      `SELECT source_node_id, target_node_id, relation, weight FROM kg_edge ` +
        `WHERE source_node_id = '${esc(nodeId)}' ` +
        `   OR target_node_id = '${esc(nodeId)}'`
    );
  }

  // -----------------------------------------------------------------------
  // Notes / Wiki
  // -----------------------------------------------------------------------

  async createNote(
    workspaceId: string,
    title: string,
    content: string,
    opts?: { embed?: boolean }
  ): Promise<void> {
    await this._call("create_note", [
      workspaceId,
      title,
      content,
      opts?.embed ?? true,
    ]);
  }

  async updateNote(
    noteId: string,
    content: string
  ): Promise<void> {
    return this._call("update_note", [noteId, content]);
  }

  async deleteNote(noteId: string): Promise<void> {
    return this._call("delete_note", [noteId]);
  }

  async listNotes(workspaceId: string): Promise<any[]> {
    return this._sql(
      `SELECT * FROM note WHERE workspace_id = '${esc(workspaceId)}'`
    );
  }

  async getNote(noteId: string): Promise<any[]> {
    return this._sql(
      `SELECT * FROM note WHERE id = '${esc(noteId)}'`
    );
  }

  // -----------------------------------------------------------------------
  // Maintenance
  // -----------------------------------------------------------------------

  async detectCommunities(workspaceId: string): Promise<void> {
    return this._call("detect_communities", [workspaceId]);
  }

  async runMaintenance(): Promise<void> {
    return this._call("run_maintenance", []);
  }

  async dedup(workspaceId: string): Promise<void> {
    return this._call("dedup_memories", [workspaceId]);
  }

  // -----------------------------------------------------------------------
  // Profiles / Facts
  // -----------------------------------------------------------------------

  async addFact(
    workspaceId: string,
    peerId: string,
    content: string,
    opts?: { factType?: string; confidence?: number }
  ): Promise<void> {
    await this._call("add_fact", [
      workspaceId,
      peerId,
      content,
      opts?.factType ?? "",
      opts?.confidence ?? 0.8,
    ]);
  }

  async listFacts(workspaceId: string, peerId: string): Promise<any[]> {
    return this._sql(
      `SELECT * FROM fact_result WHERE workspace_id = '${esc(workspaceId)}' AND peer_id = '${esc(peerId)}'`
    );
  }

  async deleteFact(factId: string): Promise<void> {
    return this._call("delete_fact", [factId]);
  }

  async updateFact(
    factId: string,
    content: string,
    confidence?: number
  ): Promise<void> {
    await this._call("update_fact", [factId, content, confidence ?? 0.8]);
  }

  async searchFacts(
    workspaceId: string,
    query: string
  ): Promise<any[]> {
    return this._sql(
      `SELECT * FROM fact WHERE workspace_id = '${esc(workspaceId)}' AND content LIKE '%${esc(query)}%'`
    );
  }

  // -----------------------------------------------------------------------
  // Tours
  // -----------------------------------------------------------------------

  async createTour(
    workspaceId: string,
    name: string,
    description?: string
  ): Promise<void> {
    return this._call("create_tour", [workspaceId, name, description ?? ""]);
  }

  async addTourStop(
    tourId: string,
    nodeId: string,
    sequence: number
  ): Promise<void> {
    return this._call("add_tour_stop", [tourId, nodeId, sequence]);
  }

  async removeTourStop(tourStopId: string): Promise<void> {
    return this._call("remove_tour_stop", [tourStopId]);
  }

  async deleteTour(tourId: string): Promise<void> {
    return this._call("delete_tour", [tourId]);
  }

  // -----------------------------------------------------------------------
  // Advanced KG
  // -----------------------------------------------------------------------

  async updateNode(
    nodeId: string,
    summary?: string,
    nodeType?: string
  ): Promise<void> {
    await this._call("update_node", [
      nodeId,
      summary ?? "",
      nodeType ?? "",
    ]);
  }

  async deleteNode(nodeId: string): Promise<void> {
    return this._call("delete_node", [nodeId]);
  }

  async updateEdge(
    edgeId: string,
    weight?: number
  ): Promise<void> {
    await this._call("update_edge", [edgeId, weight ?? 1.0]);
  }

  async deleteEdge(edgeId: string): Promise<void> {
    return this._call("delete_edge", [edgeId]);
  }

  async bfs(
    workspaceId: string,
    startNodeId: string,
    maxDepth?: number
  ): Promise<any[]> {
    await this._call("graph_bfs", [
      workspaceId,
      startNodeId,
      maxDepth ?? 5,
    ]);
    return this._sql(
      `SELECT * FROM bfs_result WHERE workspace_id = '${esc(workspaceId)}'`
    );
  }

  async shortestPath(
    workspaceId: string,
    sourceId: string,
    targetId: string
  ): Promise<any[]> {
    await this._call("shortest_path", [
      workspaceId,
      sourceId,
      targetId,
    ]);
    return this._sql(
      `SELECT * FROM bfs_result WHERE workspace_id = '${esc(workspaceId)}'`
    );
  }

  async getEdgeHistory(edgeGroupId: string): Promise<any[]> {
    return this._sql(
      `SELECT * FROM edge_history_result WHERE edge_group_id = '${esc(edgeGroupId)}'`
    );
  }

  // -----------------------------------------------------------------------
  // Sessions
  // -----------------------------------------------------------------------

  async createSession(
    workspaceId: string,
    name?: string
  ): Promise<void> {
    return this._call("create_session", [workspaceId, name ?? ""]);
  }

  async joinSession(sessionId: string): Promise<void> {
    return this._call("join_session", [sessionId]);
  }

  async leaveSession(sessionId: string): Promise<void> {
    return this._call("leave_session", [sessionId]);
  }

  async addAgentStep(
    sessionId: string,
    step: string,
    stepType?: string
  ): Promise<void> {
    return this._call("add_agent_step", [
      sessionId,
      step,
      stepType ?? "action",
    ]);
  }

  async getSessionSteps(sessionId: string): Promise<any[]> {
    return this._sql(
      `SELECT * FROM session_step WHERE session_id = '${esc(sessionId)}'`
    );
  }

  // -----------------------------------------------------------------------
  // Tags
  // -----------------------------------------------------------------------

  async createTag(
    workspaceId: string,
    name: string,
    color?: string
  ): Promise<void> {
    return this._call("create_tag", [workspaceId, name, color ?? ""]);
  }

  async tagMemory(tagId: string, memoryId: string): Promise<void> {
    return this._call("tag_memory", [tagId, memoryId]);
  }

  async untagMemory(tagId: string, memoryId: string): Promise<void> {
    return this._call("untag_memory", [tagId, memoryId]);
  }

  // -----------------------------------------------------------------------
  // Context Packs
  // -----------------------------------------------------------------------

  async storeContextPack(
    workspaceId: string,
    name: string,
    memoryIds: string[],
    contextText?: string
  ): Promise<void> {
    await this._call("store_context_pack", [
      workspaceId,
      name,
      JSON.stringify(memoryIds),
      contextText ?? "",
    ]);
  }

  async updateMemoryTier(
    memoryId: string,
    tier: string
  ): Promise<void> {
    return this._call("update_memory_tier", [memoryId, tier]);
  }

  // -----------------------------------------------------------------------
  // Compounder / Wiki Operations
  // -----------------------------------------------------------------------

  async crossLink(
    workspaceId: string,
    limit?: number
  ): Promise<{ linksCreated: number; pairsChecked: number }> {
    const memories = await this._sql(
      `SELECT id, content FROM memory WHERE workspace_id = '${esc(workspaceId)}' AND is_active = true ORDER BY created_at DESC LIMIT ${limit ?? 50}`
    );

    let linksCreated = 0;
    let pairsChecked = 0;

    for (const mem of memories) {
      const mid = mem.id;
      const content = mem.content;
      if (!content || content.length < 20) continue;

      // Look for existing edges from this memory to others
      // by searching for semantically similar content via keyword
      const similar = await this._sql(
        `SELECT id, content FROM memory WHERE workspace_id = '${esc(workspaceId)}' AND id != '${esc(mid)}' AND content LIKE '%${esc(content.slice(0, 30))}%' LIMIT 5`
      );

      for (const sim of similar) {
        pairsChecked++;
        // Check if edge already exists
        const existing = await this._sql(
          `SELECT id FROM kg_edge WHERE source_node_id = '${esc(mid)}' AND target_node_id = '${esc(sim.id)}'`
        );
        if (existing.length === 0) {
          try {
            await this._call("create_edge", [
              workspaceId,
              mid,
              sim.id,
              "related_to",
              0.7,
              "EXTRACTED",
              "{}",
            ]);
            linksCreated++;
          } catch {}
        }
      }
    }

    return { linksCreated, pairsChecked };
  }

  async suggestConnections(
    workspaceId: string
  ): Promise<any[]> {
    // Find node pairs that share neighbors but aren't directly connected
    await this._call("compute_community_hierarchy", [workspaceId]);
    return this._sql(
      `SELECT * FROM kg_node WHERE workspace_id = '${esc(workspaceId)}'`
    );
  }

  async lintWorkspace(
    workspaceId: string
  ): Promise<{ orphans: number; total: number }> {
    // Find KG nodes with no edges
    const allNodes = await this._sql(
      `SELECT id FROM kg_node WHERE workspace_id = '${esc(workspaceId)}'`
    );
    let orphans = 0;
    for (const node of allNodes) {
      const edges = await this._sql(
        `SELECT id FROM kg_edge WHERE source_node_id = '${esc(node.id)}' OR target_node_id = '${esc(node.id)}' LIMIT 1`
      );
      if (edges.length === 0) orphans++;
    }
    return { orphans, total: allNodes.length };
  }

  async generateOverview(workspaceId: string): Promise<any> {
    // Gather workspace stats
    const [memories, kgNodes, kgEdges, notes] = await Promise.all([
      this._sql(`SELECT COUNT(*) as c FROM memory WHERE workspace_id = '${esc(workspaceId)}'`),
      this._sql(`SELECT COUNT(*) as c FROM kg_node WHERE workspace_id = '${esc(workspaceId)}'`),
      this._sql(`SELECT COUNT(*) as c FROM kg_edge WHERE workspace_id = '${esc(workspaceId)}'`),
      this._sql(`SELECT COUNT(*) as c FROM note WHERE workspace_id = '${esc(workspaceId)}'`),
    ]);

    return {
      workspaceId,
      memories: memories[0]?.c ?? 0,
      kgNodes: kgNodes[0]?.c ?? 0,
      kgEdges: kgEdges[0]?.c ?? 0,
      notes: notes[0]?.c ?? 0,
    };
  }

  async exportWorkspace(workspaceId: string): Promise<string> {
    const notes = await this._sql(
      `SELECT title, content FROM note WHERE workspace_id = '${esc(workspaceId)}'`
    );
    return notes
      .map((n: any) => `# ${n.title}\n\n${n.content ?? ""}`)
      .join("\n\n---\n\n");
  }

  // -----------------------------------------------------------------------
  // Store Answer (simplified compounder — no LLM needed)
  // -----------------------------------------------------------------------

  async storeAnswer(
    query: string,
    answer: string,
    opts?: {
      workspaceId?: string;
      title?: string;
      sourceMemoryIds?: string[];
      embed?: boolean;
    }
  ): Promise<{ note: any; entities: string[]; links: number }> {
    const wsId = opts?.workspaceId ?? "default";
    const title = opts?.title ?? `Q: ${query.slice(0, 60)}`;

    if (!answer.trim()) return { note: {}, entities: [], links: 0 };

    // 1. Create the note
    await this._call("create_note", [wsId, title, answer, opts?.embed ?? true]);

    // Get the note we just created
    const notes = await this._sql(
      `SELECT id FROM note WHERE workspace_id = '${esc(wsId)}' AND title = '${esc(title)}' ORDER BY created_at DESC LIMIT 1`
    );
    if (notes.length === 0) return { note: {}, entities: [], links: 0 };
    const noteId = notes[0].id;

    // 2. Extract entities via regex (capitalized multi-word phrases)
    const entityRegex = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b/g;
    const matches = answer.match(entityRegex) ?? [];
    const seen = new Set<string>();
    const entities: string[] = [];
    for (const m of matches) {
      const clean = m.trim();
      if (clean.length < 3 || clean.length > 60) continue;
      if (seen.has(clean.toLowerCase())) continue;
      seen.add(clean.toLowerCase());
      entities.push(clean);
    }

    // 3. Create KG nodes + link to note
    let links = 0;
    for (const entity of entities.slice(0, 10)) {
      try {
        await this._call("create_node", [wsId, entity, "concept", "", "{}"]);
        const nodes = await this._sql(
          `SELECT id FROM kg_node WHERE workspace_id = '${esc(wsId)}' AND label = '${esc(entity)}'`
        );
        if (nodes.length > 0) {
          await this._call("create_edge", [
            wsId,
            nodes[nodes.length - 1].id,
            noteId,
            "informed_by",
            1.0,
            "EXTRACTED",
            "{}",
          ]);
          links++;
        }
      } catch {}
    }

    // 4. Link to source memories
    const sourceIds = opts?.sourceMemoryIds ?? [];
    for (const sid of sourceIds) {
      try {
        await this._call("create_edge", [
          wsId,
          sid,
          noteId,
          "informed_by",
          0.8,
          "EXTRACTED",
          "{}",
        ]);
      } catch {}
    }

    return { note: { id: noteId, title }, entities, links };
  }
}
