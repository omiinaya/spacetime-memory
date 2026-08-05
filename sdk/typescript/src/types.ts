/**
 * Shared types for the spacetime-memory TypeScript SDK.
 */

/** Prefix used in a memory's context field to store image attachments as JSON. */
export const IMAGES_CONTEXT_PREFIX = "__images__:";

// ---------------------------------------------------------------------------
// Record types
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
  source_url?: string;
}

export interface Workspace {
  id: string;
  name: string;
  description?: string;
  created_at?: number;
}

export interface KGNodeRecord {
  id: string;
  workspace_id: string;
  label: string;
  node_type: string;
  summary?: string;
  metadata_json?: string;
  created_at?: number;
}

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

export interface NoteRecord {
  id: string;
  workspace_id: string;
  title: string;
  content: string;
  note_date: string;
  embedding_json?: string;
  backlink_count?: number;
  block_ref_count?: number;
  is_active?: boolean;
  version?: number;
  created_at?: number;
  updated_at?: number;
}

export interface TagRecord {
  id: string;
  workspace_id: string;
  name: string;
  color?: string;
}

export interface FactRecord {
  id: string;
  workspace_id: string;
  peer_id: string;
  content: string;
  fact_type?: string;
  confidence?: number;
  created_at?: number;
}

export interface SessionRecord {
  id: string;
  workspace_id: string;
  name?: string;
  is_active?: boolean;
  created_at?: number;
}

export interface MentalModelRecord {
  id: string;
  workspace_id: string;
  name: string;
  content: string;
  status?: string;
  confidence?: number;
  created_at?: number;
}

export interface TourRecord {
  id: string;
  workspace_id: string;
  name: string;
  description?: string;
  created_at?: number;
}

export interface SpaceMemberRecord {
  id: string;
  workspace_id: string;
  peer_id: string;
  permission: string;
  joined_at?: number;
}

export interface PeerRecord {
  id: string;
  workspace_id: string;
  name: string;
  peer_type: string;
  metadata: string;
  created_at: number;
  updated_at: number;
}

export interface SessionStepRecord {
  id: string;
  session_id: string;
  step: string;
  step_type: string;
  created_at?: number;
}

export interface MemoryRevisionRecord {
  id: string;
  memory_id: string;
  content: string;
  version: number;
  changed_at?: number;
}

export interface GenericQueryResult {
  id: string;
  query_id: string;
  table_name: string;
  row_json: string;
  created_at?: number;
}

// ---------------------------------------------------------------------------
// Operation result types
// ---------------------------------------------------------------------------

export interface CrossLinkResult {
  linksCreated: number;
  pairsChecked: number;
}

export interface LintResult {
  orphans: number;
  total: number;
}

export interface StoreAnswerResult {
  note: { id: string; title: string };
  entities: string[];
  links: number;
}

export interface OverviewResult {
  workspaceId: string;
  memories: number;
  kgNodes: number;
  kgEdges: number;
  notes: number;
}

export interface ExportResult {
  markdown: string;
}

// ---------------------------------------------------------------------------
// Options interfaces
// ---------------------------------------------------------------------------

export interface StoreOptions {
  summary?: string;
  memoryType?: string;
  peerId?: string;
  tier?: string;
  /** Image attachment(s): a URL string or array of URL strings. */
  images?: string | string[];
}

export interface SearchOptions {
  memoryType?: string;
  tier?: string;
  limit?: number;
  semantic?: boolean;
  /** If True (default), passes top results through the MCP cross-encoder reranker. */
  crossEncoder?: boolean;
  /**
   * Shorthand temporal range filter. Accepts `{from?: number, to?: number}`
   * where values are Unix timestamps (microseconds).
   */
  temporalFilter?: { from?: number; to?: number };
  /** Optional Unix timestamp (microseconds) — only return results with `created_at < before`. */
  before?: number;
  /** Optional Unix timestamp (microseconds) — only return results with `created_at > after`. */
  after?: number;
}

export interface ListMemoriesOptions {
  memoryType?: string;
  limit?: number;
}

export interface StoreAnswerOptions {
  workspaceId?: string;
  title?: string;
  sourceMemoryIds?: string[];
  embed?: boolean;
}

export interface BatchMemoryItem {
  content: string;
  summary?: string;
  memoryType?: string;
  peerId?: string;
  confidence?: number;
  /** Image attachment(s): a URL string or array of URL strings. */
  images?: string | string[];
}

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
  /** Unix timestamp (microseconds) when the memory was created. */
  created_at?: number;
}

export interface ClientOptions {
  host?: string;
  port?: number | string;
  database?: string;
  embedderUrl?: string;
  /** Bearer token (JWT) for authenticated reducer calls. */
  token?: string;
  /** Tantivy BM25 search sidecar URL (default: http://127.0.0.1:9091). */
  tantivyUrl?: string;
  /** MCP server URL for cross-encoder reranking and other LLM tools (default: http://127.0.0.1:8099). */
  mcpUrl?: string;
}

export interface CrossEncoderRerankOptions {
  /** Which field in each candidate contains the text to score (default: "memory_content"). */
  contentKey?: string;
  /** Max number of top-scoring candidates to return (default: 20). */
  topK?: number;
}

/**
 * Minimum interface that domain module functions need from the Client instance.
 * The actual Client class implements these.
 */
export interface ClientLike {
  _call(reducer: string, args: unknown[]): Promise<any>;
  _callWithResult(reducer: string, args: unknown[]): Promise<string>;
  _sql(query: string): Promise<any[]>;
  _sqlExec(template: string, params: Record<string, string>, opts?: { like?: boolean }): Promise<any[]>;
  _embed(text: string): Promise<number[]>;
  _query(table: string, workspaceId?: string, filter?: Record<string, string>): Promise<any[]>;
  _authHeaders(): Record<string, string>;
  embedderUrl: string;
  mcpUrl: string;
  tantivyUrl: string;
  baseUrl: string;
  host: string;
  port: string;
  database: string;
  token: string;
  _metricsCollector: { record?: unknown; record_latency?: unknown; to_dict?: () => Record<string, unknown>; toDict?: () => Record<string, unknown> } | null;
}

// ---------------------------------------------------------------------------
// Backup
// ---------------------------------------------------------------------------

export const BACKUP_TABLES = [
  "workspace",
  "space_permission",
  "memory",
  "memory_version",
  "kg_node",
  "kg_edge",
  "kg_community",
  "session",
  "session_participant",
  "message",
  "profile",
  "note",
  "fact",
  "peer",
  "context_pack",
  "context_entry",
  "directory",
  "directory_link",
  "backlink",
  "merge_suggestion",
  "connector_config",
] as const;
