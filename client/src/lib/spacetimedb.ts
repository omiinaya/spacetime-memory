/**
 * SpacetimeDB HTTP SQL API client for the spacetime-memory backend.
 * 
 * The API accepts SQL queries via POST and returns JSON arrays of tables.
 * Each table has a schema with column names and rows as positional arrays.
 */

const API_BASE = 'http://localhost:3001/v1/database/spacetime-memory';

export interface KgNode {
  node_id: number;
  label: string;
  node_type: string;
  summary: string;
  community_id: number | null;
  properties: string | null;
  created_at: string | null;
}

export interface KgEdge {
  edge_id: number;
  source_id: number;
  target_id: number;
  relation: string;
  weight: number;
  properties: string | null;
  created_at: string | null;
}

interface ColumnSchema {
  name: {
    some: string;
  };
}

interface SqlTableResponse {
  schema: {
    elements: ColumnSchema[];
  };
  rows: unknown[][];
}

type SqlResponse = SqlTableResponse[];

function parseSqlResponse<T>(response: SqlResponse): T[] {
  if (!response || response.length === 0) return [];

  const table = response[0];
  const columns = table.schema.elements.map((el) => el.name.some);
  return table.rows.map((row) => {
    const obj: Record<string, unknown> = {};
    columns.forEach((col, idx) => {
      obj[col] = row[idx];
    });
    return obj as unknown as T;
  });
}

async function executeSql(sql: string): Promise<SqlResponse> {
  const res = await fetch(`${API_BASE}/sql`, {
    method: 'POST',
    headers: {
      'Content-Type': 'text/plain',
    },
    body: sql,
  });

  if (!res.ok) {
    throw new Error(`SpacetimeDB SQL error: ${res.status} ${res.statusText}`);
  }

  return res.json();
}

/**
 * Fetch all knowledge graph nodes, optionally filtered by workspace.
 */
export async function fetchNodes(workspaceId?: string): Promise<KgNode[]> {
  let sql = 'SELECT * FROM kg_node';
  if (workspaceId) {
    sql += ` WHERE workspace_id = ${workspaceId}`;
  }
  sql += ' LIMIT 500';

  const response = await executeSql(sql);
  return parseSqlResponse<KgNode>(response);
}

/**
 * Fetch all knowledge graph edges, optionally filtered by workspace.
 */
export async function fetchEdges(workspaceId?: string): Promise<KgEdge[]> {
  let sql = 'SELECT * FROM kg_edge';
  if (workspaceId) {
    sql += ` WHERE workspace_id = ${workspaceId}`;
  }
  sql += ' LIMIT 2000';

  const response = await executeSql(sql);
  return parseSqlResponse<KgEdge>(response);
}

/**
 * Search nodes by label (case-insensitive LIKE).
 */
export async function searchNodes(query: string): Promise<KgNode[]> {
  const sql = `SELECT * FROM kg_node WHERE label LIKE '%${query.replace(/'/g, "''")}%' LIMIT 100`;

  const response = await executeSql(sql);
  return parseSqlResponse<KgNode>(response);
}

/**
 * Get all edges for a specific node (as source or target).
 */
export async function getNeighbors(nodeId: number): Promise<{ edges: KgEdge[]; nodeIds: number[] }> {
  const sql = `SELECT * FROM kg_edge WHERE source_id = ${nodeId} OR target_id = ${nodeId} LIMIT 200`;

  const response = await executeSql(sql);
  const edges = parseSqlResponse<KgEdge>(response);

  const nodeIds = new Set<number>();
  for (const edge of edges) {
    nodeIds.add(edge.source_id);
    nodeIds.add(edge.target_id);
  }

  return { edges, nodeIds: Array.from(nodeIds) };
}
