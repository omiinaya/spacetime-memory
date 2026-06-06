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
    this.host = opts.host ?? process.env.SPACETIMEDB_HOST ?? "localhost";
    this.port = String(opts.port ?? process.env.SPACETIMEDB_PORT ?? "3001");
    this.database =
      opts.database ??
      process.env.SPACETIMEDB_DB ??
      "spacetime-memory";
    this.embedderUrl =
      opts.embedderUrl ?? process.env.EMBEDDER_URL ?? "http://localhost:9090";
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
}
