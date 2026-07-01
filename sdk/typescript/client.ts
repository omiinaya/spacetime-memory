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

/** A workspace record. */
export interface Workspace {
  id: string;
  name: string;
  description?: string;
  created_at?: number;
}

/** A knowledge graph node record. */
export interface KGNodeRecord {
  id: string;
  workspace_id: string;
  label: string;
  node_type: string;
  summary?: string;
  metadata_json?: string;
  created_at?: number;
}

/** A knowledge graph edge record. */
export interface KGEdgeRecord {
  id: string;
  workspace_id: string;
  source_node_id: string;
  target_node_id: string;
  relation: string;
  weight: number;
  source?: string;
  metadata_json?: string;
  created_at?: number;
}

/** A wiki note record. */
export interface NoteRecord {
  id: string;
  workspace_id: string;
  title: string;
  content: string;
  is_active?: boolean;
  created_at?: number;
  updated_at?: number;
}

/** A tag record. */
export interface TagRecord {
  id: string;
  workspace_id: string;
  name: string;
  color?: string;
}

/** A fact record. */
export interface FactRecord {
  id: string;
  workspace_id: string;
  peer_id: string;
  content: string;
  fact_type?: string;
  confidence?: number;
  created_at?: number;
}

/** A session record. */
export interface SessionRecord {
  id: string;
  workspace_id: string;
  name?: string;
  is_active?: boolean;
  created_at?: number;
}

/** A mental model record. */
export interface MentalModelRecord {
  id: string;
  workspace_id: string;
  name: string;
  content: string;
  status?: string;
  confidence?: number;
  created_at?: number;
}

/** A tour record. */
export interface TourRecord {
  id: string;
  workspace_id: string;
  name: string;
  description?: string;
  created_at?: number;
}

/** A space member record. */
export interface SpaceMemberRecord {
  id: string;
  workspace_id: string;
  peer_id: string;
  permission: string;
  joined_at?: number;
}

/** A peer record. */
export interface PeerRecord {
  id: string;
  workspace_id: string;
  name: string;
  peer_type: string;
  metadata: string;
  created_at: number;
  updated_at: number;
}

/** A session step record. */
export interface SessionStepRecord {
  id: string;
  session_id: string;
  step: string;
  step_type: string;
  created_at?: number;
}

/** A memory revision record. */
export interface MemoryRevisionRecord {
  id: string;
  memory_id: string;
  content: string;
  version: number;
  changed_at?: number;
}

/** A generic query result row (from query_table reducer). */
export interface GenericQueryResult {
  id: string;
  query_id: string;
  table_name: string;
  row_json: string;
  created_at?: number;
}

/** Result of crossLink operation. */
export interface CrossLinkResult {
  linksCreated: number;
  pairsChecked: number;
}

/** Result of lintWorkspace operation. */
export interface LintResult {
  orphans: number;
  total: number;
}

/** Result of storeAnswer operation. */
export interface StoreAnswerResult {
  note: { id: string; title: string };
  entities: string[];
  links: number;
}

/** Result of generateOverview operation. */
export interface OverviewResult {
  workspaceId: string;
  memories: number;
  kgNodes: number;
  kgEdges: number;
  notes: number;
}

/** Result of exportWorkspace operation. */
export interface ExportResult {
  markdown: string;
}

/** Options for store() method. */
export interface StoreOptions {
  summary?: string;
  memoryType?: string;
  peerId?: string;
  tier?: string;
}

/** Options for search() method. */
export interface SearchOptions {
  memoryType?: string;
  tier?: string;
  limit?: number;
  semantic?: boolean;
}

/** Options for listMemories() method. */
export interface ListMemoriesOptions {
  memoryType?: string;
  limit?: number;
}

/** Options for storeAnswer() method. */
export interface StoreAnswerOptions {
  workspaceId?: string;
  title?: string;
  sourceMemoryIds?: string[];
  embed?: boolean;
}

/** Options for storeBatch items. */
export interface BatchMemoryItem {
  content: string;
  summary?: string;
  memoryType?: string;
  peerId?: string;
  confidence?: number;
}

/** Options for addFact() method. */
export interface AddFactOptions {
  factType?: string;
  confidence?: number;
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

/** Escape a string for safe SQL equality context. Doubles single quotes, escapes backslashes. */
function esc(val: string): string {
  return val.replace(/\\/g, '\\\\').replace(/'/g, "''");
}

/**
 * Escape a string for safe SQL LIKE context.
 * Escapes single quotes, backslashes, and LIKE wildcards (% and _).
 * Always use with ESCAPE '\\' in the SQL clause.
 */
function escLike(val: string): string {
  return esc(val).replace(/%/g, '\%').replace(/_/g, '\_');
}

/**
 * Ensure an identifier (table name, column name) contains only safe characters.
 * Throws if the identifier contains SQL-metacharacters that could facilitate injection.
 */
function safeIdent(name: string): string {
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name)) {
    throw new Error(`Invalid SQL identifier — contains unsafe characters: "${name}"`);
  }
  return name;
}

/**
 * Numeric placeholder helper for _sqlExec. Returns the raw number as a SQL-safe literal,
 * or 0 if undefined/null.
 */
function safeNum(n: number | undefined | null): string {
  if (n == null) return "0";
  const clamped = isFinite(n) ? Math.max(0, Math.floor(n)) : 0;
  return String(clamped);
}

function queryHash(query: string): string {
  let h = 0;
  for (let i = 0; i < query.length; i++) {
    h = (Math.imul(h, 6364136223846793005) + query.charCodeAt(i)) >>> 0;
  }
  return h.toString(16).padStart(16, "0");
}

/**
 * Parse a SpacetimeDB SQL HTTP response into a flat array of objects.
 * Each element in the response corresponds to a table; each table has
 * a schema with column names and rows with positional values.
 */
function parseSqlResponse(raw: string): any[] {
  if (!raw.trim()) return [];
  const tables: unknown[] = JSON.parse(raw);
  const results: Record<string, unknown>[] = [];
  for (const table of tables) {
    const tbl = table as Record<string, unknown>;
    const elements = ((tbl?.schema as Record<string, unknown>)?.elements ?? []) as Record<string, unknown>[];
    const colNames: string[] = elements.map(
      (el: Record<string, unknown>) => ((el?.name as Record<string, string>)?.some ?? "?col?")
    );
    for (const row of (tbl?.rows as unknown[][]) ?? []) {
      const r: Record<string, unknown> = {};
      for (let i = 0; i < colNames.length; i++) {
        r[colNames[i]] = row[i];
      }
      results.push(r);
    }
  }
  return results;
  }

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

  /**
   * Execute a raw SQL SELECT query against the SpacetimeDB SQL API.
   * Prefer _query() for content tables; reserved for public result tables.
   */
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

  /**
   * SAFE parameterized SQL execution.
   *
   * Builds a query by replacing `:param` placeholders with properly escaped
   * string values. Use this instead of raw string interpolation with `_sql()`.
   *
   * For LIKE clauses, set `opts.like = true` to escape `%` and `_` wildcards
   * via `escLike()`.  The caller MUST also add `ESCAPE '\'` to the SQL clause
   * when doing LIKE matching.
   *
   * For numeric parameters, pass the value through the `:param` placeholder
   * as a string representation — the method coerces via the `safeNum()` helper.
   *
   * Example:
   * ```
   * this._sqlExec(
   *   "SELECT * FROM memory WHERE workspace_id = :ws AND id = :id",
   *   { ws: workspaceId, id: memoryId },
   * );
   * ```
   *
   * @param template - SQL query with `:name` placeholders (NOT `$1` style)
   * @param params - Map of placeholder name (without colon) → value
   * @param opts - `{ like: true }` to use LIKE-safe escaping
   */
  private async _sqlExec(
    template: string,
    params: Record<string, string>,
    opts?: { like?: boolean },
  ): Promise<any[]> {
    let query = template;
    for (const [key, val] of Object.entries(params)) {
      const escaped = opts?.like
        ? `'${escLike(val)}'`
        : `'${esc(val)}'`;
      // Replace all occurrences of `:key` with the escaped value
      query = query.replace(
        new RegExp(`:${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'g'),
        escaped,
      );
    }
    return this._sql(query);
  }

  /**
   * Call a named reducer (stored procedure) with positional arguments.
   * Reducers are the safe way to mutate data in SpacetimeDB.
   */
  private async _call(reducer: string, args: unknown[]): Promise<void> {
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

  /**
   * Call a reducer and return the raw response body.
   * Use when the reducer emits data via reducer_result (e.g. list_admins).
   */
  private async _callWithResult(reducer: string, args: unknown[]): Promise<string> {
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
    const text = await resp.text();
    if (text.length === 0) {
      throw new Error(`Reducer '${reducer}' returned empty response`);
    }
    return text;
  }

  /**
   * Get a text embedding vector from the embedder sidecar.
   * Returns an empty array if the embedder is unreachable or errors.
   */
  private async _embed(text: string): Promise<number[]> {
    try {
      const resp = await fetch(`${this.embedderUrl}/embed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!resp.ok) return [];
      const data = await resp.json() as Record<string, unknown>;
      return (data?.embedding as number[]) ?? [];
    } catch {
      return [];
    }
  }

  /**
   * Query a content table through the query_table reducer (SQL injection safe).
   *
   * The reducer checks auth + workspace access and stores results in the
   * public query_result table, scoped by a random query_id. This is the
   * preferred way to read from private content tables.
   *
   * @param table - Name of the content table (e.g. "memory", "kg_node", "note")
   * @param workspaceId - Workspace ID for access control (empty = no scope)
   * @param filter - Optional equality filters as {column: value} pairs
   * @returns Array of result rows as plain objects
   */
  private async _query(
    table: string,
    workspaceId: string = "",
    filter?: Record<string, string>
  ): Promise<Record<string, unknown>[]> {
    const queryId = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36);
    const filterJson = JSON.stringify(filter ?? {});
    await this._call("query_table", [
      queryId,
      table,
      workspaceId,
      filterJson,
      "[]",
    ]);
    const rows = await this._sqlExec(
      `SELECT table_name, row_json FROM query_result WHERE query_id = :qid`,
      { qid: queryId },
    );
    const results: Record<string, unknown>[] = [];
    for (const r of rows) {
      if (r?.row_json) {
        results.push(JSON.parse(r.row_json as string));
      } else {
        results.push(r);
      }
    }
    return results;
  }

  // ---------------------------------------------------------------------------
  // Auth / Account
  // ---------------------------------------------------------------------------

  /**
   * Register a new account. First user becomes admin.
   * @param username - Unique username for the account.
   * @param displayName - Optional display name (defaults to username).
   * @param password - Password (minimum 6 characters).
   */
  async register(
    username: string,
    displayName: string = "",
    password: string = ""
  ): Promise<void> {
    return this._call("register", [username, displayName, password]);
  }

  /**
   * Login with username + password. Links this identity to the account.
   * @param username - Account username.
   * @param password - Account password.
   */
  async login(username: string, password: string): Promise<void> {
    return this._call("login", [username, password]);
  }

  /**
   * Logout — detach the current identity from its account.
   */
  async logout(): Promise<void> {
    return this._call("logout", []);
  }

  /**
   * Update account display name and/or password.
   * @param displayName - New display name (empty = no change).
   * @param currentPassword - Current password (required for verification).
   * @param newPassword - New password (empty = no change, min 6 chars).
   */
  async updateAccount(
    displayName: string = "",
    currentPassword: string = "",
    newPassword: string = ""
  ): Promise<void> {
    return this._call("update_account", [
      displayName,
      currentPassword,
      newPassword,
    ]);
  }

  /**
   * Deactivate (soft-delete) this account.
   * The account remains in the database with is_active=false,
   * preventing future logins.
   * @param password - Account password (required for verification).
   */
  async deactivateAccount(password: string): Promise<void> {
    return this._call("deactivate_account", [password]);
  }

  /**
   * Promote a user to admin. Caller must be an existing admin.
   * @param targetIdentity - The identity hex string of the user to promote.
   */
  async promoteAdmin(targetIdentity: string): Promise<void> {
    return this._call("promote_admin", [targetIdentity]);
  }

  /**
   * Demote an admin to regular user. Caller must be an existing admin.
   * Cannot demote yourself. At least one admin must always remain.
   * @param targetIdentity - The identity hex string of the admin to demote.
   */
  async demoteAdmin(targetIdentity: string): Promise<void> {
    return this._call("demote_admin", [targetIdentity]);
  }

  /**
   * List all admin accounts.
   * @returns Array of admin account records.
   */
  async listAdmins(): Promise<Record<string, unknown>[]> {
    await this._call("list_admins", []);
    // list_admins emits results into the admin_result public table
    const rows = await this._sqlExec(
      `SELECT row_json FROM admin_result`,
      {}
    );
    return rows.map((r: Record<string, unknown>) => {
      if (r?.row_json) {
        try {
          return JSON.parse(r.row_json as string) as Record<string, unknown>;
        } catch {
          return r;
        }
      }
      return r;
    });
  }

  // -----------------------------------------------------------------------
  // Workspace
  // -----------------------------------------------------------------------

  /**
   * Create a new workspace.
   * @param name - Display name for the workspace
   * @param description - Optional description text
   */
  async createWorkspace(
    name: string,
    description?: string
  ): Promise<void> {
    return this._call("create_workspace", [name, description ?? ""]);
  }

  /**
   * List all workspaces.
   * @returns Array of workspace records
   */
  async listWorkspaces(): Promise<Workspace[]> {
    return (await this._sql("SELECT * FROM workspace")) as Workspace[];
  }

  /**
   * Update workspace name and description.
   * @param id - Workspace ID
   * @param name - New name
   * @param description - New description
   */
  async updateWorkspace(
    id: string,
    name: string,
    description: string
  ): Promise<void> {
    return this._call("update_workspace", [id, name, description]);
  }

  /**
   * Delete a workspace.
   * @param workspaceId - Workspace ID to delete
   */
  async deleteWorkspace(workspaceId: string): Promise<void> {
    return this._call("delete_workspace", [workspaceId]);
  }

  /**
   * Set a workspace's visibility (public/private).
   * @param workspaceId - Workspace ID
   * @param isPublic - Whether the workspace should be publicly visible
   */
  async setWorkspaceVisibility(
    workspaceId: string,
    isPublic: boolean
  ): Promise<void> {
    return this._call("set_workspace_visibility", [workspaceId, isPublic]);
  }

  /**
   * Retrieve context information for a workspace by calling the
   * get_workspace_context reducer then reading the result table.
   * @param workspaceId - The workspace ID
   * @returns Workspace context row, or null if none found
   */
  async getWorkspaceContext(workspaceId: string): Promise<Record<string, unknown> | null> {
    await this._call("get_workspace_context", [workspaceId]);
    const rows = await this._sqlExec(
      `SELECT * FROM workspace_context_result WHERE workspace_id = :wsid`,
      { wsid: workspaceId },
    );
    return rows.length > 0 ? rows[0] : null;
  }

  /**
   * List members of a space.
   * @param workspaceId - Workspace ID
   * @returns Array of space member records
   */
  async listSpaceMembers(workspaceId: string): Promise<SpaceMemberRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM space_member WHERE workspace_id = :ws`,
      { ws: workspaceId },
    )) as SpaceMemberRecord[];
  }

  /**
   * List peers, optionally filtered by workspace.
   * @param workspaceId - Optional workspace ID to filter by
   * @returns Array of peer records
   */
  async listPeers(workspaceId?: string): Promise<PeerRecord[]> {
    if (workspaceId) {
      return (await this._sqlExec(
        `SELECT * FROM peer WHERE workspace_id = :ws`,
        { ws: workspaceId },
      )) as PeerRecord[];
    }
    return (await this._sqlExec(
      `SELECT * FROM peer`,
      {},
    )) as PeerRecord[];
  }

  /**
   * Grant space access to a peer.
   * @param workspaceId - Workspace ID
   * @param peerId - Peer identity string
   * @param permission - Permission level (e.g. "viewer", "editor", "admin")
   */
  async grantSpaceAccess(
    workspaceId: string,
    peerId: string,
    permission: string
  ): Promise<void> {
    return this._call("grant_space_access", [workspaceId, peerId, permission]);
  }

  /**
   * Revoke space access from a peer.
   * @param workspaceId - Workspace ID
   * @param peerId - Peer identity string
   */
  async revokeSpaceAccess(
    workspaceId: string,
    peerId: string
  ): Promise<void> {
    return this._call("revoke_space_access", [workspaceId, peerId]);
  }

  // -----------------------------------------------------------------------
  // API Keys
  // -----------------------------------------------------------------------

  /**
   * Create a new API key with a specific permission set.
   * Generates a secure random key secret (sk-...), hashes it, and stores
   * the hash. The unhashed secret is returned only once.
   * @param workspaceId - Workspace ID
   * @param name - Human-readable label for the key
   * @param permissions - Permission array as JSON string (default: '["read"]')
   * @returns Object with status, apiKey (the secret), id (key DB ID), and warning
   */
  async createApiKey(
    workspaceId: string,
    name: string,
    permissions?: string
  ): Promise<Record<string, unknown>> {
    // Generate a secure random key using crypto
    const raw = new Uint8Array(32);
    crypto.getRandomValues(raw);
    const hex = Array.from(raw).map(b => b.toString(16).padStart(2, "0")).join("");
    const apiKey = "sk-" + hex;
    const encoder = new TextEncoder();
    const hashBuffer = await crypto.subtle.digest("SHA-256", encoder.encode(apiKey));
    const keyHash = Array.from(new Uint8Array(hashBuffer)).map(b => b.toString(16).padStart(2, "0")).join("");

    const requestId = Array.from(crypto.getRandomValues(new Uint8Array(16)))
      .map(b => b.toString(16).padStart(2, "0")).join("");

    const perms = permissions ?? '["read"]';

    await this._call("create_api_key", [
      workspaceId,
      name,
      perms,
      keyHash,
      requestId,
    ]);

    const rows = await this._sql(
      `SELECT api_key_id, name, permissions FROM api_key_result WHERE request_id = '${requestId}' AND operation = 'create'`
    );
    const keyId = (rows[0]?.api_key_id as string) ?? "";

    return {
      status: "ok",
      api_key: apiKey,
      id: keyId,
      note: "Save this key — it will not be shown again.",
    };
  }

  /**
   * Deactivate (revoke) an API key so it can no longer be used.
   * @param keyId - The primary-key id of the API key row
   */
  async deactivateApiKey(keyId: string): Promise<void> {
    return this._call("deactivate_api_key", [keyId]);
  }

  /**
   * List all API keys for a workspace.
   * Calls the list_api_keys reducer which populates the api_key_result table.
   * @param workspaceId - Workspace ID
   * @returns Array of API key metadata records
   */
  async listApiKeys(workspaceId: string): Promise<Record<string, unknown>[]> {
    await this._call("list_api_keys", [workspaceId]);
    return this._sql(
      `SELECT * FROM api_key_result WHERE request_id = '${workspaceId}' ORDER BY created_at DESC`
    );
  }

  // -----------------------------------------------------------------------
  // Mental Models
  // -----------------------------------------------------------------------

  /**
   * Synthesize mental models from a set of memories.
   * Calls the reducer then reads results from the mental_model_result table.
   * @param workspaceId - Workspace ID
   * @param memoryIds - Array of memory IDs to synthesize from
   * @returns Array of synthesized mental model records
   */
  async synthesizeMentalModels(
    workspaceId: string,
    memoryIds: string[]
  ): Promise<MentalModelRecord[]> {
    await this._call("synthesize_mental_models", [
      workspaceId,
      JSON.stringify(memoryIds),
    ]);
    return (await this._sqlExec(
      `SELECT * FROM mental_model_result WHERE workspace_id = :ws`,
      { ws: workspaceId },
    )) as MentalModelRecord[];
  }

  /**
   * Get a single mental model by ID.
   * @param modelId - Mental model ID
   * @returns Array containing the mental model record (or empty)
   */
  async getMentalModel(modelId: string): Promise<MentalModelRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM mental_model WHERE id = :mid`,
      { mid: modelId },
    )) as MentalModelRecord[];
  }

  /**
   * List mental models for a workspace, optionally filtered by status.
   * Results are ordered by created_at descending.
   * @param workspaceId - Workspace ID
   * @param status - Optional status filter (e.g. "completed", "draft")
   * @returns Array of mental model records
   */
  async listMentalModels(
    workspaceId: string,
    status?: string
  ): Promise<MentalModelRecord[]> {
    let q = `SELECT * FROM mental_model WHERE workspace_id = :ws`;
    const params: Record<string, string> = { ws: workspaceId };
    if (status) {
      q += ` AND status = :st`;
      params.st = status;
    }
    return (await this._sqlExec(
      q + ` ORDER BY created_at DESC`,
      params,
    )) as MentalModelRecord[];
  }

  /**
   * Delete a mental model.
   * @param modelId - Mental model ID to delete
   */
  async deleteMentalModel(modelId: string): Promise<void> {
    return this._call("delete_mental_model", [modelId]);
  }

  /**
   * Update a mental model's content, confidence, and status.
   * @param modelId - Mental model ID
   * @param content - New content text
   * @param confidence - Updated confidence score (0-1)
   * @param status - Updated status (e.g. "completed", "draft")
   */
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

  /**
   * Store a memory in the workspace.
   * Calls the store_memory reducer, then optionally indexes the embedding.
   * @param workspaceId - Target workspace ID
   * @param content - Memory content text
   * @param opts - Optional: summary, memoryType, peerId, tier
   */
  async store(
    workspaceId: string,
    content: string,
    opts?: StoreOptions
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
      const mems = await this._sqlExec(
        `SELECT id FROM memory WHERE workspace_id = :ws`,
        { ws: workspaceId },
      );
      if (mems.length > 0) {
        await this._call("index_entity", [
          workspaceId,
          "memory",
          mems[mems.length - 1].id as string,
          content,
          JSON.stringify(emb),
        ]);
      }
    }

    if (opts?.tier && ["L0", "L1", "L2"].includes(opts.tier)) {
      const mems = await this._sqlExec(
        `SELECT id FROM memory WHERE workspace_id = :ws`,
        { ws: workspaceId },
      );
      if (mems.length > 0) {
        await this._call("update_memory_tier", [(mems[mems.length - 1].id as string), opts.tier]);
      }
    }
  }

  /**
   * Search memories using hybrid search (semantic + keyword + graph + temporal)
   * or fallback keyword search.
   *
   * When semantic=true, calls the hybrid_search reducer then reads from
   * hybrid_result table. Enriches results with entity content.
   * When semantic=false, does a direct SQL query on the memory table.
   *
   * @param workspaceId - Workspace ID
   * @param query - Search query text
   * @param opts - Options: memoryType, tier, limit, semantic (default: true)
   * @returns Array of search results, sorted by relevance
   */
  async search(
    workspaceId: string,
    query: string,
    opts?: SearchOptions
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
      let rows = await this._sqlExec(
        `SELECT * FROM hybrid_result WHERE workspace_id = :ws AND query_hash = :qh`,
        { ws: workspaceId, qh: qhash },
      );
      rows.sort((a, b) => ((b.score ?? 0) as number) - ((a.score ?? 0) as number));

      // Look up entity content in Python-style
      const memIds: string[] = rows.filter((r) => r.entity_type === "memory").map((r) => r.entity_id as string);
      const nodeIds: string[] = rows.filter((r) => r.entity_type === "node").map((r) => r.entity_id as string);
      const memMap: Record<string, string> = {};
      const nodeMap: Record<string, string> = {};
      for (const mid of memIds) {
        const mems = await this._sqlExec(
          `SELECT id, content FROM memory WHERE id = :mid`,
          { mid },
        );
        if (mems.length > 0) memMap[mid] = (mems[0].content ?? "") as string;
      }
      for (const nid of nodeIds) {
        const nodes = await this._sqlExec(
          `SELECT id, label FROM kg_node WHERE id = :nid`,
          { nid },
        );
        if (nodes.length > 0) nodeMap[nid] = (nodes[0].label ?? "") as string;
      }
      for (const r of rows) {
        const eid = (r.entity_id ?? "") as string;
        if (r.entity_type === "memory") r.memory_content = memMap[eid] ?? "";
        else if (r.entity_type === "node") r.memory_content = nodeMap[eid] ?? "";
        else r.memory_content = "";
      }
      return rows.slice(0, limit) as SearchResult[];
    }

    let qBase = `SELECT * FROM memory WHERE workspace_id = :ws`;
    const params: Record<string, string> = { ws: workspaceId };
    if (query) {
      qBase += ` AND (content LIKE '%' || :q || '%' ESCAPE '\\' OR summary LIKE '%' || :q || '%' ESCAPE '\\')`;
      params.q = query;
    }
    if (opts?.memoryType) {
      qBase += ` AND memory_type = :mt`;
      params.mt = opts.memoryType;
    }
    if (opts?.tier) {
      qBase += ` AND tier = :t`;
      params.t = opts.tier;
    }
    let rows = await this._sqlExec(qBase, params, query ? { like: true } : undefined);
    rows.sort((a, b) => ((b.created_at ?? 0) as number) - ((a.created_at ?? 0) as number));
    return rows.slice(0, limit) as unknown as SearchResult[];
  }

  /**
   * Get a single memory by ID. Also reinforces the memory (increments access count).
   * @param memoryId - The memory ID to retrieve
   * @returns Array containing the memory record (or empty)
   */
  async getMemory(memoryId: string): Promise<MemoryRecord[]> {
    const results = (await this._sqlExec(
      `SELECT * FROM memory WHERE id = :mid`,
      { mid: memoryId },
    )) as unknown as MemoryRecord[];
    if (results.length > 0) {
      try {
        await this._call("reinforce_memory", [memoryId]);
      } catch {}
    }
    return results;
  }

  /**
   * Soft-delete a memory by deactivating it.
   * @param memoryId - The memory ID to deactivate
   */
  async deleteMemory(memoryId: string): Promise<void> {
    return this._call("deactivate_memory", [memoryId]);
  }

  /**
   * Reinforce a memory (increment access count / strengthen recall).
   * @param memoryId - The memory ID to reinforce
   */
  async reinforce(memoryId: string): Promise<void> {
    return this._call("reinforce_memory", [memoryId]);
  }

  /**
   * Update a memory's content, summary, confidence, and optional expiration.
   * @param memoryId - The memory ID
   * @param content - New content text
   * @param summary - Optional new summary
   * @param confidence - Updated confidence score (default: 0.8)
   * @param expiresAt - Optional expiration timestamp (epoch ms)
   */
  async updateMemory(
    memoryId: string,
    content: string,
    summary?: string,
    confidence?: number,
    expiresAt?: number
  ): Promise<void> {
    const args: unknown[] = [memoryId, content, summary ?? "", confidence ?? 0.8];
    if (expiresAt !== undefined) {
      args.push(expiresAt);
    }
    return this._call("update_memory", args);
  }

  /**
   * Rate a memory (user feedback).
   * @param memoryId - The memory ID to rate
   * @param rating - Rating label (e.g. "helpful", "unhelpful")
   * @param peerId - The peer providing the rating
   */
  async rateMemory(
    memoryId: string,
    rating: string,
    peerId: string
  ): Promise<void> {
    return this._call("rate_memory", [memoryId, rating, peerId]);
  }

  /**
   * Consolidate multiple memories into a single memory with merged content.
   * @param workspaceId - Workspace ID
   * @param sourceIds - Array of source memory IDs to consolidate
   * @param targetContent - Merged content for the consolidated memory
   * @param targetSummary - Summary for the consolidated memory
   */
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

  /**
   * Expire all memories that have passed their expiration timestamp.
   * Calls the expire_memories reducer which deactivates stale entries.
   */
  async expireMemories(): Promise<void> {
    return this._call("expire_memories", []);
  }

  /**
   * Get the revision history of a memory.
   * @param memoryId - The memory ID
   * @returns Array of memory revision records, ordered by version
   */
  async getMemoryHistory(memoryId: string): Promise<MemoryRevisionRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM memory_revision WHERE memory_id = :mid ORDER BY version ASC`,
      { mid: memoryId },
    )) as MemoryRevisionRecord[];
  }

  /**
   * Search the contents of a directory in the context of a workspace.
   * @param workspaceId - Workspace ID
   * @param directoryPath - Directory path to search
   * @returns Array of directory content result records
   */
  async searchDirectoryContents(
    workspaceId: string,
    directoryPath: string
  ): Promise<Record<string, unknown>[]> {
    await this._call("search_directory_contents", [workspaceId, directoryPath]);
    return await this._sqlExec(
      `SELECT * FROM directory_content_result WHERE workspace_id = :ws AND directory_path = :dp ORDER BY created_at DESC LIMIT 1`,
      { ws: workspaceId, dp: directoryPath },
    );
  }

  /**
   * List memories in a workspace with optional type filter and limit.
   * Results are sorted by created_at descending.
   * @param workspaceId - Workspace ID
   * @param opts - Options: memoryType, limit (default 50)
   * @returns Array of memory records
   */
  async listMemories(
    workspaceId: string,
    opts?: ListMemoriesOptions
  ): Promise<MemoryRecord[]> {
    const limit = opts?.limit ?? 50;
    let q = `SELECT * FROM memory WHERE workspace_id = :ws AND is_active = true`;
    const params: Record<string, string> = { ws: workspaceId };
    if (opts?.memoryType) {
      q += ` AND memory_type = :mt`;
      params.mt = opts.memoryType;
    }
    let rows = await this._sqlExec(q, params);
    rows.sort((a: any, b: any) => (b.created_at ?? 0) - (a.created_at ?? 0));
    return rows.slice(0, limit) as MemoryRecord[];
  }

  // -----------------------------------------------------------------------
  // Knowledge Graph
  // -----------------------------------------------------------------------

  /**
   * Create a knowledge graph node (entity) in a workspace.
   * Optionally indexes the node with an embedding for semantic search.
   * @param workspaceId - Workspace ID
   * @param label - Human-readable label for the node
   * @param nodeType - Type of node (e.g. "concept", "person", "org")
   * @param summary - Optional short description
   */
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
      const nodes = await this._sqlExec(
        `SELECT id FROM kg_node WHERE workspace_id = :ws AND label = :label`,
        { ws: workspaceId, label },
      );
      if (nodes.length > 0) {
        await this._call("index_entity", [
          workspaceId,
          "node",
          nodes[nodes.length - 1].id as string,
          content,
          JSON.stringify(emb),
        ]);
      }
    }
  }

  /**
   * Create a directed edge between two knowledge graph nodes.
   * @param workspaceId - Workspace ID
   * @param sourceNodeId - Source node ID
   * @param targetNodeId - Target node ID
   * @param relation - Relation type label (e.g. "related_to", "informed_by")
   * @param weight - Optional edge weight (default: 1.0)
   */
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

  /**
   * Search knowledge graph nodes by label (supports partial match via LIKE).
   * If no query is provided, returns all nodes for the workspace.
   * @param workspaceId - Workspace ID
   * @param query - Optional search string (LIKE match on label)
   * @returns Array of matching KG node records
   */
  async queryGraph(
    workspaceId: string,
    query?: string
  ): Promise<KGNodeRecord[]> {
    if (query) {
      return (await this._sqlExec(
        `SELECT * FROM kg_node WHERE workspace_id = :ws AND label LIKE '%' || :q || '%' ESCAPE '\\'`,
        { ws: workspaceId, q: query },
        { like: true },
      )) as KGNodeRecord[];
    }
    return (await this._sqlExec(
      `SELECT * FROM kg_node WHERE workspace_id = :ws`,
      { ws: workspaceId },
    )) as KGNodeRecord[];
  }

  /**
   * Get all edges (neighbors) connected to a node, both incoming and outgoing.
   * @param nodeId - The node ID
   * @returns Array of edge records involving this node
   */
  async getNeighbors(nodeId: string): Promise<KGEdgeRecord[]> {
    return (await this._sqlExec(
      `SELECT source_node_id, target_node_id, relation, weight FROM kg_edge ` +
        `WHERE source_node_id = :nid ` +
        `   OR target_node_id = :nid`,
      { nid: nodeId },
    )) as KGEdgeRecord[];
  }

  // -----------------------------------------------------------------------
  // Notes / Wiki
  // -----------------------------------------------------------------------

  /**
   * Create a wiki note in the workspace.
   * @param workspaceId - Workspace ID
   * @param title - Note title
   * @param content - Markdown content
   * @param opts - Options: embed (default: true) — generate embedding for search
   */
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

  /**
   * Update a note's content.
   * @param noteId - Note ID
   * @param content - New markdown content
   */
  async updateNote(
    noteId: string,
    content: string
  ): Promise<void> {
    return this._call("update_note", [noteId, content]);
  }

  /**
   * Delete a note.
   * @param noteId - Note ID to delete
   */
  async deleteNote(noteId: string): Promise<void> {
    return this._call("delete_note", [noteId]);
  }

  /**
   * List all notes in a workspace.
   * @param workspaceId - Workspace ID
   * @returns Array of note records
   */
  async listNotes(workspaceId: string): Promise<NoteRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM note WHERE workspace_id = :ws`,
      { ws: workspaceId },
    )) as NoteRecord[];
  }

  /**
   * Get a single note by ID.
   * @param noteId - Note ID
   * @returns Array containing the note record (or empty)
   */
  async getNote(noteId: string): Promise<NoteRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM note WHERE id = :nid`,
      { nid: noteId },
    )) as NoteRecord[];
  }

  // -----------------------------------------------------------------------
  // Backlinks & Document References
  // -----------------------------------------------------------------------

  /**
   * Get all backlinks referencing a note (incoming wiki links).
   * @param noteId - Note ID to find backlinks for
   * @returns Array of backlink records
   */
  async getBacklinks(noteId: string): Promise<Record<string, unknown>[]> {
    await this._call("get_backlinks", [noteId]);
    return this._sqlExec(
      `SELECT * FROM backlink_result WHERE target_note_id = :nid`,
      { nid: noteId },
    );
  }

  // -----------------------------------------------------------------------
  // Documents
  // -----------------------------------------------------------------------

  /**
   * Create a document with auto-chunking.
   * Documents with content >= 100 chars are automatically split into
   * overlapping ~500-char chunks (sentence-boundary-aware).
   * @param workspaceId - Target workspace
   * @param title - Document title
   * @param content - Document body text (auto-chunked if >= 100 chars)
   * @param contentType - Content type: "text", "pdf", "image", "video", "code", or "url"
   * @param filePath - Optional file path
   * @param sourceUrl - Optional source URL
   * @param metadata - Optional metadata dict
   */
  async createDocument(
    workspaceId: string,
    title: string,
    content?: string,
    contentType?: string,
    filePath?: string,
    sourceUrl?: string,
    metadata?: Record<string, unknown>
  ): Promise<void> {
    const metaJson = metadata ? JSON.stringify(metadata) : "{}";
    return this._call("create_document", [
      workspaceId,
      title,
      content ?? "",
      contentType ?? "text",
      filePath ?? "",
      sourceUrl ?? "",
      metaJson,
    ]);
  }

  /**
   * Get a document by ID.
   * @param docId - Document ID
   * @returns Document record or null
   */
  async getDocument(docId: string): Promise<Record<string, unknown> | null> {
    const rows = await this._sqlExec(
      `SELECT * FROM document WHERE id = :did`,
      { did: docId },
    );
    return rows.length > 0 ? rows[0] : null;
  }

  /**
   * List all documents in a workspace.
   * @param workspaceId - Workspace ID
   * @returns Array of document records
   */
  async listDocuments(workspaceId: string): Promise<Record<string, unknown>[]> {
    return this._sqlExec(
      `SELECT * FROM document WHERE workspace_id = :ws`,
      { ws: workspaceId },
    );
  }

  /**
   * Get chunks for a document.
   * @param docId - Document ID
   * @returns Array of document chunk records
   */
  async getDocumentChunks(docId: string): Promise<Record<string, unknown>[]> {
    return this._sqlExec(
      `SELECT * FROM document_chunk WHERE document_id = :did ORDER BY chunk_index ASC`,
      { did: docId },
    );
  }

  /**
   * Delete a document.
   * @param docId - Document ID to delete
   */
  async deleteDocument(docId: string): Promise<void> {
    return this._call("delete_document", [docId]);
  }

  // -----------------------------------------------------------------------
  // Profiles & Facts
  // -----------------------------------------------------------------------

  /**
   * Add a fact to a peer's profile (appended to static_facts_json array).
   * @param peerId - Peer identity
   * @param fact - Fact text to add
   */
  async addProfileFact(peerId: string, fact: string): Promise<void> {
    return this._call("add_profile_fact", [peerId, fact]);
  }

  /**
   * Add dynamic context to a peer's profile.
   * @param peerId - Peer identity
   * @param context - Context text to add
   */
  async addDynamicContext(peerId: string, context: string): Promise<void> {
    return this._call("add_dynamic_context", [peerId, context]);
  }

  /**
   * Get a peer's profile by peer_id.
   * @param peerId - Peer identity
   * @returns Profile record or null
   */
  async getProfile(peerId: string): Promise<Record<string, unknown> | null> {
    const rows = await this._sqlExec(
      `SELECT * FROM profile WHERE id = :pid`,
      { pid: peerId },
    );
    return rows.length > 0 ? rows[0] : null;
  }

  /**
   * List all profiles in a workspace.
   * @param workspaceId - Workspace ID
   * @returns Array of profile records
   */
  async listProfiles(workspaceId: string): Promise<Record<string, unknown>[]> {
    return this._sqlExec(
      `SELECT p.* FROM profile p INNER JOIN peer pr ON p.id = pr.id WHERE pr.workspace_id = :ws`,
      { ws: workspaceId },
    );
  }

  // -----------------------------------------------------------------------
  // Context & Utilities
  // -----------------------------------------------------------------------

  /**
   * Attach a context string to a workspace.
   * @param workspaceId - Workspace ID
   * @param context - Context text
   */
  async setWorkspaceContext(
    workspaceId: string,
    context: string
  ): Promise<void> {
    return this._call("set_workspace_context", [workspaceId, context]);
  }

  /**
   * Attach a context string to a memory.
   * @param memoryId - Memory ID
   * @param context - Context text
   */
  async setMemoryContext(
    memoryId: string,
    context: string
  ): Promise<void> {
    return this._call("set_memory_context", [memoryId, context]);
  }

  /**
   * Get the context chain for a memory (parents, ancestors).
   * @param memoryId - Memory ID
   * @returns Context chain record or empty
   */
  async getContextChain(memoryId: string): Promise<Record<string, unknown>[]> {
    await this._call("get_context_chain", [memoryId]);
    return this._sqlExec(
      `SELECT * FROM context_chain_result WHERE memory_id = :mid`,
      { mid: memoryId },
    );
  }

  /**
   * Add an alias to an existing entity link.
   * @param entityLinkId - Entity link ID
   * @param alias - Alias text to add
   */
  async addAlias(entityLinkId: string, alias: string): Promise<void> {
    return this._call("add_alias", [entityLinkId, alias]);
  }

  /**
   * Create an entity link that maps an alias to an identity.
   * @param workspaceId - Workspace ID
   * @param name - Entity name
   * @param identity - Identity to link to
   */
  async createEntityLink(
    workspaceId: string,
    name: string,
    identity: string
  ): Promise<void> {
    return this._call("create_entity_link", [workspaceId, name, identity]);
  }

  /**
   * Get a KG node by ID.
   * @param nodeId - Node ID
   * @returns Array containing the node record (or empty)
   */
  async getNode(nodeId: string): Promise<Record<string, unknown>[]> {
    return this._sqlExec(
      `SELECT * FROM kg_node WHERE id = :nid`,
      { nid: nodeId },
    );
  }

  /**
   * Get a note by its date string (YYYY-MM-DD).
   * @param noteDate - Date string in YYYY-MM-DD format
   * @returns Array of matching note records
   */
  async getNoteByDate(noteDate: string): Promise<NoteRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM note WHERE note_date = :nd AND is_active = true`,
      { nd: noteDate },
    )) as NoteRecord[];
  }

  /**
   * Find a note by exact title.
   * @param title - Exact note title
   * @returns Array of matching note records
   */
  async getNoteByTitle(title: string): Promise<NoteRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM note WHERE title = :t AND is_active = true`,
      { t: title },
    )) as NoteRecord[];
  }

  /**
   * Get neighbouring nodes of a node via reducer (results in graph_traversal_result).
   * @param workspaceId - Workspace ID
   * @param nodeId - Node ID
   */
  async getNeighborsViaReducer(
    workspaceId: string,
    nodeId: string
  ): Promise<void> {
    return this._call("get_neighbors", [workspaceId, nodeId]);
  }

  /**
   * List sessions a peer has participated in.
   * @param peerId - Peer identity
   * @returns Array of session records with role and joined_at
   */
  async getPeerSessions(peerId: string): Promise<Record<string, unknown>[]> {
    const parts = await this._sqlExec(
      `SELECT session_id, role, joined_at FROM session_participant WHERE peer_id = :pid`,
      { pid: peerId },
    );
    const results: Record<string, unknown>[] = [];
    for (const sp of parts) {
      const sessions = await this._sqlExec(
        `SELECT * FROM session WHERE id = :sid`,
        { sid: sp.session_id as string },
      );
      for (const s of sessions) {
        s.role = sp.role ?? "";
        s.joined_at = sp.joined_at ?? 0;
        results.push(s);
      }
    }
    results.sort((a, b) => ((b.joined_at ?? 0) as number) - ((a.joined_at ?? 0) as number));
    return results;
  }

  /**
   * Retrieve messages for a session.
   * @param sessionId - Session ID
   * @returns Array of message records sorted by created_at
   */
  async getSessionMessages(sessionId: string): Promise<Record<string, unknown>[]> {
    const rows = await this._sqlExec(
      `SELECT * FROM message WHERE session_id = :sid ORDER BY created_at ASC`,
      { sid: sessionId },
    );
    return rows;
  }

  /**
   * Compute PageRank centrality for all nodes in a workspace.
   * @param workspaceId - Workspace ID
   * @param damping - PageRank damping factor (default: 0.85)
   * @param maxIterations - Maximum iterations (default: 100)
   */
  async computePageRank(
    workspaceId: string,
    damping?: number,
    maxIterations?: number
  ): Promise<void> {
    return this._call("compute_pagerank", [
      workspaceId,
      damping ?? 0.85,
      maxIterations ?? 100,
    ]);
  }

  /**
   * Compute knowledge graph statistics for a workspace.
   * @param workspaceId - Workspace ID
   * @returns Stats record or null
   */
  async computeKgStats(workspaceId: string): Promise<Record<string, unknown> | null> {
    await this._call("compute_kg_stats", [workspaceId]);
    const rows = await this._sqlExec(
      `SELECT * FROM kg_stats_result WHERE workspace_id = :ws`,
      { ws: workspaceId },
    );
    return rows.length > 0 ? rows[0] : null;
  }

  /**
   * Compute community hierarchy for a workspace.
   * @param workspaceId - Workspace ID
   */
  async computeCommunityHierarchy(workspaceId: string): Promise<void> {
    return this._call("compute_community_hierarchy", [workspaceId]);
  }

  /**
   * Approve a merge suggestion.
   * @param suggestionId - Suggestion ID to approve
   */
  async approveMerge(suggestionId: string): Promise<void> {
    return this._call("approve_merge", [suggestionId]);
  }

  /**
   * Reject a merge suggestion.
   * @param suggestionId - Suggestion ID to reject
   */
  async rejectMerge(suggestionId: string): Promise<void> {
    return this._call("reject_merge", [suggestionId]);
  }

  /**
   * Resolve an entity name to its identity via alias resolution.
   * @param workspaceId - Workspace ID
   * @param name - Entity name to resolve
   */
  async resolveEntity(workspaceId: string, name: string): Promise<void> {
    return this._call("resolve_entity", [workspaceId, name]);
  }

  /**
   * Get decay configuration for a workspace.
   * @param workspaceId - Workspace ID
   * @returns Decay config record or null
   */
  async getDecayConfig(workspaceId: string): Promise<Record<string, unknown> | null> {
    const rows = await this._sqlExec(
      `SELECT * FROM workspace_config WHERE id = :wsid`,
      { wsid: workspaceId },
    );
    return rows.length > 0 ? rows[0] : null;
  }

  /**
   * Get reputation stats for a peer.
   * @param peerId - Peer identity
   * @returns Reputation record or null
   */
  async getPeerReputation(peerId: string): Promise<Record<string, unknown> | null> {
    const rows = await this._sqlExec(
      `SELECT * FROM peer_reputation WHERE id = :pid`,
      { pid: peerId },
    );
    return rows.length > 0 ? rows[0] : null;
  }

  /**
   * Quick connectivity check against SpacetimeDB.
   * @returns Status record
   */
  async ping(): Promise<Record<string, unknown>> {
    return this._callWithResult("ping", []).then(
      () => ({ status: "ok" }),
      () => ({ status: "error" }),
    );
  }

  /**
   * Set the decay model configuration for a workspace.
   * @param workspaceId - Workspace ID
   * @param modelType - Decay model type (e.g. "exponential", "linear")
   * @param halfLife - Half-life in seconds
   * @param maxStrength - Maximum strength value
   */
  async setDecayModel(
    workspaceId: string,
    modelType: string,
    halfLife: number,
    maxStrength: number
  ): Promise<void> {
    return this._call("set_decay_model", [
      workspaceId,
      modelType,
      halfLife,
      maxStrength,
    ]);
  }

  // -----------------------------------------------------------------------
  // Maintenance
  // -----------------------------------------------------------------------

  /**
   * Detect communities in the knowledge graph for a workspace.
   * Runs community detection algorithm and stores results.
   * @param workspaceId - Workspace ID
   */
  async detectCommunities(workspaceId: string): Promise<void> {
    return this._call("detect_communities", [workspaceId]);
  }

  /**
   * Seed communities in the knowledge graph (initialise community structure).
   * @param workspaceId - Workspace ID
   */
  async seedCommunities(workspaceId: string): Promise<void> {
    return this._call("seed_communities", [workspaceId]);
  }

  /**
   * Get community information by community ID.
   * @param communityId - Community ID (integer)
   * @returns Community record or empty
   */
  async getCommunity(communityId: number): Promise<Record<string, unknown>[]> {
    await this._call("get_community", [communityId]);
    return this._sqlExec(
      `SELECT * FROM community_result WHERE community_id = :cid`,
      { cid: String(communityId) },
    );
  }

  /**
   * Run general system maintenance tasks.
   * Calls the run_maintenance reducer (cleans stale data, re-indexes, etc.).
   */
  async runMaintenance(): Promise<void> {
    return this._call("run_maintenance", []);
  }

  /**
   * Deduplicate memories in a workspace.
   * @param workspaceId - Workspace ID
   */
  async dedup(workspaceId: string): Promise<void> {
    return this._call("dedup_memories", [workspaceId]);
  }

  // -----------------------------------------------------------------------
  // Profiles / Facts
  // -----------------------------------------------------------------------

  /**
   * Add a fact about a peer in a workspace.
   * @param workspaceId - Workspace ID
   * @param peerId - Peer identity string
   * @param content - Fact content text
   * @param opts - Options: factType, confidence
   */
  async addFact(
    workspaceId: string,
    peerId: string,
    content: string,
    opts?: AddFactOptions
  ): Promise<void> {
    await this._call("add_fact", [
      workspaceId,
      peerId,
      content,
      opts?.factType ?? "",
      opts?.confidence ?? 0.8,
    ]);
  }

  /**
   * List facts for a peer in a workspace.
   * @param workspaceId - Workspace ID
   * @param peerId - Peer identity string
   * @returns Array of fact records
   */
  async listFacts(workspaceId: string, peerId: string): Promise<FactRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM fact_result WHERE workspace_id = :ws AND peer_id = :pid`,
      { ws: workspaceId, pid: peerId },
    )) as FactRecord[];
  }

  /**
   * Delete a fact.
   * @param factId - Fact ID to delete
   */
  async deleteFact(factId: string): Promise<void> {
    return this._call("delete_fact", [factId]);
  }

  /**
   * Update a fact's content and confidence.
   * @param factId - Fact ID
   * @param content - New content text
   * @param confidence - Updated confidence score (default: 0.8)
   */
  async updateFact(
    factId: string,
    content: string,
    confidence?: number
  ): Promise<void> {
    await this._call("update_fact", [factId, content, confidence ?? 0.8]);
  }

  /**
   * Search facts by content (LIKE match on text).
   * @param workspaceId - Workspace ID
   * @param query - Search string to match against fact content
   * @returns Array of matching fact records
   */
  async searchFacts(
    workspaceId: string,
    query: string
  ): Promise<FactRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM fact WHERE workspace_id = :ws AND content LIKE '%' || :q || '%' ESCAPE '\\'`,
      { ws: workspaceId, q: query },
      { like: true },
    )) as FactRecord[];
  }

  // -----------------------------------------------------------------------
  // Tours
  // -----------------------------------------------------------------------

  /**
   * Create a guided tour in a workspace.
   * @param workspaceId - Workspace ID
   * @param name - Tour name
   * @param description - Optional description
   */
  async createTour(
    workspaceId: string,
    name: string,
    description?: string
  ): Promise<void> {
    return this._call("create_tour", [workspaceId, name, description ?? ""]);
  }

  /**
   * Add a stop to a tour (links a node at a sequence position).
   * @param tourId - Tour ID
   * @param nodeId - Knowledge graph node ID to add
   * @param sequence - Order position in the tour
   */
  async addTourStop(
    tourId: string,
    nodeId: string,
    sequence: number
  ): Promise<void> {
    return this._call("add_tour_stop", [tourId, nodeId, sequence]);
  }

  /**
   * Remove a stop from a tour.
   * @param tourStopId - Tour stop ID to remove
   */
  async removeTourStop(tourStopId: string): Promise<void> {
    return this._call("remove_tour_stop", [tourStopId]);
  }

  /**
   * Delete a tour.
   * @param tourId - Tour ID to delete
   */
  async deleteTour(tourId: string): Promise<void> {
    return this._call("delete_tour", [tourId]);
  }

  // -----------------------------------------------------------------------
  // Advanced KG
  // -----------------------------------------------------------------------

  /**
   * Update a knowledge graph node's summary and/or type.
   * @param nodeId - Node ID
   * @param summary - New summary text
   * @param nodeType - New node type
   */
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

  /**
   * Delete a knowledge graph node.
   * @param nodeId - Node ID to delete
   */
  async deleteNode(nodeId: string): Promise<void> {
    return this._call("delete_node", [nodeId]);
  }

  /**
   * Update an edge's weight.
   * @param edgeId - Edge ID
   * @param weight - New weight value (default: 1.0)
   */
  async updateEdge(
    edgeId: string,
    weight?: number
  ): Promise<void> {
    await this._call("update_edge", [edgeId, weight ?? 1.0]);
  }

  /**
   * Delete an edge.
   * @param edgeId - Edge ID to delete
   */
  async deleteEdge(edgeId: string): Promise<void> {
    return this._call("delete_edge", [edgeId]);
  }

  /**
   * Run BFS traversal from a starting node in the knowledge graph.
   * Calls the graph_bfs reducer then reads the bfs_result table.
   * @param workspaceId - Workspace ID
   * @param startNodeId - Starting node ID
   * @param maxDepth - Maximum traversal depth (default: 5)
   * @returns Array of BFS result records
   */
  async bfs(
    workspaceId: string,
    startNodeId: string,
    maxDepth?: number
  ): Promise<Record<string, unknown>[]> {
    await this._call("graph_bfs", [
      workspaceId,
      startNodeId,
      maxDepth ?? 5,
    ]);
    return await this._sqlExec(
      `SELECT * FROM bfs_result WHERE workspace_id = :ws`,
      { ws: workspaceId },
    );
  }

  /**
   * Find the shortest path between two nodes in the knowledge graph.
   * Calls the shortest_path reducer then reads the bfs_result table.
   * @param workspaceId - Workspace ID
   * @param sourceId - Source node ID
   * @param targetId - Target node ID
   * @returns Array of path result records
   */
  async shortestPath(
    workspaceId: string,
    sourceId: string,
    targetId: string
  ): Promise<Record<string, unknown>[]> {
    await this._call("shortest_path", [
      workspaceId,
      sourceId,
      targetId,
    ]);
    return await this._sqlExec(
      `SELECT * FROM bfs_result WHERE workspace_id = :ws`,
      { ws: workspaceId },
    );
  }

  /**
   * Get revision history for an edge group.
   * @param edgeGroupId - Edge group ID
   * @returns Array of edge history result records
   */
  async getEdgeHistory(edgeGroupId: string): Promise<Record<string, unknown>[]> {
    return await this._sqlExec(
      `SELECT * FROM edge_history_result WHERE edge_group_id = :egid`,
      { egid: edgeGroupId },
    );
  }

  // -----------------------------------------------------------------------
  // Sessions
  // -----------------------------------------------------------------------

  /**
   * Create a new agent session in a workspace.
   * @param workspaceId - Workspace ID
   * @param name - Optional session name
   */
  async createSession(
    workspaceId: string,
    name?: string
  ): Promise<void> {
    return this._call("create_session", [workspaceId, name ?? ""]);
  }

  /**
   * Join an existing session.
   * @param sessionId - Session ID to join
   */
  async joinSession(sessionId: string): Promise<void> {
    return this._call("join_session", [sessionId]);
  }

  /**
   * Leave a session.
   * @param sessionId - Session ID to leave
   */
  async leaveSession(sessionId: string): Promise<void> {
    return this._call("leave_session", [sessionId]);
  }

  /**
   * Record an agent step in a session.
   * @param sessionId - Session ID
   * @param step - Step text description
   * @param stepType - Type of step (default: "action"; also "thought", "observation")
   */
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

  /**
   * Get all steps recorded in a session.
   * @param sessionId - Session ID
   * @returns Array of session step records
   */
  async getSessionSteps(sessionId: string): Promise<SessionStepRecord[]> {
    return (await this._sqlExec(
      `SELECT * FROM session_step WHERE session_id = :sid`,
      { sid: sessionId },
    )) as SessionStepRecord[];
  }

  // -----------------------------------------------------------------------
  // Tags
  // -----------------------------------------------------------------------

  /**
   * Create a tag in a workspace.
   * @param workspaceId - Workspace ID
   * @param name - Tag name
   * @param color - Optional hex color (e.g. "#ff0000")
   */
  async createTag(
    workspaceId: string,
    name: string,
    color?: string
  ): Promise<void> {
    return this._call("create_tag", [workspaceId, name, color ?? ""]);
  }

  /**
   * Tag a memory with a tag.
   * @param tagId - Tag ID
   * @param memoryId - Memory ID to tag
   */
  async tagMemory(tagId: string, memoryId: string): Promise<void> {
    return this._call("tag_memory", [tagId, memoryId]);
  }

  /**
   * Remove a tag from a memory.
   * @param tagId - Tag ID
   * @param memoryId - Memory ID to untag
   */
  async untagMemory(tagId: string, memoryId: string): Promise<void> {
    return this._call("untag_memory", [tagId, memoryId]);
  }

  /**
   * List all tags in a workspace.
   * @param workspaceId - Workspace ID
   * @returns Array of tag records
   */
  async listTags(workspaceId: string): Promise<TagRecord[]> {
    await this._call("list_tags", [workspaceId]);
    // list_tags emits results into the query_result table
    const rows = await this._sqlExec(
      `SELECT row_json FROM tag LIMIT 1000`,
      {}
    );
    return rows as TagRecord[];
  }

  /**
   * Delete a tag and all its memory associations.
   * @param tagId - Tag ID to delete
   */
  async deleteTag(tagId: string): Promise<void> {
    return this._call("delete_tag", [tagId]);
  }

  // -----------------------------------------------------------------------
  // Directories
  // -----------------------------------------------------------------------

  /**
   * List children of a directory.
   * @param directoryId - Directory ID
   * @returns Array of directory children records
   */
  async listDirectory(directoryId: string): Promise<Record<string, unknown>[]> {
    await this._call("get_children", [directoryId, true]);
    return this._sqlExec(
      `SELECT * FROM directory_result WHERE query_hash = :qid`,
      { qid: directoryId },
    );
  }

  /**
   * Recursive BFS traversal of a directory tree.
   * @param workspaceId - Workspace ID
   * @param rootDirectoryId - Root directory ID to start traversal from
   * @returns Array of directory records
   */
  async traverseDirectory(
    workspaceId: string,
    rootDirectoryId: string
  ): Promise<Record<string, unknown>[]> {
    await this._call("traverse_recursive", [workspaceId, rootDirectoryId]);
    return this._sqlExec(
      `SELECT * FROM directory_result WHERE query_hash = :qid`,
      { qid: rootDirectoryId },
    );
  }

  /**
   * Get a directory by ID or path.
   * @param workspaceId - Workspace ID
   * @param pathOrId - Directory ID or path string
   * @returns Array of directory records
   */
  async getDirectory(
    workspaceId: string,
    pathOrId: string
  ): Promise<Record<string, unknown>[]> {
    await this._call("get_directory", [workspaceId, pathOrId]);
    return this._sqlExec(
      `SELECT * FROM directory_result WHERE workspace_id = :ws`,
      { ws: workspaceId },
    );
  }

  /**
   * Create a directory in the context directory tree.
   * @param workspaceId - Workspace ID
   * @param name - Directory name
   * @param path - Directory path
   * @param parentId - Optional parent directory ID
   * @param description - Optional description
   */
  async createDirectory(
    workspaceId: string,
    name: string,
    path: string,
    parentId?: string,
    description?: string
  ): Promise<void> {
    return this._call("create_directory", [
      workspaceId,
      name,
      path,
      parentId ?? "",
      description ?? "",
    ]);
  }

  /**
   * Link a memory to a directory.
   * @param directoryId - Directory ID
   * @param memoryId - Memory ID to link
   * @param workspaceId - Workspace ID
   */
  async linkMemoryToDirectory(
    directoryId: string,
    memoryId: string,
    workspaceId: string
  ): Promise<void> {
    return this._call("link_memory_to_directory", [
      directoryId,
      memoryId,
      workspaceId,
    ]);
  }

  /**
   * Unlink a memory from a directory.
   * @param directoryId - Directory ID
   * @param memoryId - Memory ID to unlink
   */
  async unlinkMemoryFromDirectory(
    directoryId: string,
    memoryId: string
  ): Promise<void> {
    return this._call("unlink_memory_from_directory", [directoryId, memoryId]);
  }

  // -----------------------------------------------------------------------
  // Context Packs
  // -----------------------------------------------------------------------

  /**
   * List context packs for a workspace.
   * @param workspaceId - Workspace ID
   * @returns Array of context pack records
   */
  async listContextPacks(
    workspaceId: string
  ): Promise<Record<string, unknown>[]> {
    return this._sql(
      `SELECT * FROM context_pack WHERE workspace_id = '${workspaceId}'`
    );
  }

  /**
   * List entries in a context pack.
   * @param packId - Context pack ID
   * @returns Array of context entry records
   */
  async listContextEntries(
    packId: string
  ): Promise<Record<string, unknown>[]> {
    return this._sql(
      `SELECT * FROM context_entry WHERE pack_id = '${packId}'`
    );
  }

  /**
   * List delta entries for a pack.
   * @param previousPackId - Previous pack ID
   * @returns Array of context delta records
   */
  async listContextDeltas(
    previousPackId: string
  ): Promise<Record<string, unknown>[]> {
    return this._sql(
      `SELECT * FROM context_delta WHERE previous_pack_id = '${previousPackId}'`
    );
  }

  /**
   * Store a context pack (named collection of memories).
   * @param workspaceId - Workspace ID
   * @param name - Context pack name
   * @param memoryIds - Array of memory IDs to include
   * @param contextText - Optional context description text
   */
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

  /**
   * Update a memory's storage tier.
   * @param memoryId - Memory ID
   * @param tier - Tier label ("L0", "L1", or "L2")
   */
  async updateMemoryTier(
    memoryId: string,
    tier: string
  ): Promise<void> {
    return this._call("update_memory_tier", [memoryId, tier]);
  }

  // -----------------------------------------------------------------------
  // Compounder / Wiki Operations
  // -----------------------------------------------------------------------

  /**
   * Cross-link related memories by finding semantically similar content.
   * Creates "related_to" edges between memory pairs that share content.
   * @param workspaceId - Workspace ID
   * @param limit - Maximum number of recent memories to check (default: 50)
   * @returns Summary with counts of links created and pairs checked
   */
  async crossLink(
    workspaceId: string,
    limit?: number
  ): Promise<CrossLinkResult> {
    const memories = await this._sqlExec(
      `SELECT id, content FROM memory WHERE workspace_id = :ws AND is_active = true ORDER BY created_at DESC LIMIT ${limit ?? 50}`,
      { ws: workspaceId },
    );

    let linksCreated = 0;
    let pairsChecked = 0;

    for (const mem of memories) {
      const mid = mem.id as string;
      const content = mem.content as string;
      if (!content || content.length < 20) continue;

      // Look for existing edges from this memory to others
      // by searching for semantically similar content via keyword
      const similar = await this._sqlExec(
        `SELECT id, content FROM memory WHERE workspace_id = :ws AND id != :mid AND content LIKE '%' || :q || '%' ESCAPE '\\' LIMIT 5`,
        { ws: workspaceId, mid, q: content.slice(0, 30) },
        { like: true },
      );

      for (const sim of similar) {
        pairsChecked++;
        // Check if edge already exists
        const existing = await this._sqlExec(
          `SELECT id FROM kg_edge WHERE source_node_id = :mid AND target_node_id = :sid`,
          { mid, sid: sim.id as string },
        );
        if (existing.length === 0) {
          try {
            await this._call("create_edge", [
              workspaceId,
              mid,
              sim.id as string,
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

  /**
   * Find KG node pairs that share neighbors but aren't directly connected.
   * Useful for suggesting new graph connections.
   * @param workspaceId - Workspace ID
   * @returns Array of KG node records (community hierarchy computed first)
   */
  async suggestConnections(
    workspaceId: string
  ): Promise<KGNodeRecord[]> {
    // Find node pairs that share neighbors but aren't directly connected
    await this._call("compute_community_hierarchy", [workspaceId]);
    return (await this._sqlExec(
      `SELECT * FROM kg_node WHERE workspace_id = :ws`,
      { ws: workspaceId },
    )) as KGNodeRecord[];
  }

  /**
   * Lint a workspace: count orphan KG nodes (nodes with no edges).
   * @param workspaceId - Workspace ID
   * @returns Summary with orphan count and total node count
   */
  async lintWorkspace(
    workspaceId: string
  ): Promise<LintResult> {
    // Find KG nodes with no edges
    const allNodes = await this._sqlExec(
      `SELECT id FROM kg_node WHERE workspace_id = :ws`,
      { ws: workspaceId },
    );
    let orphans = 0;
    for (const node of allNodes) {
      const edges = await this._sqlExec(
        `SELECT id FROM kg_edge WHERE source_node_id = :nid OR target_node_id = :nid LIMIT 1`,
        { nid: node.id as string },
      );
      if (edges.length === 0) orphans++;
    }
    return { orphans, total: allNodes.length };
  }

  /**
   * Generate a workspace overview with counts of memories, KG nodes, edges, and notes.
   * @param workspaceId - Workspace ID
   * @returns Overview statistics object
   */
  async generateOverview(workspaceId: string): Promise<OverviewResult> {
    // Gather workspace stats
    const params = { ws: workspaceId };
    const [memories, kgNodes, kgEdges, notes] = await Promise.all([
      this._sqlExec(`SELECT COUNT(*) as c FROM memory WHERE workspace_id = :ws`, params),
      this._sqlExec(`SELECT COUNT(*) as c FROM kg_node WHERE workspace_id = :ws`, params),
      this._sqlExec(`SELECT COUNT(*) as c FROM kg_edge WHERE workspace_id = :ws`, params),
      this._sqlExec(`SELECT COUNT(*) as c FROM note WHERE workspace_id = :ws`, params),
    ]);

    return {
      workspaceId,
      memories: (memories[0]?.c ?? 0) as number,
      kgNodes: (kgNodes[0]?.c ?? 0) as number,
      kgEdges: (kgEdges[0]?.c ?? 0) as number,
      notes: (notes[0]?.c ?? 0) as number,
    };
  }

  /**
   * Export workspace notes as a single markdown string.
   * Each note becomes an H1 title followed by its content, separated by ---.
   * @param workspaceId - Workspace ID
   * @returns Concatenated markdown string
   */
  async exportWorkspace(workspaceId: string): Promise<string> {
    const notes = await this._sqlExec(
      `SELECT title, content FROM note WHERE workspace_id = :ws`,
      { ws: workspaceId },
    );
    return notes
      .map((n) => `# ${n.title}\n\n${n.content ?? ""}` as string)
      .join("\n\n---\n\n");
  }

  // -----------------------------------------------------------------------
  // Store Answer (simplified compounder — no LLM needed)
  // -----------------------------------------------------------------------

  /**
   * Store an answer as a wiki note, automatically extracting entities and
   * linking them to the note via KG edges. This implements a simplified
   * "compounder" pattern without requiring an LLM call.
   *
   * @param query - The question/query that prompted this answer
   * @param answer - The answer text (markdown)
   * @param opts - Options: workspaceId (default "default"), title, sourceMemoryIds, embed
   * @returns Object containing the created note, extracted entities, and link count
   */
  async storeAnswer(
    query: string,
    answer: string,
    opts?: StoreAnswerOptions
  ): Promise<StoreAnswerResult> {
    const wsId = opts?.workspaceId ?? "default";
    const title = opts?.title ?? `Q: ${query.slice(0, 60)}`;

    if (!answer.trim()) return { note: { id: '', title: '' }, entities: [], links: 0 };

    // 1. Create the note
    await this._call("create_note", [wsId, title, answer, opts?.embed ?? true]);

    // Get the note we just created
    const notes = await this._sqlExec(
      `SELECT id FROM note WHERE workspace_id = :ws AND title = :title ORDER BY created_at DESC LIMIT 1`,
      { ws: wsId, title },
    );
    if (notes.length === 0) return { note: { id: '', title: '' }, entities: [], links: 0 };
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
        const nodes = await this._sqlExec(
          `SELECT id FROM kg_node WHERE workspace_id = :ws AND label = :label`,
          { ws: wsId, label: entity },
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

  // -----------------------------------------------------------------------
  // Batch Memory Operations
  // -----------------------------------------------------------------------

  /**
   * Store multiple memories in a single batch reducer call.
   *
   * Batch-embeds all items in one call to the embedder sidecar, then sends a
   * single `store_memory_batch` reducer with all items. Much faster than N
   * sequential `store()` calls when the embedder is the bottleneck.
   *
   * @param workspaceId - Target workspace UUID.
   * @param items - Array of memory items, each with:
   *   - `content` (string, required) — memory text content
   *   - `summary` (string, optional) — short summary, defaults to content[:200]
   *   - `memoryType` (string, optional, default "experience")
   *   - `peerId` (string, optional)
   *   - `confidence` (number, optional, default 0.8)
   * @returns Promise that resolves when all items are stored and indexed.
   */
  async storeBatch(
    workspaceId: string,
    items: {
      content: string;
      summary?: string;
      memoryType?: string;
      peerId?: string;
      confidence?: number;
    }[]
  ): Promise<void> {
    // Filter out empty items and build clean batch
    const cleanItems = items.filter((item) => item.content.trim().length > 0);
    if (cleanItems.length === 0) return;

    // Extract contents for batch embedding
    const contents = cleanItems.map((item) => item.content);

    // Batch-embed all texts in one call
    let embeddings: number[][] = [];
    try {
      const resp = await fetch(`${this.embedderUrl}/embed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ texts: contents }),
        signal: AbortSignal.timeout(10_000 * contents.length),
      });
      if (resp.ok) {
        const data: any = await resp.json();
        embeddings = data?.embeddings ?? [];
        // Fallback for single-item response
        if (embeddings.length === 0 && data?.embedding) {
          embeddings = [data.embedding];
        }
      }
    } catch {
      embeddings = [];
    }

    // Build the payload for the batch reducer
    const payload = cleanItems.map((item) => ({
      workspace_id: workspaceId,
      peer_id: item.peerId ?? "",
      observer_id: "",
      memory_type: item.memoryType ?? "experience",
      content: item.content,
      summary: item.summary ?? item.content.slice(0, 200),
      entities_json: "[]",
      confidence: item.confidence ?? 0.8,
      source_session_id: "",
      source_message_id: "",
    }));

    // Call the batch reducer
    await this._call("store_memory_batch", [JSON.stringify(payload)]);

    // Index each item with its embedding
    for (let i = 0; i < cleanItems.length; i++) {
      const emb = embeddings[i];
      if (emb && emb.length > 0) {
        // Find the newly created memory by content prefix
        const mems = await this._sqlExec(
          `SELECT id FROM memory WHERE workspace_id = :ws`,
          { ws: workspaceId },
        );
        if (mems.length > 0) {
          // Take the last match (most recently inserted)
          const memId = mems[mems.length - 1].id;
          await this._call("index_entity", [
            workspaceId,
            "memory",
            memId,
            cleanItems[i].content,
            JSON.stringify(emb),
          ]);
        }
      }
    }
  }
}
